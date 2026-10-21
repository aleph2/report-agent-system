"""P22 fault sensitivity of the retained native fake chain, not app repairs.

Only a fake Layout action or one delivered review field is changed. The original
first-draft / coordinator assertions must detect that exact fault. These cases
do not assert that production automatically detects or repairs the corruption.
"""
import ast
from copy import deepcopy
import inspect
import json
from pathlib import Path

from docx import Document
from langchain_core.messages import ToolMessage
import pytest

import duty_probe_completion_chain as chain
from report_agent.content_store import ContentStore
from report_agent.task_context import TaskContext
from test_agent_duty_repro_artifacts import save_evidence, toc_fields
from test_task_supervision import ws, offline


REMAINING = 'B classification evidence is required.'


def original_assertion(function, expression):
    path = Path(inspect.getsourcefile(chain.run_completion_chain)).resolve()
    tree = ast.parse(path.read_text(encoding='utf-8'))
    scope = next(n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function)
    node = next(n for n in ast.walk(scope)
                if isinstance(n, ast.Assert) and ast.unparse(n.test) == expression)
    return {'file': str(path), 'function': function, 'line': node.lineno, 'expression': expression}


@pytest.mark.parametrize('fault', ['missing_toc', 'lost_review_remaining'])
async def test_complete_chain_original_oracle_detects_injected_fault(ws, request, monkeypatch, fault):
    expected = original_assertion(
        'first_artifact_oracle' if fault == 'missing_toc' else 'coordinator_select',
        "len(toc_fields(doc)) == standard['toc_count']" if fault == 'missing_toc'
        else "'B classification evidence is required.' in text")
    held = {'fault': fault, 'injections': [], 'assertions': [], 'sensitivity_only': True}
    original_action = chain.action
    original_bound = TaskContext.bound_result
    original_respond = chain.Driver.respond

    def fake_action(name, call_id, **args):
        message = original_action(name, call_id, **args)
        if (fault == 'missing_toc' and name == 'export_content_snapshot'
                and call_id == 'word' and args.get('operation_id') == 'p22-word'):
            before = deepcopy(message.tool_calls)
            after = deepcopy(before)
            assert after[0]['args']['layout']['toc'] is True
            after[0]['args']['layout']['toc'] = False
            held['injections'].append({'boundary': 'fake Layout chosen action',
                                      'before': before, 'after': after})
            return message.model_copy(update={'tool_calls': after})
        return message

    def delivered_result(self, result, tool_args=None):
        delivered = original_bound(self, result, tool_args)
        if (fault == 'lost_review_remaining' and self.role == 'coordinator'
                and isinstance(delivered, ToolMessage) and delivered.name == 'task'
                and delivered.tool_call_id == 'review-task' and delivered.status == 'success'):
            assert not held['injections'], 'Inject only once into the actual coordinator delivery.'
            assert isinstance(delivered.content, str)
            packet = json.loads(delivered.content)
            item = next(item for item in packet['items'] if item['scope_id'] == 'b')
            assert item['check_results'][0]['remaining'] == REMAINING
            old = '"remaining": ' + json.dumps(REMAINING)
            assert delivered.content.count(old) == 1
            content = delivered.content.replace(old, '"remaining": ""', 1)
            expected_packet = deepcopy(packet)
            next(item for item in expected_packet['items'] if item['scope_id'] == 'b')['check_results'][0]['remaining'] = ''
            assert json.loads(content) == expected_packet
            changed = delivered.model_copy(update={'content': content})
            record = ContentStore(ws.store).read(packet['review_ref'])
            held['injections'].append({'boundary': 'actual review-task ToolMessage after original bound_result',
                'before': delivered.model_dump(mode='json'), 'after': changed.model_dump(mode='json'),
                'review_record_before': deepcopy(record)})
            return changed
        return delivered

    async def observe_assertions(self, role, messages):
        try:
            return await original_respond(self, role, messages)
        except AssertionError as exc:
            tb, frames = exc.__traceback__, []
            while tb is not None:
                frame = tb.tb_frame
                entry = {'file': str(Path(frame.f_code.co_filename).resolve()),
                         'function': frame.f_code.co_name, 'line': tb.tb_lineno}
                frames.append(entry)
                if all(entry[k] == expected[k] for k in ('file', 'function', 'line')):
                    # Observe original locals only; never replace its verdict.
                    held['observed'] = frame.f_locals['observed']
                tb = tb.tb_next
            held['assertions'].append({'role': role, 'message': str(exc), 'frames': frames})
            raise

    monkeypatch.setattr(chain, 'action', fake_action)
    monkeypatch.setattr(TaskContext, 'bound_result', delivered_result)
    monkeypatch.setattr(chain.Driver, 'respond', observe_assertions)
    # Native runtime records a failed scripted oracle. The helper's original
    # outer result check must remain red; only this test calibrates that failure.
    with pytest.raises(AssertionError):
        await chain.run_completion_chain(ws, request, False)

    assert len(held['injections']) == 1
    matches = [a for a in held['assertions']
               if a['frames'][-1] == {k: expected[k] for k in ('file', 'function', 'line')}]
    assert len(matches) == 1, held['assertions']
    observed = held['observed']
    assert observed['runtime_result']['last_error'] is not None
    assert observed['final_selected_state'] is None
    cs = ContentStore(ws.store)
    assert ws.store.manifest['sources'] == observed['input_sources']
    assert observed['content_before_layout'] == {k: cs.read(r) for k, r in observed['refs'].items()}
    if fault == 'missing_toc':
        assert len(toc_fields(Document(ws.store.root / observed['word']['file_ref']))) == 0
        assert observed['render']['execution_state'] == 'completed'
        assert not cs.list_objects('ReviewRecord')
        assert not observed.get('first_draft_oracle_before_review')
    else:
        record = held['injections'][0]['review_record_before']
        assert cs.read(record['ref']) == record
        assert next(i for i in record['payload']['items'] if i['scope_id'] == 'b')['check_results'][0]['remaining'] == REMAINING
        assert observed['first_draft_oracle_before_review']['passed'] is True
        assert observed['review_status']['execution_complete'] is False
        assert observed['review_status']['remaining']
        assert REMAINING not in json.dumps(observed['parent_review'])
    observed['fault_sensitivity'] = {k: v for k, v in held.items() if k != 'observed'}
    observed['fault_sensitivity'].update(expected_original_assertion=expected,
        exact_original_oracle_detected_fault=True, application_bug_discovered=False,
        production_automatic_detection_proven=False, final_delivery_completed=False)
    save_evidence(request, ws, observed)
    request.node.user_properties.append(('chain_fault_sensitivity', json.dumps(observed['fault_sensitivity'])))
