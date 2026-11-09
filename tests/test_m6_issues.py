"""M6 preserves issue content, history and transaction boundaries."""
import json

import pytest

from report_agent import issue_state
from report_agent.store import Store


def test_issue_versions_preserve_history_and_identical_redo(tmp_path):
    store = Store(tmp_path)
    original = [dict(id='one', category='requirement', description='Confirm scope', resolved=False)]
    issue_state.set_report_issues(store, original)
    issue_state.set_report_issues(store, original)
    issue_state.set_report_issues(store, [{**original[0], 'resolved': True, 'decision': 'Approved'}])
    assert issue_state.get_report_issues(store)[0]['resolved']
    with store.connect() as db:
        rows = db.execute("SELECT version,data FROM content_versions WHERE type='IssueWaits' ORDER BY version").fetchall()
        assert [(v, json.loads(raw)['payload']) for v, raw in rows] == [(1, original), (2, issue_state.get_report_issues(db))]
        assert db.execute("SELECT count(*) FROM state WHERE key='report_issues'").fetchone()[0] == 0


@pytest.mark.parametrize('kind', ['record', 'binding', 'route'])
def test_issue_content_versions_rollback_and_historical_read(tmp_path, kind):
    store = Store(tmp_path)
    key = 'g6_issue_' + kind + ':old'
    store.set(key, {'original': True})
    read = getattr(issue_state, 'get_g6_issue_' + kind)
    write = getattr(issue_state, 'set_g6_issue_' + kind)
    assert read(store, 'old') == {'original': True}
    write(store, 'old', {'new': True})
    assert read(store, 'old') == {'new': True}
    with pytest.raises(RuntimeError), store.connect() as db:
        write(db, 'old', {'rolled_back': True})
        raise RuntimeError('interrupted')
    assert read(store, 'old') == {'new': True}
    assert store.get(key) == {'original': True}


def test_historical_issue_read_does_not_create_native_tables(tmp_path):
    store = Store(tmp_path)
    store.set('report_issues', [{'id': 'old', 'resolved': False}])
    assert issue_state.get_report_issues(store)[0]['id'] == 'old'
    with store.connect() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='content_versions'").fetchone()


def test_human_reply_is_authoritative_before_projection_and_can_be_revised(tmp_path):
    from report_agent.issue_authority import record_answer
    from report_agent.assertions.launch import Commission
    store = Store(tmp_path)
    issue = dict(id='question', description='Which scope?', category='requirement', resolved=False)
    issue_state.set_report_issues(store, [issue])
    first = record_answer(store, issue, 'A only', True)
    assert record_answer(store, issue, 'A only', True) == first
    assert issue_state.get_report_issues(store)[0]['decision'] == 'A only'
    record_answer(store, issue, 'Reopen for B', False)
    assert not issue_state.get_report_issues(store)[0]['resolved']
    assert issue_state.get_report_issues(store)[0]['decision'] == 'Reopen for B'
    assert len(Commission.issue_actions(store.root)) == 4


def test_crash_before_owner_assertion_leaves_wait_open_and_redo_finishes(tmp_path, monkeypatch):
    from report_agent import issue_authority
    store = Store(tmp_path)
    issue = dict(id='question', description='Confirm?', category='requirement', resolved=False)
    issue_state.set_report_issues(store, [issue])
    decide = issue_authority.assertions.decide
    def fail(*args, **kwargs):
        raise RuntimeError('lost before owner act')
    monkeypatch.setattr(issue_authority.assertions, 'decide', fail)
    with pytest.raises(RuntimeError):
        issue_authority.record_answer(store, issue, 'Yes', True)
    assert not issue_state.get_report_issues(store)[0]['resolved']
    monkeypatch.setattr(issue_authority.assertions, 'decide', decide)
    issue_authority.record_answer(store, issue, 'Yes', True)
    assert issue_state.get_report_issues(store)[0]['resolved']


@pytest.mark.parametrize('family', ['report_issues', 'g6_issue_record', 'g6_issue_binding', 'g6_issue_route'])
def test_migrated_family_has_no_legacy_write_accessor(family):
    from report_agent import legacy_state
    assert not hasattr(legacy_state, 'set_' + family)


def test_native_issue_record_wins_iteration_without_changing_history(tmp_path):
    store = Store(tmp_path)
    store.set('g6_issue_record:one', {'issue': {'id': 'old'}})
    issue_state.set_g6_issue_record(store, 'one', {'issue': {'id': 'new'}})
    issue_state.set_g6_issue_record(store, 'two', {'issue': {'id': 'second'}})
    with store.connect() as db:
        rows = issue_state.iter_g6_issue_record(db)
    assert [json.loads(raw)['issue']['id'] for _, raw in rows] == ['new', 'second']
    assert store.get('g6_issue_record:one')['issue']['id'] == 'old'


def test_report_uncertainty_never_creates_runtime_waits(tmp_path):
    from report_agent.issue_authority import record_answer
    store = Store(tmp_path)
    issue = dict(id='question', description='Confirm?', category='requirement', resolved=False)
    issue_state.set_report_issues(store, [issue])
    record_answer(store, issue, 'Yes', True)
    view = issue_state.issue_view(store)
    wait = next(x for x in view if x['kind'] == 'human_wait')
    question = next(x for x in view if x['kind'] == 'question')
    assert not question['state']['open']
    assert wait['record']['resolved']


def test_workspace_redo_finishes_projection_after_owner_act(tmp_path, monkeypatch):
    from report_agent.workspace import Workspace
    from report_agent.assertions.launch import Commission
    ws = Workspace(Store(tmp_path))
    issue = dict(id='question', description='Confirm?', category='requirement', resolved=False)
    issue_state.set_report_issues(ws.store, [issue])
    ws.store.set('report_status', 'waiting_for_human')
    project = ws._issue_change
    def fail(*args, **kwargs):
        raise RuntimeError('lost after owner act')
    monkeypatch.setattr(ws, '_issue_change', fail)
    with pytest.raises(RuntimeError):
        ws.decide_issue('question', 'Yes', True)
    assert ws.store.get('report_status') == 'waiting_for_human'
    monkeypatch.setattr(ws, '_issue_change', project)
    ws.decide_issue('question', 'Yes', True)
    assert ws.store.get('report_status') == 'ready'
    assert ws.store.get('context_revision') == 1
    events = ws.store.events()
    ws.decide_issue('question', 'Yes', True)
    assert ws.store.events() == events and ws.store.get('context_revision') == 1
    assert len(Commission.issue_actions(ws.store.root)) == 2


def test_host_cli_exposes_issue_view_and_locations(tmp_path, monkeypatch, capsys):
    from report_agent.cli import main
    store = Store(tmp_path)
    issue_state.set_report_issues(store, [dict(id='pending', description='Confirm?', resolved=False)])
    issue_state.set_g6_issue_record(store, 'one', {'issue': {'id': 'material', 'kind': 'missing'},
        'binding': {'section_id': '4', 'object_id': 'A'}})
    monkeypatch.setattr('sys.argv', ['report-agent', 'issues', '--project', str(tmp_path)])
    main()
    rows = json.loads(capsys.readouterr().out)['issues']
    assert {row['id'] for row in rows} == {'pending', 'material'}
    assert next(row for row in rows if row['id'] == 'material')['report_locations'] == [
        {'section_id': '4', 'object_id': 'A'}]
