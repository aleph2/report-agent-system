"""Actual supported GEPA adapter/serialization contract; offline, no quality claim."""
import socket

import pytest

gepa = pytest.importorskip('gepa')
from report_agent.gepa_report_learning import ReportExperiment
from report_agent.learning import LearningLibrary, LearningScope
from report_agent.report_learning import COMPONENT, read_json


def test_supported_adapter_reflects_trace_and_persists_normal_runtime_candidate(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No provider allowed in compatibility check')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    library = LearningLibrary(tmp_path / 'library')
    scope = LearningScope('a', '/origin')
    item = library.feedback(scope, {}, {}, 'Observed output defect', {}, [{'id': 'evidence'}])
    seed = library.propose(scope, [item['id']], 'customer_preference', 'Title', 'Original text', 'Fixed conditions', 'Pending')
    def case(name):
        return {'case_id': name, 'goal': name, 'sources': [{'content': name}]}
    config = {'seed': seed, 'library_root': str(tmp_path / 'library'),
        'splits': {'train': [case('train')], 'validation': [case('val')], 'holdout': [case('holdout')]}}
    experiment = ReportExperiment(config, tmp_path / 'experiment', runtime_python='forbidden', driver='forbidden')
    seen = []
    def rollout(candidate, example):
        seen.append((candidate, example['case_id']))
        return {'score': float(candidate[COMPONENT] == 'Improved text'), 'feedback': 'Actual trace fixture defect',
            'execution_trace': {'observed_tool_returns': [{'content': 'TRACE_OBSERVATION'}]},
            'artifact_observation': {'complete': True}, 'messages': []}
    monkeypatch.setattr(experiment, 'rollout', rollout)
    prompts = []
    def reflection(prompt):
        prompts.append(prompt)
        return '```\nImproved text\n```'
    monkeypatch.setattr(experiment, 'reflect', reflection)
    record = experiment.run(4)
    assert record['state'] == 'completed' and record['num_candidates'] == 2
    assert 'TRACE_OBSERVATION' in str(prompts)
    assert 'holdout' not in str(prompts)
    selected = read_json(tmp_path / 'experiment/selected-experience.json')
    assert selected['strategy'] == 'Improved text' and selected['conditions'] == 'Fixed conditions'
    assert selected['version'] == 2 and not selected['active']
    assert record['holdout'][0]['baseline']['score'] == 0 and record['holdout'][0]['candidate']['score'] == 1


@pytest.mark.parametrize('exercise,expected_reflections', [(False,0),(True,1)])
def test_perfect_baseline_has_supported_stopping_bound(tmp_path, monkeypatch, exercise, expected_reflections):
    def forbidden(*args, **kwargs):
        raise AssertionError('No provider allowed')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    library=LearningLibrary(tmp_path/'library');scope=LearningScope('a','/origin')
    item=library.feedback(scope,{}, {}, 'Actual correction fixture',{},[{'id':'source'}])
    seed=library.propose(scope,[item['id']],'customer_preference','Title','Original text','Fixed','Pending')
    def case(name):return {'case_id':name,'goal':name,'sources':[{'content':name}]}
    config={'seed':seed,'library_root':str(tmp_path/'library'),'exercise_reflection':exercise,
        'splits':{'train':[case('train')],'validation':[case('val')],'holdout':[case('holdout')]}}
    experiment=ReportExperiment(config,tmp_path/'experiment',runtime_python='forbidden',driver='forbidden')
    monkeypatch.setattr(experiment,'rollout',lambda candidate,example:{'score':1.0,'feedback':'All fixture checks pass',
        'execution_trace':{'observed_tool_returns':[]},'artifact_observation':{'complete':True},'messages':[]})
    prompts=[]
    def reflect(prompt):prompts.append(prompt);return '```\nAlternative text\n```'
    monkeypatch.setattr(experiment,'reflect',reflect)
    result=experiment.run(4)
    assert len(prompts)==expected_reflections
    assert result['candidate'][COMPONENT]=='Original text'
    assert result['num_candidates']==1
