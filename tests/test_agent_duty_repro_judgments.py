"""J01-J04/I01: retained fake-model reproductions, never semantic acceptance.

Independent expected values are fixed before native calls. Sensitivity changes
only in-memory program boundaries AFTER the original model output/selection.
No application repair, provider call, or historical report mutation is performed.
"""
import json
from copy import deepcopy
import re
import traceback

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent import decision_data, deep_runtime, text_work
from report_agent.content_store import ContentStore
from report_agent.store import digest
from report_agent.task_context import TaskContext
from report_agent.task_supervision import reconcile
from test_agent_result_delivery import force_offload, packet, reply, run_role, wire_text
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_producer_observations import as_legacy_producer
from test_task_supervision import ws, offline


def evidence(request, group, **details):
    request.node.user_properties.append((group, json.dumps(details, ensure_ascii=False)))


def wire_packet(message):
    """Compare decoded actual adapter content, not escaped JSON with raw text."""
    content = json.loads(wire_text(message))['content']
    return json.loads(content if isinstance(content, str) else content[-1]['text'])


def producer_fixture():
    return {
        'payloads': [
            {'kind': 'block', 'body': {'text': 'Candidate A: the selected geology describes class B.'},
             'claim_kind': 'fact', 'qualifiers': {
                 'source': 'geology:page1', 'support': 'A_SUPPORTED: source explicitly states class B.'}},
            {'kind': 'block', 'body': {'text': 'Candidate B: no determined score is established.'},
             'claim_kind': 'inference', 'qualifiers': {
                 'source': 'guide:page1:selected-three-columns',
                 'limitations': 'Index B condition remains unresolved. ' * 120 +
                     'B_TAIL: the explanation column is unselected; indicator mapping unverified; no definite score.'}}],
        'generation_notes': [
            {'output_index': 0, 'text': 'A_PROCESS: producer used the supplied synthetic packet.'},
            {'output_index': 1, 'text': 'B_PROCESS: generated the second candidate, no additional reading.'}]}


async def writer_case(ws, monkeypatch, mode, request, repeat_operation='first'):
    cs, _, refs, snapshot, _ = seed(ws)
    original_objects = {k: cs.read(v) for k, v in refs.items()}
    activate(ws)
    # Long candidate output must still offload (asserted below); leave capacity
    # for the ~852-character exact body recovery packet. The prior deliberately
    # tiny 100-token/read_file experiment is retained in judgments/run4-recovery.
    force_offload(monkeypatch, mode == 'offload', threshold=1000)
    if mode == 'legacy':
        original = TaskContext.bound_result

        def legacy_once(self, result, tool_args=None):
            shown = original(self, result, tool_args)
            if isinstance(shown, ToolMessage) and shown.name == 'process_report_content':
                monkeypatch.setattr(TaskContext, 'bound_result', original)
                return as_legacy_producer(shown)
            return shown
        monkeypatch.setattr(TaskContext, 'bound_result', legacy_once)
    expected = producer_fixture()
    raw = json.dumps(expected, ensure_ascii=False)
    model = Model(raw)
    receipts, observed, adopted, receipt_snapshots = [], [], [], []
    args = dict(object_type='ContentNode', output_count=2,
                objective='Produce two distinct qualified candidates; do not infer a score.', input_refs=[refs['claim']])

    def inspect_candidates(messages):
        message = reply(messages, 'process_report_content')
        shown = packet(message)
        value = shown['metadata']
        observed.append(deepcopy(value))
        saved_raw = json.loads(ws.store.get('tool_observation:' + shown['observation_ref'])['text'])
        assert saved_raw['payloads'] == expected['payloads']
        assert saved_raw['generation_notes'] == expected['generation_notes']
        assert value['generation_notes'] == expected['generation_notes']
        assert value['state'] == 'completed' and value['semantic_correctness_verified'] is False
        for i, source in enumerate(expected['payloads']):
            entry = value['outputs']['entries'][i]
            assert entry['index'] == i
            assert entry['claim_kind'] == source['claim_kind']
            assert entry['qualifiers'] == source['qualifiers'], 'J01_INDEXED_QUALIFIERS_LOST'
            assert entry['payload_digest'] == digest(source)
            assert entry['original_path'] == ['payloads', i]
            assert entry['body_deferred'] and source['body']['text'] not in wire_text(message)
            assert wire_packet(message)['metadata']['outputs']['entries'][i]['qualifiers'] == source['qualifiers']
        if mode == 'offload':
            assert message.additional_kwargs.get('report_controls_restored')
        receipts.append(value['text_work_id'])
        if repeat_operation != 'first':
            receipt_snapshots.append(deepcopy(ws.store.get('text_work_receipt:' + receipts[-1])))
        if len(receipts) == 1:
            return invoke('process_report_content', operation_id=repeat_operation, **args)
        if repeat_operation == 'first':
            assert value['reused'] and receipts[0] == receipts[1]
        else:
            # A distinct operation may own a distinct receipt even when its raw
            # analysis is reused. Verify durability, not an ID policy.
            assert ws.store.get('text_work_receipt:' + receipts[0]) == receipt_snapshots[0]
        return invoke('read_tool_observation', observation_ref=shown['observation_ref'],
                      field_path=['payloads', 1, 'body', 'text'], offset=0, characters=1000)

    def inspect_body(messages):
        returned = reply(messages, 'read_tool_observation')
        recovered = packet(returned)
        assert recovered['text'] == expected['payloads'][1]['body']['text']
        assert recovered['field_path'] == ['payloads', 1, 'body', 'text']
        assert recovered['complete_field'] and recovered['next_offset'] is None
        evidence(request, 'J01-exact-body-recovery', actual_wire=wire_text(returned), decoded=recovered,
                 offload_threshold_tokens=1000 if mode == 'offload' else None)
        return invoke('save_text_node', operation_id='adopt-b', text_work_id=receipts[-1], text_work_index=1)

    def inspect_save(messages):
        value = packet(reply(messages, 'save_text_node'))
        actual = cs.read(value['result']['refs']['text'])
        index = 1 if not adopted else 0
        assert actual['payload'] == expected['payloads'][index]
        assert 'generation_notes' not in actual['payload']
        adopted.append(actual)
        return (invoke('save_text_node', operation_id='adopt-a', text_work_id=receipts[-1], text_work_index=0)
                if len(adopted) == 1 else AIMessage(content='Both exact candidates saved; no semantic acceptance.'))

    try:
        await run_role(ws, 'writer', [invoke('process_report_content', operation_id='first', **args),
            inspect_candidates, inspect_candidates, inspect_body, inspect_save, inspect_save], refs, snapshot, model)
    finally:
        with ws.store.connect() as db:
            producer_state = [{'key': key, 'value': json.loads(value)} for key, value in db.execute(
                "SELECT key,value FROM state WHERE key LIKE 'text_work:%' OR key LIKE 'text_work_receipt:%'")]
        evidence(request, 'J01-execution', mode=mode, repeat_operation=repeat_operation,
                 delivered=observed, actual_text_calls=len(model.calls), producer_state=producer_state,
                 original_public_output=expected, source_objects_unchanged=all(cs.read(v) == original_objects[k] for k,v in refs.items()))
    assert model.response == raw and len(model.calls) == 1
    assert len(adopted) == 2
    assert {k: cs.read(v) for k, v in refs.items()} == original_objects
    if mode == 'legacy':
        assert sum(e['kind'] == 'producer_observation_reprojected' for e in ws.store.events()) == 1
    evidence(request, 'J01', mode=mode, original_public_output=expected,
             delivered=observed, adoption_payloads=[o['payload'] for o in adopted],
             input_packet=json.loads(model.calls[0][1][1]), semantic_behavior_tested=False)


@pytest.mark.parametrize('mode', ['inline', 'offload', 'legacy'])
async def test_j01_distinct_indexed_judgments_cache_recovery_and_exact_adoption(ws, monkeypatch, mode, request):
    await writer_case(ws, monkeypatch, mode, request)


@pytest.mark.parametrize('mode', ['inline', 'offload', 'legacy'])
async def test_j01_new_operation_reuses_identical_analysis_without_receipt_collision(ws, monkeypatch, mode, request):
    # Retained RED on the current application: same-material raw cache hit tries
    # to insert the same receipt primary key again. Do not xfail or repair here.
    await writer_case(ws, monkeypatch, mode, request, repeat_operation='new-operation')


def assessment_fixture(outcome):
    completed = outcome != 'blocked'
    return {'items': [{'scope_id': 'rule-comparison',
        'checked_requirement_indexes': [0] if completed else [],
        'execution_state': 'completed' if completed else 'blocked',
        'verdict': outcome if completed else None,
        'reason': 'REASON: adopted score differs from the supplied rule.' if outcome == 'not_satisfied' else
                  ('REASON: the assigned comparison is complete.' if completed else 'REASON: the assigned comparison is unresolved.'),
        'observations': [{'evidence_index': 0, 'locator': 'claim-local',
            'observation': 'OBSERVATION: adopted class B and score 70.',
            'limitations': 'Only this assigned claim was inspected. ' * 100 + 'OBS_LIMIT_TAIL: whole-report quality unassessed.'}],
        'check_results': [{'requirement_index': 0, 'execution_state': 'completed' if completed else 'blocked',
            'result': 'CHECK_RESULT: local comparison record.', 'observation_indexes': [0],
            'remaining': '' if completed else 'REMAINING: obtain the unselected explanation column.'}],
        'coverage': {'checked': ['COVERAGE_CHECKED: selected claim read.'],
            'unchecked': [] if completed else ['COVERAGE_UNCHECKED: explanation column comparison.'],
            'blocked': [] if completed else ['COVERAGE_BLOCKED: original table not selected.'],
            'basis': 'COVERAGE_BASIS: selected original object only.'},
        'findings': [] if outcome == 'satisfied' else [{
            'finding_type': 'confirmed_defect' if completed else 'unresolved',
            'locator_state': 'located', 'description': 'FINDING: independent finding marker, not the reason field.',
            'impact': 'IMPACT: scoped score cannot be accepted.',
            'needed_outcome': 'OUTCOME: resolve this exact comparison.',
            'requirement_index': 0, 'observation_indexes': [0],
            'basis_kind': 'supplied_content' if completed else 'input_gap'}]}]}


async def reviewer_case(ws, monkeypatch, outcome, offload, request):
    cs, _, refs, snapshot, _ = seed(ws)
    original_nodes = cs.list_objects('ContentNode')
    activate(ws)
    force_offload(monkeypatch, offload)
    expected = assessment_fixture(outcome)
    model = Model(json.dumps(expected, ensure_ascii=False))
    observed = []

    def inspect(messages):
        message = reply(messages, 'perform_assigned_review')
        value = packet(message)['metadata']
        saved = cs.read(value['review_ref'])['payload']['items'][0]
        delivered = value['items'][0]
        raw = expected['items'][0]
        for key in ('scope_id', 'checked_requirement_indexes', 'execution_state', 'verdict',
                    'reason', 'coverage', 'check_results', 'findings'):
            assert saved[key] == raw[key]
            assert delivered[key] == raw[key], 'J02_INDEPENDENT_JUDGMENT_LOST:' + key
        assert saved['observations'][0]['limitations'] == raw['observations'][0]['limitations']
        assert delivered['observations'][0]['limitations'] == raw['observations'][0]['limitations'], 'J02_OBSERVATION_LIMITATION_LOST'
        # Saved receipt IDs legitimately replace raw evidence indexes. Basis
        # text and locator must still match their original independent values.
        assert delivered['observations'] == saved['observations']
        for source, stored, actual in zip(raw['observations'], saved['observations'], delivered['observations'], strict=True):
            for field in ('observation', 'locator', 'limitations'):
                assert stored[field] == source[field]
                assert actual[field] == source[field], 'J02_OBSERVATION_FIELD_LOST:' + field
        assert raw['observations'][0]['limitations'] in wire_text(message)
        assert delivered['target_ref'] == refs['claim'] and delivered['criterion_ref'] == refs['k']
        if offload:
            assert message.additional_kwargs.get('report_controls_restored')
        observed.append(deepcopy(value))
        if len(observed) == 1:
            return invoke('perform_assigned_review', operation_id='cached-review', scope_ids=['rule-comparison'],
                          source_selections=[], content_selections=[])
        assert value['reused'] and observed[0]['review_ref'] == value['review_ref']
        return AIMessage(content=json.dumps({'review_ref': value['review_ref'], 'items': value['items']}))

    def parent(messages):
        returned = reply(messages, 'task')
        if offload:
            # Native offload deliberately keeps a prefix and a filesystem path.
            # Recover the exact review by its ID actually present in that prefix;
            # do not take a ref from hidden test/host state as model evidence.
            match = re.search(r'"review_ref": (\{[^}]+\})', str(returned.content))
            assert match and '/large_tool_results/task' in str(returned.content)
            return invoke('read_context', target_ref=json.loads(match.group(1)))
        assert expected['items'][0]['reason'] in str(returned.content)
        return verify_parent(returned)

    def recovered_parent(messages):
        returned = reply(messages, 'read_context')
        recovered = wire_packet(returned)['metadata']['result']['objects'][0]['payload']['items'][0]
        assert recovered['reason'] == expected['items'][0]['reason']
        assert recovered['observations'][0]['limitations'] == expected['items'][0]['observations'][0]['limitations']
        assert recovered['findings'] == expected['items'][0]['findings']
        return verify_parent(returned)

    def verify_parent(returned):
        tasks = cs.list_objects('DelegatedTask')
        status = reconcile(cs, tasks[0]['ref']['id'])
        assert status['execution_complete'] is (outcome != 'blocked')
        assert bool(status['remaining']) is (outcome == 'blocked')
        assert status['semantic_coverage_verified'] is False
        evidence(request, 'J02-parent', status=status, scripted_forwarding=True,
                 actual_parent_input=wire_text(returned), automatic_semantic_summary_tested=False)
        return AIMessage(content='Scoped result received, no whole-report acceptance.')

    args = dict(review_call(snapshot, refs)['args'])
    args.pop('supervision_plugin', None)
    driver = Driver(coordinator=[invoke('task', **args), parent] + ([recovered_parent] if offload else []), reviewer=[
        invoke('perform_assigned_review', operation_id='first-review', scope_ids=['rule-comparison'],
               source_selections=[], content_selections=[]), inspect, inspect])
    result = await deep_runtime.run_report(ws, lambda name: model if name == 'text_tool' else driver(name))
    assert result['last_error'] is None, result
    assert len(model.calls) == 1 and len(observed) == 2
    assert cs.list_objects('ContentNode') == original_nodes
    evidence(request, 'J02', public_output=expected, delivered=observed,
             input_packet=json.loads(model.calls[0][1][1]), artifact_review_R7_covered=False)


@pytest.mark.parametrize('outcome', ['satisfied', 'not_satisfied', 'blocked'])
@pytest.mark.parametrize('offload', [False, True], ids=['inline', 'offload'])
async def test_j02_independent_review_fields_saved_and_delivered(ws, monkeypatch, outcome, offload, request):
    await reviewer_case(ws, monkeypatch, outcome, offload, request)


def source_blocks(ws, blocks):
    manifest = deepcopy(ws.store.manifest)
    manifest['sources'] = [{'id': 's', 'title': 'Synthetic selected evidence',
                           'content': '\n'.join(blocks), 'coverage': 'partial'}]
    ws.store.set('manifest', manifest)
    with ws.store.connect() as db:
        db.execute('delete from source_blocks')
        for n, text in enumerate(blocks):
            db.execute('insert into source_blocks values (?,?,?,?)', ('s', n, f'page {n+1}', text))


def analysis_fixture(q_known=False):
    return ('SUPPORT: source page 1 explicitly establishes A.\n'
            'CONTRADICT: source page 1 contradicts the proposed claim B.\n'
            + ('Q_KNOWN: Q=8 is explicitly supplied on page 1.\n' if q_known else
               'Q_UNKNOWN: Q is not in the selected page; no determined Q value.\n')
            + 'Public extent explanation. ' * 120
            + '\nEXTENT_TAIL: only page 1 read; page 2 unselected does not mean the source lacks it.')


async def analysis_case(ws, role, tool, q_known, request, decision=False):
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    selected = 'A is established. Claim B is false.' + (' Q=8.' if q_known else ' Q not provided here.')
    source_blocks(ws, [selected, 'PAGE2_UNSELECTED: other information exists here.'])
    before = cs.list_objects()
    finding = analysis_fixture(q_known)
    model = Model(finding)
    args = ({'source_id': 's', 'purpose': 'Inspect selected evidence and unknowns.', 'offset': 0, 'limit': 1}
            if tool == 'analyze_text' else {'question': 'Inspect selected evidence and unknowns.',
                'source_selections': [{'source_id': 's', 'offset': 0, 'limit': 1}], 'result_selections': []})
    captured = []

    def inspect_analysis(messages):
        message = reply(messages, tool)
        value = packet(message)['metadata']
        assert value['analysis'] == finding, 'J03_PUBLIC_ANALYSIS_CHANGED'
        assert wire_packet(message)['metadata']['analysis'] == finding
        actual = json.loads(model.calls[0][1][1])
        assert actual['evidence'][0]['observation']['blocks'][0]['text'] == selected
        assert actual['evidence'][0]['selection'] == {'source_id': 's', 'offset': 0, 'limit': 1}
        assert 'PAGE2_UNSELECTED' not in json.dumps(actual)
        captured.append({'tool_result': value, 'input_packet': actual})
        if decision:
            # A test-only deterministic actor deliberately consumes the public
            # observation. This checks action reachability, NOT model judgment.
            if 'Q_UNKNOWN:' in value['analysis']:
                return invoke('read_source_page', source_id='s', offset=1, limit=1)
            return invoke('read_source_page', source_id='s', offset=0, limit=1)
        return AIMessage(content='Complete public analysis retained; no semantic acceptance.')

    def inspect_action(messages):
        value = packet(reply(messages, 'read_source_page'))['metadata']
        expected_offset = 0 if q_known else 1
        assert value['offset'] == expected_offset
        assert value['blocks'][0]['text'] == (selected if q_known else 'PAGE2_UNSELECTED: other information exists here.')
        captured.append({'scripted_action_result': value})
        return AIMessage(content=json.dumps({'q_status': 'supported' if q_known else 'unresolved',
                                            'acceptance': False}))

    await run_role(ws, role, [invoke(tool, **args), inspect_analysis] + ([inspect_action] if decision else []),
                   refs, snapshot, model)
    assert len(model.calls) == 1 and model.response == finding
    # New delegated task is expected; pre-existing objects must be immutable.
    assert all(cs.read(obj['ref']) == obj for obj in before)
    evidence(request, 'J04' if decision else 'J03', role=role, tool=tool, q_known=q_known,
             original_analysis=finding, captured=captured, scripted_actor=decision,
             real_model_judgment_tested=False)


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'layout'])
@pytest.mark.parametrize('tool', ['analyze_text', 'analyze_evidence'])
async def test_j03_support_contradiction_unknown_extent_reach_each_native_consumer(ws, role, tool, request):
    await analysis_case(ws, role, tool, False, request)


@pytest.mark.parametrize('q_known', [False, True], ids=['Q-unknown', 'Q-known'])
async def test_j04_fake_consumer_can_act_on_paired_public_condition(ws, q_known, request):
    await analysis_case(ws, 'writer', 'analyze_evidence', q_known, request, decision=True)


def test_j04_calibrated_semantic_oracle_does_not_claim_model_test(request):
    # The fixed simple scenario permits several next actions. This is a local
    # calibration of the future semantic test oracle, not production policy.
    def acceptable(q_known, decision):
        if not q_known:
            return decision['state'] in {'seek_evidence', 'conditional', 'unresolved'} and decision.get('verified_value') is None
        return decision['state'] in {'seek_evidence', 'conditional', 'supported'}
    controls = [({'state': 'seek_evidence'}, True), ({'state': 'conditional'}, True),
                ({'state': 'unresolved'}, True), ({'state': 'unresolved', 'verified_value': None}, True),
                ({'state': 'unresolved', 'verified_value': 0}, False),
                ({'state': 'supported', 'verified_value': 8}, False)]
    for action, expected in controls:
        assert acceptable(False, action) is expected
    assert acceptable(True, {'state': 'supported', 'verified_value': 8})
    evidence(request, 'J04-calibration', controls=controls, real_model_calls=0,
             limitation='Fake consumer and oracle calibration cannot establish judgment sufficiency or real agent behavior.')


GUIDE = ('| Indicator | Category | Score | Explanation |\n'
         '| geology | B | 75-100 | Apply only when weathering is strong. |\n'
         'FOOTNOTE: classify from the original geological description before choosing the score.')
SHORT_GUIDE = '| Indicator | Category | Score |\n| geology | B | 75-100 |'
GEOLOGY = 'GEOLOGY: strong weathering; category B is explicitly described.'


async def selection_case(ws, route, request):
    cs, owner, refs, snapshot, _ = seed(ws)
    activate(ws)
    source_blocks(ws, [GUIDE, GEOLOGY, SHORT_GUIDE])
    source_ref = cs.import_inputs(owner, 'synthetic-guide', ['s'])['result']['source_refs'][0]
    source_before = deepcopy(cs.read(source_ref))
    if route == 'refs':
        select = {'input_refs': [source_ref]}
    elif route == 'locators':
        select = {'source_selections': [{'source_id': 's', 'offset': 0, 'limit': 2}]}
    elif route == 'geology-only':
        select = {'source_selections': [{'source_id': 's', 'offset': 1, 'limit': 1}]}
    elif route == 'three-columns':
        select = {'source_selections': [{'source_id': 's', 'offset': 2, 'limit': 1}]}
    elif route == 'bad-version':
        select = {'input_refs': [{**source_ref, 'version': source_ref['version'] + 99}]}
    elif route == 'empty-locator':
        select = {'source_selections': [{'source_id': 's', 'offset': 100, 'limit': 1}]}
    else:
        select = {}
    complete = route in {'refs', 'locators', 'observation'}
    expected = {'kind': 'block', 'claim_kind': 'inference', 'body': {'text': 'Synthetic conditional candidate.'},
                'qualifiers': {'state': 'supported_selected_material' if complete else 'unresolved',
                               'limitation': 'Synthetic fixed response, no semantic verification.'}}
    model = Model(json.dumps(expected))
    observed = []

    def select_after_read(messages):
        shown = packet(reply(messages, 'read_source_page'))
        raw = json.loads(ws.store.get('tool_observation:' + shown['observation_ref'])['text'])
        assert raw['blocks'][0]['text'] == GUIDE
        args = {'observation_refs': [shown['observation_ref']]} if route == 'observation' else select
        observed.append({'read_receipt': shown['observation_ref'], 'selected_args': args})
        return invoke('process_report_content', operation_id='selected', object_type='ContentNode',
                      objective='Use selected guide and preserve conditions.', **args)

    def inspect_packet(messages):
        returned = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'process_report_content')
        value = packet(returned)
        if route in {'bad-version', 'empty-locator'}:
            assert not model.calls
            assert value['status'] == 'error'
            assert value['metadata']['code'] == ('NOT_FOUND' if route == 'bad-version' else 'EVIDENCE_SOURCE_SELECTION_EMPTY')
            observed.append({'rejection': value})
            return AIMessage(content='Selected material rejected before model; no claim of absence.')
        actual = json.loads(model.calls[0][1][1])
        entries = actual['evidence']
        texts = []
        for item in entries:
            if item['kind'] == 'saved_object':
                assert item['object']['ref'] == source_ref
                texts.append(item['object']['payload']['content'])
            elif item['kind'] == 'source_blocks':
                texts.extend(b['text'] for b in item['observation']['blocks'])
            elif item['kind'] == 'public_tool_return':
                assert item['observation_ref'] == observed[0]['read_receipt']
                texts.extend(b['text'] for b in json.loads(item['text'])['blocks'])
        supplied = '\n'.join(texts)
        if complete:
            assert GUIDE in supplied, 'I01_SELECTED_GUIDE_CHANGED'
        else:
            assert GUIDE not in supplied and 'FOOTNOTE:' not in supplied
            assert ('GEOLOGY:' in supplied) is (route == 'geology-only')
            assert ('| Indicator | Category | Score |' in supplied) is (route == 'three-columns')
        assert value['metadata']['outputs']['entries'][0]['qualifiers'] == expected['qualifiers']
        observed.append({'actual_packet': actual, 'selected_texts': texts})
        return AIMessage(content='Selection verified; fake result does not prove model detected missing material.')

    await run_role(ws, 'writer', [invoke('read_source_page', source_id='s', offset=0, limit=2),
                                 select_after_read, inspect_packet], refs, snapshot, model)
    assert cs.read(source_ref) == source_before
    assert len(model.calls) == (0 if route in {'bad-version', 'empty-locator'} else 1)
    evidence(request, 'I01', route=route, original_guide=GUIDE, observations=observed,
             strategy_selection_tested=False, automatic_inheritance_assumed=False)


@pytest.mark.parametrize('route', ['refs', 'locators', 'observation', 'geology-only', 'three-columns', 'bad-version', 'empty-locator'])
async def test_i01_read_then_explicit_selection_matches_actual_independent_packet(ws, route, request):
    await selection_case(ws, route, request)


@pytest.mark.parametrize('fault', ['writer-second-tail', 'writer-swap-indexes', 'review-limitations',
                                  'review-findings', 'analysis-tail', 'analysis-contradiction', 'selected-footnote'])
async def test_public_judgment_oracles_detect_post_output_program_information_loss(ws, monkeypatch, fault, request):
    sites, injected, assertion_messages = [], [], []
    original_respond = Driver.respond

    async def capture(self, role, messages):
        try:
            return await original_respond(self, role, messages)
        except AssertionError as exc:
            sites.extend({'function': f.name, 'line': f.line} for f in traceback.extract_tb(exc.__traceback__))
            assertion_messages.append(str(exc))
            raise
    monkeypatch.setattr(Driver, 'respond', capture)
    if fault == 'selected-footnote':
        original_selected = text_work.selected_evidence

        def corrupt_selected(*args, **kwargs):
            raw = original_selected(*args, **kwargs)
            value = deepcopy(raw)
            value[0]['observation']['blocks'][0]['text'] = GUIDE.split('\nFOOTNOTE:')[0]
            injected.append({'original': raw, 'changed': value})
            return value
        monkeypatch.setattr(text_work, 'selected_evidence', corrupt_selected)
        run = selection_case(ws, 'locators', request)
        expected_site = 'inspect_packet'
        expected_marker = 'I01_SELECTED_GUIDE_CHANGED'
    else:
        original = decision_data.public_value

        def corrupt(tool, value):
            shown, complete = original(tool, value)
            shown = deepcopy(shown)
            if fault.startswith('writer-') and tool == 'process_report_content':
                entries = shown['outputs']['entries']
                if fault == 'writer-second-tail':
                    entries[1]['qualifiers']['limitations'] = entries[1]['qualifiers']['limitations'][:240]
                else:
                    entries[0]['qualifiers'], entries[1]['qualifiers'] = entries[1]['qualifiers'], entries[0]['qualifiers']
                injected.append(tool)
            elif fault.startswith('review-') and tool == 'perform_assigned_review':
                if fault == 'review-limitations':
                    shown['items'][0]['observations'][0]['limitations'] = ''
                else:
                    shown['items'][0]['findings'] = []
                injected.append(tool)
            elif fault.startswith('analysis-') and tool == 'analyze_evidence':
                shown['analysis'] = (shown['analysis'].split('\nEXTENT_TAIL:')[0] if fault == 'analysis-tail'
                    else shown['analysis'].replace('CONTRADICT: source page 1 contradicts', 'SUPPORT: source page 1 supports'))
                injected.append(tool)
            return shown, complete
        monkeypatch.setattr(decision_data, 'public_value', corrupt)
        if fault.startswith('writer-'):
            run, expected_site = writer_case(ws, monkeypatch, 'inline', request), 'inspect_candidates'
            expected_marker = 'J01_INDEXED_QUALIFIERS_LOST'
        elif fault.startswith('review-'):
            run, expected_site = reviewer_case(ws, monkeypatch, 'not_satisfied', False, request), 'inspect'
            expected_marker = ('J02_OBSERVATION_LIMITATION_LOST' if fault == 'review-limitations'
                               else 'J02_INDEPENDENT_JUDGMENT_LOST:findings')
        else:
            run, expected_site = analysis_case(ws, 'writer', 'analyze_evidence', False, request), 'inspect_analysis'
            expected_marker = 'J03_PUBLIC_ANALYSIS_CHANGED'
    with pytest.raises(AssertionError):
        await run
    assert injected, 'Fault did not reach the intended program boundary'
    assert any(s['function'] == expected_site for s in sites), sites
    assert any(expected_marker in message for message in assertion_messages), assertion_messages
    evidence(request, 'sensitivity', fault=fault, assertion_sites=sites, injected=injected,
             oracle_marker=expected_marker, memory_only=True, application_repair=False, current_bug_proved=False)
