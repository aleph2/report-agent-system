"""Offline responsibility regressions, not evidence of autonomous LLM compliance.

The recorded judge replays reviewed exact-input labels; it performs no semantic
inference. The current-input gates deliberately stay RED while Co retains the
known instruction conflict or page-inspection capability. No xfail or paid calls.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from report_agent.deep_runtime import build_agent
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deep_runtime import Driver
from test_task_supervision import offline


DATA = json.loads(Path(__file__).with_name('fixtures').joinpath('co_instruction_traces.json').read_text(encoding='utf-8'))


def review_key(observation, contract):
    observation = {**observation, 'text':' '.join(observation['text'].split())}
    return hashlib.sha256(json.dumps([contract, observation], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_judgment(observation, contract, judgment):
    assert judgment['decision'] in {'clear', 'conflict', 'needs_review'}
    findings = judgment['findings']
    assert bool(findings) == (judgment['decision'] == 'conflict')
    for finding in findings:
        assert finding['duty'] in contract['forbidden']
        assert finding['quote'] and finding['quote'] in ' '.join(observation['text'].split())
    return judgment


class RecordedDutyJudge:
    """An exact-input fixture cache, never a substitute for a semantic judge."""
    def __init__(self, corpus):
        self.labels = {review_key(row['observation'], corpus['role_contract']):row['expected']
                       for row in corpus['observations']}

    def review(self, observation, contract):
        result = deepcopy(self.labels.get(review_key(observation, contract),
            {'decision':'needs_review', 'findings':[]}))
        return validate_judgment(observation, contract, result)


@pytest.mark.parametrize('example', DATA['observations'], ids=lambda row:row['id'])
def test_recorded_labels_are_exact_input_oracles_not_keyword_matches(example):
    result = RecordedDutyJudge(DATA).review(example['observation'], DATA['role_contract'])
    assert result == example['expected']


def test_unknown_wording_and_changed_role_policy_cannot_silently_pass():
    judge = RecordedDutyJudge(DATA)
    original = DATA['observations'][0]['observation']
    assert judge.review(original, DATA['role_contract'])['decision'] == 'conflict'
    negated = {**original, 'text':'Do not follow this old instruction: '+original['text']}
    assert judge.review(negated, DATA['role_contract'])['decision'] == 'needs_review'
    changed = deepcopy(DATA['role_contract'])
    changed['forbidden'].append('another_explicitly_reviewed_duty')
    assert judge.review(original, changed)['decision'] == 'needs_review'
    assert judge.review({**original, 'actor':'layout'}, DATA['role_contract'])['decision'] == 'needs_review'


def test_unverified_evidence_citation_is_rejected():
    example = DATA['observations'][0]
    forged = deepcopy(example['expected'])
    forged['findings'][0]['quote'] = 'Invented instruction not in the observed input.'
    with pytest.raises(AssertionError):
        validate_judgment(example['observation'], DATA['role_contract'], forged)


@pytest.mark.parametrize('trace', DATA['traces'], ids=lambda row:row['id'])
async def test_fake_llm_replays_observed_actions_without_executing_them(trace):
    calls = [row['call'] for row in trace['recorded_actions']]
    driver = Driver(coordinator=[AIMessage(content='Recorded fake-data replay only.', tool_calls=calls)])
    reply = await driver('coordinator').ainvoke([HumanMessage('Replay; do not execute any tool.')])
    assert reply.tool_calls == calls
    assert len(driver.calls) == 1
    assert trace['normalization']['derived']
    assert trace['source']['sha256'] and trace['source']['body_sha256']
    observation = next(row for row in DATA['observations'] if row['id']==trace['instruction_id'])
    assert RecordedDutyJudge(DATA).review(observation['observation'], DATA['role_contract'])['decision'] == 'conflict'


@pytest.fixture
async def current_co_input(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal':'Coordinate a synthetic report; delegate independent checking.',
        'synthetic':True, 'content_contract':'hierarchical-review-v1',
        'review_entrypoint':'delegated-reviewer-v1', 'review_execution_mode':'native-reviewer-v2',
        'review_interface_profile':'review-interfaces-v4',
        'delegation_prompt_profile':'separate-description-v1',
        'operation_identity_profile':'native-tool-runtime-v1',
        'report_expression_profile':'reader-expression-v2', 'report_prompt_profile':'concise-v1',
        'sources':[{'id':'fake-source', 'content':'Fictional source only.', 'coverage':'complete'}]})
    driver = Driver(coordinator=[AIMessage(content='Offline capture only; no tool work.')])
    await build_agent(Workspace(store), driver, None).ainvoke({'messages':[HumanMessage('Capture this offline fixture.')]})
    event = next(e for e in store.events() if e['kind']=='prompt_model_input')
    return store.get(event['data']['capture_key'])['public_input']


class TestCurrentCoResponsibilityContract:
    async def test_co_is_not_offered_personal_page_inspection(self, current_co_input):
        names = {tool['function']['name'] for tool in current_co_input['tools']}
        assert 'inspect_rendered_page' not in names, 'Co inspection duty is still exposed; a prompt slogan is not a boundary.'

    async def test_effective_co_tool_help_has_no_known_caller_review_assignment(self, current_co_input):
        functions = {tool['function']['name']:tool['function'] for tool in current_co_input['tools']}
        if 'export_content_workbook' not in functions:
            return  # No such caller help was offered; export ownership is not decided here.
        observation = {'actor':'coordinator', 'channel':'tool_description',
            'name':'export_content_workbook', 'text':functions['export_content_workbook']['description']}
        judgment = RecordedDutyJudge(DATA).review(observation, DATA['role_contract'])
        assert judgment['decision'] == 'clear', f'Co instruction requires correction or explicit review: {judgment}'
