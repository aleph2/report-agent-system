"""Real registered boundaries with fake one-shot services; not semantic acceptance."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import business_tools, build_agent
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.text_work import AdoptionObject
from test_bounded_review import Model
from test_deep_runtime import Driver, call, invoke, observation
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def content(kind="block"):
    return {"kind": kind, "body": {"text": "The supplied rule permits the stated interval."},
            "qualifiers": {"conditions": "Only the selected material was used."}, "claim_kind": "fact"}


def tools(ws, role, model):
    return {t.__name__: t for t in business_tools(ws, role, None, model)}


def writer_call(id="writer"):
    return call("task", {"subagent_type": "writer", "description": "Produce the scoped report content."}, id)


async def test_tool_produces_without_business_write_and_writer_adopts_exact_payload(ws):
    cs, _, refs, _, _ = seed(ws)
    model = Model(json.dumps(content()))
    before = cs.list_objects("ContentNode")
    with delegated_task(ws, "coordinator", writer_call()) as (_, actor):
        t = tools(ws, "writer", model)
        work = await t["process_report_content"]("one", "Describe the supplied rule", "ContentNode", [refs["claim"]])
        assert cs.list_objects("ContentNode") == before
        saved = t["save_text_node"]("adopt", work["text_work_id"])
        node = cs.read(saved["result"]["refs"]["text"])
        assert node["payload"] == content() and node["owner_id"] == actor.id
        assert not work["semantic_correctness_verified"]
        again = await t["process_report_content"]("one", "Describe the supplied rule", "ContentNode", [refs["claim"]])
        assert again["reused"] and len(model.calls) == 1


@pytest.mark.parametrize("payload", [
    content(),
    {"kind": "table", "body": {"columns": ["Issue"], "rows": [["A source conflict"]], "title": "Located issue"},
     "qualifiers": {"conditions": "Selected case"}, "claim_kind": "inference"},
    {"kind": "figure", "body": {"source_id": "s", "caption": "A substantive caption", "page": 1},
     "qualifiers": {}, "claim_kind": "fact"},
])
async def test_all_semantic_payload_fields_are_receipt_bound_and_cannot_be_rewritten(ws, payload):
    cs, _, refs, _, _ = seed(ws)
    model = Model(json.dumps(payload))
    with delegated_task(ws, "coordinator", writer_call()) as (_, actor):
        t = tools(ws, "writer", model)
        with pytest.raises(ActionRejected, match="REQUIRES_TEXT_WORK"):
            t["commit_objects"]("raw", [AdoptionObject(client_key="node", type="ContentNode", payload=payload)])
        work = await t["process_report_content"]("produce", "Produce the requested selected content", "ContentNode", [refs["claim"]])
        changed = deepcopy(payload)
        changed["qualifiers"]["invented"] = "A new factual assertion"
        with pytest.raises(ActionRejected, match="OUTPUT_CHANGED"):
            t["commit_objects"]("changed", [AdoptionObject(client_key="node", type="ContentNode",
                payload=changed, text_work_id=work["text_work_id"])])
        if payload["kind"] == "table":
            changed = deepcopy(payload); changed["body"]["rows"][0][0] = "A different issue"
            with pytest.raises(ActionRejected, match="OUTPUT_CHANGED"):
                t["commit_objects"]("changed-cell", [AdoptionObject(client_key="node", type="ContentNode",
                    payload=changed, text_work_id=work["text_work_id"])])
        saved = t["commit_objects"]("exact", [AdoptionObject(client_key="node", type="ContentNode", text_work_id=work["text_work_id"])])
        assert cs.read(saved["result"]["refs"]["node"])["payload"] == payload


async def test_receipts_do_not_expand_role_task_or_revision_ownership(ws):
    cs, _, refs, _, _ = seed(ws)
    model = Model(json.dumps(content()))
    with delegated_task(ws, "coordinator", writer_call("first")) as (_, first):
        t = tools(ws, "writer", model)
        work = await t["process_report_content"]("work", "Describe the selected evidence", "ContentNode", [refs["claim"]])
        saved = t["save_text_node"]("save", work["text_work_id"])
    with delegated_task(ws, "coordinator", writer_call("other")):
        with pytest.raises(ActionForbidden, match="another task"):
            tools(ws, "writer", model)["save_text_node"]("steal", work["text_work_id"])
    with pytest.raises(ActionForbidden, match="authorship"):
        await tools(ws, "coordinator", model)["process_report_content"]("coordinator", "Write report", "ContentNode", [refs["claim"]])
    assert cs.read(saved["result"]["refs"]["text"])["owner_id"] == first.id


@pytest.mark.parametrize("answer", ["invalid JSON", RuntimeError("synthetic timeout")])
async def test_failed_or_unknown_work_is_preserved_without_semantic_retry(ws, answer):
    cs, _, refs, _, _ = seed(ws)
    model = Model(answer)
    with delegated_task(ws, "coordinator", writer_call()):
        t = tools(ws, "writer", model)
        with pytest.raises(Exception):
            await t["process_report_content"]("attempt", "Describe evidence", "ContentNode", [refs["claim"]])
        with pytest.raises(ActionRejected, match="PREVIOUS_OUTPUT_REJECTED" if isinstance(answer, str) else "UNRESOLVED"):
            await t["process_report_content"]("attempt", "Describe evidence", "ContentNode", [refs["claim"]])
        assert len(model.calls) == 1


def test_structure_decisions_do_not_require_text_model_but_are_not_body_bypass(ws):
    cs, _, _, _, _ = seed(ws)
    with delegated_task(ws, "coordinator", writer_call()):
        t = tools(ws, "writer", Model())
        heading = {"kind": "chapter", "body": {"text": "Source evidence"}, "qualifiers": {}, "claim_kind": "structure"}
        t["commit_objects"]("heading", [AdoptionObject(client_key="chapter", type="ContentNode", payload=heading)])
        heading["body"]["text"] += "\nA substantive report paragraph"
        with pytest.raises(ActionRejected, match="REQUIRES_TEXT_WORK"):
            t["commit_objects"]("body-in-heading", [AdoptionObject(client_key="chapter", type="ContentNode", payload=heading)])


def test_active_reviewer_has_only_independent_semantic_publication_routes(ws):
    seed(ws)
    names = set(tools(ws, "reviewer", Model()))
    assert {"perform_assigned_review", "perform_assigned_artifact_review"} <= names
    assert not {"submit_review", "submit_artifact_review", "correct_own_review"} & names


@pytest.mark.parametrize("entrypoint", ["non-hierarchical", "native-rubric-v1"])
def test_old_agent_loop_is_inactive_before_model_factory_or_business_write(ws, entrypoint):
    manifest = ws.store.manifest
    if entrypoint == "non-hierarchical":
        manifest.pop("content_contract")
    else:
        manifest["review_entrypoint"] = entrypoint
    ws.store.set("manifest", manifest)
    def forbidden(role):
        pytest.fail("Retired loop must not construct an agent/model")
    with pytest.raises(ActionRejected, match="HISTORICAL_AGENT_EXECUTION_INACTIVE"):
        build_agent(ws, forbidden, None)


async def test_real_native_graph_uses_independent_service_before_saving_owned_body(ws):
    from report_agent.deep_runtime import run_report
    from report_agent.content_store import ContentStore
    def save_work(messages):
        work = observation(messages, "process_report_content")
        return invoke("save_text_node", operation_id="save-native", text_work_id=work["text_work_id"])
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[writer_call()]),
        AIMessage(content="Actual saved output is available; no acceptance claimed.")],
        writer=[invoke("process_report_content", operation_id="produce-native", objective="Describe the selected rule",
            object_type="ContentNode", source_selections=[{"source_id": "s"}]), save_work,
            AIMessage(content="Saved exact tool payload; substantive verification remains open.")],
        text_tool=[AIMessage(content=json.dumps(content()))])
    result = await run_report(ws, driver)
    assert result["last_error"] is None, result
    nodes = ContentStore(ws.store).list_objects("ContentNode")
    assert len(nodes) == 1 and nodes[0]["payload"] == content()
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == 1
    assert nodes[0]["owner_id"].startswith("content:writer:")


@pytest.mark.parametrize('field,value', [('result', {'invented_score': 99}), ('method', 'invented'),
    ('tool_receipt', 'invented'), ('input_refs', [{'type': 'Evidence', 'id': 'invented', 'version': 1}]),
    ('extraction_ref', {'type': 'Extraction', 'id': 'invented', 'version': 1})])
def test_literal_excerpt_cannot_smuggle_derived_fields(ws, field, value):
    cs, _, _, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    with delegated_task(ws, 'coordinator', writer_call()):
        t = tools(ws, 'writer', Model())
        literal = {'source_refs': [source], 'locator': 'source text', 'excerpt': 'Class B permits 75 to 100.'}
        t['commit_objects']('literal', [AdoptionObject(client_key='e', type='Evidence', payload=literal)])
        with pytest.raises(ActionRejected, match='DERIVED_EVIDENCE'):
            t['commit_objects']('smuggled', [AdoptionObject(client_key='e', type='Evidence', payload={**literal, field: value})])


async def test_one_bounded_batch_preserves_distinct_nodes_and_exact_index(ws):
    cs, _, refs, _, _ = seed(ws)
    blocks = [content(), {**content(), 'body': {'text': 'A separate related report block.'}}]
    model = Model(json.dumps(blocks))
    with delegated_task(ws, 'coordinator', writer_call()):
        t = tools(ws, 'writer', model)
        work = await t['process_report_content']('batch', 'Produce two related blocks in supplied order',
            'ContentNode', [refs['claim']], output_count=2)
        saved = t['commit_objects']('adopt-batch', [AdoptionObject(client_key=str(i), type='ContentNode',
            text_work_id=work['text_work_id'], text_work_index=i) for i in range(2)])
        assert [cs.read(saved['result']['refs'][str(i)])['payload'] for i in range(2)] == blocks
        # A revision retains the first original identity, not a merged replacement.
        previous = saved['result']['refs']['0']
        revised = t['save_text_node']('same-identity', work['text_work_id'], previous, 0)
        assert revised['result']['refs']['text']['id'] == previous['id']
        with pytest.raises(ActionRejected, match='INDEX_INVALID'):
            t['save_text_node']('wrong-index', work['text_work_id'], text_work_index=2)
        assert len(model.calls) == 1


async def test_long_source_version_uses_located_fragments_without_whole_file(ws):
    from report_agent.content_store import ContentStore
    manifest = ws.store.manifest
    manifest['sources'][0]['content'] += '\n' + ('Unselected original source details.\n' * 4000)
    ws.store.set('manifest', manifest)
    cs = ContentStore(ws.store)
    captured = cs.import_inputs(actor_for('coordinator'), 'capture-long', ['s'])
    source = captured['result']['source_refs'][0]
    evidence = {'source_refs': [source], 'locator': 'selected block 0', 'excerpt': 'Class B permits 75 to 100.'}
    model = Model(json.dumps(evidence))
    with delegated_task(ws, 'coordinator', writer_call()):
        t = tools(ws, 'writer', model)
        work = await t['process_report_content']('located', 'Extract the selected rule', 'Evidence',
            [source], [{'source_id': 's', 'offset': 0, 'limit': 1}])
        packet = json.loads(model.calls[0][1][1])
        assert 'content' not in packet['evidence'][0]['object']['payload']
        assert len(json.dumps(packet)) < 64000
        saved = t['commit_objects']('located-evidence', [AdoptionObject(client_key='e', type='Evidence', text_work_id=work['text_work_id'])])
        assert cs.read(saved['result']['refs']['e'])['payload']['source_refs'] == [source]


@pytest.mark.parametrize('finish', ['length', 'content_filter'])
async def test_known_incomplete_json_never_becomes_adoptable(ws, finish):
    cs, _, refs, _, _ = seed(ws)
    class Incomplete(Model):
        async def ainvoke(self, messages):
            self.calls.append(messages)
            return AIMessage(content=json.dumps(content()), response_metadata={'finish_reason': finish})
    model = Incomplete()
    with delegated_task(ws, 'coordinator', writer_call()):
        t = tools(ws, 'writer', model)
        with pytest.raises(ActionRejected, match='INCOMPLETE_OR_INVALID'):
            await t['process_report_content']('incomplete', 'Produce selected prose', 'ContentNode', [refs['claim']])
        with pytest.raises(ActionRejected, match='UNRESOLVED'):
            await t['process_report_content']('incomplete', 'Produce selected prose', 'ContentNode', [refs['claim']])
    rejected = [e for e in ws.store.events() if e['kind'] == 'evidence_analysis_rejected_response']
    assert rejected[0]['data']['content'] == json.dumps(content()) and len(model.calls) == 1


async def test_public_retired_entrypoints_leave_status_and_checkpoints_unchanged(ws):
    from report_agent.deep_runtime import run_report, project_agent
    from report_agent.runtime import run_task
    from report_agent.report_runtime import run_report as old_run
    manifest = ws.store.manifest
    manifest.pop('content_contract')
    ws.store.set('manifest', manifest)
    ws.store.set('report_status', 'historical_terminal')
    ws.store.set('report_error', {'type': 'preserved'})
    events = ws.store.events()
    for attempt in (lambda: run_report(ws), lambda: run_task(ws.store), lambda: old_run(ws)):
        with pytest.raises(ActionRejected, match='HISTORICAL_AGENT_EXECUTION_INACTIVE'):
            await attempt()
    with pytest.raises(ActionRejected, match='HISTORICAL_AGENT_EXECUTION_INACTIVE'):
        async with project_agent(ws):
            pytest.fail('Old agent must never be built')
    assert ws.store.get('report_status') == 'historical_terminal'
    assert ws.store.get('report_error') == {'type': 'preserved'}
    assert ws.store.events() == events and not (ws.store.root / 'checkpoints.db').exists()


async def test_real_native_decision_observation_stops_before_text_service_and_cannot_resume(ws):
    from report_agent.deep_runtime import run_report
    from report_agent.content_store import ContentStore
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[writer_call()]), AIMessage(content='Observed decision.')],
        writer=[invoke('process_report_content', operation_id='unexecuted', objective='Describe selected rule',
            object_type='ContentNode', source_selections=[{'source_id': 's'}])],
        text_tool=[AIMessage(content=json.dumps(content()))])
    result = await run_report(ws, driver, decision_only=True)
    assert result['last_error'] is None, result
    observed = ws.store.get('decision_observation')
    assert observed['executed'] is False and observed['tool_call']['args']['objective'] == 'Describe selected rule'
    assert not any(role == 'text_tool' for role, _, _ in driver.calls)
    assert not ContentStore(ws.store).list_objects('ContentNode')
    before = len(driver.calls)
    with pytest.raises(ActionRejected, match='DECISION_OBSERVATION_TERMINAL'):
        await run_report(ws, driver)
    assert len(driver.calls) == before
    from report_agent.deep_runtime import project_agent
    with pytest.raises(ActionRejected, match='DECISION_OBSERVATION_TERMINAL'):
        build_agent(ws, driver, None, decision_only=False)
    with pytest.raises(ActionRejected, match='DECISION_OBSERVATION_TERMINAL'):
        async with project_agent(ws, driver, decision_only=False):
            pytest.fail('Terminal observation cannot create another executable graph')


async def test_already_constructed_graph_cannot_resume_unexecuted_observation(ws):
    from report_agent.deep_runtime import project_agent
    from langgraph.types import Command
    driver = Driver(coordinator=[invoke('analyze_text', source_id='s', purpose='Compare selected source')],
        text_tool=[AIMessage(content='Must never execute')])
    config = {'configurable': {'thread_id': 'terminal-decision'}}
    async with project_agent(ws, driver, decision_only=True) as graph:
        await graph.ainvoke({'messages': [('user', 'Choose useful source comparison')]}, config)
        assert ws.store.get('decision_observation')['executed'] is False
        with pytest.raises(ActionRejected, match='DECISION_OBSERVATION_TERMINAL'):
            await graph.ainvoke(Command(resume=True), config)
    assert not any(role == 'text_tool' for role, _, _ in driver.calls)


@pytest.mark.parametrize('tool_name', ['analyze_text', 'analyze_evidence'])
@pytest.mark.parametrize('answer', ['length', 'refusal', 'unknown'])
async def test_all_registered_source_analyses_reject_incomplete_and_do_not_replay(ws, tool_name, answer):
    class Failed(Model):
        async def ainvoke(self, messages):
            self.calls.append(messages)
            if answer == 'unknown':
                raise RuntimeError('Synthetic unknown transport outcome')
            return AIMessage(content='Partial local observation',
                response_metadata={'finish_reason': 'length'} if answer == 'length' else {},
                additional_kwargs={'refusal': 'Synthetic refusal'} if answer == 'refusal' else {})
    model = Failed()
    if tool_name == 'analyze_evidence':
        # Historical read-only reviewer helper is retained, but its agent loop
        # is inactive. Native Reviewer uses assigned bounded comparison instead.
        manifest = ws.store.manifest
        manifest.pop('content_contract')
        ws.store.set('manifest', manifest)
        tool = tools(ws, 'reviewer', model)[tool_name]
    else:
        tool = tools(ws, 'coordinator', model)[tool_name]
    args = ('s', 'Compare actual supplied text') if tool_name == 'analyze_text' else (
        'Compare actual supplied text', [{'source_id': 's'}], [])
    with pytest.raises((ActionRejected, RuntimeError)):
        await tool(*args)
    with pytest.raises(ActionRejected, match='PREVIOUS_ATTEMPT_UNRESOLVED'):
        await tool(*args)
    assert len(model.calls) == 1


async def test_text_tool_cannot_make_up_calculation_receipt_in_derived_evidence(ws):
    cs, _, _, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    answer = {'source_refs': [source], 'locator': 'Source text', 'excerpt': 'Class B permits 75 to 100.',
        'tool_receipt': 'invented-calculation', 'method': 'sum_products', 'result': 90}
    with delegated_task(ws, 'coordinator', writer_call()):
        model = Model(json.dumps(answer))
        tool = tools(ws, 'writer', model)['process_report_content']
        with pytest.raises(ActionRejected, match='OUTPUT_CONTRACT_INVALID.*tool_receipt'):
            await tool('fake-calc', 'Compare selected rule', 'Evidence', [source])
        with pytest.raises(ActionRejected, match='PREVIOUS_OUTPUT_REJECTED'):
            await tool('fake-calc', 'Compare selected rule', 'Evidence', [source])
        assert len(model.calls) == 1


def test_deterministic_calculation_adoption_matches_owned_result_and_needs_no_llm(ws):
    cs, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()):
        t = tools(ws, 'writer', Model())
        observed = t['observe_evidence']('calculation', terms=[['1', '2']])
        evidence = {'source_refs': [], 'input_refs': [refs['claim']], 'locator': 'Selected calculation',
            'excerpt': '', 'method': 'sum_products', 'tool_receipt': observed['receipt_id'], 'result': '2'}
        evidence['result'] = observed['result']['result']
        saved = t['commit_objects']('calc', [AdoptionObject(client_key='calc', type='Evidence', payload=evidence)])
        assert cs.read(saved['result']['refs']['calc'])['payload']['result'] == evidence['result']
        with pytest.raises(ActionRejected, match='EXACT_OWNED_RECEIPT'):
            t['commit_objects']('fake', [AdoptionObject(client_key='calc', type='Evidence', payload={**evidence, 'result': 'invented'})])


@pytest.mark.parametrize('reference_delivery', [False, True])
async def test_native_scoped_trunk_adopts_batch_and_exports_same_snapshot_word_and_xlsx(ws, reference_delivery):
    from io import BytesIO
    from docx import Document
    from openpyxl import load_workbook
    from report_agent.deep_runtime import run_report
    from report_agent.content_store import ContentStore
    from report_agent.content_export import _bytes
    if reference_delivery:
        from test_decision_data import activate
        activate(ws)

    def returned(messages, name):
        value = observation(messages, name)
        return value['metadata'] if value.get('representation') == 'exact-public-result-v2' else value
    blocks = [content(), {'kind': 'table', 'body': {'columns': ['Issue', 'Source'],
        'rows': [['Unknown source date', 's']], 'title': 'Unresolved issues'},
        'qualifiers': {}, 'claim_kind': 'inference'},
        {'kind': 'block', 'body': {'text': 'Confirm the source date before using a dated conclusion.'},
         'qualifiers': {}, 'claim_kind': 'recommendation'}]
    def commit_batch(messages):
        work = returned(messages, 'process_report_content')
        objects = [{'client_key': 'root', 'type': 'ContentNode', 'payload': {
            'kind': 'report', 'body': {'text': 'Synthetic scoped report'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
            *[{'client_key': str(i), 'type': 'ContentNode', 'text_work_id': work['text_work_id'],
               'text_work_index': i} for i in range(3)],
            {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'root'},
                'object_ref': {'client_key': '0'}, 'predicate': 'contains', 'position': 0,
                'provenance_kind': 'adopted_during_generation'}}]
        return invoke('commit_objects', operation_id='save-batch', objects=objects)
    def freeze(messages):
        saved = returned(messages, 'commit_objects')['result']['refs']
        return invoke('freeze_snapshot', operation_id='freeze-scoped', root_ref=saved['root'],
            refs=list(saved.values()), workbook_refs=[saved['1'], saved['2']])
    def word(messages):
        snap = returned(messages, 'freeze_snapshot')['result']['snapshot_ref']
        return invoke('export_content_snapshot', operation_id='word', snapshot_ref=snap)
    def excel(messages):
        saved = returned(messages, 'commit_objects')['result']['refs']
        snap = returned(messages, 'freeze_snapshot')['result']['snapshot_ref']
        export = returned(messages, 'export_content_snapshot')['result']['export_ref']
        return invoke('export_content_workbook', operation_id='xlsx', snapshot_ref=snap,
            sheets=[{'name': 'Issues', 'table_ref': saved['1'], 'note_refs': [saved['2']]}], report_export_ref=export)
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[writer_call('scoped-trunk')]),
        AIMessage(content='Scoped exports saved; no review/engineering acceptance.')],
        writer=[invoke('process_report_content', operation_id='trunk-batch', objective='Produce the scoped report block, issues table and separate note in that order',
            object_type='ContentNode', source_selections=[{'source_id': 's'}], output_count=3),
            commit_batch, freeze, word, excel, AIMessage(content='Saved exact candidate output and linked exports.')],
        text_tool=[AIMessage(content=json.dumps(blocks))])
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    cs = ContentStore(ws.store)
    exports = cs.list_objects('ExportArtifact')
    assert len(exports) == 2 and len({json.dumps(e['payload']['snapshot_ref'], sort_keys=True) for e in exports}) == 1
    for saved in exports:
        payload = saved['payload']
        data = _bytes(ws.store, payload['file_ref'], payload['file_digest'])
        if payload['file_ref'].endswith('.docx'):
            text = '\n'.join(p.text for p in Document(BytesIO(data)).paragraphs)
            assert blocks[0]['body']['text'] in text and 'Unknown source date' not in text
        else:
            workbook = load_workbook(BytesIO(data))
            values = [v for row in workbook['Issues'].iter_rows(values_only=True) for v in row if v is not None]
            assert 'Unknown source date' in values and blocks[2]['body']['text'] in values
    assert not cs.list_objects('ReviewRecord')
    assert sum(role == 'text_tool' for role, _, _ in driver.calls) == 1
