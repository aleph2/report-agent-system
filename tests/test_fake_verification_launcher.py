"""Offline operator-boundary checks. No real ledger, credentials or model request."""
import hashlib
import json
from pathlib import Path
import shutil
from unittest.mock import patch

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
    # The operator configures every service role in the process environment.
    with patch.dict('os.environ'):
        yield authority, write_json(authority, data), data


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
    from types import SimpleNamespace
    from report_agent import mini_commission
    from report_agent.content_store import ContentStore
    from report_agent.store import Store
    from support.judgment_inputs import install_test_judgment_inputs
    original_prepare = mini_commission.prepare_mini_commission
    def prepare_with_confirmed_observations(inputs, case):
        result = original_prepare(inputs, case)
        cs = ContentStore(Store(case))
        plan_ref = result['plan_ref']
        fixture = SimpleNamespace(cs=cs, plan_ref=plan_ref, plan=cs.read(plan_ref)['payload'])
        source, = [s for s in cs.store.source_catalog() if s['filename']=='01_initial.pdf']
        # This test exercises native transport with a synthetic X11 rule; engineering uncertainty is tested separately.
        for oid, page, quote, grade in [('A',1,'坡段 A：坡高 18 米','low'), ('B',2,'坡段 B：坡高 25 米','moderate')]:
            install_test_judgment_inputs(fixture, oid, source['id'], page, quote,
                                         classifications={'X11':grade}, section_id='3')
        return result
    monkeypatch.setattr(mini_commission, 'prepare_mini_commission', prepare_with_confirmed_observations)
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
        saves = {row['function']['name']:row['function']['parameters'] for row in body['tools']
                 if row['function']['name'].startswith('save_')}
        assert set(saves) == {'save_evidence','save_assumption','save_gap'}
        assert all('kind' not in schema.get('properties',{}) for schema in saves.values())
        assert not any('expected.json' in str(m) for m in body['messages'])
        text = next(m['content'] for m in body['messages'] if m['role']=='user')
        if isinstance(text,list):
            text = ''.join(part['text'] for part in text if part['type']=='text')
        step = json.loads(text)
        label, indicator = step['object_label'], step['indicator_id']
        choices = {g['min_value']:g['choice'] for g in step['grades']}
        if indicator=='X11' and label=='坡段 A':
            tool = 'save_evidence'
            outcome = {'grade':choices['0'],'value':'10','basis_kind':'direct_evidence',
                       'rationale':'A is 18 m tall.','quotes':['坡段 A：坡高 18 米']}
        elif indicator=='X11' and label=='坡段 B':
            tool = 'save_assumption'
            outcome = {'grade':choices['25'],'value':'35','quotes':['坡段 B：坡高 25 米'],
                       'rationale':'Material is unspecified.','plausible_grades':[choices['0'],choices['25']],
                       'question':'Confirm soil or rock for B?'}
        else:
            tool = 'save_gap'
            outcome = {'missing':'Scripted transport test gap.','question':'Review against the fixture?',
                       'rationale':'Explanation retained by the simulated test.'}
        calls.append((label, indicator, tool))
        if interrupted:
            raise httpx.ReadError('Synthetic reply lost after sending.')
        message = {'role':'assistant','content':None,'tool_calls':[{
            'id':'call_'+str(len(calls)), 'type':'function','function':{'name':tool,
            'arguments':json.dumps(outcome)}}]}
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
    if not interrupted:
        import sqlite3
        from contextlib import closing
        assert len({(label,indicator) for label,indicator,_ in calls}) == 22
        assert {tool for _,_,tool in calls} == {'save_evidence','save_assumption','save_gap'}
        db_path = Path(prepared['case_path'])/'state.db'
        with closing(sqlite3.connect(db_path.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            from report_agent.store import Store
            from report_agent.writer_judgments import read_progress
            store = Store(Path(prepared['case_path']))
            keys = [k for k, in db.execute("SELECT DISTINCT assignment FROM writer_step_receipts")]
            drafts = [read_progress(store,k,db)['rows'] for k in keys]
        assert len(drafts)==2 and all(len(d)==11 for d in drafts)
        first_rows = {d['X11']['kind']:d['X11'] for d in drafts}
        assert first_rows['evidence']['judgment']['grade_id']=='low'
        assert set(first_rows['assumption']['judgment']['plausible_grades'])=={'low','moderate'}
        assert all(d['X12']['kind']=='gap' and d['X12']['input']['rationale'] for d in drafts)
        assert not any(s['refusals'] for s in result['slopes'])
    with pytest.raises(FileExistsError):
        await operator.launch(path,pin,prepared['prepared_sha256'],env)


def test_module_cli_prepares_checks_runs_and_rejects_duplicate_launch(tmp_path):
    """Every action runs via the documented entry point in a separate interpreter."""
    import os
    import subprocess
    import sys

    # The CLI checks its real Git tree. Use a disposable copy so a developer can
    # run this regression against working source before committing a change.
    root = Path(operator.__file__).resolve().parents[2]
    snapshot = tmp_path/'snapshot'
    shutil.copytree(root/'src/report_agent', snapshot/'src/report_agent',
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(operator.INPUTS.parent, snapshot/'tests/fake_data/mini_commission')
    shutil.copyfile(root/'pyproject.toml', snapshot/'pyproject.toml')
    for git_args in (
        ['init','-q'], ['add','--','src','tests','pyproject.toml'],
        ['-c','user.name=Test','-c','user.email=test@localhost',
         '-c','commit.gpgsign=false','commit','-qm','Synthetic test candidate'],
    ):
        subprocess.run(['git','-C',str(snapshot),*git_args],check=True,capture_output=True)

    shim = tmp_path/'no-network'
    shim.mkdir()
    wire_log = tmp_path/'wire.jsonl'
    (shim/'sitecustomize.py').write_text(
        "import json, os, socket, uuid\n"
        "import httpx\n"
        "def deny(*args, **kwargs): raise AssertionError('offline test forbids sockets')\n"
        "socket.socket.connect = socket.create_connection = deny\n"
        "async def reply(self, request):\n"
        "    assert request.url.host == 'offline.invalid'\n"
        "    body = json.loads(request.content)\n"
        "    saves = sorted(t['function']['name'] for t in body['tools'] if t['function']['name'].startswith('save_'))\n"
        "    assert saves == ['save_assumption','save_evidence','save_gap']\n"
        "    with open(os.environ['FAKE_CLI_WIRE_LOG'], 'a') as stream: stream.write(json.dumps(saves)+'\\n')\n"
        "    call = {'id':uuid.uuid4().hex,'type':'function','function':{'name':'save_gap',"
        "'arguments':json.dumps({'missing':'Offline CLI test fact.','question':'Review the test input?'})}}\n"
        "    message = {'role':'assistant','content':None,'tool_calls':[call]}\n"
        "    return httpx.Response(200,json={'id':'offline','object':'chat.completion','created':1,"
        "'model':'glm-5.3','choices':[{'index':0,'finish_reason':'tool_calls','message':message}],"
        "'usage':{'prompt_tokens':6,'completion_tokens':4,'total_tokens':10}})\n"
        "httpx.AsyncHTTPTransport.handle_async_request = reply\n")
    url = 'https://offline.invalid/v1'
    env_file = tmp_path/'services.env'
    env_file.write_text(
        'HIGHWAY_MODEL_DEEPSEEK_NAME=deepseek-v4.1-flash-1017\n'
        f'HIGHWAY_MODEL_DEEPSEEK_BASE_URL={url}\nHIGHWAY_MODEL_DEEPSEEK_API_KEY=test\n'
        f'HIGHWAY_MODEL_NAME=glm-5.3\nHIGHWAY_MODEL_BASE_URL={url}\nHIGHWAY_MODEL_API_KEY=test\n')
    env = {**os.environ, 'PYTHONPATH':os.pathsep.join((str(shim),str(snapshot/'src'))),
           'FAKE_CLI_WIRE_LOG':str(wire_log), 'REPORT_CONNECT_RETRIES':'2','REPORT_SDK_RETRIES':'0',
           'LANGCHAIN_TRACING_V2':'false','LANGSMITH_TRACING':'false'}
    def invoke(action, *options, success=True):
        cp = subprocess.run([sys.executable,'-B','-m','report_agent.fake_verification',action,*options],
                            cwd=snapshot,env=env,capture_output=True,text=True,timeout=120)
        if success:
            assert cp.returncode==0, (cp.stderr,cp.stdout)
            return json.loads(cp.stdout)
        assert cp.returncode!=0
        return cp.stderr

    identity = invoke('identify')
    grant = tmp_path/'synthetic-grant'
    authority = tmp_path/'synthetic-authority.json'
    sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
    pin = write_json(authority, {**identity,'workflow':operator.WORKFLOW,'run_id':'cli-01',
        'per_run_tokens':3_700_000,'aggregate_tokens':10_000_000,'grant_dir':str(grant),
        'owner_authority_ref':'offline-test','request_bound_proof':{
            'model':'glm-5.3','input_limit':1_048_576,'output_limit':131_072,
            'basis':'documented_model_ceiling_not_measured_request_fit',
            'env_sha256':operator._sha(env_file),'base_url_sha256':sha(url),
            'request_url_sha256':sha(url+'/chat/completions'),
            'sources':['https://docs.z.ai/guides/llm/glm-5.3','https://help.aliyun.com/zh/model-studio/glm-5-3']}})
    args = ['--authority',str(authority),'--authority-sha256',pin]
    invoke('init-grant',*args)
    prepared = invoke('prepare',*args)
    args += ['--prepared-sha256',prepared['prepared_sha256']]
    checked = invoke('check',*args)
    assert checked['plan_ref']==prepared['plan_ref']
    assert not wire_log.exists()
    args += ['--env',str(env_file)]
    result = invoke('run',*args)
    receipt = grant/'runs/cli-01/result.json'
    original = receipt.read_bytes()
    assert json.loads(original)==result
    assert result['status']=='closed_with_gaps' and result['finished_at_utc']
    assert [s['object_id'] for s in result['slopes']]==['A','B']
    assert result['budget']['settled']==220 and result['budget']['held']==0
    assert 'FAKE_ALREADY_CLAIMED' in invoke('run',*args,success=False)
    assert receipt.read_bytes()==original
    assert len(wire_log.read_text().splitlines())==22
