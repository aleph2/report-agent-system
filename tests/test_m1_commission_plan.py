"""Commission authority is persisted and version-bound, not inferred from agent prose."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from support.plan_fixture import approve, save
from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.store import Store
from report_agent.workspace import Workspace


def api():
    from report_agent import commission_plan
    return commission_plan


@pytest.fixture
def commission(tmp_path):
    texts = {
        'scope': 'Assess S1 S2 S3 S4 S5. Design takes priority; survey fills gaps; list conflicts.',
        'outline': 'Fixed: 1.1 1.2 1.4 3.1 3.2 6. Extracted: 1.3 2 4. Derived: 5 from 4.',
        'design': 'S1 S2 S3 S4 S5 are design objects. S1 height is unknown. S2 height is 30 m.',
        'survey': 'Survey includes S1 S2 S3 S4. S2 height is 28 m.',
        'layout': 'The general layout shows S1 S2 S3 S4 S5.',
        'template': 'Fixed method and conclusion wording; replace project name and counts.'}
    store = Store(tmp_path)
    store.initialize({'goal': texts['scope'], 'content_contract': 'hierarchical-review-v1',
        'commission_checkpoint_required': True, 'coverage_contract': 'object-coverage-v1',
        'sources': [{'id': key, 'title': key, 'content': value, 'coverage': 'complete'}
                    for key, value in texts.items()]})
    ws, co = Workspace(store), actor_for('coordinator')
    cs = ContentStore(store)
    imported = cs.import_inputs(co, 'commission-inputs', list(texts))['result']
    sources = {cs.read(ref)['payload']['source_id']: ref for ref in imported['source_refs']}

    def cite(source, quote=None):
        return {'source_ref': sources[source], 'locator': 'manifest text', 'quote': quote or texts[source]}

    sections = []
    for section_id in ['1.1', '1.2', '1.4', '3.1', '3.2', '6', '1.3', '2', '4', '5']:
        kind = 'derived' if section_id == '5' else 'extracted' if section_id in {'1.3', '2', '4'} else 'fixed'
        sections.append({'section_id': section_id, 'title': 'Section ' + section_id, 'kind': kind,
            'outline': cite('outline'), 'sources': [cite('template' if kind == 'fixed' else 'design')],
            'pending_sources': [],
            'text': texts['template'] if kind == 'fixed' else '',
            'substitutions': ['project name', 'counts'] if kind == 'fixed' else [],
            'derived_from': ['4'] if kind == 'derived' else [],
            'rule': 'Insert chapter 4 outcomes into the template summary.' if kind == 'derived' else '',
            'examples': []})
    objects = [{'object_id': 'S' + str(i), 'label': 'Slope ' + str(i), 'included': True,
        'reason': 'Named in the design and commissioned list.', 'origin': 'customer',
        'attributes': [{'name': 'height', 'values': [
            {'value': None if i == 1 else '30 m', 'source': None if i == 1 else cite('design'),
             'reason': 'Missing height remains unknown.' if i == 1 else 'Design value.'}]}],
        'sources': [cite('design'), cite('scope')]} for i in range(1, 6)]
    objects[1]['attributes'][0]['values'].append({'value': '28 m', 'source': cite('survey'),
                                                'reason': 'Conflicting survey value retained.'})
    plan = {'sections': sections, 'objects': objects, 'inventory_attributes': ['height'],
        'conventions': [{'source': cite('scope', 'Design takes priority; survey fills gaps; list conflicts.'),
                         'interpretation': 'Use design inventory even where survey omits an object.'}],
        'deliverables': ['Word', 'Excel clarification list'],
        'reconciliations': [{'sources': [cite('design'), cite('layout'), cite('survey')],
            'result': 'Five design/layout objects retained.', 'differences': ['Survey omits S5; S2 height differs.']}],
        'open_questions': ['Confirm the five objects and section plan.']}
    return SimpleNamespace(ws=ws, cs=cs, co=co, plan=plan, sources=sources, cite=cite)


def writer(fixture, saved, *, section_ids=None, operation='writer-task', assessment_object_id=None):
    from report_agent.content_tasks import delegated_task
    args = {'subagent_type': 'writer', 'section_ids': section_ids or ['4'], 'description': 'Write the agreed sections.'}
    if assessment_object_id is not None:
        args['assessment_object_id'] = assessment_object_id
    with delegated_task(fixture.ws, 'coordinator', {'id': operation, 'name': 'task', 'args': args}) as (_, actor):
        task = fixture.cs.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
        assert task['payload']['commission_plan_ref'] == saved['plan_ref']
        return actor


def unapproved_writer(fixture, saved, *, section_ids=None, operation='writer-task'):
    def register(db):
        return fixture.cs._insert(db, fixture.co, 'DelegatedTask', {
            'role': 'writer', 'goal': 'Write the agreed sections.',
            'write_scope': 'Only this task artifacts.', 'delegated_by': fixture.co.id,
            'commission_plan_ref': saved['plan_ref'], 'section_ids': section_ids or ['4']})
    ref = fixture.cs.operation(fixture.co, operation, {'synthetic-task': operation}, register)['result']
    return Actor('content:writer:' + ref['id'], 'writer', ref['id'])


def test_plan_preserves_exact_conventions_unknowns_conflicts_and_section_mapping(commission):
    saved = save(commission)
    record = api().read_plan(commission.ws.store)
    assert record['ref'] == saved['plan_ref']
    payload = record['payload']
    for field in ('sections', 'objects', 'inventory_attributes', 'conventions', 'reconciliations', 'deliverables'):
        assert payload[field] == commission.plan[field]
    assert len(saved['inventory_refs']) == 5
    assert all(ref['type'] == 'Requirement' for ref in saved['inventory_refs'])
    count = len(commission.cs.list_objects())
    assert save(commission) == saved
    assert len(commission.cs.list_objects()) == count


def test_commission_plan_requires_explicit_inventory_attribute_contract(commission):
    plan = deepcopy(commission.plan)
    plan.pop('inventory_attributes')
    with pytest.raises((ActionRejected, ValueError), match='(?i)(inventory_attributes|attribute)'):
        save(commission, plan, operation='undeclared-inventory-attributes')


@pytest.mark.parametrize('fault', ['empty-contract', 'duplicate-contract', 'missing-attribute',
    'duplicate-attribute', 'unexpected-attribute'])
def test_every_object_preserves_each_declared_inventory_attribute_once(commission, fault):
    # A valid explicit unknown must be accepted before checking a malformed proposal.
    save(commission, operation='valid-attribute-contract')
    plan = deepcopy(commission.plan)
    if fault == 'empty-contract':
        plan['inventory_attributes'] = []
    elif fault == 'duplicate-contract':
        plan['inventory_attributes'].append('height')
    elif fault == 'missing-attribute':
        plan['inventory_attributes'].append('slope_type')
    elif fault == 'duplicate-attribute':
        plan['objects'][0]['attributes'].append(deepcopy(plan['objects'][0]['attributes'][0]))
    else:
        extra = deepcopy(plan['objects'][0]['attributes'][0])
        extra['name'] = 'undeclared-slope-type'
        plan['objects'][0]['attributes'].append(extra)
    with pytest.raises((ActionRejected, ValueError), match='(?i)(attribute|inventory)'):
        save(commission, plan, operation='invalid-attribute-contract')


@pytest.mark.parametrize('fault', ['invented-quote', 'known-without-source', 'duplicate-object',
    'derived-without-rule', 'drop-object-revision'])
def test_invalid_plan_or_silent_object_removal_is_refused(commission, fault):
    plan = deepcopy(commission.plan)
    if fault == 'invented-quote':
        plan['conventions'][0]['source']['quote'] = 'Customer said the survey overrides design.'
    elif fault == 'known-without-source':
        plan['objects'][1]['attributes'][0]['values'][0]['source'] = None
    elif fault == 'duplicate-object':
        plan['objects'].append(deepcopy(plan['objects'][0]))
    elif fault == 'derived-without-rule':
        plan['sections'][-1]['rule'] = ''
    else:
        save(commission)
        plan['objects'].pop()
    with pytest.raises((ActionRejected, ActionForbidden, ValueError)):
        save(commission, plan, operation='invalid-plan')


def test_checkpoint_brief_and_exact_reply_are_idempotent(commission,monkeypatch):
    import json, hashlib
    from report_agent import plan_authority
    saved = save(commission)
    checkpoint = api().request_checkpoint(commission.ws)
    decision = dict(plan_ref=saved['plan_ref'], approved=True, corrections='', reductions=[])
    authority = commission.ws.store.root.parent / 'confirmation-authority.json'
    authority.write_text(json.dumps({'workflow': 'fake03-coordinator-page-sheet-probe-v1', 'case_path': str(commission.ws.store.root),
        'confirmers': {'delegate': {'name': 'Fixture delegate', 'acting_for': 'Fixture owner'}}}))
    pin = hashlib.sha256(authority.read_bytes()).hexdigest()
    decision['confirmer'] = dict(id='delegate', name='Fixture delegate', acting_for='Fixture owner', authority_sha256=pin)
    for change, args, code in [
        ({}, {}, 'COMMISSION_CONFIRMER_PIN_REQUIRED'),
        ({}, dict(authority_path=authority, authority_sha256='0'*64), 'COMMISSION_CONFIRMER_AUTHORITY_CHANGED'),
        ({'id': 'unknown'}, dict(authority_path=authority, authority_sha256=pin), 'COMMISSION_CONFIRMER_NOT_AUTHORIZED'),
        ({'acting_for': 'Someone else'}, dict(authority_path=authority, authority_sha256=pin), 'COMMISSION_CONFIRMER_IDENTITY_MISMATCH')]:
        with pytest.raises(ActionRejected, match=code):
            api().reply(commission.ws, checkpoint['issue_id'], {**decision, 'confirmer': {**decision['confirmer'], **change}}, **args)
        assert not commission.cs.list_objects('CommissionDecision')
    from report_agent import cli
    decision_file=authority.with_name('native-owner-decision.json')
    decision_file.write_text(json.dumps(decision))
    monkeypatch.setattr('sys.argv',['report-agent','commission-reply','--project',str(commission.ws.store.root),
        '--issue-id',checkpoint['issue_id'],'--file',str(decision_file),'--authority',str(authority),'--authority-sha256',pin])
    def file_state():
        import sqlite3
        from contextlib import closing
        rows = {}
        for p in commission.ws.store.root.iterdir():
            if p.suffix not in ('.db', '.sqlite3'):
                continue
            with closing(sqlite3.connect(p.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                    quoted = '"' + table.replace('"', '""') + '"'
                    rows[(p.name, table)] = sorted(db.execute('SELECT * FROM ' + quoted).fetchall(), key=repr)
        files = {str(p.relative_to(commission.ws.store.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in commission.ws.store.root.rglob('*') if p.is_file()
                 and p.suffix not in ('.db', '.sqlite3') and not p.name.endswith(('-wal', '-shm'))}
        return rows, files, commission.cs.list_objects()
    before = file_state()
    for changed in ({'reductions':[{'object_id':'unknown','reason':'Invalid object'}]},
                    {'unconfirmed_page_bindings':['not-in-sheet']}):
        with pytest.raises(ActionRejected):
            api().check_reply(commission.ws.store.root, checkpoint['issue_id'], {**decision, **changed},
                authority_path=authority, authority_sha256=pin)
        assert file_state() == before
    monkeypatch.setattr('sys.argv', [*__import__('sys').argv, '--check-only'])
    assert cli.main() == 0
    assert file_state() == before
    assert not commission.cs.list_objects('CommissionDecision')
    missing = commission.ws.store.root / 'nonexistent-case'
    with pytest.raises(ActionRejected, match='EXISTING_COMMISSION_CASE_REQUIRED'):
        api().check_reply(missing, checkpoint['issue_id'], decision,
            authority_path=authority, authority_sha256=pin)
    assert not missing.exists()
    monkeypatch.setattr('sys.argv', __import__('sys').argv[:-1])
    assert cli.main()==0
    record = commission.cs.read(plan_authority.decision_ref(commission.ws.store))
    assert record['payload']['confirmer'] == decision['confirmer'] and record['owner_id'] == 'operator'

    from report_agent.run_authority import _verify_checkpoint_reply
    from report_agent.issue_state import get_report_issues
    issue=next(i for i in get_report_issues(commission.ws.store,[]) if i['id']==checkpoint['issue_id'])
    assert _verify_checkpoint_reply(commission.ws,checkpoint['issue_id'],issue,authority,pin)==record['ref']
    unattributed={k:v for k,v in decision.items() if k!='confirmer'}
    with pytest.raises(ActionRejected,match='COMMISSION_CONFIRMER_NOT_AUTHORIZED'):
        _verify_checkpoint_reply(commission.ws,checkpoint['issue_id'],{**issue,'decision':json.dumps(unattributed)},authority,pin)

    path = Path(checkpoint['brief_path'])
    path = path if path.is_absolute() else commission.ws.store.root / path
    brief = path.read_text(encoding='utf-8')
    assert all(obj['label'] in brief for obj in commission.plan['objects'])
    assert all(section['section_id'] in brief for section in commission.plan['sections'])
    assert 'Word' in brief and 'Excel' in brief and 'Design takes priority' in brief
    assert 'Survey omits S5; S2 height differs.' in brief
    assert 'Missing height remains unknown.' in brief
    assert '30 m' in brief and '28 m' in brief
    assert api().request_checkpoint(commission.ws)['issue_id'] == checkpoint['issue_id']
    before = file_state()
    assert api().check_reply(commission.ws.store.root, checkpoint['issue_id'], decision,
        authority_path=authority, authority_sha256=pin)['status'] == 'approval_checks_passed'
    assert file_state() == before
    api().reply(commission.ws, checkpoint['issue_id'], decision, authority_path=authority, authority_sha256=pin)
    assert len(commission.cs.list_objects('CommissionDecision')) == 1
    from report_agent import fake_full_flow as entry
    monkeypatch.setattr(entry, 'preflight', lambda path,sha: json.loads(authority.read_text()))
    entry.confirm(authority,pin,checkpoint['issue_id'],decision,'delegate')
    with pytest.raises(ValueError):
        entry.confirm(authority,pin,checkpoint['issue_id'],{'decision':'resume_delivery'},'delegate')
    assert len(commission.cs.list_objects('CommissionDecision')) == 1
    actor = writer(commission, saved)
    with commission.cs.store.connect() as db:
        assert api().assert_writing_allowed(commission.cs, db, actor)


@pytest.mark.parametrize('state', ['unanswered', 'corrections', 'stale-plan', 'stale-task'])
def test_writing_requires_current_plan_and_operator_confirmation(commission, state):
    saved = save(commission)
    checkpoint = api().request_checkpoint(commission.ws)
    actor = unapproved_writer(commission, saved)
    if state == 'corrections':
        api().reply(commission.ws, checkpoint['issue_id'], {'plan_ref': saved['plan_ref'],
            'approved': False, 'corrections': 'Correct the section source.', 'reductions': []})
    elif state in {'stale-plan', 'stale-task'}:
        approve(commission, saved)
        revised = deepcopy(commission.plan)
        revised['open_questions'] = ['Confirm corrected source interpretation.']
        current = save(commission, revised, operation='revised-plan')
        if state == 'stale-task':
            approve(commission, current)
    with commission.cs.store.connect() as db, pytest.raises((ActionRejected, ActionForbidden), match='(?i)(commission|checkpoint|plan|task)'):
        api().assert_writing_allowed(commission.cs, db, actor)


def test_reply_cannot_approve_different_plan_or_unrelated_issue(commission):
    saved = save(commission)
    checkpoint = api().request_checkpoint(commission.ws)
    bad = {**saved['plan_ref'], 'version': saved['plan_ref']['version'] + 1}
    with pytest.raises((ActionRejected, ActionForbidden, ValueError)):
        api().reply(commission.ws, checkpoint['issue_id'], {'plan_ref': bad, 'approved': True,
            'corrections': '', 'reductions': []})
    other = commission.ws.issue('requirement', 'Unrelated question', [])
    with pytest.raises((ActionRejected, ActionForbidden, ValueError)):
        api().reply(commission.ws, other['id'], {'plan_ref': saved['plan_ref'], 'approved': True,
            'corrections': '', 'reductions': []})


async def test_precheckpoint_text_work_refuses_before_helper_invocation(commission):
    from report_agent import text_work
    from test_bounded_review import Model
    saved = save(commission)
    actor = unapproved_writer(commission, saved)
    model = Model('{}')
    with pytest.raises((ActionRejected, ActionForbidden), match='(?i)(commission|checkpoint)'):
        await text_work.produce(commission.ws, actor, model, 'premature-text', 'Write chapter 4',
                                'ContentNode', input_refs=list(commission.sources.values()))
    assert model.calls == []
    assert not commission.cs.list_objects('ContentNode')
