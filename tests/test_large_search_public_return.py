"""Large native search returns remain recoverable without weakening source receipts."""
import hashlib
import json
import traceback
from copy import deepcopy

import pytest

from langchain_core.messages import AIMessage

from report_agent.content_store import ContentStore
from report_agent.deep_runtime import run_report
from report_agent.decision_data import deliver_controls
from report_agent.errors import ActionRejected
from test_agent_result_delivery import force_offload, packet, reply
from test_decision_data import activate
from test_deep_runtime import Driver, invoke, call
from test_hierarchical_content import seed
from test_task_supervision import ws


async def test_large_search_native_offload_preserves_owned_exact_source(ws, monkeypatch):
    seed(ws)
    activate(ws)
    ws.store.set('context_policy', 'stateful-tools-v2')
    manifest = ws.store.manifest
    literal = 'deepcut ' + 'x' * 7500 + ' END'
    source = {'id': 's', 'title': 'Synthetic', 'content': '\n'.join([literal]*10), 'coverage': 'partial'}
    ws.store.set('manifest', {**manifest, 'sources': [source],
        'execution_progress_policy': {'version':1,'window':64,'repeats':3,'after_notice':2},
        'review_interface_profile':'review-interfaces-v4', 'review_execution_mode':'native-reviewer-v2',
        'delegation_prompt_profile':'separate-description-v1', 'operation_identity_profile':'native-tool-runtime-v1',
        'context_policy':'stateful-tools-v2', 'context_projection':'review-materials-v1',
        'review_plan_contract':'work-units-v1', 'review_submission_contract':'task-scope-selectors-v1'})
    with ws.store.connect() as db:
        db.execute('delete from source_blocks')
        db.executemany('insert into source_blocks values (?,?,?,?)',
            [('s', i, json.dumps({'page':i+1}), literal) for i in range(10)])
    force_offload(monkeypatch, True, threshold=2000)
    captured = []

    def inspect_search(messages):
        message = reply(messages, 'search_sources')
        shown = packet(message)
        original = ws.store.get('tool_observation:' + shown['observation_ref'])
        raw = json.loads(original['text'])
        assert original['owner'] == 'content:coordinator'
        assert original['sha256'] == hashlib.sha256(original['text'].encode()).hexdigest()
        assert raw['matches'][0]['text'] == literal and raw['total'] == 10
        assert message.artifact['source_material']['public_sha256'] == original['sha256']
        assert not shown['complete_original_in_decision']
        with pytest.raises(ActionRejected, match='PUBLIC_DELIVERY_OWNER_OR_CALL_MISMATCH'):
            deliver_controls(ws, 'coordinator', message.model_copy(update={'tool_call_id':'forged'}))
        altered = deepcopy(message.artifact)
        altered['report_public_delivery']['public_digest'] = '0'*64
        with pytest.raises(ActionRejected, match='PUBLIC_DELIVERY_VIEW_CHANGED'):
            deliver_controls(ws, 'coordinator', message.model_copy(update={'artifact':altered}))
        ws.store.set('tool_observation:' + shown['observation_ref'], {**original, 'text':'tampered'})
        try:
            with pytest.raises(ActionRejected, match='PUBLIC_DELIVERY_ORIGINAL_CHANGED'):
                deliver_controls(ws, 'coordinator', message)
        finally:
            ws.store.set('tool_observation:' + shown['observation_ref'], original)
        captured.append(shown['observation_ref'])
        return invoke('read_tool_observation', observation_ref=shown['observation_ref'],
            offset=0, characters=6000, field_path=['matches', 0, 'text'])

    parts = []
    def inspect_recovery(messages):
        restored = packet(next(m for m in reversed(messages) if getattr(m, 'name', None) == 'read_tool_observation'))
        assert restored['observation_ref'] == captured[0]
        assert restored['text'] == literal[len(''.join(parts)):len(''.join(parts))+6000]
        parts.append(restored['text'])
        if restored['next_offset'] is not None:
            assert restored['complete_field'] is False
            args = {'observation_ref':captured[0], 'offset':restored['next_offset'],
                    'characters':6000, 'field_path':['matches', 0, 'text']}
            return AIMessage(content='', tool_calls=[call('read_tool_observation', args, identity='recovery-next')])
        assert ''.join(parts) == literal and restored['complete_field'] is False
        return AIMessage(content='Selected text recovered; source completeness remains unproven.')

    failures = []
    def checked(fn):
        def call(messages):
            try:
                return fn(messages)
            except Exception:
                failures.append(traceback.format_exc())
                raise
        return call
    driver = Driver(coordinator=[invoke('search_sources', query='deepcut', limit=10, source_id='s'),
                                 checked(inspect_search), checked(inspect_recovery), checked(inspect_recovery)])
    result = await run_report(ws, driver)
    if result['last_error']:
        diagnostic = ws.store.root / 'diagnostics' / 'private' / (result['last_error']['diagnostic_id'] + '.json')
        failures.append(diagnostic.read_text() if diagnostic.exists() else 'no diagnostic')
    assert result['last_error'] is None, {'failures':failures, 'captured':len(captured), 'parts':len(parts)}
    assert len(captured) == 1
    assert not ContentStore(ws.store).list_objects('ReviewRecord')
