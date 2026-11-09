"""Prepare and inspect the authorized O6 pages; the operator supplies a finance-bound model."""
import argparse
from hashlib import file_digest, sha256
import json
from pathlib import Path
from typing import TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pypdf import PdfReader, PdfWriter

from . import plan_inputs
from . import plan_authority
from .assertion_host import AssertionHost
from .catalog import Catalog
from .commission_planning import save_item
from .content_store import ContentStore
from .errors import ActionForbidden, ActionRejected
from .hierarchical_tools import actor_for, role_prompt
from .planning_assertions import planning_assertion_tools
from .source_use import source_version_material, validate_source_versions
from .store import Store, encode

SUBJECT = 'HP-02-K9023p670-L'
DOCUMENTS = {
    'design': ('synthetic-design.pdf',
               '1111111111111111111111111111111111111111111111111111111111111111', (96, 113, 114, 115, 116, 117)),
    'survey': ('synthetic-survey.pdf',
               '2222222222222222222222222222222222222222222222222222222222222222', (43,)),
}
ACTIONS = ('assert_source', 'record_conflict', 'ask')
GOAL = '仅提取 HP-02-K9023p670-L 左侧边坡的来源事实、资料冲突和待回答问题，供业主逐项与原件比较。'
LIMIT = '仅提供指定原始物理页的原生文字层。图纸线形、图例对应和图内空间关系未经视觉核验。'


def _json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def prepare(library, case):
    """Snapshot the selected original physical pages into a new, self-contained case."""
    library, case = Path(library).resolve(strict=True), Path(case).resolve()
    if case.is_relative_to(library):
        raise ValueError('O6_CASE_MUST_BE_OUTSIDE_LIBRARY')
    case.mkdir(parents=True, exist_ok=False)
    sources, blocks, docs = [], {}, {}
    for key, (filename, pin, numbers) in DOCUMENTS.items():
        with (library / filename).open('rb') as original:
            if file_digest(original, 'sha256').hexdigest() != pin:
                raise ValueError('O6_ORIGINAL_DIGEST_CHANGED: ' + key)
            original.seek(0)
            pdf = PdfReader(original)
            excerpt = PdfWriter()
            rows = []
            for number in numbers:
                page = pdf.pages[number-1]
                rows.append(dict(locator='page ' + str(number), text=page.extract_text() or ''))
                excerpt.add_page(page)
            target = case / (key + '-selected.pdf')
            excerpt.write(target)
        selected_hash = sha256(target.read_bytes()).hexdigest()
        sources.append(dict(id=key, title=filename, coverage='partial',
                            content='\n\n'.join(r['text'] for r in rows),
                            original_sha256=pin, original_pages=list(numbers), selected_pdf_sha256=selected_hash))
        blocks[key] = rows
        docs[key] = dict(original_file=filename, original_sha256=pin, original_pages=list(numbers),
                         selected_file=target.name, selected_pdf_sha256=selected_hash)
    store = Store(case)
    store.initialize(dict(goal=GOAL, report_id='O6/' + SUBJECT, sources=sources,
        content_contract='hierarchical-review-v1', commission_checkpoint_required=True,
        commission_planning_contract='commission-planning-v1',
        source_use=dict(source_ids=list(DOCUMENTS), authorization_origin='Operator-selected O6 physical pages')))
    cs = ContentStore(store)
    with store.connect() as db:
        # Catalog initialized these new manifest sources with generic text locators.
        # Retain the original physical page numbers for the issued excerpts.
        for source_id, rows in blocks.items():
            db.execute('DELETE FROM source_blocks WHERE source_id=?', (source_id,))
            Catalog._blocks(db, source_id, rows)
    co = actor_for('coordinator')
    refs = cs.import_inputs(co, 'o6-selected-originals', list(DOCUMENTS))['result']['source_refs']
    origin = next(ref for ref in refs if cs.read(ref)['payload']['source_id'] == 'design')
    quote = 'K9023+670-K9023+760'
    citation = dict(source_ref=origin, locator='page 96', quote=quote)
    save_item(cs, co, 'o6-owner-slope', 'object', dict(object_id=SUBJECT, label=SUBJECT, included=True,
        reason='Operator-selected comparison subject.', origin='customer', sources=[citation],
        attributes=[dict(name='source chainage', values=[dict(value=quote, source=citation, reason='Source locator.')])]))
    for key in DOCUMENTS:
        docs[key]['source_version'] = source_version_material(cs, key)[0]
    receipt = dict(subject=SUBJECT, documents=docs, allowed_tools=ACTIONS, limitations=LIMIT)
    _json(case / 'o6-inputs.json', receipt)
    return receipt


def _inputs(case):
    receipt = json.loads((case / 'o6-inputs.json').read_bytes())
    cs, co = ContentStore(Store(case)), actor_for('coordinator')
    if receipt['subject'] != SUBJECT or set(receipt['documents']) != set(DOCUMENTS):
        raise ValueError('O6_INPUT_SCOPE_CHANGED')
    if set(s['id'] for s in cs.store.source_catalog()) != set(DOCUMENTS):
        raise ValueError('O6_MATERIAL_SCOPE_CHANGED')
    objects = plan_inputs.get_draft(cs.store, {}).get('items', {}).get('object', {})
    if set(objects) != {SUBJECT} or plan_authority.plan_ref(cs.store):
        raise ValueError('O6_SUBJECT_SCOPE_CHANGED')
    validate_source_versions(cs, co, source_ids=list(DOCUMENTS))
    packet = []
    for key, (filename, pin, numbers) in DOCUMENTS.items():
        doc = receipt['documents'][key]
        file = case / (key + '-selected.pdf')
        version, material = source_version_material(cs, key)
        if (doc['original_file'] != filename or doc['original_sha256'] != pin
                or doc['original_pages'] != list(numbers) or version != doc['source_version']
                or set(material['pages']) != {str(n) for n in numbers}
                or sha256(file.read_bytes()).hexdigest() != doc['selected_pdf_sha256']):
            raise ValueError('O6_INPUT_PINS_CHANGED')
        excerpt = PdfReader(file)
        if len(excerpt.pages) != len(numbers):
            raise ValueError('O6_EXCERPT_PAGE_COUNT_CHANGED')
        for index, page in enumerate(numbers):
            if (excerpt.pages[index].extract_text() or '') != material['pages'][str(page)]:
                raise ValueError('O6_EXCERPT_TEXT_CHANGED')
            packet.append(dict(source_id=key, original_page=page, text=material['pages'][str(page)]))
    return cs, co, packet


class ExtractionReceipt(TypedDict):
    subject: str
    allowed_tools: tuple[str, ...]
    stop: str
    model_invocations: int
    tool_attempts: list[dict]
    financial_attempts_source: str
    limitations: str
    final_message: str | list[str | dict] | None
    assertions: list[dict]
    archive_sha256: str
    owner_comparison: str


async def extract(case, bound_model) -> ExtractionReceipt:
    """Run the Coordinator on selected text only. The caller owns transport budget and accounting."""
    case = Path(case).resolve(strict=True)
    cs, co, pages = _inputs(case)
    tools = planning_assertion_tools(cs, lambda: co)
    if tuple(t.__name__ for t in tools) != ACTIONS:
        raise ValueError('O6_UNEXPECTED_ACTION_SCOPE')
    line = ('按来源明示的事实使用工具保存可追溯记录，注意桩号、左右侧和工程对象。'
            '保留资料分歧，资料不足时说明具体未知项，完成提取后结束。' + LIMIT)
    prompt = GOAL + line + '\n' + encode(pages)
    message = HumanMessage(prompt)
    attempts = []

    @wrap_tool_call
    async def log_action(request, handler):
        call = request.tool_call
        attempt = dict(tool=call['name'], native_call_id=call['id'])
        attempts.append(attempt)
        try:
            result = await handler(request)
        except (ActionForbidden, ActionRejected) as exc:
            result = ToolMessage(content=str(exc), name=call['name'], tool_call_id=call['id'], status='error')
        attempt['status'] = result.status
        if result.status == 'error':
            attempt['reason'] = result.content
        return result

    agent = create_agent(bound_model, tools=tools, system_prompt=role_prompt('coordinator'), middleware=[log_action])

    class Calls(BaseCallbackHandler):
        count = 0
        def on_chat_model_start(self, serialized, messages, **kwargs):
            self.count += len(messages)

    count = Calls()
    # Exclusive claim also survives a crash or unknown provider outcome.
    with (case / 'o6-extraction-started.json').open('x', encoding='utf-8') as mark:
        mark.write(encode(dict(subject=SUBJECT, input_sha256=sha256(prompt.encode()).hexdigest())))
    host = AssertionHost(case)
    stopped = 'interrupted'
    final_message = None
    try:
        run = await agent.ainvoke({'messages':[message]}, config={'callbacks':[count], 'recursion_limit':128})
        final = run['messages'][-1]
        if not isinstance(final, AIMessage) or final.tool_calls:
            raise ValueError('O6_COORDINATOR_FINAL_MESSAGE_REQUIRED')
        stopped = 'coordinator_final'
        final_message = final.content
    finally:
        archive = case / 'o6-assertions.jsonl'
        host.commission.export(archive)
        actions = [row for line in archive.read_text().splitlines()
                   if 'assertion' in (row := json.loads(line))]
        receipt = ExtractionReceipt(subject=SUBJECT, allowed_tools=ACTIONS, stop=stopped, model_invocations=count.count,
                       tool_attempts=attempts, financial_attempts_source='operator transport ledger', limitations=LIMIT,
                       final_message=final_message, assertions=[r['assertion'] for r in actions],
                       archive_sha256=sha256(archive.read_bytes()).hexdigest(), owner_comparison='pending')
        _json(case / 'o6-results.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prepare the seven-page O6 input without calling any model.')
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--case', type=Path, required=True)
    args = parser.parse_args()
    print(encode(prepare(args.library, args.case)))
