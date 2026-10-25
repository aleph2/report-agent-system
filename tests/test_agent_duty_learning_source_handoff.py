"""Trace-derived source selection handoff, with actual native tools and fake LLMs.

R11's observed question and six selections are reused as test data only. This
does not resume R11, repair the app, or attribute scripted choices to a real LLM.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from duty_probe_optimizer_outcome import (
    PREFERENCE, assess_optimizer_state, classify_observed_call, prepare_optimizer_fixture,
)
from report_agent.content_store import ContentStore
from report_agent.learning_text_work import LearningAnalysis
from report_agent.learning_worker import consume_pending
from report_agent.store import digest, encode
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


ROOT = Path(__file__).resolve().parents[1]
R11 = ROOT / '.analysis/agent-duty-validation-20261018/completion-execution-20261019/real/live-r11/optimizer-feedback-outcomes'
R11_HASHES = {
    'wire-response-0004.json': '4c9a9f3c48b6212cdb99665965154dda7d291855a74dbae03b5bb85d2fffdab1',
    'capture.json': 'c0fb4b82b2f35aa2941afddf3dcd53bf8765ce4f4d55ecd6f7bbef2b6a1661c8',
}
TAIL = 'SOURCE_HANDOFF_FINDINGS_TAIL: supplied selections are not engineering acceptance.'


def historical_call_and_rebinding(fixture, folder):
    originals = {}
    for name, expected_hash in R11_HASHES.items():
        raw = (R11 / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected_hash
        originals[name] = json.loads(raw)
        # Retain the selected observed call bytes; the full old capture stays
        # immutable at its original path, referenced by its pinned digest.
        if name.startswith('wire-response'):
            (folder / ('r11-original-' + name)).write_bytes(raw)
    calls = originals['wire-response-0004.json']['choices'][0]['message']['tool_calls']
    assert len(calls) == 1 and calls[0]['function']['name'] == 'analyze_learning_material'
    original_args = json.loads(calls[0]['function']['arguments'])
    historical = originals['capture.json']['fixture']
    old_ids = [historical['feedback_a']['id'], historical['feedback_b']['id']]
    new_ids = [fixture['feedback_a']['id'], fixture['feedback_b']['id']]
    ids = dict(zip(old_ids, new_ids, strict=True))
    rebound = deepcopy(original_args)
    for selection in rebound['feedback_selections']:
        selection['feedback_id'] = ids[selection['feedback_id']]
    for old, new in ids.items():
        # R11 naturally used eight-character labels in its question. Full IDs
        # remain in tool arguments; only those exact labels are rebound here.
        rebound['question'] = rebound['question'].replace(old[:8], new[:8])
    for label in ('a', 'b'):
        old, new = historical['feedback_' + label], fixture['feedback_' + label]
        assert old['correction'] == new['correction'] and old['before'] == new['before']
        expected_evidence = deepcopy(old['evidence'])
        if label == 'a':
            expected_evidence[0]['source_ref'] = new['evidence'][0]['source_ref']
        assert expected_evidence == new['evidence']
    assert len(rebound['feedback_selections']) == 6
    by_id = {fixture['feedback_' + label]['id']: fixture['feedback_' + label] for label in ('a', 'b')}
    for selection in rebound['feedback_selections']:
        value = by_id[selection['feedback_id']][selection['field']]
        text = value if isinstance(value, str) else encode(value)
        assert selection.get('offset', 0) == 0
        assert selection['characters'] == len(text)  # Preserve actual R11 full-field lengths.
    dump(folder / 'r11-rebinding.json', {
        'historical_hashes': R11_HASHES, 'historical_directory': str(R11),
        'original_tool_call': calls[0], 'original_arguments': original_args,
        'rebound_arguments': rebound, 'feedback_id_mapping': ids,
        'source_ref_mapping': {'from': historical['feedback_a']['evidence'][0]['source_ref'],
                               'to': fixture['feedback_a']['evidence'][0]['source_ref']},
        'unchanged_fields': ['question except exact eight-character feedback labels',
                             'six selection order/field/characters', 'feedback correction/before',
                             'feedback evidence except the exact SourceArtifact ref'],
    })
    return rebound


@pytest.mark.parametrize('include_source', [False, True], ids=['feedback-only-after-source-read', 'source-explicitly-selected'])
async def test_native_learning_source_selection_is_not_implicit_read_history(ws, request, include_source):
    folder = Path(os.environ.get('REPORT_LEARNING_SOURCE_HANDOFF_OUT', str(ws.store.root / 'captures'))) / (
        'full' if include_source else 'missing')
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_optimizer_fixture(ws)
    dump(folder / 'fixture.json', fixture)
    args = historical_call_and_rebinding(fixture, folder)
    source_ref = fixture['feedback_a']['evidence'][0]['source_ref']
    source_original = deepcopy(ContentStore(ws.store).read(source_ref))
    source_text = encode(source_original)
    assert PREFERENCE in source_text and len(source_text) <= 8000
    source_selection = {'ref': source_ref, 'offset': 0, 'characters': len(source_text)}
    missing_args = {**deepcopy(args), 'object_selections': []}
    full_args = {**deepcopy(args), 'object_selections': [source_selection]}
    assert {k: v for k, v in missing_args.items() if k != 'object_selections'} == {
        k: v for k, v in full_args.items() if k != 'object_selections'}
    selected_args = full_args if include_source else missing_args
    dump(folder / 'selection-only-difference.json', {'missing': missing_args, 'full': full_args,
         'active': 'full' if include_source else 'missing', 'only_active_argument_difference': 'object_selections'})
    fields = {fixture['feedback_' + label]['id']: fixture['feedback_' + label] for label in ('a', 'b')}
    expected_evidence = []
    for selection in args['feedback_selections']:
        value = fields[selection['feedback_id']][selection['field']]
        text = value if isinstance(value, str) else encode(value)
        expected_evidence.append({'selection': {**selection, 'offset': 0}, 'text': text,
            'total_characters': len(text), 'original_digest': digest(value)})
    if include_source:
        expected_evidence.append({'selection': source_selection, 'text': source_text,
            'total_characters': len(source_text), 'original_digest': digest(source_original)})
    conclusion = (
        'The selected exact SourceArtifact version contains the preference verbatim. Its scope is this synthetic '
        "customer's construction-safety reports. Neither feedback establishes the alleged missing-title report version, "
        'location or supporting evidence, or that both items concern the same table.' if include_source else
        'This independent invocation did not receive the SourceArtifact object. The feedback quotation and source ref '
        'alone do not establish that the original was checked in this invocation. This is an input-selection limit, '
        'not a claim that the project lacks a source. Missing-title version, location and shared table identity remain unknown.')
    findings = conclusion + '\n' + '\n'.join(
        f'Extent note {i:02d}: feedback allegations remain distinct from verified source facts; no report acceptance is claimed.'
        for i in range(30)) + '\n' + TAIL
    expected_payload = {'findings': findings, 'project_fact': None}
    assert len(findings) > 3000
    raw_fake_answer = encode(expected_payload)
    dump(folder / 'independent-oracle.json', {'expected_evidence': expected_evidence,
         'expected_payload': expected_payload, 'source_original': source_original,
         'original_source_sha256': hashlib.sha256(source_text.encode()).hexdigest(),
         'fake_response_content': raw_fake_answer})
    held = {'analysis_packets': [], 'next_observations': []}

    def initial_or_analysis(messages):
        # Independent analysis uses the same actual client with two messages and
        # no AI history. Classify only its actual packet; no extra agent loop.
        try:
            packet = json.loads(messages[-1].content)
        except (ValueError, TypeError):
            packet = None
        if isinstance(packet, dict) and {'question', 'scope', 'job_id', 'evidence', 'output_schema'} <= packet.keys():
            held['analysis_packets'].append(deepcopy(packet))
            dump(folder / 'actual-independent-packets.json', held['analysis_packets'])
            assert packet['question'] == args['question']
            assert packet['evidence'] == expected_evidence
            assert packet['output_schema'] == LearningAnalysis.model_json_schema()
            assert packet['scope'] == {'customer': fixture['customer'], 'project': fixture['project']}
            assert packet['job_id'] == ws.store.get('learning_job')['id']
            assert len(packet['evidence']) == (7 if include_source else 6)
            if not include_source:
                assert all('ref' not in entry['selection'] for entry in packet['evidence'])
                assert source_text not in encode(packet)
            for entry, expected in zip(packet['evidence'], expected_evidence, strict=True):
                assert entry['text'] and entry['text'][-40:] == expected['text'][-40:]
            return AIMessage(content=raw_fake_answer)
        prefix = 'Your current assignment (first page; total and continuation are explicit) is: '
        assignment, _ = json.JSONDecoder().raw_decode(messages[-1].content.split(prefix, 1)[1])
        assert assignment['feedback_ids'] == [fixture['feedback_a']['id'], fixture['feedback_b']['id']]
        return AIMessage(content='', tool_calls=[{'name': 'read_learning_feedback', 'id': 'read-' + str(i),
            'type': 'tool_call', 'args': {'feedback_id': s['feedback_id'], 'field': s['field'],
                                        'offset': 0, 'limit': s['characters']}}
            for i, s in enumerate(args['feedback_selections'])])

    def source_read(messages):
        for i, expected in enumerate(expected_evidence[:6]):
            raw = tool_reply(messages, 'read-' + str(i))
            page = result_value(raw)
            assert raw.status == 'success' and page['next_offset'] is None
            assert page['text'] == expected['text'] and page['digest'] == expected['original_digest']
            assert page['total_chars'] == expected['total_characters'] and page['offset'] == 0
        # This ref is chosen from the actual tool-delivered feedback, not injected
        # into a model message by the host or copied from the expected packet.
        actual_ref = json.loads(result_value(tool_reply(messages, 'read-2'))['text'])[0]['source_ref']
        assert actual_ref == source_ref
        return action('read_learning_evidence', 'read-source', ref=actual_ref, offset=0, limit=8000)

    def analyze(messages):
        raw = tool_reply(messages, 'read-source')
        page = result_value(raw)
        assert raw.status == 'success' and page['next_offset'] is None
        assert page['ref'] == source_ref and page['text'] == source_text
        assert page['digest'] == digest(source_original) and page['total_chars'] == len(source_text)
        held['actual_source_read'] = raw.model_dump()
        return action('analyze_learning_material', 'analyze-selected', **deepcopy(selected_args))

    def dispose(messages):
        raw = tool_reply(messages, 'analyze-selected')
        held['next_observations'].append({'actual_tool_message': raw.model_dump(),
                                         'actual_next_model_input': messages_to_dict(messages)})
        dump(folder / 'actual-next-observation.json', held['next_observations'])
        value = result_value(raw)
        assert raw.status == 'success' and value['fact_correctness_verified'] is False
        assert value['payload'] == expected_payload and value['analysis'] == raw_fake_answer
        assert value['payload']['findings'].endswith(TAIL)
        assert value['evidence'] == expected_evidence
        saved = ws.store.get('learning_analysis:' + value['analysis_id'])
        assert saved['payload'] == expected_payload and saved['operation'] == value['operation']
        held['analysis_result'] = value
        return AIMessage(content='', tool_calls=[{
            'name': 'record_feedback_disposition', 'id': 'dispose-a', 'type': 'tool_call',
            'args': {'feedback_id': fixture['feedback_a']['id'], 'outcome': 'no_change',
                'rationale': 'The explicit customer preference remains applicable and unchanged; this handoff check adds no reusable candidate or report edits.'}}, {
            'name': 'record_feedback_disposition', 'id': 'dispose-b', 'type': 'tool_call',
            'args': {'feedback_id': fixture['feedback_b']['id'], 'outcome': 'insufficient_evidence',
                'rationale': 'Report version, location and evidence for the suspected title problem remain unprovided.'}}])

    def finish(messages):
        for label, outcome in [('a', 'no_change'), ('b', 'insufficient_evidence')]:
            raw = tool_reply(messages, 'dispose-' + label)
            value = result_value(raw)
            assert raw.status == 'success' and value['outcome'] == outcome
            assert value['quality_verified'] is False
        return AIMessage(content='Feedback handling is recorded; no candidate, publication, report edits or fact verification is claimed. ' + conclusion)

    driver = Driver(optimizer=[initial_or_analysis, source_read, analyze, dispose, finish])
    calls = []
    model = traced_model(driver('optimizer'), 'optimizer', calls)
    runtime, error = None, None
    try:
        runtime = await consume_pending(ws, lambda: model, max_steps=40)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        for call in calls:
            call['boundary'] = classify_observed_call(call)
        assessment = assess_optimizer_state(ws, fixture)
        dump(folder / 'capture.json', {'runtime': runtime, 'raised_error': error, 'fixture': fixture,
             'native_model_calls': calls, 'assessment': assessment, 'selected_arguments': selected_args,
             'held_observations': held, 'source_after': ContentStore(ws.store).read(source_ref),
             'same_client_analysis': True, 'source_test_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'limits': ['Fake decisions and analysis do not establish real-model semantic behavior.',
                        'Already read source objects are selected explicitly, not inherited by independent tools.',
                        'No-change is no new candidate; it does not waive the original customer requirement.']})
    request.node.user_properties.append(('learning_source_handoff_capture', str(folder)))
    assert error is None, error
    assert runtime['state'] == 'completed' and assessment['job']['state'] == 'completed'
    assert assessment['feedback_originals_unchanged'] and assessment['business_originals_unchanged']
    assert ContentStore(ws.store).read(source_ref) == source_original
    assert not assessment['candidates'] and not assessment['active_library']
    assert not assessment['missing_feedback_ids'] and not assessment['unexpected_feedback_ids']
    assert all(not d['quality_verified'] for d in assessment['dispositions'].values())
    assert assessment['job']['quality_verified'] is False and assessment['semantic_status'] == 'not_semantically_assessed'
    assert len(driver.calls) == len(calls) == 6
    assert [c['boundary'] for c in calls].count('native_optimizer_decision') == 5
    assert [c['boundary'] for c in calls].count('independent_learning_analysis') == 1
    assert len(held['analysis_packets']) == len(held['next_observations']) == 1
