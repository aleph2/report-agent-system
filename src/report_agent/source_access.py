"""Owner-facing source access evidence, projected from existing native receipts."""
import json
from types import SimpleNamespace

from .catalog import Catalog
from .content_store import Actor, ContentStore
from .document_tools import _pdf_page, physical_page_number
from .errors import ActionForbidden, ActionRejected
from .source_materials import verify
from .store import digest


def _payload_digests(source):
    # Replacement changes the catalogue's computed current flag, not historical bytes.
    return {digest(ContentStore.source_payload({**source, 'current': current})) for current in (True, False)}


def coverage(cs, plan):
    """No reading gate or new ledger: return metadata about actual tool returns."""
    from .commission_plan import _citations
    workspace = SimpleNamespace(store=cs.store)
    catalogue = Catalog(cs.store).sources()
    artifacts = cs.list_objects('SourceArtifact')
    cited = {cs.read(c['source_ref'])['payload']['source_id'] for c in _citations(plan)}
    selected = [s for s in catalogue if s['current'] or s['id'] in cited]
    issues, rows, evidence = [], {}, {}
    with cs.store.connect() as db:
        blocks = {}
        for source_id, ordinal, locator in db.execute('SELECT source_id,ordinal,locator FROM source_blocks'):
            blocks.setdefault(source_id, {})[ordinal] = locator
        receipts = db.execute("SELECT key,value FROM state WHERE key LIKE 'source_material:%' ORDER BY key").fetchall()
    for source in selected:
        source_id = source['id']
        expected = _payload_digests(source)
        refs = [a['ref'] for a in artifacts if digest(a['payload']) in expected]
        count, status = None, 'physical_pages_unavailable'
        if source.get('filename', '').lower().endswith('.pdf'):
            try:
                _, _, _, count = _pdf_page(workspace, source_id, 1)
                status = 'verified_original_pdf'
            except ActionRejected as exc:
                status = 'original_unavailable'
                issues.append({'source_id': source_id, 'code': str(exc)})
        rows[source_id] = {'source_id': source_id, 'title': source['title'], 'current': source['current'],
            'file_digest': source.get('sha256') or digest(source['content']), 'source_version_refs': refs,
            'total_pages': count, 'page_count_status': status, 'snippet_pages': [],
            'text_returned_pages': [], 'full_text_pages': [], 'partial_text_pages': [],
            'inspected_text_pages': [], 'text_analysis_input_pages': [], 'image_observations': [], 'never_directly_returned_pages': None,
            'observations': []}
        evidence[source_id] = {'digests': expected, 'ordinals': set(), 'snippets': set(), 'inspected': set(), 'analysis': set(), 'images': {}}
    for key, raw in receipts:
        receipt_id = key.removeprefix('source_material:')
        try:
            record = json.loads(raw)
            original = cs.store.get('tool_observation:' + record['body_ref'])
            verified = verify(workspace, Actor(**record['actor']), receipt_id, original['text'], record['tool'])
            for part in verified['materials']:
                source_id = part['source_id']
                if source_id not in rows:
                    continue
                row, state = rows[source_id], evidence[source_id]
                if part['source_payload_digest'] not in state['digests'] or part['file_digest'] != row['file_digest']:
                    issues.append({'receipt': receipt_id, 'source_id': source_id, 'code': 'SOURCE_VERSION_MISMATCH'})
                    continue
                kind, selection = part['kind'], part['selection']
                returned = set()
                if kind in ('frozen_source_selection', 'literal_source_search_match', 'model_text_interpretation'):
                    ordinals, locators = selection['ordinals'], selection['locators']
                    known = blocks.get(source_id, {})
                    if len(ordinals) != len(locators) or any(known.get(i) != loc for i, loc in zip(ordinals, locators)):
                        issues.append({'receipt': receipt_id, 'source_id': source_id, 'code': 'SOURCE_BLOCK_SELECTION_MISMATCH'})
                        continue
                    returned = {page for loc in locators if (page := physical_page_number(loc)) is not None}
                    if kind == 'literal_source_search_match':
                        state['snippets'].update(returned)
                    elif kind == 'model_text_interpretation':
                        state['analysis'].update(returned)
                    else:
                        state['ordinals'].update(ordinals)
                elif kind == 'source_page_text_and_mechanical_tables':
                    returned = {selection['page']}
                    state['inspected'].update(returned)
                elif kind == 'model_image_interpretation':
                    status = part['coverage']['response_status']
                    if status not in ('observed', 'incomplete'):
                        continue
                    image = {'page': selection['page'], 'crop': selection.get('crop'), 'status': status}
                    state['images'][digest(image)] = image
                    returned = {image['page']}
                else:
                    continue
                row['observations'].append({'receipt': receipt_id, 'actor': verified['actor'], 'tool': verified['tool'],
                    'kind': kind, 'pages': sorted(returned), 'source_version_refs': part['source_version_refs'],
                    'body_ref': verified['body_ref'], 'public_sha256': verified['public_sha256']})
        except (ActionRejected, ActionForbidden, ValueError, TypeError, KeyError) as exc:
            issues.append({'receipt': receipt_id, 'code': 'UNVERIFIED_SOURCE_RECEIPT', 'detail': type(exc).__name__})
    for source_id, row in rows.items():
        state = evidence[source_id]
        page_blocks = {}
        for ordinal, locator in blocks.get(source_id, {}).items():
            page = physical_page_number(locator)
            if page is not None:
                page_blocks.setdefault(page, set()).add(ordinal)
        text = {p for p, ordinals in page_blocks.items() if ordinals & state['ordinals']}
        full = {p for p, ordinals in page_blocks.items() if ordinals <= state['ordinals']}
        row.update(snippet_pages=sorted(state['snippets']), text_returned_pages=sorted(text),
            full_text_pages=sorted(full), partial_text_pages=sorted(text - full),
            inspected_text_pages=sorted(state['inspected']),
            text_analysis_input_pages=sorted(state['analysis']),
            image_observations=sorted(state['images'].values(), key=lambda v: (v['page'], str(v['crop']), v['status'])))
        direct = text | state['inspected'] | {image['page'] for image in row['image_observations']}
        if row['total_pages'] is not None:
            row['never_directly_returned_pages'] = sorted(set(range(1, row['total_pages'] + 1)) - direct)
    return {'sources': list(rows.values()), 'issues': issues,
        'note': 'Tool-boundary returned material may be deferred. This is not proof that a model read or understood it. '
                'Full text means all stored extracted blocks, not full physical-page or visual comprehension. '
                'Search matches, citations, ingestion and image URLs alone do not establish direct page access.'}


def _ranges(pages):
    if pages is None:
        return '无法确定（无稳定物理页码或原件不可用）'
    spans = []
    for page in sorted(set(pages)):
        if spans and page == spans[-1][1] + 1:
            spans[-1][1] = page
        else:
            spans.append([page, page])
    return '、'.join(str(first) if first == last else f'{first}–{last}' for first, last in spans) or '无'


def lines(report):
    result = ['', '## 来源访问记录', '',
        '以下为工具返回凭据，内容可能仍待展开，不代表智能体已阅读或理解。页码为物理页码。',
        '“完整提取文本”仅表示该页已存储的文本块均有返回记录，不代表原页提取完整。',
        '搜索命中、引用、原件导入和图片链接均不计为直接页面访问；不强制指定阅读顺序。']
    for row in report['sources']:
        result += ['', '- ' + row['title'] + ('（当前资料）' if row['current'] else '（计划引用的历史版本）'),
            '  原件哈希：' + row['file_digest'],
            '  物理页数：' + (str(row['total_pages']) if row['total_pages'] is not None else '未知'),
            '  搜索命中页：' + _ranges(row['snippet_pages']),
            '  文本块返回页：' + _ranges(row['text_returned_pages']),
            '  完整提取文本页：' + _ranges(row['full_text_pages']),
            '  部分提取文本页：' + _ranges(row['partial_text_pages']),
            '  页面文本/表格检查返回页：' + _ranges(row['inspected_text_pages']),
            '  文本分析工具输入页（仅输入凭据，非原页直接返回或已理解）：' + _ranges(row['text_analysis_input_pages']),
            '  没有直接文本或图像返回记录的页：' + _ranges(row['never_directly_returned_pages'])]
        for image in row['image_observations']:
            result.append(f"  图像分析：第{image['page']}页；区域{image['crop'] if image['crop'] is not None else '全页输入'}；返回状态{image['status']}（非工程核验）")
    if report['issues']:
        result += ['', '无法核实的记录（不计访问）：', *['- ' + json.dumps(i, ensure_ascii=False) for i in report['issues']]]
    return result
