"""Offline operator-boundary checks. No real ledger, credentials or model request."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from report_agent import fake_verification as operator


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def packet(tmp_path, monkeypatch):
    inputs = tmp_path / 'fixture'
    shutil.copytree(operator.INPUTS, inputs)
    monkeypatch.setattr(operator, 'INPUTS', inputs)
    monkeypatch.setattr(operator, '_candidate_commit', lambda: 'a' * 40)
    authority = tmp_path / 'authority.json'
    grant = tmp_path / 'grant'
    info = operator.identify()
    data = {**info, 'workflow': operator.WORKFLOW, 'run_id': 'test-01',
            'grant_dir': str(grant), 'per_run_tokens': 3_700_000, 'aggregate_tokens': 10_000_000,
            'owner_authority_ref':'synthetic-test', 'request_bound_proof': {}}
    return authority, write_json(authority, data), data


def test_authority_hash_candidate_manifest_and_limits_are_pinned(packet):
    path, pin, data = packet
    assert operator.preflight(path, pin)['run_id'] == 'test-01'
    with pytest.raises(ValueError, match='AUTHORITY_PIN'):
        operator.preflight(path, '0'*64)
    for key, value in [('per_run_tokens', 3_700_001), ('aggregate_tokens', 10_000_001),
                       ('candidate_commit', '0'*40), ('fixture_manifest_sha256', '0'*64),
                       ('run_id', '../outside')]:
        digest = write_json(path, {**data, key: value})
        with pytest.raises(ValueError):
            operator.preflight(path, digest)


def test_input_hash_mismatch_and_verifier_in_inputs_fail_closed(packet, monkeypatch):
    path, pin, _ = packet
    extra = operator.INPUTS / 'expected.json'
    extra.write_text('synthetic verifier')
    with pytest.raises(ValueError, match='FIXTURE_INPUT_SET'):
        operator.preflight(path, pin)
    extra.unlink()
    scope = operator.INPUTS / '00_scope.md'
    scope.write_bytes(scope.read_bytes() + b' altered')
    with pytest.raises(ValueError, match='AUTHORITY_SCOPE'):
        operator.preflight(path, pin)


def test_clean_preparation_and_tampered_case_preflight(packet):
    path, pin, _ = packet
    prepared = operator.prepare(path, pin)
    assert prepared['plan_ref']['type'] == 'CommissionPlan'
    assert prepared['object_ids'] == ['A','B']
    verified = operator.check_prepared(path, pin, prepared['prepared_sha256'])
    assert verified['decision_ref']['type'] == 'CommissionDecision'
    with pytest.raises(FileExistsError):
        operator.prepare(path, pin)
    case = Path(prepared['case_path'])
    with (case/'state.db').open('ab') as stream:
        stream.write(b'tampered')
    with pytest.raises(ValueError, match='PREPARED_CASE_CHANGED'):
        operator.check_prepared(path, pin, prepared['prepared_sha256'])

@pytest.mark.asyncio
@pytest.mark.parametrize('interrupted', [False, True])
async def test_launch_claim_is_single_use_and_accounts_at_real_client_boundary(packet, tmp_path, monkeypatch, interrupted):
    from report_agent import deep_models, model_config
    from report_agent.fake_verification_budget import FakeVerificationBudget
    import httpx

    path, _, data = packet
    env = tmp_path/'synthetic-services'
    env.write_text('test configuration only')
    url = 'https://offline.invalid/v1'
    sha = lambda value: hashlib.sha256(value.encode()).hexdigest()
    data['request_bound_proof'] = {
        'model':'glm-5.3','input_limit':1_048_576,'output_limit':131_072,
        'basis':'documented_model_ceiling_not_measured_request_fit','env_sha256':operator._sha(env),
        'base_url_sha256':sha(url),'request_url_sha256':sha(url+'/chat/completions'),
        'sources':['https://docs.z.ai/guides/llm/glm-5.3','https://help.aliyun.com/zh/model-studio/glm-5-3'],
    }
    pin = write_json(path, data)
    FakeVerificationBudget.initialize(Path(data['grant_dir']), {operator.MODEL:operator.BOUND})
    prepared = operator.prepare(path, pin)
    for key, value in {'REPORT_CONNECT_RETRIES':'2','REPORT_SDK_RETRIES':'0',
                       'REPORT_REASONING_EFFORT':'high', 'REPORT_WRITER_MODEL':'glm-5.3',
                       'REPORT_WRITER_BASE_URL':url,'REPORT_WRITER_API_KEY':'synthetic'}.items():
        monkeypatch.setenv(key,value)
    monkeypatch.setattr(model_config,'load_mixed_services',lambda _: None)
    monkeypatch.setattr(model_config,'bind_role_services',lambda _: None)
    original = deep_models.configured_model
    calls = []
    async def provider(request):
        body = json.loads(request.content)
        tool = 'save_indicator_outcome'
        assert tool in {row['function']['name'] for row in body['tools']}
        assert not any('expected.json' in str(m) for m in body['messages'])
        calls.append(body['model'])
        if interrupted:
            raise httpx.ReadError('Synthetic reply lost after sending.')
        message = {'role':'assistant','content':None,'tool_calls':[{
            'id':'call_'+str(len(calls)), 'type':'function','function':{'name':tool,
            'arguments':json.dumps({'kind':'gap','missing':'Scripted transport test gap.',
                                    'question':'Review against the actual fixture?'})}}]}
        return httpx.Response(200,json={'id':'test_'+str(len(calls)),'object':'chat.completion','created':1,
            'model':operator.MODEL,'choices':[{'index':0,'finish_reason':'tool_calls','message':message}],
            'usage':{'prompt_tokens':6,'completion_tokens':4,'total_tokens':10}})
    def offline_model(store, role):
        model = original(store, role)
        monkeypatch.setattr(model.http_async_client._transport,'handle_async_request',provider)
        return model
    monkeypatch.setattr(deep_models,'configured_model',offline_model)
    await operator.launch(path,pin,prepared['prepared_sha256'],env)
    result = json.loads((Path(prepared['case_path']).parent/'result.json').read_text())
    assert result['status'] == ('interrupted' if interrupted else 'closed_with_gaps'), result
    assert result['budget']['settled'] == (0 if interrupted else 220)
    assert result['budget']['held'] == (operator.BOUND if interrupted else 0)
    assert len(calls) == (1 if interrupted else 22)
    assert [s['object_id'] for s in result['slopes']] == (['A'] if interrupted else ['A','B'])
    with pytest.raises(FileExistsError):
        await operator.launch(path,pin,prepared['prepared_sha256'],env)
