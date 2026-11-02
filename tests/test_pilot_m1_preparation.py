"""M1 prepares requirements-led real-input cases without model requests."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import sys
import tarfile

import httpx
import pytest
from pypdf import PdfReader

from report_agent.errors import ActionRejected
from report_agent.request_budget import (RequestBudgetExceeded, current_budget_observation,
    account_request, enforce_host_admission, request_reservation_observer)
from report_agent.store import Store
from report_agent.token_budget import TokenBudget, account_response, token_budget
from test_ingestion import pdf_bytes


ROOT = Path(__file__).resolve().parents[1]
COMMISSION = '报告编写范围说明.md'
REQUIREMENTS = ('请以所提供的巡检记录为依据编制设备验收备忘录，列出未确认事项。\n'
    '交付 UTF-8 Markdown 正文与 JSON 问题清单；保持记录中的时间和设备编号。\n'
    '本次不委托施工安全风险评分，也不需要风险评估表。')


def put_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def input_set(root, *, references=0, extras=1, scopes=1):
    root.mkdir(parents=True)
    for index in range(scopes):
        path = root / ('nested' if index else '') / COMMISSION
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(REQUIREMENTS, encoding='utf-8-sig')
    for index in range(extras):
        (root / ('记录-' + str(index) + '.md')).write_text(
            '设备A17于2026-10-24完成巡检；验收结论尚待核实。', encoding='utf-8')
    for index in range(references):
        path = root / '成果报告' / ('仅格式参考-' + str(index) + '.pdf')
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(pdf_bytes(('Structure and formatting example only.',)))
    return root


def host_case(tmp_path, monkeypatch, *, references=0, extras=1, scopes=1):
    import resource
    monkeypatch.setattr(resource, 'setrlimit', lambda *args: None)
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    ns = runpy.run_path(str(ROOT / 'scripts/report_host.py'), run_name='m1_offline_prepare')
    state = ns['prepare'].__globals__
    here = tmp_path / 'run'; here.mkdir()
    inputs = input_set(here / 'inputs', references=references, extras=extras, scopes=scopes)
    config = deepcopy(state['CONFIG'])
    config.update(synthetic=False, round_token_limit=100_000_000, m1_token_limit=200_000_000)
    # A stale legacy count must not constrain a requirements-led input set.
    config['input_file_count'] = 999
    for name, value in {'HERE': here, 'INPUT': inputs, 'CASE': here / 'case',
        'LEDGER': tmp_path / 'finance/token-budget.db', 'CANONICAL': tmp_path / 'old-finance.db',
        'CONFIG': config, 'LIMIT': 100_000_000, 'SOURCE': ROOT,
        'endpoint_pins': lambda: {'coordinator': 'offline-endpoint-pin'}}.items():
        monkeypatch.setitem(state, name, value)
    pins = {str(p.relative_to(inputs)): state['sha'](p) for p in sorted(inputs.rglob('*')) if p.is_file()}
    put_json(here / 'approved-input-hashes.json', pins)
    put_json(here / 'approved-endpoint-pins.json', state['endpoint_pins']())
    profiles = []
    for name, digest in pins.items():
        if not name.endswith('.pdf'):
            continue
        reader = PdfReader(inputs / name)
        sizes = [len(page.get_contents().get_data()) if page.get_contents() is not None else 0
            for page in reader.pages]
        profiles.append({'path': name, 'sha256': digest, 'input_bytes': (inputs / name).stat().st_size,
            'pages': len(reader.pages), 'largest_page_bytes': max(sizes, default=0),
            'total_decoded_bytes': sum(sizes)})
    put_json(here / 'pdf-limits.json', profiles)
    deployment = {'repository': str(ROOT), 'ledger': str(state['LEDGER'])}
    monkeypatch.setitem(state, 'DEPLOYMENT', deployment)
    put_json(here / 'deployment.json', deployment)
    put_json(here / 'authorization.json', {'authority': 'Offline M1 preparation fixture only',
        'round_token_limit': 100_000_000, 'm1_token_limit': 200_000_000})
    return state


@pytest.mark.parametrize('references,extras', [(0, 1), (2, 7)], ids=['no-format-directory', 'two-format-pdfs'])
def test_prepare_uses_complete_requirements_and_optional_template_pdfs(tmp_path, monkeypatch, references, extras):
    state = host_case(tmp_path, monkeypatch, references=references, extras=extras)
    state['prepare']()
    prepared = json.loads((state['HERE'] / 'prepared.json').read_text())
    manifest = Store(state['CASE']).manifest
    assert prepared['synthetic'] is False and manifest['synthetic'] is False
    assert REQUIREMENTS in manifest['goal'] and prepared['goal'] == manifest['goal']
    assert '总体施工安全风险评估报告' not in manifest['goal']
    assert 'Word' not in manifest['goal'] and 'Excel' not in manifest['goal']
    assert len(prepared['source_files']) == 1 + extras + references
    for name, item in prepared['source_files'].items():
        assert item['sha256'] == state['sha'](state['INPUT'] / name)
        if Path(name).parts[0] == '成果报告':
            assert item['purpose'] == 'template'
        elif Path(name).name == COMMISSION:
            assert item['purpose'] == 'commission'
        else:
            assert item['purpose'] == 'source_or_applicable_standard'
    if not references:
        assert '成果报告' not in manifest['goal']
        assert '成果报告' not in manifest.get('scope_instruction', '')
    else:
        assert '结构' in manifest['goal']
        assert '仅供结构' not in manifest['goal'] and '仅作格式' not in manifest['goal']
    assert not (state['CASE'] / 'checkpoints.db').exists()


@pytest.mark.parametrize('scopes', [0, 2], ids=['missing-commission', 'duplicate-commission'])
def test_prepare_requires_exactly_one_commission_without_creating_case(tmp_path, monkeypatch, scopes):
    state = host_case(tmp_path, monkeypatch, scopes=scopes)
    with pytest.raises((ValueError, RuntimeError), match='COMMISSION'):
        state['prepare']()
    assert not state['CASE'].exists()
    assert not (state['HERE'] / 'prepared.json').exists()


@pytest.mark.parametrize('references', [0, 2])
def test_g2_preparation_uses_neutral_commission_frame_optional_templates_and_checkpoint(tmp_path, monkeypatch, references):
    state = host_case(tmp_path, monkeypatch, references=references)
    state['prepare']()
    prepared = json.loads((state['HERE'] / 'prepared.json').read_text())
    manifest = Store(state['CASE']).manifest
    assert manifest['commission_checkpoint_required'] is True
    assert REQUIREMENTS in manifest['goal']
    frame = manifest['goal'].replace(REQUIREMENTS, '') + manifest.get('scope_instruction', '')
    assert '设计' not in frame and '地勘' not in frame
    assert 'Word' not in frame and 'Excel' not in frame
    assert 'structure_and_format_only' not in frame
    assert '仅供结构' not in frame and '仅作结构' not in frame
    assert '仅供格式' not in frame and '仅作格式' not in frame
    templates = [item for name, item in prepared['source_files'].items()
                 if Path(name).parts[0] == '成果报告']
    assert len(templates) == references
    assert all(item['purpose'] == 'template' for item in templates)
    from report_agent.handoff_release import release
    assert release(manifest)['commission_checkpoint_required'] is True


def stage_fixture(tmp_path, monkeypatch, *, extras):
    import resource
    monkeypatch.setattr(resource, 'setrlimit', lambda *args: None)
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    ns = runpy.run_path(str(ROOT / 'scripts/stage_report.py'), run_name='m1_offline_stage')
    state = ns['stage'].__globals__
    repository = tmp_path / 'repository'; repository.mkdir()
    monkeypatch.setitem(state, 'REPOSITORY', repository)
    archive = BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as tar:
        for relative in state['RELEASE_PATHS']:
            tar.add(ROOT / relative, arcname=relative, filter=lambda info: None if '__pycache__' in info.name else info)
    original_run_path = runpy.run_path
    def load_host(path, **kwargs):
        host = original_run_path(path, **kwargs)
        host['endpoint_pins'] = lambda: {'coordinator': 'offline-endpoint-pin'}
        return host
    monkeypatch.setattr(runpy, 'run_path', load_host)
    def git(*args):
        if args[0] == 'rev-parse':
            return b'0123456789012345678901234567890123456789\n'
        if args[0] == 'show':
            return (ROOT / 'scripts/stage_report.py').read_text().encode()
        assert args[:2] == ('archive', '--format=tar')
        return archive.getvalue()
    monkeypatch.setitem(state, 'git', git)
    args = SimpleNamespace(run=tmp_path / 'staged', inputs=input_set(tmp_path / 'originals', extras=extras),
        ledger=tmp_path / 'finance/token-budget.db', revision='offline-fixture',
        authority='Offline stage fixture, no dispatch', reuse_ledger=False, budget_authority=None)
    return state, args


@pytest.mark.parametrize('extras', [2, 7], ids=['three-originals', 'eight-originals'])
def test_stage_pins_variable_input_sets_without_fixed_file_count(tmp_path, monkeypatch, extras):
    state, args = stage_fixture(tmp_path, monkeypatch, extras=extras)
    state['stage'](args)
    receipt = json.loads((args.run / 'stage-receipt.json').read_text())
    assert receipt['status'] == 'staged_no_model_calls'
    assert len(receipt['input_hashes']) == extras + 1
    for name, digest in receipt['input_hashes'].items():
        assert state['hashlib'].sha256((args.inputs / name).read_bytes()).hexdigest() == digest
        assert (args.inputs / name).read_bytes() == (args.run / 'inputs' / name).read_bytes()
    assert not args.ledger.exists() and not (args.run / 'case').exists()


@pytest.mark.parametrize('fault', ['symlink', 'unsupported-type'])
def test_stage_keeps_escape_and_type_guards_with_variable_input_count(tmp_path, monkeypatch, fault):
    state, args = stage_fixture(tmp_path, monkeypatch, extras=2)
    if fault == 'symlink':
        target = tmp_path / 'private.md'; target.write_text('Not an authorized source.', encoding='utf-8')
        (args.inputs / 'escape.md').symlink_to(target)
    else:
        (args.inputs / 'executable.exe').write_bytes(b'not-an-input')
    with pytest.raises(ValueError, match='INPUT_ESCAPE_TYPE_OR_LIMIT'):
        state['stage'](args)
    assert not args.ledger.exists()


def test_pilot_defaults_are_real_inputs_initial_100m_and_shared_m1_200m():
    config = json.loads((ROOT / 'config/current.json').read_text())
    assert config['synthetic'] is False
    assert config['round_token_limit'] == 100_000_000
    assert config['m1_token_limit'] == 200_000_000


def attempt_rows(budget):
    with budget.connect() as db:
        return db.execute('SELECT * FROM attempts ORDER BY id').fetchall()


def test_one_persistent_m1_ledger_counts_smoke_full_and_rerun_without_resetting_unknown(tmp_path, monkeypatch):
    state = host_case(tmp_path, monkeypatch)
    budget = TokenBudget(state['LEDGER'], 200_000_000, {'m': 40_000_000})
    smoke = budget.reserve('m'); budget.settle(smoke, {'total_tokens': 10_000_000})
    unknown = budget.reserve('m'); budget.settle(unknown, None)
    baseline = state['finance'](); original = attempt_rows(budget)
    full = TokenBudget(budget.path, 200_000_000, {'m': 40_000_000})
    attempt = full.reserve('m'); full.settle(attempt, {'total_tokens': 30_000_000})
    missing_usage = full.reserve('m'); full.settle(missing_usage, None)
    assert state['budget_scope_cost'](baseline, state['finance']()) == (30_000_000, 40_000_000, True)
    rerun = TokenBudget(budget.path, 200_000_000, {'m': 40_000_000})
    attempt = rerun.reserve('m'); rerun.settle(attempt, {'total_tokens': 20_000_000})
    assert state['budget_scope_cost'](baseline, state['finance']()) == (50_000_000, 40_000_000, True)
    assert rerun.snapshot()['recorded_tokens'] == 60_000_000
    assert rerun.snapshot()['reserved_or_unknown_upper_bounds'] == 80_000_000
    rerun.reserve('m')
    before_refusal = attempt_rows(rerun)
    with pytest.raises(RequestBudgetExceeded, match='AUTHORIZED_TOKEN_BUDGET_REACHED'):
        rerun.reserve('m')
    assert attempt_rows(rerun) == before_refusal
    final = {row[0]: row for row in attempt_rows(rerun)}
    assert all(final[row[0]] == row for row in original)


@pytest.mark.parametrize('fault', ['authorization', 'deleted-row', 'released-unknown'])
def test_run_scope_rejects_prior_ledger_drift_instead_of_subtracting_it(tmp_path, monkeypatch, fault):
    state = host_case(tmp_path, monkeypatch)
    budget = TokenBudget(state['LEDGER'], 200_000_000, {'m': 2_000_000})
    budget.settle(budget.reserve('m'), None)
    before = state['finance'](); now = deepcopy(before)
    if fault == 'authorization':
        now['auth'][0] += 1
    elif fault == 'deleted-row':
        now['rows'].clear()
    else:
        now['rows'][0][4] = 'known_not_sent'
    with pytest.raises(RequestBudgetExceeded, match='HOST_BASELINE_CHANGED'):
        state['budget_scope_cost'](before, now)
    assert state['finance']() == before


@pytest.mark.parametrize('field', ['response_id', 'reason', 'at'])
def test_run_scope_detects_prior_attempt_metadata_drift_from_actual_ledger(tmp_path, monkeypatch, field):
    state = host_case(tmp_path, monkeypatch)
    budget = TokenBudget(state['LEDGER'], 200_000_000, {'m': 2_000_000})
    identity = budget.reserve('m'); budget.settle(identity, None)
    before = state['finance']()
    # Only these three explicit SQL column identifiers are parameterized.
    with budget.connect() as db:
        db.execute('UPDATE attempts SET ' + field + '=? WHERE id=?',
            ('Synthetic external metadata change', identity))
    changed = attempt_rows(budget)
    with pytest.raises(RequestBudgetExceeded, match='HOST_BASELINE_CHANGED'):
        state['budget_scope_cost'](before, state['finance']())
    assert attempt_rows(budget) == changed
    assert budget.snapshot()['recorded_tokens'] == 0
    assert budget.snapshot()['reserved_or_unknown_upper_bounds'] == 2_000_000


def test_host_token_limit_is_visible_without_inventing_request_count_or_recovery_permission(tmp_path):
    from report_agent import execution_progress
    budget = TokenBudget(tmp_path / 'm1.db', 200_000_000, {'m': 2_000_000})
    def observe():
        return {'scope_id': 'm1-initial', 'maximum_tokens': 100_000_000, 'recorded_tokens': 0,
            'reserved_or_unknown_upper_bounds': 0, 'remaining_for_new_reservations': 100_000_000,
            'model_reservation_bounds': budget.model_bounds, 'includes_original_phases': True}
    with token_budget(budget), request_reservation_observer(lambda: None, observation=observe):
        observed = current_budget_observation()
        assert observed['host_run_limits'] == [{**observe(), 'status': 'observed'}]
        assert 'maximum_http_attempts' not in observed and 'remaining_http_attempts' not in observed
        episode = {'ledger': execution_progress._ledger()}
        with pytest.raises(ActionRejected, match='PROGRESS_RECOVERY_RESOURCES_OR_LEDGER_REQUIRED'):
            execution_progress._resources(episode, 1)


async def test_initial_100m_scope_refuses_before_transport_inside_shared_200m(tmp_path, monkeypatch):
    state = host_case(tmp_path, monkeypatch)
    budget = TokenBudget(state['LEDGER'], 200_000_000, {'m': 40_000_000})
    budget.settle(budget.reserve('m'), {'total_tokens': 40_000_000})
    budget.settle(budget.reserve('m'), None)
    baseline = state['finance'](); old = attempt_rows(budget)
    sends = []
    def observer():
        used, held, unknown = state['budget_scope_cost'](baseline, state['finance']())
        enforce_host_admission(used_plus_held=used + held, limit=100_000_000, unknown=False, failed=False)
    def respond(request):
        sends.append(request)
        return httpx.Response(200, json={'usage': {}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond),
            event_hooks={'request': [account_request], 'response': [account_response]}) as client:
        with token_budget(budget), request_reservation_observer(observer):
            for _ in range(2):
                await client.post('https://offline.invalid/chat', json={'model': 'm'})
            with pytest.raises(RequestBudgetExceeded, match='HOST_TOKEN_BUDGET_REACHED'):
                await client.post('https://offline.invalid/chat', json={'model': 'm'})
    assert len(sends) == 2
    assert state['budget_scope_cost'](baseline, state['finance']()) == (0, 80_000_000, True)
    assert budget.snapshot()['attempt_states']['known_not_sent'] == 1
    current = {row[0]: row for row in attempt_rows(budget)}
    assert all(current[row[0]] == row for row in old)


def authorize_existing_ledger(state, args, tmp_path):
    host = runpy.run_path(str(ROOT / 'scripts/report_host.py'), run_name='m1_budget_contract')
    bounds = host['MODEL_BOUNDS']
    budget = TokenBudget(args.ledger, 200_000_000, bounds)
    budget.settle(budget.reserve('glm-5.3'), {'total_tokens': 17})
    budget.settle(budget.reserve('glm-5.3'), None)
    args.reuse_ledger = True
    args.budget_authority = tmp_path / 'm1-authority.json'
    put_json(args.budget_authority, {'ledger': str(args.ledger.resolve()), 'maximum_tokens': 200_000_000,
        'model_bounds': bounds, 'authorization_id': 'm1-offline-fixture-only',
        'user_authority': 'Synthetic fixture tests aggregate M1 accounting; not a real spend grant.'})
    return budget


def test_explicit_m1_reuse_pins_identity_and_baseline_and_prepare_preserves_all_old_rows(tmp_path, monkeypatch):
    state, args = stage_fixture(tmp_path, monkeypatch, extras=2)
    budget = authorize_existing_ledger(state, args, tmp_path)
    original = attempt_rows(budget)
    state['stage'](args)
    deployment = json.loads((args.run / 'deployment.json').read_text())
    assert deployment['budget_authority'] == str(args.budget_authority.resolve())
    assert deployment['budget_authority_sha256'] == state['hashlib'].sha256(args.budget_authority.read_bytes()).hexdigest()
    host = runpy.run_path(str(args.run / 'host.py'), run_name='m1_reused_prepare')
    context = host['prepare'].__globals__
    monkeypatch.setitem(context, 'endpoint_pins', lambda: {'coordinator': 'offline-endpoint-pin'})
    monkeypatch.setitem(context, 'CANONICAL', tmp_path / 'unrelated-missing.db')
    staged = json.loads((args.run / 'stage-receipt.json').read_text())
    assert staged['ledger_baseline'] == context['finance']()
    context['prepare']()
    prepared = json.loads((args.run / 'prepared.json').read_text())
    assert prepared['ledger_baseline'] == staged['ledger_baseline'] == context['finance']()
    assert budget.snapshot()['maximum_tokens'] == 200_000_000
    assert attempt_rows(budget) == original


@pytest.mark.parametrize('fault', ['no-explicit-reuse', 'missing-authority', 'foreign-ledger', 'blank-id'])
def test_shared_ledger_is_not_reused_by_amount_alone(tmp_path, monkeypatch, fault):
    state, args = stage_fixture(tmp_path, monkeypatch, extras=2)
    budget = authorize_existing_ledger(state, args, tmp_path)
    original = attempt_rows(budget)
    if fault == 'no-explicit-reuse':
        args.reuse_ledger = False
    elif fault == 'missing-authority':
        args.budget_authority = None
    else:
        authority = json.loads(args.budget_authority.read_text())
        authority['ledger' if fault == 'foreign-ledger' else 'authorization_id'] = (
            str(tmp_path / 'other.db') if fault == 'foreign-ledger' else '')
        put_json(args.budget_authority, authority)
    with pytest.raises((ValueError, RuntimeError)):
        state['stage'](args)
    assert attempt_rows(budget) == original


@pytest.mark.parametrize('fault', ['authority-bytes', 'ledger-after-stage'])
def test_prepare_revalidates_reuse_authority_and_exact_staged_ledger(tmp_path, monkeypatch, fault):
    state, args = stage_fixture(tmp_path, monkeypatch, extras=2)
    budget = authorize_existing_ledger(state, args, tmp_path)
    state['stage'](args)
    if fault == 'authority-bytes':
        args.budget_authority.write_text(args.budget_authority.read_text() + '\n')
    else:
        budget.reserve('glm-5.3')
    original = attempt_rows(budget)
    host = runpy.run_path(str(args.run / 'host.py'), run_name='m1_refuse_drift')
    context = host['prepare'].__globals__
    monkeypatch.setitem(context, 'endpoint_pins', lambda: {'coordinator': 'offline-endpoint-pin'})
    monkeypatch.setitem(context, 'CANONICAL', tmp_path / 'unrelated-missing.db')
    with pytest.raises((ValueError, RuntimeError)):
        context['prepare']()
    assert attempt_rows(budget) == original
    assert not (args.run / 'case').exists() and not (args.run / 'prepared.json').exists()


def test_prepare_refuses_missing_imported_blob_before_publishing_receipt(tmp_path, monkeypatch):
    from report_agent.catalog import Catalog
    state = host_case(tmp_path, monkeypatch)
    original = Catalog.import_file

    def lose_original(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        (self.store.root / result['source']['original_blob']['path']).unlink()
        return result

    monkeypatch.setattr(Catalog, 'import_file', lose_original)
    with pytest.raises((ActionRejected, RuntimeError, ValueError), match='(?i)(blob|integrity)'):
        state['prepare']()
    assert not (state['HERE'] / 'prepared.json').exists()
    assert not (state['CASE'] / 'checkpoints.db').exists()


def test_prepare_refuses_uncheckpointed_state_before_publishing_receipt(tmp_path, monkeypatch):
    import sqlite3
    from report_agent.content_store import ContentStore
    state = host_case(tmp_path, monkeypatch)
    original = ContentStore.list_objects
    writers = []

    def keep_committed_wal(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        writer = sqlite3.connect(self.store.path)
        writers.append(writer)
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO state VALUES ('post-prepare-drift', 'true')")
        writer.commit()
        return result

    monkeypatch.setattr(ContentStore, 'list_objects', keep_committed_wal)
    try:
        with pytest.raises((ActionRejected, RuntimeError, ValueError), match='(?i)(wal|fresh|integrity)'):
            state['prepare']()
        assert not (state['HERE'] / 'prepared.json').exists()
        assert (state['CASE'] / 'state.db-wal').stat().st_size > 0
    finally:
        for writer in writers:
            writer.close()
