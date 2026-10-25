"""Coordinator's real task schema versus native artifact assignment admission.

Only an existing RenderArtifact pointer's declared type is varied. This does not
claim that a ContentNode/SourceArtifact with that same ID exists. Native rejection
and missing model-visible schema constraints are separate assertions.
"""
from copy import deepcopy
import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage
import pytest

from duty_probe_visual_packets import prepare_visual, perform_public_visual_and_artifact
from report_agent.deep_runtime import run_report
from test_agent_duty_repro_artifacts import save_evidence
from test_deep_runtime import Driver
from test_duty_artifact_contrast import ContrastModel
from test_task_supervision import ws, offline
from test_vision import VisionModel


def task_schema(bindings):
    return next(s['parameters'] for s in bindings['coordinator'][0] if s['name'] == 'task')


def changed_type_args(original, declared_type):
    changed = deepcopy(original)
    changed['review_requirements'][0]['artifact_refs'][0]['type'] = declared_type
    restored = deepcopy(changed)
    restored['review_requirements'][0]['artifact_refs'][0]['type'] = 'RenderArtifact'
    assert restored == original
    return changed


def diagnostic_objects(value):
    """Read nested JSON error envelopes, retaining the unmodified public message."""
    if isinstance(value, dict):
        yield value
        for part in value.values():
            yield from diagnostic_objects(part)
    elif isinstance(value, list):
        for part in value:
            yield from diagnostic_objects(part)
    elif isinstance(value, str):
        # ActionRejected can prefix the complete readiness JSON with a code.
        start = value.find('{')
        if start >= 0:
            try:
                parsed = json.loads(value[start:])
            except ValueError:
                return
            yield from diagnostic_objects(parsed)


@pytest.mark.parametrize('declared_type', ['RenderArtifact', 'ContentNode', 'SourceArtifact'])
async def test_native_coordinator_task_artifact_admission_before_child_dispatch(ws, request, declared_type):
    folder = Path(os.environ.get('REPORT_ARTIFACT_REPRO_OUT', str(ws.store.root / 'repro'))) / request.node.name
    prepared = await prepare_visual(ws, folder, include_note_column=True)
    cs = prepared['cs']
    baseline = deepcopy(prepared['call']['args'])
    prepared['call']['args'] = changed_type_args(baseline, declared_type)
    protected = [*prepared['refs'].values(), prepared['snapshot'], prepared['export_ref'], prepared['render_ref']]
    before = [cs.read(r) for r in protected]
    checker = ContrastModel(note_present=True, duplicate_index=False)
    service = VisionModel(content='Displayed rule: Class B uses score 75. Table columns Indicator, Class, Score, Note; '
        'row TEST-OBJECT, B, 70, Synthetic note. Four columns present; score differs. Synthetic uncertain observation.')
    observed = {'baseline_args': baseline, 'actual_task_args': prepared['call']['args'],
        'single_mutation': '$.review_requirements[0].artifact_refs[0].type',
        'declared_type': declared_type, 'identity_limitation': 'Wrong declared type of the same Render pointer; no claim that a same-ID source/content object exists.'}
    try:
        result = await perform_public_visual_and_artifact(ws, prepared, folder,
            vision_client=service, artifact_model=checker, operation_prefix='task-artifact-type')
        observed.update(result=result, fake_vision_calls=len(service.calls), fake_checker_calls=len(checker.calls),
            fake_reviewer_calls=sum(c['role'] == 'reviewer' for c in result['fake_decision_calls']),
            actual_coordinator_schema=task_schema(result['bindings']), review_records=cs.list_objects('ReviewRecord'))
        with ws.store.connect() as db:
            observed['raw_analyses'] = {r[0]: json.loads(r[1]) for r in db.execute('SELECT operation,data FROM analyses')}
        Draft202012Validator(observed['actual_coordinator_schema']).validate(baseline)
        assert result['runtime_result']['last_error'] is None, result
        assert before == [cs.read(r) for r in protected]
        assert result['next_coordinator_tool_message']
        if declared_type == 'RenderArtifact':
            assert len(service.calls) == len(checker.calls) == 1
            assert observed['fake_reviewer_calls'] == 5
            assert len(observed['review_records']) == 1
            saved = result['saved_review']
            assert saved == observed['review_records'][0]
            assert saved['owner_id'] == result['actor']['id'] and saved['task_id'] == result['actor']['task_id']
            assert saved['payload']['snapshot_ref'] == prepared['snapshot']
            assert result['artifact']['review'] == saved['payload']
            assert result['artifact_check_completed']
            item, = saved['payload']['items']
            assert item['verdict'] == 'not_satisfied'
            assert [c['requirement_index'] for c in item['check_results']] == [0, 1]
            assert all(c['execution_state'] == 'completed' for c in item['check_results'])
            assert checker.packet['requirements'][0]['required_checks'] == baseline['review_requirements'][0]['required_checks']
        else:
            public = result['next_coordinator_tool_message']
            issues = [o for o in diagnostic_objects(public) if o.get('code') == 'TASK_ARTIFACT_OUTSIDE_SNAPSHOT'
                      and o.get('path') == '/review_requirements/0/artifact_refs/0']
            observed['matching_native_type_issues'] = issues
            if issues:
                assert all(o['ref'] == prepared['call']['args']['review_requirements'][0]['artifact_refs'][0] for o in issues)
            else:
                # The same existing type rule may now reject at typed input,
                # before readiness. Require the exact field, not a generic error.
                content = public['content']
                assert ('literal_error' in content and 'INVALID_REVIEW_REQUIREMENTS' in content
                        and 'ReviewRequirement' in content and 'artifact_refs.0.type' in content), public
            assert observed['fake_reviewer_calls'] == len(service.calls) == len(checker.calls) == 0
            assert not observed['raw_analyses']
            assert not observed['review_records'] and result['saved_review'] is None
            assert not result['artifact_check_completed']
    finally:
        await service.close()
        save_evidence(request, ws, observed)


@pytest.mark.parametrize('forbidden_type', ['ContentNode', 'SourceArtifact'])
async def test_final_coordinator_schema_expresses_task_artifact_type_constraint(ws, request, forbidden_type):
    folder = Path(os.environ.get('REPORT_ARTIFACT_REPRO_OUT', str(ws.store.root / 'repro'))) / request.node.name
    prepared = await prepare_visual(ws, folder, include_note_column=True)
    # Real native agent construction/bind_tools; no submitted task or child call
    # is needed to capture the schema actually presented to this Coordinator.
    driver = Driver(coordinator=[AIMessage(content='Capture registered task schema only; no review commissioned.')])
    runtime = await run_report(ws, driver)
    schema = task_schema(driver.bindings)
    baseline = deepcopy(prepared['call']['args'])
    Draft202012Validator(schema).validate(baseline)
    invalid = changed_type_args(baseline, forbidden_type)
    errors = list(Draft202012Validator(schema).iter_errors(invalid))
    observed = {'runtime_result': runtime, 'actual_final_coordinator_task_schema': schema,
        'valid_render_baseline': baseline, 'single_type_variant': invalid,
        'single_mutation': '$.review_requirements[0].artifact_refs[0].type',
        'schema_errors': [{'message': e.message, 'path': list(e.path), 'schema_path': list(e.schema_path)} for e in errors],
        'rule_origin': 'task_supervision.review_readiness checks ExportArtifact/RenderArtifact at lines 269-273.',
        'native_admission_evidence': 'Separate three-state native test in this same file; no direct validator substitutes for delegation.',
        'case_scope': 'Final model-visible JSON type constraint only; no same-ID object existence or full semantic acceptance claim.',
        'fake_model_calls': [{'role': role, 'step': step} for role, step, _ in driver.calls],
        'paid_calls': 0}
    save_evidence(request, ws, observed, driver)
    assert runtime['last_error'] is None, runtime
    assert [role for role, _, _ in driver.calls] == ['coordinator']
    # Retain red when the schema omits the existing native simple type rule.
    assert errors, ('COORDINATOR_TASK_ARTIFACT_TYPE_NOT_EXPRESSED', forbidden_type)
