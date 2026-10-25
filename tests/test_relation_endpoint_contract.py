"""Expose resolved Relation conditions without weakening native batch validation."""
import json

import httpx
import pytest
from langchain.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool

from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionRejected
from report_agent.content_tasks import delegated_task
from test_bounded_review import Model
from test_hierarchical_content import seed, ws
from test_text_work import writer_call


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("NETWORK_FORBIDDEN")
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)


def registered_commit(ws, role='coordinator'):
    ws.store.set('manifest', {**ws.store.manifest, 'content_input_profile': 'relation-endpoints-v2'})
    return next(t for t in business_tools(ws, role, None, Model('{}'))
                if t.__name__ == 'commit_objects')


@pytest.mark.parametrize('role', ['coordinator', 'writer'])
def test_model_facing_relation_explains_resolved_endpoint_conditions(ws, role):
    seed(ws)
    schema = convert_to_openai_tool(registered_commit(ws, role))['function']['parameters']
    relation = next(branch for branch in schema['properties']['objects']['items']['oneOf']
                    if branch['properties']['type']['const'] == 'Relation')
    payload = relation['properties']['payload']
    description = payload['properties']['predicate'].get('description', '')
    for condition in ('contains', 'position', 'supported_by', 'contradicted_by',
                      'subject_ref', 'ContentNode', 'object_ref', 'Evidence',
                      'not SourceArtifact', 'client_key'):
        assert condition in description, f'Missing Relation condition: {condition}'
    assert 'client_key' in json.dumps(payload['properties']['object_ref'])


def evidence_object(source):
    return {'client_key': 'fresh-evidence', 'type': 'Evidence', 'payload': {
        'source_refs': [source], 'locator': 's', 'excerpt': 'Class B permits 75 to 100.'}}


def relation_object(subject, target, predicate):
    return {'client_key': 'fresh-relation', 'type': 'Relation', 'payload': {
        'subject_ref': subject, 'object_ref': target, 'predicate': predicate,
        'provenance_kind': 'adopted_during_generation'}}


@pytest.mark.parametrize('predicate', ['supported_by', 'contradicted_by'])
def test_native_relation_accepts_same_batch_evidence_after_resolution(ws, predicate):
    cs, _, refs, _, _ = seed(ws)
    source = cs.list_objects('SourceArtifact')[0]['ref']
    wrapped = tool(registered_commit(ws))
    result = wrapped.invoke({'operation_id': 'typed-evidence-' + predicate, 'objects': [
        evidence_object(source),
        relation_object(refs['claim'], {'client_key': 'fresh-evidence'}, predicate)]})
    saved = result['result']['refs']
    relation = cs.read(saved['fresh-relation'])['payload']
    assert relation['subject_ref'] == refs['claim']
    assert relation['object_ref'] == saved['fresh-evidence']
    assert relation['object_ref']['type'] == 'Evidence'


@pytest.mark.parametrize('predicate', ['supported_by', 'contradicted_by'])
def test_native_source_artifact_endpoint_rejects_and_rolls_back_whole_batch(ws, predicate):
    cs, actor, refs, _, _ = seed(ws)
    source = cs.list_objects('SourceArtifact')[0]['ref']
    before = cs.list_objects()
    operation = 'wrong-endpoint-' + predicate
    wrapped = tool(registered_commit(ws))
    with pytest.raises(ActionRejected, match='SUPPORT_RUNS_FROM_CONTENT_TO_EVIDENCE'):
        wrapped.invoke({'operation_id': operation, 'objects': [
            evidence_object(source), relation_object(refs['claim'], source, predicate)]})
    assert cs.list_objects() == before
    receipt = cs.receipt(actor, operation)
    assert receipt['state'] == 'known_failure'
    assert not receipt['response']['retryable']


def test_native_contains_resolves_same_batch_content_nodes_and_position(ws):
    cs, _, _, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call('typed-contains')):
        wrapped = tool(registered_commit(ws, 'writer'))
        objects = [{'client_key': key, 'type': 'ContentNode', 'payload': {
            'kind': kind, 'body': {'text': text}, 'claim_kind': 'structure', 'qualifiers': {}}}
            for key, kind, text in [('parent', 'report', 'Report'), ('child', 'chapter', 'Chapter')]]
        edge = relation_object({'client_key': 'parent'}, {'client_key': 'child'}, 'contains')
        edge['payload']['position'] = 0
        result = wrapped.invoke({'operation_id': 'typed-contains', 'objects': [*objects, edge]})
    refs = result['result']['refs']
    relation = cs.read(refs['fresh-relation'])['payload']
    assert relation['subject_ref'] == refs['parent']
    assert relation['object_ref'] == refs['child']
    assert relation['position'] == 0


@pytest.mark.parametrize('invalid', ['missing-position', 'evidence-subject', 'source-object'])
def test_native_contains_keeps_position_and_content_endpoint_checks(ws, invalid):
    cs, actor, refs, _, _ = seed(ws)
    source = cs.list_objects('SourceArtifact')[0]['ref']
    edge = relation_object(refs['root'], refs['claim'], 'contains')
    if invalid != 'missing-position':
        edge['payload']['position'] = 0
        if invalid == 'evidence-subject':
            edge['payload']['subject_ref'] = refs['evidence']
        else:
            edge['payload']['object_ref'] = source
    operation = 'contains-' + invalid
    before = cs.list_objects()
    with pytest.raises(ActionRejected, match='CONTAINS_REQUIRES_POSITION_AND_CONTENT_ENDPOINTS'):
        tool(registered_commit(ws)).invoke({'operation_id': operation, 'objects': [edge]})
    assert cs.list_objects() == before
    assert cs.receipt(actor, operation)['state'] == 'known_failure'


@pytest.mark.parametrize('predicate', ['supported_by', 'contradicted_by'])
def test_native_support_keeps_content_subject_check(ws, predicate):
    cs, actor, refs, _, _ = seed(ws)
    source = cs.list_objects('SourceArtifact')[0]['ref']
    before = cs.list_objects()
    operation = 'wrong-subject-' + predicate
    with pytest.raises(ActionRejected, match='SUPPORT_RUNS_FROM_CONTENT_TO_EVIDENCE'):
        tool(registered_commit(ws)).invoke({'operation_id': operation, 'objects': [
            relation_object(source, refs['evidence'], predicate)]})
    assert cs.list_objects() == before
    assert cs.receipt(actor, operation)['state'] == 'known_failure'


@pytest.mark.parametrize('predicate', ['depends_on', 'references', 'expresses'])
def test_other_native_predicates_do_not_inherit_evidence_endpoint_restriction(ws, predicate):
    cs, _, refs, _, _ = seed(ws)
    source = cs.list_objects('SourceArtifact')[0]['ref']
    result = tool(registered_commit(ws)).invoke({'operation_id': 'other-' + predicate,
        'objects': [relation_object(refs['claim'], source, predicate)]})
    saved = cs.read(result['result']['refs']['fresh-relation'])['payload']
    assert saved['predicate'] == predicate
    assert saved['object_ref'] == source
