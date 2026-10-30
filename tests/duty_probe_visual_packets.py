"""R3 offline preparation; live clients may only be supplied by the budgeted runner.

These helpers do not configure providers, retry calls, or claim visual/engineering
acceptance. prepare_visual creates actual Office files from synthetic inputs.
perform_visual_and_artifact uses internal implementations of the registered
inspect_rendered_page and perform_assigned_artifact_review interfaces, explicitly
inside one real delegated Reviewer context; it is not an autonomous agent run.
"""
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from langchain_core.messages import AIMessage, messages_to_dict

from report_agent.artifact_review import bounded_artifact_review_tool
from report_agent.content_export import export_snapshot, render_export, inspect_render
from report_agent.content_models import Ref
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import run_report
from report_agent.hierarchical_tools import actor_for
from report_agent.task_supervision import reconcile
from duty_probe_packets import _capture, provider_call
from test_decision_data import activate
from test_deep_runtime import Driver, invoke, call
from test_agent_duty_repro_artifacts import structural_snapshot


LAYOUT_STANDARD = ('Current governing synthetic format standard: margins top/bottom/left 25 mm, right 15 mm; '
    'Normal body font size 12 pt; body, heading, TOC and table paragraph spacing 1.5 lines; '
    'heading sizes 18/15/14 pt; keep all four table columns and the footnote; one logical TOC. '
    'The exact cover line "Synthetic cover project" may use single spacing; that exception does not apply to body text. '
    'Existing older exports or their parameters are unverified references, not an acceptance baseline.')


def _write(folder, name, value):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


async def capture_layout(ws, case, folder):
    if case not in {'layout-standard', 'layout-old-reference'}:
        raise ValueError(case)
    cs, refs, snapshot, before, _ = structural_snapshot(ws, child_count=3, with_format_content=False)
    owner = actor_for('coordinator')
    records = cs.commit(owner, 'r3-layout-reference-inputs', [
        {'client_key': 'standard', 'type': 'ContentNode', 'payload': {'kind': 'block',
         'body': {'text': LAYOUT_STANDARD}, 'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'old', 'type': 'ContentNode', 'payload': {'kind': 'block',
         'body': {'text': 'Old R6 layout reference only; NOT validated against the current standard. '
             'Parameters: right margin 25 mm; body line spacing 1.3; table line spacing 1.15. '
             'This is historical metadata, not a new instruction or requirement.'},
         'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'table', 'type': 'ContentNode', 'payload': {'kind': 'table',
         'body': {'columns': ['Indicator', 'Class', 'Score', 'Note'], 'rows': [['Synthetic item', 'B', '75', 'Conditional']]},
         'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'footnote', 'type': 'ContentNode', 'payload': {'kind': 'block',
         'body': {'text': 'Original footnote: applicability remains conditional on actual classification.'},
         'qualifiers': {}, 'claim_kind': 'structure'}},
        *[{'client_key': key + '_edge', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
          'object_ref': {'client_key': key}, 'predicate': 'contains', 'position': i + 10,
          'provenance_kind': 'adopted_during_generation'}} for i, key in enumerate(['table', 'footnote'])]])['result']['refs']
    additions = {k: v for k, v in records.items() if k not in {'standard', 'old'}}
    snapshot = cs.freeze(owner, 'r3-layout-complete-snapshot', refs['root'],
        [*cs.read(snapshot)['payload']['refs'], *additions.values()])['result']['snapshot_ref']
    refs.update(additions)
    before.update({k: cs.read(r) for k, r in additions.items()})
    description = ('Prepare layout for this saved synthetic report using the current governing format standard. '
        'Preserve the source content. Standard reference: ' + json.dumps(records['standard']) + '.')
    steps = [invoke('read_layout_capabilities'), invoke('read_context', target_ref=records['standard']),
             invoke('read_context', target_ref=snapshot)]
    if case == 'layout-old-reference':
        description += ' An older unverified layout reference is available: ' + json.dumps(records['old']) + '.'
        steps.append(invoke('read_context', target_ref=records['old']))
    steps.append(AIMessage(content='Offline native input capture only.'))
    ws.store.set('manifest', {**ws.store.manifest, 'goal': description})
    activate(ws)
    driver = Driver(coordinator=[invoke('task', subagent_type='layout', description=description,
        layout_snapshot_ref=snapshot), AIMessage(content='Offline capture ended.')], layout=steps)
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    assert before == {k: cs.read(r) for k, r in refs.items()}
    fake_response = provider_call('export_content_snapshot', {'operation_id': 'r3-layout-example',
        'snapshot_ref': snapshot, 'layout': {'toc': True, 'top_margin_mm': 25, 'bottom_margin_mm': 25,
            'left_margin_mm': 25, 'right_margin_mm': 15, 'line_spacing': 1.5, 'table_line_spacing': 1.5,
            'styles': [{'name': 'Normal', 'font_size': 12, 'line_spacing': 1.5}]}})
    captured = _capture(driver, 'layout', {'case': case, 'snapshot_ref': snapshot,
        'standard_ref': records['standard'], 'standard_original': cs.read(records['standard']),
        'old_reference': cs.read(records['old']) if case == 'layout-old-reference' else None,
        'pending_action': 'Actual next Layout decision; the example response is a harness shape fixture, not appended to messages.',
        'independent_expected': {'right_margin_mm': 15, 'body_line_spacing': 1.5, 'table_line_spacing': 1.5,
                                 'old_parameters_must_not_override_current_standard': True}}, fake_response)
    _write(folder, 'native-capture.json', {**captured, 'messages': messages_to_dict(captured['messages'])})
    return captured


async def prepare_visual(ws, folder, *, include_note_column=False):
    """Actual one-page fixture; the optional Note column is a test-only contrast.

    Default keeps the original R3 three-column fixture. The source, criterion,
    two required checks and visual question remain identical in both variants.
    """
    expected = ('Synthetic rule: Class B uses score 75. The comparison table must have four columns: '
                'Indicator, Class, Score, Note. Record visible discrepancies and any uncertainty; '
                'do not infer fieldwork, engineering safety or unobserved pages.')
    ws.store.set('manifest', {**ws.store.manifest, 'goal': 'Inspect one synthetic report page against its exact source standard.',
        'sources': [{'id': 'r3-standard', 'title': 'Independent synthetic visual standard',
                     'content': expected, 'coverage': 'complete'}]})
    cs, owner = ContentStore(ws.store), actor_for('coordinator')
    inputs = cs.import_inputs(owner, 'r3-visual-inputs', ['r3-standard'])['result']
    objects = [
        {'client_key': 'root', 'type': 'ContentNode', 'payload': {'kind': 'report',
         'body': {'text': 'SYNTHETIC VISUAL CHECK'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'rule', 'type': 'ContentNode', 'payload': {'kind': 'block',
         'body': {'text': 'Displayed reference rule: CLASS B uses SCORE 75. Required table columns: Indicator, Class, Score, Note.'},
         'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'table', 'type': 'ContentNode', 'payload': {'kind': 'table',
         'body': {'columns': ['Indicator', 'Class', 'Score'] + (['Note'] if include_note_column else []),
                  'rows': [['TEST-OBJECT', 'B', '70'] + (['Synthetic note'] if include_note_column else [])]},
         'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'criterion', 'type': 'Criterion', 'payload': {'requirement_refs': [inputs['requirement_ref']],
         'purpose': 'Compare the visible table with the independent synthetic source rule.', 'scope': 'Exact single rendered page only',
         'expected_outcome': 'Identify any visible 70/75 disagreement and missing required Note column, or retain uncertainty if not observable.',
         'evidence_expectation': 'Exact independent source and full-page actual image observation with version/page binding.',
         'allowed_limits': 'Visual observation is uncertain; this is not engineering or whole-report acceptance.'}},
        *[{'client_key': key + '_edge', 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'root'},
          'object_ref': {'client_key': key}, 'predicate': 'contains', 'position': i,
          'provenance_kind': 'adopted_during_generation'}} for i, key in enumerate(['rule', 'table'])]]
    refs = cs.commit(owner, 'r3-visual-objects', objects)['result']['refs']
    refs['standard_source'] = inputs['source_refs'][0]
    snapshot = cs.freeze(owner, 'r3-visual-snapshot', refs['root'],
        [*refs.values(), inputs['requirement_ref']])['result']['snapshot_ref']
    exported = export_snapshot(cs, owner, 'r3-visual-export', snapshot, {'toc': False, 'line_spacing': 1.5,
        'styles': [{'name': 'Normal', 'font_family': 'DejaVu Sans', 'font_size': 14}]})['result']
    rendered = render_export(cs, owner, 'r3-visual-render', exported['export_ref'])['result']
    assert rendered['execution_state'] == 'completed', {'environment_or_render_gap': rendered}
    payload = cs.read(rendered['render_ref'])['payload']
    assert len(payload['page_assets']) == 1, 'Single-page fixture precondition failed; do not call paid vision.'
    copied = []
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for file_ref in [exported['file_ref'], payload['pdf_ref'], payload['page_assets'][0]['asset_ref']]:
        raw = (ws.store.root / file_ref).read_bytes()
        path = folder / Path(file_ref).name
        path.write_bytes(raw)
        copied.append({'file_ref': file_ref, 'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()})
    question = ('Read this physical page. Transcribe the reference rule and the table headers and data cells. '
                'Describe visible inconsistencies or missing columns, and state any uncertainty. '
                'Do not infer unshown pages or engineering acceptance.')
    requirements = [{'target_ref': refs['table'], 'criterion_ref': refs['criterion'], 'scope_id': 'r3-visible-table',
        'required_checks': ['Compare displayed score with the exact source rule.', 'Compare visible columns with the four-column standard.'],
        'required_read_refs': [refs['standard_source']],
        'required_materials': [{'requirement_index': i, 'purpose': 'Exact table and independent source standard.',
            'refs': [refs['table'], refs['standard_source']]} for i in range(2)],
        'assessment_kind': 'render', 'artifact_refs': [rendered['render_ref']]}]
    assignment = call('task', {'subagent_type': 'reviewer',
        'description': 'Compare only the single actual rendered page against the supplied synthetic standard. Preserve uncertainty.',
        'review_snapshot_ref': snapshot, 'review_requirements': requirements}, 'r3-visual-review-task')
    activate(ws)
    result = {'cs': cs, 'refs': refs, 'snapshot': snapshot, 'export_ref': exported['export_ref'],
        'render_ref': rendered['render_ref'], 'call': assignment, 'question': question}
    _write(folder, 'visual-preparation.json', {k: v for k, v in result.items() if k != 'cs'} | {
        'assets': copied, 'source': cs.read(refs['standard_source']), 'criterion': cs.read(refs['criterion']),
        'render_record': cs.read(rendered['render_ref']), 'case_kind': 'compound_synthetic_case_not_single_variable_pair',
        'expected_observations': ['Score cell 70 differs from displayed/source class-B score75.',
            'Four required table columns are present.' if include_note_column else 'Three table columns; required Note column absent.'],
        'include_note_column': include_note_column,
        'real_model_calls': 0, 'artifact_check_completed': False, 'engineering_acceptance': False})
    return result


async def perform_visual_and_artifact(ws, prepared, folder, *, vision_client, artifact_model, operation_prefix='r3'):
    """Caller owns full vision+text provider budget and ledger; no implicit live client.

    Internal implementations are exercised under a genuine delegated identity.
    Caller must not interpret this as an autonomous Reviewer decision loop.
    Each invocation attempts at most one inspect_render call and one checker call;
    SDK retries, if configured, must be included in the caller's request budget.
    """
    cs = prepared['cs']
    result = {'interface_boundary': 'internal inspect_render + bounded_artifact_review_tool under real delegated task',
              'real_model_count_not_inferred': True, 'engineering_acceptance': False, 'automatic_retry': False}
    try:
        with delegated_task(ws, 'coordinator', prepared['call']) as (task, reviewer):
            result.update(actor=asdict(reviewer), task=task)
            reads = [cs.read_context(reviewer, prepared['refs'][k]) for k in ['table', 'standard_source']]
            result['material_reads'] = reads
            _write(folder, 'execution-progress.json', result)
            vision = await inspect_render(cs, reviewer, prepared['render_ref'], 1, prepared['question'], client=vision_client)
            result['vision'] = vision
            assert vision['ok'] and vision['result']['status'] == 'observed', vision
            result['receipts'] = [r['receipt_id'] for r in reads] + [vision['receipt_id']]
            _write(folder, 'execution-progress.json', result)
            checker = bounded_artifact_review_tool(ws, artifact_model)
            result['artifact'] = await checker(operation_prefix + '-artifact', ['r3-visible-table'], result['receipts'])
            result['reconcile'] = reconcile(cs, reviewer.task_id)
            result['saved_review'] = cs.read(result['artifact']['result']['review_ref'])
            result['artifact_check_completed'] = result['reconcile']['execution_complete']
            return result
    except Exception as exc:
        result['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        _write(folder, 'execution-result.json', result)


async def perform_public_visual_and_artifact(ws, prepared, folder, *, vision_client,
                                            artifact_model, operation_prefix='r12'):
    """Fake decisions, real public Reviewer tools, caller-supplied model clients.

    No response substitution occurs here. Caller owns budgets, wire observers and
    the supplied artifact model; inspect_rendered_page closes its supplied vision
    client through its normal public path. These scripted choices are a native
    I/O probe, not evidence that a live Coordinator/Reviewer chose the actions.
    """
    from unittest.mock import patch
    from report_agent.content_tasks import bound_actor
    from test_agent_duty_trace_cases import action, result_value, tool_reply

    cs, refs = prepared['cs'], prepared['refs']
    result = {'interface_boundary': 'native run_report -> public Reviewer ToolNode -> supplied vision/checker',
        'decision_models': 'fake Coordinator and Reviewer', 'real_model_count_not_inferred': True,
        'engineering_acceptance': False, 'automatic_retry': False, 'material_reads': [],
        'receipts': [], 'artifact_check_completed': False, 'saved_review': None}

    def read_standard(messages):
        reviewer = bound_actor(ws, 'reviewer', actor_for('reviewer'))
        result['actor'] = asdict(reviewer)
        response = result_value(tool_reply(messages, 'table'))
        result['material_reads'].append(response)
        if not response.get('ok'):
            result['failure'] = {'stage': 'read_table', 'response': response}
            return AIMessage(content=json.dumps(result['failure']))
        result['receipts'].append(response['receipt_id'])
        return action('read_context', 'standard', target_ref=refs['standard_source'])

    def inspect_page(messages):
        response = result_value(tool_reply(messages, 'standard'))
        result['material_reads'].append(response)
        if not response.get('ok'):
            result['failure'] = {'stage': 'read_standard', 'response': response}
            return AIMessage(content=json.dumps(result['failure']))
        result['receipts'].append(response['receipt_id'])
        return action('inspect_rendered_page', 'page', render_ref=prepared['render_ref'],
                      page=1, question=prepared['question'])

    def compare(messages):
        message = tool_reply(messages, 'page')
        result['vision_tool_message'] = message.model_dump()
        response = result_value(message)
        result['vision'] = response
        if not response.get('ok') or response.get('result', {}).get('status') != 'observed':
            result['failure'] = {'stage': 'inspect_rendered_page', 'response': response}
            return AIMessage(content=json.dumps(result['failure']))
        result['receipts'].append(response['receipt_id'])
        args = {'operation_id': operation_prefix + '-artifact', 'scope_ids': ['r3-visible-table'],
                'observation_receipts': list(result['receipts'])}
        result['actual_caller_args'] = args
        _write(folder, 'execution-progress.json', result)
        return action('perform_assigned_artifact_review', 'compare', **args)

    def child_finish(messages):
        message = tool_reply(messages, 'compare')
        result['next_reviewer_tool_message'] = message.model_dump()
        try:
            public = result_value(message)
        except (ValueError, TypeError):
            public = {'public_error': str(message.content)}
        result['artifact'] = public
        result['reconcile'] = reconcile(cs, result['actor']['task_id'])
        review_ref = public.get('result', {}).get('review_ref')
        if review_ref:
            result['saved_review'] = cs.read(review_ref)
            result['artifact_check_completed'] = result['reconcile']['execution_complete']
        else:
            result['failure'] = {'stage': 'perform_assigned_artifact_review',
                                 'tool_message': message.model_dump()}
        _write(folder, 'execution-progress.json', result)
        return AIMessage(content=str(message.content))

    def parent(messages):
        result['next_coordinator_tool_message'] = tool_reply(messages, prepared['call']['id']).model_dump()
        return AIMessage(content='Scoped public tool outcome retained. No engineering acceptance or retry.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[prepared['call']]), parent],
        reviewer=[action('read_context', 'table', target_ref=refs['table']), read_standard,
                  inspect_page, compare, child_finish])

    def model_factory(role):
        return artifact_model if role == 'text_tool' else driver(role)

    try:
        with patch('report_agent.deep_models.configured_vision_client', lambda: vision_client):
            result['runtime_result'] = await run_report(ws, model_factory)
        if result['runtime_result']['last_error']:
            result['failure'] = {'stage': 'native_runtime', 'error': result['runtime_result']['last_error']}
        return result
    except Exception as exc:
        result['failure'] = {'stage': 'native_runtime_exception', 'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        result['bindings'] = driver.bindings
        result['fake_decision_calls'] = [{'role': role, 'step': step} for role, step, _ in driver.calls]
        _write(folder, 'native-decision-inputs.json', [
            {'role': role, 'step': step, 'messages': messages_to_dict(messages)}
            for role, step, messages in driver.calls])
        _write(folder, 'execution-result.json', result)
