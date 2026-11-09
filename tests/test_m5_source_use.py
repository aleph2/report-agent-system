from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

from report_agent import assertions, plan_authority
from report_agent.assertion_host import AssertionHost, Grant
from report_agent.content_store import Actor, ContentStore
from report_agent.deliverables import source_authority
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.source_use import configure_source_use, report_binding, validate_source_versions
from report_agent.store import Store, encode


def approve(cs, co, owner, policy, call, *, scope=False):
    with cs.store.connect() as db:
        previous = plan_authority.plan_ref(db)
        args = {'id': previous['id'], 'version': previous['version'] + 1, 'previous_ref': previous} if previous else {}
        from report_agent import commission_imports
        pins = [policy] if policy else []
        if scope:
            pins.extend(r for r in commission_imports.frozen_refs(db) if r['type'] == 'CommissionSourceManifest')
        plan = cs._insert(db, co, 'CommissionPlan', {}, plan_input_refs=pins, **args)
        decision = cs._insert(db, owner, 'CommissionDecision', {'plan_ref': plan, 'approved': True})
    plan_authority.propose(cs.store, co, 'propose' + call, plan)
    return plan, plan_authority.decide(cs.store, owner, 'approve' + call, plan, decision, True)


def test_supplied_files_for_planning_and_exact_approved_policy_for_report(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal': 'Report', 'sources': [
        {'id': name, 'title': name, 'content': name, 'coverage': 'complete'} for name in ('supplied', 'other')]})
    policy = configure_source_use(store, ['supplied'], 'Supplied for this commission')
    workspace = SimpleNamespace(store=store)
    co, owner = actor_for('coordinator'), Actor('operator', 'operator', 'owner')
    cs = ContentStore(store)
    assert validate_source_versions(workspace, co, ['supplied']) == policy
    with pytest.raises(ActionRejected, match='NOT_AUTHORIZED'):
        validate_source_versions(workspace, co, ['other'])
    with pytest.raises(ActionRejected, match='SOURCE_USE_OWNER_APPROVAL_REQUIRED'):
        report_binding(store)
    store.set('source_use_authority_binding', 'unrelated-old-grant')
    approve(cs, co, owner, None, '-wrong')
    with pytest.raises(ActionRejected, match='SOURCE_USE_OWNER_APPROVAL_REQUIRED'):
        report_binding(store)
    plan, approval = approve(cs, co, owner, policy, '-right')
    assert report_binding(store) == policy
    with store.connect() as db:
        assert source_authority(cs, db, co, []) == policy
    host = AssertionHost(store.root)
    grant = Grant(str(uuid5(NAMESPACE_URL, 'operator')), 'owner', 'withdraw', 'direct', encode(plan),
                  frozenset([plan['id']]), frozenset([approval['id']]), frozenset(['retract']))
    assertions.retract(host.issue_once(grant, 'retract', 'withdraw'), subject=plan['id'],
                       claim=dict(kind='act', effect='retract', target=approval['id'], reason='Withdraw approval'))
    with pytest.raises(ActionRejected):
        report_binding(store)
    with store.connect() as db, pytest.raises(ActionRejected):
        source_authority(cs, db, co, [])


def test_unfinished_declared_intake_cannot_widen_planning_or_frozen_scope(tmp_path, monkeypatch):
    from report_agent import source_use
    store = Store(tmp_path)
    manifest = {'goal': 'Scoped', 'commission_checkpoint_required': True,
                'sources': [{'id': name, 'title': name, 'content': name, 'coverage': 'complete'}
                            for name in ('selected', 'excluded')],
                'source_use': {'source_ids': ['selected'], 'authorization_origin': 'Specific supplied file'}}
    with monkeypatch.context() as patch:
        def interrupted(*args, **kwargs):
            raise RuntimeError('interrupted after manifest commit')

        patch.setattr(source_use, 'configure_source_use', interrupted)
        with pytest.raises(RuntimeError):
            store.initialize(manifest)
    workspace = SimpleNamespace(store=store)
    with pytest.raises(ActionRejected, match='NOT_AUTHORIZED'):
        validate_source_versions(workspace, actor_for('coordinator'), ['excluded'])
    result = source_use.freeze_supplied_sources(store)
    assert ContentStore(store).read(result)['payload']['declaration'] == manifest['source_use']


def test_implicit_planning_includes_enrolled_role_but_excludes_other_catalog_files(tmp_path):
    from report_agent import commission_imports, source_use
    from report_agent.catalog import Catalog
    store = Store(tmp_path)
    store.initialize({'goal': 'Report', 'commission_checkpoint_required': True,
                      'sources': [{'id': 'brief', 'title': 'Brief', 'content': 'Review', 'coverage': 'complete'}]})
    catalog = Catalog(store)
    included = catalog.import_file('design.txt', b'Provided design')['source']['id']
    excluded = catalog.import_file('other.txt', b'Other source')['source']['id']
    workspace = SimpleNamespace(store=store)
    co = actor_for('coordinator')
    with pytest.raises(ActionRejected, match='NOT_AUTHORIZED'):
        validate_source_versions(workspace, co, [included])
    commission_imports.install_source_roles(store, {'design.txt': {'id': included, 'purpose': 'design'}})
    validate_source_versions(workspace, co, ['brief', included])
    with pytest.raises(ActionRejected, match='NOT_AUTHORIZED'):
        validate_source_versions(workspace, co, [excluded])
    with pytest.raises(ActionRejected):
        report_binding(store)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        source_use.freeze_supplied_sources(store, db=db)
        db.rollback()
    assert commission_imports.source_policy_ref(store) is None
    ref = source_use.freeze_supplied_sources(store)
    assert set(ContentStore(store).read(ref)['payload']['declaration']['source_ids']) == {'brief', included}


def test_later_owner_approval_must_include_both_scope_and_source_policy(tmp_path):
    from report_agent import source_use
    store = Store(tmp_path)
    store.initialize({'goal': 'Report', 'scope_instruction': 'Supplied slope only', 'commission_checkpoint_required': True,
                      'sources': [{'id': 'design', 'title': 'Design', 'content': 'Input', 'coverage': 'complete'}]})
    ref = source_use.freeze_supplied_sources(store)
    cs, co = ContentStore(store), actor_for('coordinator')
    owner = Actor('operator', 'operator', 'owner')
    approve(cs, co, owner, ref, 'without-scope')
    with pytest.raises(ActionRejected, match='SOURCE_USE_OWNER_APPROVAL_REQUIRED'):
        report_binding(store)
    approve(cs, co, owner, ref, 'with-scope', scope=True)
    assert report_binding(store) == ref


def test_word_and_excel_enforce_source_selection_at_normal_export_entries(tmp_path):
    import json
    from report_agent.content_export import export_snapshot
    from report_agent.content_workbook import export_workbook
    store = Store(tmp_path)
    store.initialize({'goal': 'Commission', 'commission_checkpoint_required': True,
                      'sources': [{'id': n, 'title': n, 'content': n, 'coverage': 'complete'} for n in ('yes', 'no')],
                      'source_use': {'source_ids': ['yes'], 'authorization_origin': 'Only supplied yes'}})
    from report_agent import commission_imports
    cs, co, owner = ContentStore(store), actor_for('coordinator'), Actor('operator', 'operator', 'owner')
    plan, approval = approve(cs, co, owner, commission_imports.source_policy_ref(store), 'approved', scope=True)
    source = cs.capture_sources(co, 'capture', ['no'])['result']['source_refs'][0]
    with store.connect() as db:
        snapshot = cs._insert(db, co, 'DocumentSnapshot', {
            'refs': [source], 'commission_plan_ref': plan, 'commission_confirmation_ref': json.loads(approval['claim']['reason'])})
    for invoke, args in [(export_snapshot, ()), (export_workbook, ([],))]:
        with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
            invoke(cs, co, 'export', snapshot, *args)
    assert not cs.list_objects('ExportArtifact')
