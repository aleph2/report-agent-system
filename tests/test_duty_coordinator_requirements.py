"""Two P01 native fake calibrations; structural transport is not semantic review."""
from copy import deepcopy
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from duty_probe_agent_decisions import dump
from duty_probe_coordinator_requirements import (
    CLAUSES, FINAL, FORMAT_EXCLUDED, FORMAT_INCLUDED, SOURCE_INSTRUCTION, SOURCES,
    capture_coordinator_requirements, criterion_payload,
)
from report_agent.content_store import ContentStore
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


def coordinator_requirements_script(ws, variant, held):
    def setup_not_called(messages):
        raise AssertionError('Native middleware must occupy the initial fake read step')

    def after_reads(messages):
        originals = []
        for i in range(4):
            message = tool_reply(messages, 'p01-input-' + str(i))
            value = result_value(message)
            assert message.status == 'success' and value['ok'] is True
            assert len(value['result']['objects']) == 1
            originals.append(value['result']['objects'][0])
        requirement, *sources = originals
        assert requirement['ref']['type'] == 'Requirement'
        for clause in CLAUSES:
            assert clause in requirement['payload']['text']
        for source, original in zip(sources, SOURCES, strict=True):
            assert source['ref']['type'] == 'SourceArtifact'
            assert source['payload']['source_id'] == original['id']
            assert source['payload']['content'] == original['content']
        assert all(SOURCE_INSTRUCTION not in str(m.content) for m in messages if m.type == 'system')
        held['actual_original_reads'] = originals
        normal = criterion_payload(requirement['ref'])
        submitted = criterion_payload(requirement['ref'], exclude_format=variant == 'explicit-format-exclusion')
        changed_fields = [k for k in normal if normal[k] != submitted[k]]
        assert changed_fields == (['expected_outcome'] if variant == 'explicit-format-exclusion' else [])
        assert submitted['expected_outcome'] == normal['expected_outcome'].replace(
            FORMAT_INCLUDED, FORMAT_EXCLUDED if changed_fields else FORMAT_INCLUDED)
        held['normal_payload'], held['submitted'], held['changed_fields'] = normal, submitted, changed_fields
        return action('commit_objects', 'p01-save-criterion', operation_id='p01-establish-criteria',
            objects=[{'client_key': 'commission', 'type': 'Criterion', 'payload': deepcopy(submitted)}])

    def after_commit(messages):
        message = tool_reply(messages, 'p01-save-criterion')
        value = result_value(message)
        assert message.status == 'success' and value['ok'] is True
        held['actual_commit_receipt'] = message.model_dump()
        held['saved_ref'] = value['result']['refs']['commission']
        assert ContentStore(ws.store).read(held['saved_ref'])['payload'] == held['submitted']
        return action('read_context', 'p01-read-saved', target_ref=held['saved_ref'])

    def after_readback(messages):
        message = tool_reply(messages, 'p01-read-saved')
        value = result_value(message)
        assert message.status == 'success' and value['ok'] is True
        assert len(value['result']['objects']) == 1
        saved = value['result']['objects'][0]
        assert saved['ref'] == held['saved_ref'] and saved['payload'] == held['submitted']
        held['actual_readback'] = saved
        return AIMessage(content=FINAL)

    return [setup_not_called, after_reads, after_commit, after_readback]


@pytest.mark.parametrize('variant', ['complete', 'explicit-format-exclusion'])
async def test_coordinator_preserves_original_requirements_and_explicit_semantic_counterexample(ws, tmp_path, variant):
    root = Path(os.environ.get('REPORT_COORDINATOR_REQUIREMENTS_OUT', tmp_path / 'evidence'))
    folder, held = root / variant, {}
    driver = Driver(coordinator=coordinator_requirements_script(ws, variant, held))
    capture = await capture_coordinator_requirements(ws, variant, folder, driver)
    dump(folder / 'independent-observations.json', held)
    assert capture['raised_error'] is None, capture['raised_error']
    assert capture['runtime']['last_error'] is None, capture['runtime']
    assert capture['originals_unchanged'] is True
    assert capture['finals'] == [FINAL]
    assert len(capture['criteria']) == len(capture['new_objects']) == 1
    assert capture['criteria'][0] == held['actual_readback']
    assert capture['criteria'][0]['payload'] == held['submitted']
    assert capture['tasks'] == capture['handoffs'] == capture['issues'] == []
    assert capture['execution_decision'] is None
    actions = [c['name'] for e in capture['phase_events'] for m in e.get('response', [])
               for c in m['data'].get('tool_calls', [])]
    assert actions == ['commit_objects', 'read_context']
    assert [(role, step) for role, step, _ in driver.calls] == [('coordinator', 1), ('coordinator', 2), ('coordinator', 3)]
    # Known two-output calibration: explicit exclusion + the unchanged complete
    # claim is contradictory. This is not a keyword-absence or general semantic
    # detector. All new artifacts and the entire actual action/final sequence
    # above exclude an alternative task/criterion/remaining that carries format.
    assert capture['criteria'][0]['payload']['expected_outcome'] == held['normal_payload']['expected_outcome'].replace(
        FORMAT_INCLUDED, FORMAT_EXCLUDED if variant == 'explicit-format-exclusion' else FORMAT_INCLUDED)
    actual_counterexample = capture['criteria'][0]['payload']['expected_outcome'] == held['normal_payload']['expected_outcome'].replace(
        FORMAT_INCLUDED, FORMAT_EXCLUDED)
    assert actual_counterexample is (variant == 'explicit-format-exclusion')
    semantic = 'needs_semantic_review' if actual_counterexample else 'not_semantically_assessed'
    dump(folder / 'oracle.json', {'mechanical_result': 'passed', 'known_fixture_semantic_status': semantic,
        'classification_basis': 'Exact known explicit exclusion and unchanged complete claim, considered with all new artifacts/actions.',
        'normal_is_not_semantic_acceptance': True, 'fake_consumer_calls': len(driver.calls),
        'fake_setup_read_calls': 4, 'paid_calls': 0, 'no_alternative_artifact_or_explicit_remaining': True,
        'scope': 'Criteria establishment only; no generated report, child strategy or engineering acceptance.'})
