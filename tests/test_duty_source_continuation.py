"""P03 native fake calibration: two real source read paths and an unread ending."""
import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from duty_probe_source_continuation import CASES, GEOLOGY, capture_source_continuation
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


FALSE_ABSENCE = 'The project has no geology information for Site S.'


def source_consumer_factory(case, unread, held):
    def unused(messages):
        raise AssertionError('The explicit initial-search middleware must occupy Writer step zero')

    def consume_search(messages):
        value = result_value(tool_reply(messages, 'initial-literal-search'))
        held['search'] = value
        assert value['scope']['searched_source_ids'] == ['geo-g17', 'maintenance-m02']
        assert bool(value['matches']) is (case == 'literal-hit')
        assert value['total'] == (1 if case == 'literal-hit' else 0)
        assert value['next_offset'] is None, 'Search cursor is not frozen-source read coverage'
        assert 'No match does not establish missing information.' in value['coverage_note']
        text = json.dumps([m.model_dump() for m in messages], ensure_ascii=False)
        for value in ('geo-g17', 'maintenance-m02', 'G-17 geology record', 'M-02 maintenance note'):
            assert value in text, 'Known identity must come from actual authorized context'
        if unread:
            return AIMessage(content=FALSE_ABSENCE)
        return action('read_source_page', 'read-geology-0', source_id='geo-g17', offset=0, limit=1)

    def continue_read(messages):
        value = result_value(tool_reply(messages, 'read-geology-0'))
        assert value['source']['id'] == 'geo-g17'
        assert value['blocks'] == [GEOLOGY[0]]
        assert value['next_offset'] == 1
        held['read0'] = value
        return action('read_source_page', 'read-geology-1', source_id='geo-g17', offset=value['next_offset'], limit=1)

    def finish(messages):
        value = result_value(tool_reply(messages, 'read-geology-1'))
        assert value['source']['id'] == 'geo-g17'
        assert value['blocks'] == [GEOLOGY[1]]
        assert value['next_offset'] is None
        held['read1'] = value
        return AIMessage(content=json.dumps({'source_id': value['source']['id'],
            'selected_original_blocks': [GEOLOGY[0], GEOLOGY[1]],
            'limitation': 'Original source selections only; no engineering assessment.'}, ensure_ascii=False))

    return Driver(writer=[unused, consume_search] if unread else [unused, consume_search, continue_read, finish])


@pytest.mark.parametrize('case,unread', [('literal-hit', False), ('synonym-no-hit', False),
                                      ('synonym-no-hit', True)], ids=['hit-reads-tail', 'nohit-reads-tail', 'nohit-unread-claim'])
async def test_p03_actual_search_then_native_consumer_observation(ws, request, case, unread):
    held = {}
    driver = source_consumer_factory(case, unread, held)
    folder = Path(os.environ.get('REPORT_SOURCE_CONTINUATION_OUT', str(ws.store.root / 'captures'))) / request.node.name
    capture = await capture_source_continuation(ws, case, folder, driver)
    oracle = capture['oracle']
    request.node.user_properties.append(('source_continuation', json.dumps({
        'case': case, 'unread': unread, 'capture_dir': str(folder), 'oracle': oracle,
        'paid_calls': 0, 'app_changes': 0, 'real_model_behavior': False}, ensure_ascii=False)))
    assert capture['raised_error'] is None, capture['raised_error']
    assert capture['runtime_result']['last_error'] is None, capture['runtime_result']
    assert len([e for e in capture['phase_events'] if e['phase'] == 'explicit_fake_initial_search']) == 1
    assert capture['native_model_calls'], 'Actual handler/model callback must execute'
    schema = {s['name']: s['parameters'] for s in driver.bindings['writer'][0]}
    assert {'search_sources', 'read_source_page'} <= schema.keys()
    assert schema['read_source_page']['properties']['offset']['description'].startswith('Zero-based frozen text-block offset')
    assert oracle['source_originals_unchanged']
    assert oracle['setup_tail_visible'] is False
    assert oracle['first_consumer_tail_visible'] is False, 'Report an invalid fixture premise; do not remove legal context'
    assert oracle['semantic_status'] == 'needs_semantic_review'
    assert len(oracle['actual_searches']) == 1
    assert oracle['actual_searches'][0]['actual_value'] == held['search']
    if unread:
        assert oracle['status'] == 'not_observed'
        assert oracle['actual_source_reads'] == []
        assert oracle['complete_block_input_indexes'] == []
        assert capture['parent']['task_return']['content'] == FALSE_ABSENCE
        assert len(driver.calls) == 1
    else:
        assert oracle['status'] == 'selected_blocks_observed'
        assert len(oracle['actual_source_reads']) == 2
        assert oracle['complete_block_input_indexes']
        assert [r['actual_value']['blocks'][0] for r in oracle['actual_source_reads']] == GEOLOGY
        assert GEOLOGY[1]['text'] in capture['parent']['task_return']['content']
        assert len(driver.calls) == 3
