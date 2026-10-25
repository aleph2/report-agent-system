"""Two material-selection calibrations through the native Writer/ToolNode.

Both scripted Writers previously read both sources. Only the independent tool
selection differs; it must not inherit the Writer's reading history implicitly.
Fake findings/finals calibrate I/O, not real model judgment or engineering truth.
"""
import json
import os
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage, messages_from_dict
import pytest

from duty_probe_writer_analysis_outcome import (
    FIELD, QUESTION, RULE, capture_writer_analysis)
from report_agent.store import digest
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_duty_writer_delivery_outcome import exact_final_inside
from test_task_supervision import ws, offline


def analysis_finding(rule_selected):
    main = ('SUPPORT: analysis-field block0 records Site A as B. '
            'CONFLICT: proposed70 is outside analysis-rule block0 interval75 to100. '
            if rule_selected else
            'SUPPORT: analysis-field block0 records Site A as B and proposed70. '
            'UNRESOLVED: analysis-rule was not selected for this independent comparison; '
            'this packet cannot establish whether70 meets that rule. ')
    return (main + 'Site B class and score remain unresolved in analysis-field block0. '
            + 'Selected-material qualification retained. ' * 80
            + 'LIMIT_TAIL: an unselected rule is not an absent project source; '
              'this bounded analysis is not verified facts or report acceptance.')


def writer_analysis_script(rule_selected, finding, observed):
    selected = ['analysis-field', *(['analysis-rule'] if rule_selected else [])]

    def choose(messages):
        for source_id, expected in [('analysis-rule', RULE), ('analysis-field', FIELD)]:
            returned = result_value(tool_reply(messages, 'analysis-read-' + source_id))
            assert returned['blocks'][0]['text'] == expected
        observed['prior_reads'] = [m.model_dump() for m in messages if isinstance(m, ToolMessage)]
        return action('analyze_evidence', 'writer-analysis-call', question=QUESTION,
                      source_selections=[{'source_id': s, 'offset': 0, 'limit': 1} for s in selected],
                      result_selections=[])

    def consume(messages):
        raw = tool_reply(messages, 'writer-analysis-call')
        value = result_value(raw)
        assert value['analysis'] == finding, 'W03_FULL_ANALYSIS_CHANGED'
        assert value['scope_note'] == ('A bounded model observation of the supplied selections; '
                                       'not verified facts, complete source coverage or report acceptance.')
        observed.update(analysis_message=raw.model_dump(), analysis_value=value,
                        consumer_messages=[m.model_dump() for m in messages])
        return AIMessage(content=finding)

    # One preparation AIMessage has already executed two actual read tools.
    return [AIMessage(content='Unused preparation slot; middleware owns it.'), choose, consume]


@pytest.mark.parametrize('rule_selected', [True, False], ids=['full-selection', 'rule-not-selected'])
async def test_writer_analysis_retains_selected_material_and_full_next_consumer(ws, tmp_path, rule_selected):
    finding, observed = analysis_finding(rule_selected), {}

    def independent(messages):
        packet = json.loads(messages[1].content)
        actual_sources = [e['selection']['source_id'] for e in packet['evidence']]
        expected_sources = ['analysis-field', *(['analysis-rule'] if rule_selected else [])]
        assert actual_sources == expected_sources, 'W03_INDEPENDENT_SELECTION_CHANGED'
        return AIMessage(content=analysis_finding('analysis-rule' in actual_sources))

    driver = Driver(writer=writer_analysis_script(rule_selected, finding, observed),
                    text_tool=[independent])
    out_base = Path(os.environ.get('DUTY_ANALYSIS_EVIDENCE', str(tmp_path / 'evidence')))
    folder = out_base / ('full-selection' if rule_selected else 'rule-not-selected')
    capture = await capture_writer_analysis(ws, folder, driver)
    assert capture['raised_error'] is None, capture['raised_error']
    assert capture['runtime']['last_error'] is None, capture['runtime']
    assert capture['originals_unchanged'] and capture['source_rows_unchanged'] and capture['catalog_sources_unchanged']
    analysis_calls = [m for role, _, m in driver.calls if role == 'text_tool']
    assert len(analysis_calls) == 1
    packet = json.loads(analysis_calls[0][1].content)
    assert packet['question'] == QUESTION
    selected = ['analysis-field', *(['analysis-rule'] if rule_selected else [])]
    assert [e['selection'] for e in packet['evidence']] == [
        {'source_id': s, 'offset': 0, 'limit': 1} for s in selected]
    sources = {o['payload']['source_id']: o for o in capture['fixture']['originals']
               if o['ref']['type'] == 'SourceArtifact'}
    catalog_sources = {s['id']: s for s in capture['fixture']['catalog_sources']}
    assert set(sources) == set(catalog_sources) == {'analysis-rule', 'analysis-field'}
    for source_id, source in catalog_sources.items():
        assert sources[source_id]['payload'] == {
            'source_id': source_id, 'file_digest': source.get('sha256') or digest(source['content']),
            'coverage': source['coverage'], 'content': source['content'],
            'source_metadata': {**{k: v for k, v in source.items() if k != 'content'},
                                'text_digest': digest(source['content'])}}
        page = capture['fixture']['source_pages'][source_id]
        assert len(page['blocks']) == page['total_blocks'] == 1
        assert page['next_offset'] is None and page['offset'] == 0
    for entry, source_id in zip(packet['evidence'], selected, strict=True):
        page, original = entry['observation'], capture['fixture']['source_pages'][source_id]
        assert {key: page[key] for key in original} == original
        assert entry['observation_sha256'] == digest(page)
        assert page['source']['id'] == sources[source_id]['payload']['source_id']
        assert page['blocks'][0]['text'] == sources[source_id]['payload']['content']
        assert sources[source_id]['ref']['version'] == 1
        assert 'source_ref' not in entry  # Record actual interface, do not invent Ref binding.
    if not rule_selected:
        assert RULE not in json.dumps(packet, ensure_ascii=False), 'W03_UNSELECTED_RULE_WAS_AUTO_ADDED'
    assert finding == observed['analysis_value']['analysis']
    assert observed['analysis_value']['evidence'] == packet['evidence']
    assert 'LIMIT_TAIL:' in finding and len(finding) > 3000
    parents = [e['actual_child_return'] for e in capture['fake_parent_events'] if 'actual_child_return' in e]
    assert len(parents) == 1 and parents[0]['tool_call_id'] == 'writer-analysis-task'
    assert exact_final_inside(parents[0]['content'], finding), 'W03_EXACT_PARENT_FINAL_CHANGED'
    phases = [e for e in capture['phase_events'] if e['phase'] == 'unchanged_writer_handler']
    assert len(phases) == 2
    tasks = [o for o in capture['content_objects'] if o['ref']['type'] == 'DelegatedTask']
    assert len(tasks) == 1
    task = tasks[0]
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['role'] == 'writer'
    assert task['payload']['goal'] == capture['fixture']['task_call']['args']['description']
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    for event in capture['phase_events']:
        context = event['server_context']
        assert context['role'] == 'writer'
        assert context['actor_id'] == 'content:writer:' + task['ref']['id']
        assert context['assignment'] == task['payload']
    assert all(o['ref']['type'] in {'Requirement', 'SourceArtifact', 'DelegatedTask'}
               for o in capture['content_objects'])
    proof = {'selection': selected, 'actual_independent_packet': packet,
             'complete_analysis_and_scope': observed['analysis_value'],
             'actual_consumer_tool_message': observed['analysis_message'],
             'actual_parent_return': parents[0],
             'fake_model_calibration_only': True, 'real_model_judgment_tested': False,
             'typed_version_binding_in_analysis_interface_proven': False}
    (folder / 'test-proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
