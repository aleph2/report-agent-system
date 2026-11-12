"""R1-A handle-capable internal reads; no runtime interface activation."""
from copy import deepcopy
import hashlib
import json
import socket
from types import SimpleNamespace
from typing import get_type_hints

import pytest
from langchain.tools import tool
from langchain_core.tools import BaseTool
from langchain_core.messages import ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from report_agent.content_models import Ref
from report_agent.content_selection import ContentSelection
from report_agent.content_store import Actor, ContentStore
from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import content_tools
from report_agent.source_materials import verify
from report_agent.store import Store, encode, digest
from test_deliverable_declaration_v4 import case
from test_review_handles import bound_review
from test_selected_companion_reviews import pair, ws
from test_review_message import export_unit


@pytest.fixture(autouse=True)
def no_external_model(monkeypatch):
    def refused(*args, **kwargs):
        pytest.fail('R1-A uses existing offline models only; external network is forbidden')
    monkeypatch.setattr(socket.socket, 'connect', refused)


# Actual rc3 schemas captured from e19849a, not the new factory or a new assembler.
RC3_SCHEMAS = {
    'read_context': 'd99a4438222422b99a87b749008f9f95b69339d46774641703d102e5ab798989',
    'read_content_index': '1e30bf524f3bf6ebd76fcd7807ce67cbab8947f039832e4579bd0936da2ad8fd',
    'read_content_selection': '477e0a7ed032abbcafb34758cfb0f21c6240451229461c7ee522d0ebcc81667b',
    'observe_evidence': '4c53155b5c06fb0de19fef152d02954577ef1700ac77578aa3f986d44212ffea',
    'read_content_export': '33778be5fcc72a59f0ea1dce0266f907aff16718feca499125f133585e56d60f',
    'inspect_rendered_page': 'd240363f038e6e0fd962716e928fe4b6df9619659189d111f75544abac02059a',
    'read_source_page': '556cd247d74b2445a5ec07a8c1d056f315d1127223d5aa6f3568ed5488033c3f',
    'search_sources': '1e572d9761d991676c32681c625888c373bcbc4754263f59b922e473cbf8b975',
    'inspect_source_page': '680b8deee9548391e63bc8babf88ee32090fdf122279e69ae5fe0ff07d661a87',
    'analyze_source_image': '06d508de131ad25d3c67872cd6127f692a6f9f30a8d8aef6e985cd3f4a396b69',
    'analyze_evidence': 'f9e9f950fb56467af9245b128c839cf587f40442d12a118cca83450499f0a60f'}


def tool_name(value):
    return getattr(value, '__name__', getattr(value, 'name', ''))


def schema(value):
    return convert_to_openai_tool(value if isinstance(value, BaseTool) else tool(value))


def assert_owned_receipt(cs, workspace, actor, value, name):
    from report_agent import review_handles as h
    public = json.loads(value.content) if isinstance(value, ToolMessage) else value
    assert h.resolve(cs, actor, 'evidence', public['evidence_handle']) == public['receipt_id']
    if isinstance(value, ToolMessage):
        verify(workspace, actor, value.artifact['source_material']['receipt'], value.content, name)
    return public


def named(tools, name):
    return next(t for t in tools if tool_name(t) == name)


def test_default_read_shape_and_schema_remain_legacy_and_handle_path_is_explicit(case):
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        default = content_tools(ws, 'reviewer')
        disabled = content_tools(ws, 'reviewer', reviewer_handles=False)
        assert [schema(t) for t in default] == [schema(t) for t in disabled]
        catalog = default + business_tools(ws, 'reviewer', None, None)
        expected = {**RC3_SCHEMAS,
            'analyze_source_image': '6f4cce1fdee81e7c2eab8e9bb21439c7ec0ccd0acd833376a6ac9a680c71b53d'}
        assert {tool_name(t): digest(schema(t)) for t in catalog if tool_name(t) in RC3_SCHEMAS} == expected
        old = named(default, 'read_context')
        assert get_type_hints(old)['target_ref'] is Ref
        value = old(Ref.model_validate(output['refs']['a-body']))
        assert set(value) == {'ok', 'result', 'receipt_id'} and 'evidence_handle' not in value
        expected = {'ok': True, 'receipt_id': value['receipt_id'], 'result': {
            'target_ref': output['refs']['a-body'], 'objects': [cs.read(output['refs']['a-body'])],
            'loaded_refs': [output['refs']['a-body']], 'total': 1, 'next_offset': None, 'unreturned_refs': []}}
        assert encode(value) == encode(expected)
        assert 'reviewer_interface' not in cs.store.manifest
        enabled = content_tools(ws, 'reviewer', reviewer_handles=True)
        # Foundations do not register Step4/5 tools in either catalog.
        assert {tool_name(t) for t in enabled} == {tool_name(t) for t in default}
        original = deepcopy(value)
        from report_agent import review_handles as h
        projected = h.project_read(cs, actor, value)
        assert value == original and projected['receipt_id'] == value['receipt_id']
        assert h.resolve(cs, actor, 'evidence', projected['evidence_handle']) == value['receipt_id']


def test_new_read_accepts_handle_and_index_exposes_frozen_tree_without_changing_material(case):
    from report_agent import review_handles as h
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        tools = content_tools(ws, 'reviewer', reviewer_handles=True)
        value = named(tools, 'read_context')('S1.1')
        assert value['result']['target_ref'] == output['refs']['a-body']
        assert value['result']['objects'][0] == cs.read(output['refs']['a-body'])
        assert h.resolve(cs, actor, 'evidence', value['evidence_handle']) == value['receipt_id']
        snap = Ref.model_validate(task['payload']['review_snapshot_ref'])
        index = named(tools, 'read_content_index')(snap)
        nodes = index['result']['snapshot_structure']['nodes']
        assert next(n for n in nodes if n['ref'] == output['refs']['a-body'])['handle'] == 'S1.1'
        selected = named(tools, 'read_content_selection')(snap,
            [{'ref': 'S1.1', 'unit': 'text', 'offset': 0, 'limit': 3}])
        assert selected['result']['selections'][0]['body']['text'] == cs.read(output['refs']['a-body'])['payload']['body']['text'][:3]
        assert h.resolve(cs, actor, 'evidence', selected['evidence_handle']) == selected['receipt_id']


def test_short_content_handle_cannot_be_interpreted_under_another_snapshot(case):
    with bound_review(case) as (cs, workspace, actor, receipt, task, output):
        original = cs.read(task['payload']['review_snapshot_ref'])['payload']
        different = cs.freeze(case[2], 'r1a-another-identical-tree', original['root_ref'], original['refs'],
            workbook_refs=original.get('workbook_refs', []))['result']['snapshot_ref']
        assert different != task['payload']['review_snapshot_ref']
        read = named(content_tools(workspace, 'reviewer', reviewer_handles=True), 'read_content_selection')
        with pytest.raises(ActionRejected):
            read(Ref.model_validate(different), [{'ref': 'S1.1', 'unit': 'text', 'offset': 0, 'limit': 3}])
        # Explicit old Ref selection keeps its preexisting semantics; the new
        # guard constrains contextual short aliases, not all project reading.
        selected = read(Ref.model_validate(different), [ContentSelection.model_validate({
            'ref': output['refs']['a-body'], 'unit': 'text', 'offset': 0, 'limit': 3})])
        assert selected['result']['snapshot_ref'] == different
        assert selected['result']['selections'][0]['body']['text'] == cs.read(output['refs']['a-body'])['payload']['body']['text'][:3]


def test_native_source_handle_is_inside_signed_final_text_and_survives_reopen(case):
    from report_agent import review_handles as h
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        original_materials = deepcopy(h.material_handles(cs, actor))
        tools = business_tools(ws, 'reviewer', None, None, reviewer_handles=True)
        runtime = SimpleNamespace(tool_call_id='r1a-read-source', config={'configurable': {}})
        result = named(tools, 'read_source_page')('s', runtime=runtime)
        assert isinstance(result, ToolMessage) and result.tool_call_id == runtime.tool_call_id
        public = json.loads(result.content)
        source_receipt = result.artifact['source_material']['receipt']
        authenticated = verify(ws, actor, source_receipt, result.content, 'read_source_page')
        assert authenticated['review_observation_id'] == public['receipt_id']
        materials = h.material_handles(cs, actor)
        assert all(materials[k] == v for k, v in original_materials.items())
        for material in authenticated['materials']:
            descriptor = {k: material[k] for k in ('source_id', 'source_payload_digest', 'source_version_refs')}
            assert descriptor in list(materials.values())
            handle = next(k for k, v in materials.items() if v == descriptor)
            assert h.resolve(cs, actor, 'material', handle) == descriptor
        assert public['evidence_handle'].startswith('obs-')
        assert h.evidence_handles(cs, actor)[public['evidence_handle']] == public['receipt_id']
        with pytest.raises(ActionRejected, match='SOURCE_MATERIAL_PUBLIC_RETURN_CHANGED'):
            verify(ws, actor, source_receipt, result.content + ' ', 'read_source_page')
        assert h.evidence_handles(ContentStore(Store(cs.store.root)), actor)[public['evidence_handle']] == public['receipt_id']
        assert h.material_handles(ContentStore(Store(cs.store.root)), actor) == materials
        cs.read_context(Actor('foreign-reader', 'reviewer', 'foreign-task'), output['refs']['b-body'])
        assert h.material_handles(cs, actor) == materials
        with pytest.raises(ActionForbidden):
            verify(ws, Actor('foreign', 'reviewer', 'foreign-task'), source_receipt, result.content, 'read_source_page')


def test_default_source_wire_is_not_enriched_or_resigned_by_handle_capability(case):
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        tools = business_tools(ws, 'reviewer', None, None)
        false_tools = business_tools(ws, 'reviewer', None, None, reviewer_handles=False)
        assert schema(named(tools, 'read_source_page')) == schema(named(false_tools, 'read_source_page'))
        result = named(tools, 'read_source_page')('s', runtime=SimpleNamespace(
            tool_call_id='r1a-default-source', config={'configurable': {}}))
        assert 'evidence_handle' not in json.loads(result.content)
        assert set(result.artifact['source_material']) == {'contract', 'receipt', 'body_ref',
            'review_observation_receipt_id', 'public_sha256', 'source_ids', 'source_version_refs'}
        verify(ws, actor, result.artifact['source_material']['receipt'], result.content, 'read_source_page')
        # The unchanged mechanical read helpers provide the actual source data;
        # only the inherently fresh receipt ID is substituted in the rc3 encoder.
        from report_agent.catalog import Catalog
        from report_agent.source_tables import present_source_tables
        old_value = present_source_tables(ws, Catalog(ws.store).read('s', 0, 10), None)
        assert result.content == json.dumps({**old_value, 'receipt_id': json.loads(result.content)['receipt_id']}, ensure_ascii=False)


@pytest.mark.parametrize('name', ['observe_evidence', 'search_sources', 'analyze_evidence'])
async def test_remaining_text_reads_return_own_handles_without_losing_selected_evidence(case, name):
    from test_evidence_analysis import Model
    from report_agent.evidence_analysis import SourceSelection
    with bound_review(case) as (cs, workspace, actor, receipt, task, output):
        model = Model()
        tools = business_tools(workspace, 'reviewer', None, model, reviewer_handles=True)
        runtime = SimpleNamespace(tool_call_id='r1a-' + name, config={'configurable': {}})
        if name == 'observe_evidence':
            value = named(tools, name)('source', source_id='s', runtime=runtime)
        elif name == 'search_sources':
            value = named(tools, name)('verified', runtime=runtime)
        else:
            value = await named(tools, name)('Compare the supplied source only.',
                [SourceSelection.model_validate({'source_id': 's', 'offset': 0, 'limit': 1})], [], runtime=runtime)
        public = assert_owned_receipt(cs, workspace, actor, value, name)
        if name == 'analyze_evidence':
            assert len(model.calls) == 1
            assert isinstance(public['evidence'], list) and public['evidence']
            with cs.store.connect() as db:
                stored = json.loads(db.execute('SELECT data FROM content_observations WHERE id=?',
                    (public['receipt_id'],)).fetchone()[0])
            assert stored['evidence'] == public['evidence'], 'An obs alias must never overwrite the selected-material list'
        else:
            assert not model.calls


def physical_case(template, tmp_path, kind):
    """Fresh input configured before import; no existing source/version is edited."""
    store = Store(tmp_path / ('physical-' + kind))
    source_directory = store.root / 'sources'
    source_directory.mkdir()
    path = source_directory / ('source.pdf' if kind == 'pdf' else 'source.png')
    if kind == 'pdf':
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(width=72, height=72)
        with path.open('wb') as output:
            writer.write(output)
    else:
        from PIL import Image
        with Image.new('RGB', (40, 40), 'white') as image:
            image.save(path)
    source = {**deepcopy(template[0].store.manifest['sources'][0]),
        'copied_path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    store.initialize({**deepcopy(template[0].store.manifest), 'sources': [source]})
    cs = ContentStore(store); co = Actor('content:coordinator', 'coordinator', 'root')
    task = cs.operation(co, 'writer-task', {}, lambda db: {'task': cs._insert(db, co, 'DelegatedTask', {
        'role': 'writer', 'goal': 'Save intended output.', 'delegated_by': co.id})})['result']['task']
    writer = Actor('content:writer:' + task['id'], 'writer', task['id'])
    imported = cs.import_inputs(co, 'inputs', ['s'])['result']['source_refs'][0]
    return cs, co, writer, task, imported


def test_actual_physical_source_page_issues_handle_in_signed_return(case, tmp_path):
    prepared_case = physical_case(case, tmp_path, 'pdf')
    with bound_review(prepared_case) as (cs, workspace, actor, receipt, task, output):
        value = named(business_tools(workspace, 'reviewer', None, None, reviewer_handles=True),
            'inspect_source_page')('s', 1, runtime=SimpleNamespace(
                tool_call_id='r1a-inspect-source', config={'configurable': {}}))
        public = assert_owned_receipt(cs, workspace, actor, value, 'inspect_source_page')
        assert public['page'] == 1 and public['page_count'] == 1
        assert public['native_text'] == '', 'Blank physical fixture is not an interpretation or a missing-source verdict'


async def test_source_image_uses_actual_local_input_and_actor_before_mock_interpretation(case, tmp_path, monkeypatch):
    import report_agent.vision as vision
    prepared_case = physical_case(case, tmp_path, 'image')
    with bound_review(prepared_case) as (cs, workspace, actor, receipt, task, output):
        calls = []
        class Client:
            closed = False
            async def close(self):
                self.closed = True
        client = Client()
        async def observed(store, image, provenance, question, actual_client, actual_actor=None, **kwargs):
            assert store.root == cs.store.root and actual_actor == actor and actual_client is client
            assert image.startswith(b'\x89PNG') and provenance['source_id'] == 's'
            calls.append(provenance)
            return {'status': 'observed', 'source': provenance, 'observation': 'Synthetic visual observation.',
                'limitations': ['Offline interpretation, no quality proof.']}
        monkeypatch.setattr(vision, 'configured_vision_client', lambda: client)
        monkeypatch.setattr(vision, '_observe', observed)
        value = await named(business_tools(workspace, 'reviewer', None, None, reviewer_handles=True),
            'analyze_source_image')('s', 'Observe the synthetic image.', runtime=SimpleNamespace(
                tool_call_id='r1a-source-image', config={'configurable': {}}))
        public = assert_owned_receipt(cs, workspace, actor, value, 'analyze_source_image')
        assert public['status'] == 'observed' and len(calls) == 1 and client.closed


@pytest.mark.parametrize('position', [6, 7], ids=['actual-word', 'actual-excel'])
def test_actual_export_reads_return_handles_for_unchanged_ooxml(pair, position):
    with export_unit(pair) as (workspace, cs, actor, snapshot, receipts):
        ref = pair[position]
        value = named(content_tools(workspace, 'reviewer', reviewer_handles=True),
            'read_content_export')(Ref.model_validate(ref))
        public = assert_owned_receipt(cs, workspace, actor, value, 'read_content_export')
        assert public['result']['export_ref'] == ref
        assert public['result']['file_digest'] == cs.read(ref)['payload']['file_digest']
        assert public['result']['structure'] and not cs.list_objects('ReviewRecord')


async def test_actual_render_page_scope_and_digest_precede_mock_visual_interpretation(pair, monkeypatch):
    import report_agent.vision as vision
    import report_agent.deep_models as models
    from report_agent.content_export import _asset
    from report_agent.content_tasks import delegated_task
    from test_paired_render_inspection import png
    from test_review_binding_v4 import review_call
    workspace, cs, writer, snapshot, _, refs, word, excel, _ = pair
    workspace.store.set('manifest', {**workspace.store.manifest,
        'review_execution_mode': 'native-reviewer-v2', 'review_interface_profile': 'review-interfaces-v4',
        'delegation_prompt_profile': 'separate-description-v1', 'operation_identity_profile': 'native-tool-runtime-v1'})
    image = png('blue'); sha = hashlib.sha256(image).hexdigest()
    asset = _asset(cs.store, 'r1a-render.png', image)
    with cs.store.connect() as db:
        render = cs._insert(db, writer, 'RenderArtifact', {'snapshot_ref': snapshot, 'export_ref': word,
            'export_digest': cs.read(word)['payload']['file_digest'], 'page_assets': [{'asset_ref': asset, 'sha256': sha}]})
    call = review_call([refs['k']], identity='r1a-render-review', scope={'kind': 'mapped', 'items': [{
        'criterion_ref': refs['k'], 'target_ref': snapshot, 'assessment_kind': 'render', 'artifact_refs': [render]}]})
    call['args']['review']['deliverable'] = {'kind': 'snapshot', 'snapshot_ref': snapshot}
    with delegated_task(workspace, 'coordinator', call) as (_, actor):
        calls = []
        class Client:
            closed = False
            async def close(self):
                self.closed = True
        client = Client()
        async def observed(store, data, provenance, question, actual_client, actual_actor=None, **kwargs):
            assert actual_actor == actor and data == image and actual_client is client
            assert provenance['render_ref'] == render and provenance['export_ref'] == word and provenance['page'] == 1
            calls.append(provenance)
            return {'status': 'observed', 'source': provenance, 'observation': 'Synthetic rendered observation.'}
        monkeypatch.setattr(models, 'configured_vision_client', lambda: client)
        monkeypatch.setattr(vision, '_observe', observed)
        value = await named(content_tools(workspace, 'reviewer', reviewer_handles=True),
            'inspect_rendered_page')(Ref.model_validate(render), 1, 'Observe this exact saved page.')
        assert_owned_receipt(cs, workspace, actor, value, 'inspect_rendered_page')
        assert len(calls) == 1 and client.closed and not cs.list_objects('ReviewRecord')
