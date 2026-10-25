"""Finite remaining native role interfaces; synthetic bytes, fake models only.

These cases cover named role/tool paths, not complete duty or engineering quality.
No application implementation is replaced and no historical source is edited.
"""
from copy import deepcopy
import hashlib
from io import BytesIO
import json

from docx import Document
from langchain_core.messages import AIMessage
from openpyxl import load_workbook
import pytest

from report_agent.catalog import Catalog
from report_agent.content_export import export_snapshot
from report_agent.content_store import ContentStore
from report_agent.content_workbook import export_workbook
from report_agent.deep_runtime import run_report
from report_agent.hierarchical_tools import actor_for
from test_agent_duty_repro_artifacts import save_evidence
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import review_call
from test_decision_data import activate
from test_deep_runtime import Driver
from test_hierarchical_content import seed
from test_ingestion import pdf_bytes
from test_layout_table_controls import table_snapshot
from test_task_supervision import ws, offline


def successful(messages, identity):
    value = result_value(tool_reply(messages, identity))
    assert value.get('ok', True), value
    return value


def observe_rows(ws):
    with ws.store.connect() as db:
        return [{'receipt_id': r[0], 'actor_id': r[1], 'data': json.loads(r[2])}
                for r in db.execute('SELECT id,actor_id,data FROM content_observations')]


@pytest.mark.parametrize('role', ['writer', 'layout'])
async def test_remaining_owned_writer_artifact_interfaces_and_layout_readback(ws, request, role):
    activate(ws)
    observed = {'role': role, 'assets': [], 'covered_tools': [], 'visual_acceptance': False}
    cs = ContentStore(ws.store)
    owner = actor_for('coordinator')
    inputs = cs.import_inputs(owner, 'remaining-source', ['s'])['result']
    block = {'kind': 'block', 'body': {'text': 'Synthetic source condition retained; unresolved classification stays unresolved.'},
             'qualifiers': {}, 'claim_kind': 'structure'}
    table = {'kind': 'table', 'body': {'columns': ['Object', 'Issue'], 'rows': [['A', 'Unresolved original condition']]},
             'qualifiers': {}, 'claim_kind': 'structure'}
    expected_matrix = [table['body']['columns'], *table['body']['rows']]
    initial_records = None
    if role == 'layout':
        cs, owner, table_ref, snapshot, refs = table_snapshot(ws)
        observed['snapshot'] = snapshot
        observed['word'] = export_snapshot(cs, owner, 'remaining-prepared-word', snapshot, {'toc': False})['result']
        observed['xlsx'] = export_workbook(cs, owner, 'remaining-prepared-book', snapshot,
            [{'name': 'Issues', 'table_ref': table_ref, 'note_refs': []}], observed['word']['export_ref'])['result']
        expected_matrix = [['项目', '原文'], ['岩性', '强风化；未经确认条件保留']]
        initial_records = {r['id']: cs.read(r) for r in cs.read(snapshot)['payload']['refs']}

    def produce(messages):
        return action('process_report_content', 'produce', operation_id='remaining-produce',
            objective='Write the selected synthetic content while preserving its condition.', object_type='ContentNode',
            source_selections=[{'source_id': 's'}], output_count=2)

    def producer(messages):
        observed['text_tool_input'] = json.loads(messages[-1].content)
        return AIMessage(content=json.dumps([block, table]))

    def adopt(messages):
        work = successful(messages, 'produce')
        objects = [{'client_key': 'root', 'type': 'ContentNode', 'payload': {
            'kind': 'report', 'body': {'text': 'Small synthetic report'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
            *[{'client_key': name, 'type': 'ContentNode', 'text_work_id': work['text_work_id'], 'text_work_index': i}
              for i, name in enumerate(('body', 'table'))],
            *[{'client_key': name + '_edge', 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'root'},
                'object_ref': {'client_key': name}, 'predicate': 'contains', 'position': i,
                'provenance_kind': 'adopted_during_generation'}} for i, name in enumerate(('body', 'table'))]]
        return action('commit_objects', 'adopt', operation_id='remaining-adopt', objects=objects)

    def freeze(messages):
        observed['refs'] = successful(messages, 'adopt')['result']['refs']
        observed['owned_records'] = {k: cs.read(r) for k, r in observed['refs'].items()}
        return action('freeze_snapshot', 'freeze', operation_id='remaining-freeze',
            root_ref=observed['refs']['root'], refs=list(observed['refs'].values()))

    def derive(messages):
        observed['base'] = successful(messages, 'freeze')['result']['snapshot_ref']
        observed['base_record'] = deepcopy(cs.read(observed['base']))
        observed['covered_tools'].append('freeze_snapshot')
        return action('derive_snapshot', 'derive', operation_id='remaining-derive', base_snapshot_ref=observed['base'],
            additional_refs=[inputs['requirement_ref'], *inputs['source_refs']])

    def word(messages):
        observed['snapshot'] = successful(messages, 'derive')['result']['snapshot_ref']
        observed['covered_tools'].append('derive_snapshot')
        assert cs.read(observed['base']) == observed['base_record']
        return action('export_content_snapshot', 'word', operation_id='remaining-word',
            snapshot_ref=observed['snapshot'], layout={'toc': False, 'line_spacing': 1.5, 'right_margin_mm': 15})

    def book(messages):
        observed['word'] = successful(messages, 'word')['result']
        observed['covered_tools'].append('export_content_snapshot')
        return action('export_content_workbook', 'book', operation_id='remaining-book', snapshot_ref=observed['snapshot'],
            sheets=[{'name': 'Issues', 'table_ref': observed['refs']['table'], 'note_refs': []}],
            report_export_ref=observed['word']['export_ref'])

    def read_word(messages):
        observed['xlsx'] = successful(messages, 'book')['result']
        observed['covered_tools'].append('export_content_workbook')
        return action('read_content_export', 'read-word', export_ref=observed['word']['export_ref'])

    def read_book(messages):
        observed['word_read'] = successful(messages, 'read-word')
        return action('read_content_export', 'read-book', export_ref=observed['xlsx']['export_ref'])

    def finish(messages):
        observed['xlsx_read'] = successful(messages, 'read-book')
        observed['covered_tools'].append('read_content_export')
        return AIMessage(content='Actual paired file reads completed; no review or engineering acceptance.')

    args = {'subagent_type': role, 'description': 'Exercise only your named snapshot/export/read interfaces on synthetic content.'}
    if role == 'layout':
        args['layout_snapshot_ref'] = observed['snapshot']
        steps = [action('read_content_export', 'read-word', export_ref=observed['word']['export_ref']), read_book, finish]
    else:
        steps = [produce, adopt, freeze, derive, word, book, read_word, read_book, finish]
    driver = Driver(coordinator=[action('task', 'role-task', **args), AIMessage(content='Finite interface result retained.')],
                    text_tool=[producer], **{role: steps})
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    observed['receipts'] = observe_rows(ws)
    observed['assets'] = [{'file_ref': observed[k]['file_ref'], 'kind': k} for k in ('word', 'xlsx') if k in observed]
    save_evidence(request, ws, observed, driver)
    assert result['last_error'] is None, result
    assert observed['covered_tools'] == (['read_content_export'] if role == 'layout' else
        ['freeze_snapshot', 'derive_snapshot', 'export_content_snapshot', 'export_content_workbook', 'read_content_export'])
    for format_name in ('word', 'xlsx'):
        exported = cs.read(observed[format_name]['export_ref'])
        actual_bytes = (ws.store.root / observed[format_name]['file_ref']).read_bytes()
        returned = observed[format_name + '_read']
        assert returned['result']['export_ref'] == exported['ref']
        assert returned['result']['file_digest'] == exported['payload']['file_digest'] == hashlib.sha256(actual_bytes).hexdigest()
        assert exported['payload']['snapshot_ref'] == observed['snapshot']
        receipt = next(r for r in observed['receipts'] if r['receipt_id'] == returned['receipt_id'])
        assert receipt['data'] == returned['result']
        assert 'not visual observation' in returned['result']['limitation']
    assert cs.read(observed['xlsx']['export_ref'])['payload']['export_config']['report_export_ref'] == observed['word']['export_ref']
    doc = Document(ws.store.root / observed['word']['file_ref'])
    assert [[c.text for c in r.cells] for r in doc.tables[0].rows] == expected_matrix
    book_bytes = (ws.store.root / observed['xlsx']['file_ref']).read_bytes()
    workbook = load_workbook(BytesIO(book_bytes))
    assert [list(row) for row in workbook.active.values] == expected_matrix
    workbook.close()
    if role == 'writer':
        assert block['body']['text'] in '\n'.join(p.text for p in doc.paragraphs)
        assert observed['owned_records'] == {k: cs.read(r) for k, r in observed['refs'].items()}
        assert cs.read(observed['base']) == observed['base_record']
        assert len(set(v['owner_id'] for v in observed['owned_records'].values())) == 1
        assert cs.read(observed['snapshot'])['owner_id'] == observed['owned_records']['root']['owner_id']
        assert sum(r == 'text_tool' for r, _, _ in driver.calls) == 1
    else:
        assert initial_records == {r['id']: cs.read(r) for r in cs.read(observed['snapshot'])['payload']['refs']}
        assert not any(r == 'text_tool' for r, _, _ in driver.calls)
    assert not cs.list_objects('ReviewRecord')


def source_fixture(ws):
    original = pdf_bytes(('Printed page 91: first physical page.', 'Printed page 110: second physical page.'))
    path = ws.store.root / 'sources' / 'remaining-original.pdf'
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(original)
    source = {'id': 's', 'title': 'Two physical pages', 'filename': path.name, 'copied_path': 'sources/' + path.name,
        'content': 'Frozen first fragment.\nFrozen first continuation.\nFrozen second page.',
        'coverage': 'partial', 'sha256': hashlib.sha256(original).hexdigest()}
    ws.store.set('manifest', {**ws.store.manifest, 'sources': [source]})
    Catalog(ws.store)
    blocks = [('s', 0, 'page 1', 'Frozen first fragment.'), ('s', 2, 'page 1', 'Frozen first continuation.'),
              ('s', 17, 'page 2', 'Frozen second page.')]
    with ws.store.connect() as db:
        db.execute("DELETE FROM source_blocks WHERE source_id='s'")
        db.executemany('INSERT INTO source_blocks VALUES (?,?,?,?)', blocks)
    cs, owner, refs, snapshot, members = seed(ws)
    activate(ws)
    return cs, refs, snapshot, members, source, original, blocks


def source_driver(role, steps, refs, snapshot):
    args = {'subagent_type': role, 'description': 'Read exact synthetic source coordinates; do not infer acceptance.'}
    if role == 'reviewer':
        args = {**review_call(snapshot, refs)['args'], 'description': args['description']}
        args.pop('supervision_plugin', None)
    return Driver(coordinator=[action('task', 'source-task', **args), AIMessage(content='Source observation retained.')], **{role: steps})


@pytest.mark.parametrize('role', ['writer', 'reviewer'])
@pytest.mark.parametrize('page', [2, 0, 3], ids=['physical-two', 'zero-invalid', 'beyond-two-pages'])
async def test_remaining_source_page_interfaces_keep_block_and_physical_coordinates_separate(ws, request, role, page):
    cs, refs, snapshot, members, source, original, blocks = source_fixture(ws)
    before = {r['id']: cs.read(r) for r in members}
    observed = {'role': role, 'physical_page_requested': page, 'original_source': source,
        'original_block_rows': blocks, 'assets': [{'file_ref': source['copied_path'], 'kind': 'source_pdf'}]}

    def inspect_page(messages):
        value = successful(messages, 'block')
        observed['block_read'] = value
        assert value['blocks'] == [{'ordinal': 2, 'locator': 'page 1', 'text': 'Frozen first continuation.'}]
        assert value['offset'] == 1 and value['next_offset'] == 2
        return action('inspect_source_page', 'physical', source_id='s', page=page)

    def finish(messages):
        observed['physical_tool_message'] = tool_reply(messages, 'physical').model_dump()
        observed['physical_read'] = result_value(tool_reply(messages, 'physical'))
        return AIMessage(content='Source coordinates preserved; this does not constitute visual review.')

    driver = source_driver(role, [action('read_source_page', 'block', source_id='s', offset=1, limit=1,
        table_detail='references'), inspect_page, finish], refs, snapshot)
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    with ws.store.connect() as db:
        observed['source_receipts'] = {r[0]: json.loads(r[1]) for r in db.execute("SELECT key,value FROM state WHERE key LIKE 'source_material:%'")}
        after_blocks = list(db.execute("SELECT source_id,ordinal,locator,text FROM source_blocks WHERE source_id='s' ORDER BY ordinal"))
    save_evidence(request, ws, observed, driver)
    assert result['last_error'] is None, result
    value = observed['physical_read']
    physical_receipts = [v for v in observed['source_receipts'].values() if v['tool'] == 'inspect_source_page']
    if page == 2:
        assert value['page'] == 2 and value['page_count'] == 2
        assert value['native_text'] == 'Printed page 110: second physical page.'
        assert value['frozen_text_blocks'] == [{'ordinal': 17, 'locator': 'page 2', 'text': 'Frozen second page.'}]
        assert value['image_ref'] == 'source-page://s/2' and value['sha256'] == source['sha256']
        assert len(physical_receipts) == 1
        part, = physical_receipts[0]['materials']
        assert part['selection'] == {'units': 'one-based physical PDF page', 'page': 2}
        assert part['file_digest'] == source['sha256'] and len(part['source_version_refs']) == 1
        assert cs.read(part['source_version_refs'][0])['payload']['content'] == source['content']
    else:
        assert value['ok'] is False
        assert value['code'] == ('SOURCE_PAGE_REQUIRES_POSITIVE_INTEGER' if page == 0 else 'SOURCE_PAGE_OUT_OF_RANGE')
        assert not physical_receipts
    assert after_blocks == blocks
    assert before == {r['id']: cs.read(r) for r in members}
    assert (ws.store.root / source['copied_path']).read_bytes() == original
    assert not any(r == 'text_tool' for r, _, _ in driver.calls)
    assert not cs.list_objects('ReviewRecord')


async def test_remaining_reviewer_capture_source_versions_preserves_author_inputs(ws, request):
    cs, refs, snapshot, members, source, original, blocks = source_fixture(ws)
    before = {r['id']: cs.read(r) for r in [snapshot, *members]}
    source_version_before, = [cs.read(r) for r in members if r['type'] == 'SourceArtifact']
    observed = {'assets': [{'file_ref': source['copied_path'], 'kind': 'source_pdf'}], 'source': source,
                'source_version_before': deepcopy(source_version_before)}

    def read_captured(messages):
        value = successful(messages, 'capture')
        observed['capture'] = value
        ref, = value['result']['source_refs']
        return action('read_context', 'captured-read', target_ref=ref)

    def finish(messages):
        observed['read'] = successful(messages, 'captured-read')
        return AIMessage(content='Exact captured source version is available; no evidence-support judgment.')

    driver = source_driver('reviewer', [action('capture_review_sources', 'capture', operation_id='remaining-capture',
        source_ids=['s']), read_captured, finish], refs, snapshot)
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    observed['receipts'] = observe_rows(ws)
    save_evidence(request, ws, observed, driver)
    assert result['last_error'] is None, result
    ref, = observed['capture']['result']['source_refs']
    record = cs.read(ref)
    # Catalog enrichment is part of the saved source metadata. Compare against
    # the exact version already imported before this public capture, while also
    # checking the independent source text and original PDF hash.
    assert record['payload'] == source_version_before['payload']
    assert record['payload']['content'] == source['content']
    assert record['payload']['file_digest'] == hashlib.sha256(original).hexdigest()
    assert ref['id'] not in before and record['owner_id'].startswith('content:reviewer:')
    assert observed['read']['result']['objects'] == [record]
    receipt = next(r for r in observed['receipts'] if r['receipt_id'] == observed['read']['receipt_id'])
    assert receipt['actor_id'] == record['owner_id'] and receipt['data'] == observed['read']['result']
    assert before == {r['id']: cs.read(r) for r in [snapshot, *members]}
    assert (ws.store.root / source['copied_path']).read_bytes() == original
    assert not cs.list_objects('ReviewRecord')


async def test_remaining_writer_foreign_structure_is_readable_but_not_revisable(ws, request):
    cs, owner, refs, snapshot, members = seed(ws)
    activate(ws)
    original = deepcopy(cs.read(refs['root']))
    observed = {'foreign_before': original}

    def revise_foreign(messages):
        observed['legal_read'] = successful(messages, 'read-foreign')
        assert observed['legal_read']['result']['objects'][0] == original
        return action('commit_objects', 'foreign-revise', operation_id='remaining-foreign-revise', objects=[{
            'client_key': 'root', 'type': 'ContentNode', 'previous_ref': refs['root'], 'payload': original['payload']}])

    def own_control(messages):
        value = result_value(tool_reply(messages, 'foreign-revise'))
        observed['rejection'] = value
        assert value['ok'] is False and 'FORBIDDEN' in value['code'] and 'object owner' in json.dumps(value)
        assert cs.read(refs['root']) == original
        return action('commit_objects', 'own-new', operation_id='remaining-own-new', objects=[{
            'client_key': 'root', 'type': 'ContentNode', 'payload': original['payload']}])

    def finish(messages):
        observed['own_control'] = successful(messages, 'own-new')
        return AIMessage(content='Foreign root unchanged; equal structure saved as a new separately owned node.')

    driver = source_driver('writer', [action('read_context', 'read-foreign', target_ref=refs['root']),
        revise_foreign, own_control, finish], refs, snapshot)
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    save_evidence(request, ws, observed, driver)
    assert result['last_error'] is None, result
    own = cs.read(observed['own_control']['result']['refs']['root'])
    assert own['payload'] == original['payload'] and own['owner_id'] != original['owner_id']
    assert own['ref']['id'] != original['ref']['id'] and own['ref']['version'] == 1
    assert own['previous_ref'] is None and cs.read(refs['root']) == original
    with ws.store.connect() as db:
        assert db.execute('SELECT version FROM content_heads WHERE id=?', (refs['root']['id'],)).fetchone()[0] == 1
    assert not any(r == 'text_tool' for r, _, _ in driver.calls)


@pytest.mark.parametrize('target_state', ['current', 'foreign', 'stale'])
async def test_p16_native_scoped_revision_reports_exact_target_admission_and_preserves_body(ws, request, target_state):
    """Base production is dispatched once; rejected revisions dispatch zero times.

The foreign/stale preconditions are isolated host fixture arrangements made
between native calls, not extra permissions granted to the scripted Writer.
"""
    from report_agent.content_store import Actor
    from report_agent.text_work import QUALIFIER_WORK_PROMPT
    from test_text_work_scoped_revision import TABLE, DELTA, save_fixture

    activate(ws)
    cs = ContentStore(ws.store)
    observed = {'case': 'P16.C2', 'target_state': target_state, 'producer_calls': [], 'fixture_changes': []}

    def production_state():
        with ws.store.connect() as db:
            return {'raw_analyses': {r[0]: json.loads(r[1]) for r in db.execute('SELECT operation,data FROM analyses')},
                'text_receipts': {r[0]: json.loads(r[1]) for r in db.execute(
                    "SELECT key,value FROM state WHERE key LIKE 'text_work:%' OR key LIKE 'text_work_receipt:%' OR key LIKE 'bounded_review_attempt:%'")},
                'heads': [list(r) for r in db.execute('SELECT type,id,version FROM content_heads ORDER BY type,id')]}

    def producer(messages):
        packet = json.loads(messages[-1].content)
        observed['producer_calls'].append({'messages': [m.model_dump() for m in messages], 'packet': packet})
        if 'revision' not in packet:
            return AIMessage(content=json.dumps(TABLE))
        assert target_state == 'current', 'Rejected foreign/stale revision must never reach this independent model.'
        target, = packet['revision']['targets']
        assert target['ref'] == observed['target_ref'] == observed['base_ref']
        target_inputs = [e['object'] for e in packet['evidence']
                         if e['kind'] == 'saved_object' and e['object']['ref'] == target['ref']]
        assert target_inputs == [observed['base_record']]
        assert messages[0].content == QUALIFIER_WORK_PROMPT
        return AIMessage(content=json.dumps(DELTA))

    def assert_public_output_directory(value, expected):
        # This is the actual next-Writer ToolMessage projection, not host-only
        # receipt recovery. Full body stays deferred; decision fields are exact.
        assert value['state'] == 'completed'
        assert isinstance(value['text_work_id'], str) and value['text_work_id']
        assert value['details_deferred'] is True
        assert value['outputs']['complete'] is True
        assert value['outputs']['total'] == 1
        entry, = value['outputs']['entries']
        assert entry['index'] == 0
        assert entry['original_path'] == ['payloads', 0]
        assert entry['body_deferred'] is True
        for field in ('kind', 'claim_kind', 'qualifiers'):
            assert entry[field] == expected[field]

    def adopt_base(messages):
        observed['base_work'] = successful(messages, 'base-produce')
        assert_public_output_directory(observed['base_work'], TABLE)
        observed['base_work_receipt'] = deepcopy(ws.store.get('text_work_receipt:' + observed['base_work']['text_work_id']))
        assert observed['base_work_receipt']['result']['payload'] == TABLE
        return action('save_text_node', 'base-adopt', operation_id='p16-base-adopt',
            text_work_id=observed['base_work']['text_work_id'])

    def choose_target(messages):
        ref = successful(messages, 'base-adopt')['result']['refs']['text']
        observed['base_ref'] = ref
        observed['base_record'] = deepcopy(cs.read(ref))
        assert observed['base_record']['payload'] == TABLE
        target_ref = ref
        if target_state == 'foreign':
            target_ref = save_fixture(ws, Actor('p16:foreign-writer', 'writer', 'p16:foreign-task'), 'p16-foreign-fixture')
            foreign = cs.read(target_ref)
            assert foreign['payload'] == observed['base_record']['payload']
            observed['fixture_changes'].append({'kind': 'separate_foreign_target_same_payload',
                'base_ref': ref, 'target_ref': target_ref, 'foreign_owner': foreign['owner_id']})
        elif target_state == 'stale':
            actor = Actor(observed['base_record']['owner_id'], 'writer', observed['base_record']['task_id'])
            advanced = cs.commit(actor, 'p16-competing-head', [{'client_key': 'node', 'type': 'ContentNode',
                'payload': deepcopy(TABLE), 'previous_ref': ref}])['result']['refs']['node']
            assert advanced == {**ref, 'version': 2} and cs.read(advanced)['payload'] == TABLE
            observed['fixture_changes'].append({'kind': 'head_advanced_same_owned_body_and_qualifiers',
                                               'old_ref': ref, 'current_ref': advanced})
        observed['target_ref'] = target_ref
        observed['target_record'] = deepcopy(cs.read(target_ref))
        return action('read_context', 'target-read', target_ref=target_ref)

    def revise(messages):
        observed['target_read'] = successful(messages, 'target-read')
        assert observed['target_read']['result']['objects'] == [observed['target_record']]
        observed['before_revision'] = production_state()
        observed['before_revision_nodes'] = deepcopy(cs.list_objects('ContentNode'))
        return action('process_report_content', 'revision', operation_id='p16-qualifier-revision',
            objective='Retain technical uncertainty and remove process commentary.', object_type='ContentNode',
            source_selections=[{'source_id': 's'}], revision={'scope': 'qualifiers', 'targets': [observed['target_ref']]})

    def revision_result(messages):
        observed['next_writer_after_revision'] = tool_reply(messages, 'revision').model_dump()
        value = result_value(tool_reply(messages, 'revision'))
        observed['revision_return'] = value
        if target_state == 'current':
            assert_public_output_directory(value, {**TABLE, **DELTA})
            observed['revision_receipt'] = deepcopy(ws.store.get('text_work_receipt:' + value['text_work_id']))
            full = observed['revision_receipt']['result']
            assert full['payload'] == {**TABLE, **DELTA}
            assert full['revision']['targets'][0]['ref'] == observed['base_ref']
            return action('save_text_node', 'revision-adopt', operation_id='p16-revision-adopt',
                text_work_id=value['text_work_id'], previous_ref=observed['base_ref'])
        assert value['ok'] is False, value
        if target_state == 'foreign':
            assert value['code'] == 'FORBIDDEN' and 'revision target belongs to another owner' in json.dumps(value), value
        else:
            assert value['code'] == 'TEXT_WORK_REVISION_VERSION_CONFLICT', value
        return AIMessage(content='Selected revision target rejected before independent work; existing draft and receipts retained.')

    def adopted(messages):
        observed['adoption'] = successful(messages, 'revision-adopt')
        return AIMessage(content='Exact qualifiers revision saved. Body remains unchanged; not engineering acceptance.')

    steps = [action('process_report_content', 'base-produce', operation_id='p16-base-produce',
        objective='Describe the synthetic evidence.', object_type='ContentNode', source_selections=[{'source_id': 's'}]),
        adopt_base, choose_target, revise, revision_result]
    if target_state == 'current':
        steps.append(adopted)
    driver = Driver(coordinator=[action('task', 'p16-writer', subagent_type='writer',
        description='Revise only qualifiers of an exact selected owned draft; preserve all original body content.'),
        AIMessage(content='Scoped result and remaining limitations retained.')], writer=steps, text_tool=[producer])
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    observed['after_revision'] = production_state()
    observed['after_revision_nodes'] = cs.list_objects('ContentNode')
    save_evidence(request, ws, observed, driver)
    assert result['last_error'] is None, result
    assert cs.read(observed['base_ref']) == observed['base_record']
    assert len(observed['producer_calls']) == (2 if target_state == 'current' else 1)
    assert len([c for c in observed['producer_calls'] if 'revision' in c['packet']]) == (1 if target_state == 'current' else 0)
    for key, value in observed['before_revision']['raw_analyses'].items():
        assert observed['after_revision']['raw_analyses'][key] == value
    for key, value in observed['before_revision']['text_receipts'].items():
        assert observed['after_revision']['text_receipts'][key] == value
    if target_state == 'current':
        revised = cs.read(observed['adoption']['result']['refs']['text'])
        assert revised['ref'] == {**observed['base_ref'], 'version': 2}
        assert revised['previous_ref'] == observed['base_ref']
        assert revised['owner_id'] == observed['base_record']['owner_id']
        assert revised['payload'] == {**TABLE, **DELTA}
        for field in ('body', 'kind', 'claim_kind'):
            assert revised['payload'][field] == observed['base_record']['payload'][field]
    else:
        assert observed['before_revision'] == observed['after_revision']
        assert observed['before_revision_nodes'] == observed['after_revision_nodes']
        assert cs.read(observed['target_ref']) == observed['target_record']
    assert not cs.list_objects('ReviewRecord')
