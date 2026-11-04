"""G5 J1: ID obligations, host owner records, and existing approval/export gates."""
from copy import deepcopy
from hashlib import sha256
from importlib import import_module

import pytest
from pydantic import ValidationError

from report_agent.errors import ActionForbidden, ActionRejected
from test_m1_commission_plan import api, save
from test_m1_g3_integration import method_commission
from test_m1_g4_requirements import anchored, required_case, requirements, saved_historical_bundle
from test_m1_g4_planning_steps import source_pins
from test_hierarchical_content import ws


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import httpx
    def denied(*args, **kwargs):
        raise AssertionError('G5_J1_NETWORK_FORBIDDEN')
    monkeypatch.setattr(httpx.Client, 'send', denied)
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)


def owner_api():
    return import_module('report_agent.commission_owner_records')


def owner(kind, target, value, identity='owner-1', reason='Explicit owner scope decision'):
    text = 'Recorded owner decision: ' + target
    return {'id': identity, 'kind': kind, 'target': target, 'value': value,
            'reason': reason, 'text': text, 'evidence_sha256': sha256(text.encode()).hexdigest()}


def section(**changes):
    value = {'pending_sources': [], 'notes': [], 'missing_documents': [], 'source_substitutions': []}
    value.update(changes)
    return value


def missing_doc():
    return {'id': 'doc-general', 'name': 'General notes', 'section_id': '4'}


def test_document_resolution_uses_id_not_requested_name():
    value = section(missing_documents=[missing_doc()],
        source_substitutions=[{'document_id': 'doc-general', 'requested_source': 'A different display label'}])
    assert api().unresolved_sources(value) == []


def test_equal_document_name_without_id_does_not_resolve_obligation():
    value = section(missing_documents=[missing_doc()],
        source_substitutions=[{'requested_source': 'General notes'}])
    assert api().unresolved_sources(value) == ['4/missing_documents/doc-general: General notes']


def test_wrong_document_id_does_not_fall_back_to_matching_name():
    value = section(missing_documents=[missing_doc()],
        source_substitutions=[{'document_id': 'another-doc', 'requested_source': 'General notes'}])
    assert api().unresolved_sources(value) == ['4/missing_documents/doc-general: General notes']


def test_notes_never_become_missing_document_obligations():
    value = section(notes=['章节标题；正文由3.1—3.2各节组成', 'Drafting note: verify page details'])
    assert api().unresolved_sources(value) == []


def test_real_missing_document_still_blocks_despite_notes():
    assert api().unresolved_sources(section(notes=['Notes are not obligations'],
        missing_documents=[missing_doc()])) == ['4/missing_documents/doc-general: General notes']


def test_historical_unregistered_plan_keeps_legacy_behavior():
    assert api().unresolved_sources({'pending_sources': ['Legacy unresolved entry'], 'source_substitutions': []}) == ['Legacy unresolved entry']


@pytest.fixture
def owner_case(required_case):
    from report_agent.source_use import configure_source_use
    f = required_case
    f.owner_source_refs = [p['ref'] for p in source_pins(f, f.plan)]
    f.enrolled_ids = sorted({f.cs.read(ref)['payload']['source_id'] for ref in f.owner_source_refs})
    f.source_binding = configure_source_use(f.cs.store, f.enrolled_ids, 'J1 offline test source enrollment')
    f.owner_bundle = {'contract': 'owner-records-v1', 'records': [],
        'documents': [{'id': 'doc-general', 'name': 'General notes', 'section_ids': ['4']}],
        'substitutions': [], 'objects': []}
    return f


def install(f):
    result = owner_api().install_owner_records(f.cs, deepcopy(f.owner_bundle), f.owner_source_refs)
    with f.cs.store.connect() as db:
        plan = owner_api().decorate_plan(f.cs, db, deepcopy(f.plan))
        owner_api().validate_owner_records(f.cs, db, plan)
    return result, plan


def substitution(f):
    target = next(s for s in f.plan['sections'] if s['section_id'] == '4')
    return {'document_id': 'doc-general', 'section_id': '4', 'requested_source': 'General notes',
        'replacement_sources': [deepcopy(target['sources'][0])],
        'customer_basis': deepcopy(f.plan['conventions'][0]['source']),
        'reason': 'Use the supplied cited sources under the owner scope decision.'}


def test_registry_install_is_immutable_idempotent_and_unapproved(owner_case):
    f = owner_case
    first, plan = install(f)
    assert owner_api().install_owner_records(f.cs, deepcopy(f.owner_bundle), f.owner_source_refs) == first
    assert plan['owner_records_digest']
    assert not f.cs.store.get('commission_confirmation')
    assert not f.cs.store.get('commission_plan')
    changed = deepcopy(f.owner_bundle)
    changed['documents'][0]['name'] = 'Unreviewed replacement label'
    with pytest.raises(ActionRejected):
        owner_api().install_owner_records(f.cs, changed, f.owner_source_refs)


def test_new_contract_converts_all_free_text_pending_entries_to_notes(owner_case):
    f = owner_case
    target = next(s for s in f.plan['sections'] if s['section_id'] == '4')
    original = ['Long legacy instruction; retain original wording.', 'Newly entered free text is still a note.']
    target['pending_sources'] = original[:]
    _, plan = install(f)
    result = next(s for s in plan['sections'] if s['section_id'] == '4')
    assert result['pending_sources'] == []
    assert set(original) <= set(result['notes'])
    assert api().unresolved_sources(result) == ['4/missing_documents/doc-general: General notes']
    assert target['pending_sources'] == original


def test_registry_attaches_document_obligations_only_to_named_sections(owner_case):
    _, plan = install(owner_case)
    sections = {s['section_id']: s for s in plan['sections']}
    assert sections['4']['missing_documents'][0]['id'] == 'doc-general'
    assert not sections['5'].get('missing_documents')


def test_reasoned_owner_withdrawal_resolves_only_recorded_document(owner_case):
    f = owner_case
    f.owner_bundle['records'] = [owner('withdrawal', 'doc-general', {'withdrawn': True}, reason='Owner withdraws this source obligation.')]
    _, plan = install(f)
    target = next(s for s in plan['sections'] if s['section_id'] == '4')
    assert target['missing_documents'][0]['withdrawn_by'] == 'owner-1'
    assert api().unresolved_sources(target) == []
    assert not f.cs.store.get('commission_confirmation')


@pytest.mark.parametrize('reason', ['', '   '])
def test_withdrawal_requires_nonblank_reason(owner_case, reason):
    f = owner_case
    f.owner_bundle['records'] = [owner('withdrawal', 'doc-general', {'withdrawn': True}, reason=reason)]
    with pytest.raises((ActionRejected, ValidationError)):
        owner_api().install_owner_records(f.cs, f.owner_bundle, f.owner_source_refs)


def test_unknown_document_withdrawal_is_rejected(owner_case):
    f = owner_case
    f.owner_bundle['records'] = [owner('withdrawal', 'unknown-document', {'withdrawn': True})]
    with pytest.raises(ActionRejected):
        owner_api().install_owner_records(f.cs, f.owner_bundle, f.owner_source_refs)


def test_owner_text_hash_mismatch_is_rejected(owner_case):
    f = owner_case
    f.owner_bundle['records'] = [owner('withdrawal', 'doc-general', {'withdrawn': True})]
    f.owner_bundle['records'][0]['evidence_sha256'] = '0' * 64
    with pytest.raises(ActionRejected):
        owner_api().install_owner_records(f.cs, f.owner_bundle, f.owner_source_refs)


def test_agent_cannot_forge_owner_record_or_withdraw_document(owner_case):
    f = owner_case
    _, plan = install(f)
    plan['owner_records'].append(owner('withdrawal', 'doc-general', {'withdrawn': True}))
    with f.cs.store.connect() as db, pytest.raises(ActionRejected):
        owner_api().validate_owner_records(f.cs, db, plan)


def test_agent_cannot_remove_registered_missing_document(owner_case):
    f = owner_case
    _, plan = install(f)
    next(s for s in plan['sections'] if s['section_id'] == '4')['missing_documents'] = []
    with f.cs.store.connect() as db, pytest.raises(ActionRejected):
        owner_api().validate_owner_records(f.cs, db, plan)


def test_unregistered_plan_cannot_invent_owner_authority(required_case):
    plan = deepcopy(required_case.plan)
    plan['owner_records'] = [owner('withdrawal', 'doc-general', {'withdrawn': True})]
    with required_case.cs.store.connect() as db, pytest.raises(ActionRejected):
        owner_api().validate_owner_records(required_case.cs, db, plan)


@pytest.mark.parametrize('key', ['commission_confirmation', 'commission_plan'])
def test_owner_registry_installation_requires_fresh_case(owner_case, key):
    f = owner_case
    f.cs.store.set(key, {'type': 'CommissionPlan', 'id': 'existing', 'version': 1})
    with pytest.raises(ActionRejected):
        owner_api().install_owner_records(f.cs, f.owner_bundle, f.owner_source_refs)


def test_owner_registry_does_not_expand_source_permissions(owner_case):
    f = owner_case
    before = deepcopy(f.cs.store.get('source_use_authority:' + f.source_binding))
    f.owner_bundle['substitutions'] = [substitution(f)]
    f.owner_bundle['records'] = [owner('substitution_authorization', 'doc-general', {'section_ids': ['4']})]
    _, plan = install(f)
    assert f.cs.store.get('source_use_authority:' + f.source_binding) == before
    target = next(s for s in plan['sections'] if s['section_id'] == '4')
    assert api().unresolved_sources(target) == []


def test_owner_citation_hash_resolves_to_exact_enrolled_source(owner_case):
    f = owner_case
    value = substitution(f)
    for citation in [*value['replacement_sources'], value['customer_basis']]:
        ref = citation.pop('source_ref')
        citation['source_hash'] = f.cs.read(ref)['payload']['file_digest']
    f.owner_bundle['substitutions'] = [value]
    f.owner_bundle['records'] = [owner('substitution_authorization', 'doc-general', {'section_ids': ['4']})]
    _, plan = install(f)
    result = next(s for s in plan['sections'] if s['section_id'] == '4')['source_substitutions'][0]
    assert result['replacement_sources'][0]['source_ref'] in f.owner_source_refs
    assert 'source_hash' not in result['replacement_sources'][0]


def test_unknown_owner_citation_hash_is_rejected(owner_case):
    f = owner_case
    value = substitution(f)
    value['replacement_sources'][0].pop('source_ref')
    value['replacement_sources'][0]['source_hash'] = '0' * 64
    f.owner_bundle['substitutions'] = [value]
    with pytest.raises(ActionRejected):
        owner_api().install_owner_records(f.cs, f.owner_bundle, f.owner_source_refs)



@pytest.mark.parametrize('gate', ['save', 'approval', 'approval-replay', 'writer'])
def test_forged_owner_records_are_refused_at_real_authority_gates(owner_case, gate):
    f = owner_case
    f.owner_bundle['documents'] = []
    _, plan = install(f)
    plan['owner_records'].append(owner('scope_exclusion', 'S1', {'included': False}))
    if gate != 'save':
        bundle = saved_historical_bundle(f, plan, answered=gate != 'approval')
    with pytest.raises(ActionRejected, match='OWNER_RECORD_CONTRACT'):
        if gate == 'save':
            save(f, plan, operation='j1-forged-owner-save')
        elif gate.startswith('approval'):
            api().reply(f.ws, bundle.issue_id, bundle.decision)
        else:
            with f.cs.store.connect() as db:
                api().assert_writing_allowed(f.cs, db, bundle.actor)


def test_owner_inclusion_cannot_be_reversed_by_agent(owner_case):
    f = owner_case
    target = f.plan['objects'][0]['object_id']
    f.owner_bundle['documents'] = []
    f.owner_bundle['records'] = [owner('object_fact', target, {'included': True})]
    _, plan = install(f)
    plan['objects'][0]['included'] = False
    with f.cs.store.connect() as db, pytest.raises(ActionRejected, match='owner-provided value not retained'):
        owner_api().validate_owner_records(f.cs, db, plan)


def test_owner_selected_substitution_cannot_be_changed(owner_case):
    f = owner_case
    f.owner_bundle['substitutions'] = [substitution(f)]
    f.owner_bundle['records'] = [owner('substitution_authorization', 'doc-general', {'section_ids': ['4']})]
    _, plan = install(f)
    target = next(s for s in plan['sections'] if s['section_id'] == '4')
    target['source_substitutions'][0]['reason'] = 'Unapproved change'
    with f.cs.store.connect() as db, pytest.raises(ActionRejected, match='owner-selected replacement changed'):
        owner_api().validate_owner_records(f.cs, db, plan)


def test_host_prepares_separate_owner_file_without_treating_it_as_source_document(tmp_path, monkeypatch):
    import json
    from test_pilot_m1_preparation import host_case, put_json
    state = host_case(tmp_path, monkeypatch)
    owner_file = state['INPUT'] / 'owner-decisions.json'
    put_json(owner_file, {'contract': 'owner-records-v1', 'records': [], 'documents': [], 'substitutions': [], 'objects': []})
    put_json(state['HERE'] / 'approved-input-hashes.json', state['input_files']())
    # This fixture tests owner-file routing; the pilot skeleton has separate source-bound tests.
    import report_agent.commission_skeleton as skeleton_api
    calls = []
    def skeleton(contents, refs):
        assert contents.store.get('commission_owner_records')
        assert refs
        calls.append(refs)
        return {'requirements_ref': contents.store.get('commission_requirements'), 'digest': 'synthetic-skeleton'}
    monkeypatch.setattr(skeleton_api, 'prepare_skeleton', skeleton)
    state['prepare']()
    prepared = json.loads((state['HERE'] / 'prepared.json').read_text())
    assert len(calls) == 1 and prepared['skeleton_digest'] == 'synthetic-skeleton'
    assert 'owner-decisions.json' in prepared['input_hashes']
    assert 'owner-decisions.json' not in prepared['source_files']
    from report_agent.store import Store
    assert Store(state['CASE']).get('commission_owner_records')
    assert not Store(state['CASE']).get('commission_confirmation')
    assert not (state['HERE'] / 'started.json').exists()


@pytest.mark.parametrize('relative', ['planning-seed.json', 'other.json', 'nested/owner-decisions.json'])
def test_owner_file_exception_does_not_admit_j2_seed_or_unrelated_json(tmp_path, monkeypatch, relative):
    from test_pilot_m1_preparation import host_case
    state = host_case(tmp_path, monkeypatch)
    path = state['INPUT'] / relative
    path.parent.mkdir(exist_ok=True)
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(RuntimeError, match='INPUT_ESCAPE_OR_TYPE'):
        state['input_files']()


def test_stage_pins_root_owner_decisions_file_without_preparing_or_launching(tmp_path, monkeypatch):
    import json
    from test_pilot_m1_preparation import stage_fixture
    state, args = stage_fixture(tmp_path, monkeypatch, extras=1)
    path = args.inputs / 'owner-decisions.json'
    path.write_text('{"contract":"owner-records-v1","records":[]}', encoding='utf-8')
    expected = sha256(path.read_bytes()).hexdigest()
    state['stage'](args)
    pins = json.loads((args.run / 'approved-input-hashes.json').read_text())
    assert pins['owner-decisions.json'] == expected
    assert not (args.run / 'prepared.json').exists()
    assert not (args.run / 'started.json').exists()



def test_existing_owner_scope_reduction_needs_no_second_reduction_decision(owner_case):
    f = owner_case
    f.owner_bundle['documents'] = []
    obj = f.plan['objects'][0]
    reason = 'Owner explicitly excludes this object from the commissioned scope.'
    obj.update(included=False, reason=reason)
    f.owner_bundle['records'] = [owner('scope_exclusion', obj['object_id'],
        {'included': False, 'reason': reason}, reason=reason)]
    _, plan = install(f)
    saved = save(f, plan, operation='j1-owner-reduction-plan')
    assert not f.cs.store.get('commission_confirmation'), 'Owner records do not approve the full plan'
    checkpoint = api().request_checkpoint(f.ws)
    decision = {'plan_ref': saved['plan_ref'], 'requirements_ref': f.requirements_ref,
                'approved': True, 'corrections': '', 'reductions': []}
    api().reply(f.ws, checkpoint['issue_id'], decision)
    confirmation = f.cs.read(f.cs.store.get('commission_confirmation'))['payload']
    assert confirmation['reductions'] == [{'object_id': obj['object_id'], 'reason': reason}]
    # The exact repeated approval remains idempotent even though effective reductions were materialized.
    api().reply(f.ws, checkpoint['issue_id'], decision)


def test_owner_open_facts_automatically_reach_word_comments_and_excel_rows(ws):
    from io import BytesIO
    from docx import Document
    from openpyxl import load_workbook
    from test_m1_g3_exports import fixture as export_fixture, exports
    cs, actor, snapshot, added = export_fixture(ws, body={'columns': ['Scope'], 'rows': [['Excluded']]})
    original = cs.read(snapshot)
    source_ref = next(ref for ref in original['payload']['refs'] if ref['type'] == 'SourceArtifact')
    record = owner('scope_exclusion', 'survey-extra', {'included': False}, reason='Owner scope decision only.')
    record['open_facts'] = [{'id': 'height-conflict', 'kind': 'conflict', 'object_label': 'Survey-only slope',
        'basis': '12 m versus 14 m remains unresolved; exclusion is the owner scope decision.',
        'sources': [{'source_ref': source_ref, 'locator': 'manifest text', 'quote': 'Class B permits 75 to 100.'}],
        'adopted_value': 'Excluded by owner scope decision',
        'question': 'Designer to confirm the 12 m / 14 m height conflict.', 'affects_level': False}]
    # Export fixture uses a schema-valid plan and native frozen obligations; approval gates are tested separately.
    citation = deepcopy(record['open_facts'][0]['sources'][0])
    plan = {'sections': [{'section_id': '4', 'title': 'Scope record', 'kind': 'extracted',
                         'outline': citation, 'sources': [citation]}],
            'inventory_attributes': ['height'],
            'objects': [{'object_id': 'survey-extra', 'label': 'Survey-only slope', 'included': False,
                         'reason': record['reason'], 'origin': 'customer', 'sources': [citation],
                         'attributes': [{'name': 'height', 'values': [{'value': None, 'source': None,
                         'reason': 'Retained conflict requires designer confirmation.'}]}]}],
            'conventions': [], 'deliverables': ['Word', 'Excel'],
            'reconciliations': [{'sources': [citation, citation], 'result': 'Synthetic retained-source check.', 'differences': []}],
            'open_questions': []}
    owner_api().install_owner_records(cs, {'contract': 'owner-records-v1', 'records': [record],
        'documents': [], 'substitutions': [], 'objects': []}, [source_ref])
    with cs.store.connect() as db:
        plan = owner_api().decorate_plan(cs, db, plan)
        owner_api().validate_owner_records(cs, db, plan)
        plan = api().CommissionPlan.model_validate(plan).model_dump()
        plan_ref = cs._insert(db, actor, 'CommissionPlan', plan)
        from report_agent.content_store import Actor
        required = api().required_material_issues(cs, db, plan_ref, plan)
        confirmation = cs._insert(db, Actor('operator', 'operator', 'j1-export-fixture'), 'CommissionDecision',
            {'plan_ref': plan_ref, 'approved': True, 'required_material_issues': required})
        frozen = cs._insert(db, actor, 'DocumentSnapshot', {**original['payload'],
            'refs': [*original['payload']['refs'], plan_ref, confirmation], 'commission_plan_ref': plan_ref,
            'commission_confirmation_ref': confirmation})
    word, excel = exports(ws, cs, actor, frozen, added)
    doc = Document(BytesIO(word))
    workbook = load_workbook(BytesIO(excel))
    rows = list(workbook['资料澄清清单'].values)
    assert len(doc.comments) == 1
    assert len(rows) == 2
    comment = list(doc.comments)[0].text
    assert '12 m versus 14 m' in comment and 'Designer to confirm' in comment
    assert '12 m versus 14 m' in str(rows[1]) and 'Designer to confirm' in str(rows[1])
    assert rows[1][7] is None, 'Unresolved designer response must remain blank'
    assert not cs.read(added['table'])['payload']['body'].get('material_issues'), 'Agent did not manually attach the owner issue'



def test_owner_registry_refuses_unenrolled_cited_source_without_expanding_authority(required_case):
    from report_agent.source_use import configure_source_use
    f = required_case
    refs = [pin['ref'] for pin in source_pins(f, f.plan)]
    value = substitution(f)
    forbidden_id = f.cs.read(value['replacement_sources'][0]['source_ref'])['payload']['source_id']
    allowed = sorted({f.cs.read(ref)['payload']['source_id'] for ref in refs} - {forbidden_id})
    binding = configure_source_use(f.cs.store, allowed, 'Restricted J1 fixture source grant')
    before = deepcopy(f.cs.store.get('source_use_authority:' + binding))
    bundle = {'contract': 'owner-records-v1', 'records': [],
        'documents': [{'id': 'doc-general', 'name': 'General notes', 'section_ids': ['4']}],
        'substitutions': [value], 'objects': []}
    with pytest.raises((ActionRejected, ActionForbidden)):
        owner_api().install_owner_records(f.cs, bundle, refs)
    assert not f.cs.store.get('commission_owner_records')
    assert f.cs.store.get('source_use_authority:' + binding) == before


def test_duplicate_owner_record_ids_are_rejected(owner_case):
    f = owner_case
    value = owner('withdrawal', 'doc-general', {'withdrawn': True})
    f.owner_bundle['records'] = [value, deepcopy(value)]
    with pytest.raises(ActionRejected):
        owner_api().install_owner_records(f.cs, f.owner_bundle, f.owner_source_refs)


def test_duplicate_document_ids_are_rejected(owner_case):
    f = owner_case
    f.owner_bundle['documents'].append(deepcopy(f.owner_bundle['documents'][0]))
    with pytest.raises(ActionRejected):
        owner_api().install_owner_records(f.cs, f.owner_bundle, f.owner_source_refs)


def test_owner_substitution_requires_document_id_registered_for_that_section(owner_case):
    f = owner_case
    value = substitution(f)
    value['document_id'] = 'unknown-doc'
    f.owner_bundle['substitutions'] = [value]
    with pytest.raises(ActionRejected) as error:
        owner_api().install_owner_records(f.cs, f.owner_bundle, f.owner_source_refs)
    assert '4' in str(error.value) and 'unknown-doc' in str(error.value)


def test_host_rehashes_owner_file_before_json_parse_and_registry_install(tmp_path, monkeypatch):
    from test_pilot_m1_preparation import host_case, put_json
    state = host_case(tmp_path, monkeypatch)
    path = state['INPUT'] / 'owner-decisions.json'
    put_json(path, {'contract': 'owner-records-v1', 'records': []})
    original_input_files = state['input_files']
    put_json(state['HERE'] / 'approved-input-hashes.json', original_input_files())
    def mutate_after_initial_hash():
        pins = original_input_files()
        path.write_bytes(b'not JSON after initial pin check')
        return pins
    monkeypatch.setitem(state, 'input_files', mutate_after_initial_hash)
    called = []
    def must_not_install(*args, **kwargs):
        called.append(True)
        raise AssertionError('Changed owner file reached trusted installer')
    monkeypatch.setattr(owner_api(), 'install_owner_records', must_not_install)
    with pytest.raises(RuntimeError, match='OWNER.*CHANGED'):
        state['prepare']()
    assert not called
    assert not (state['HERE'] / 'prepared.json').exists()



def test_enrolled_but_omitted_source_ref_cannot_enter_owner_registry(owner_case):
    f = owner_case
    value = substitution(f)
    omitted = value['replacement_sources'][0]['source_ref']
    refs = [ref for ref in f.owner_source_refs if ref != omitted]
    f.owner_bundle['substitutions'] = [value]
    assert f.cs.read(omitted)['payload']['source_id'] in f.enrolled_ids
    with pytest.raises(ActionRejected):
        owner_api().install_owner_records(f.cs, f.owner_bundle, refs)
    assert not f.cs.store.get('commission_owner_records')


def test_rejected_plan_does_not_materialize_owner_reductions_as_approval(owner_case):
    f = owner_case
    f.owner_bundle['documents'] = []
    obj = f.plan['objects'][0]
    reason = 'Owner scope exclusion remains recorded but does not approve this plan.'
    obj.update(included=False, reason=reason)
    f.owner_bundle['records'] = [owner('scope_exclusion', obj['object_id'],
        {'included': False, 'reason': reason}, reason=reason)]
    _, plan = install(f)
    saved = save(f, plan, operation='j1-rejected-owner-plan')
    checkpoint = api().request_checkpoint(f.ws)
    api().reply(f.ws, checkpoint['issue_id'], {'plan_ref': saved['plan_ref'],
        'requirements_ref': f.requirements_ref, 'approved': False,
        'corrections': 'Revise the plan before approval.', 'reductions': []})
    decision = f.cs.read(f.cs.store.get('commission_confirmation'))['payload']
    assert decision['approved'] is False
    assert decision['reductions'] == []



def test_stage_explicit_owner_decisions_file_is_copied_and_pinned_separately(tmp_path, monkeypatch):
    import json
    from test_pilot_m1_preparation import stage_fixture
    state, args = stage_fixture(tmp_path, monkeypatch, extras=1)
    external = tmp_path / 'reviewed-owner-records.json'
    external.write_text('{"contract":"owner-records-v1","records":[]}', encoding='utf-8')
    args.owner_decisions = external
    assert not (args.inputs / 'owner-decisions.json').exists()
    state['stage'](args)
    target = args.run / 'inputs/owner-decisions.json'
    assert target.read_bytes() == external.read_bytes()
    pins = json.loads((args.run / 'approved-input-hashes.json').read_text())
    assert pins['owner-decisions.json'] == sha256(external.read_bytes()).hexdigest()
    assert not (args.run / 'prepared.json').exists()
    assert not (args.run / 'started.json').exists()


def test_explicit_owner_file_cannot_overwrite_a_different_input_owner_file(tmp_path, monkeypatch):
    from test_pilot_m1_preparation import stage_fixture
    state, args = stage_fixture(tmp_path, monkeypatch, extras=1)
    original = args.inputs / 'owner-decisions.json'
    original.write_text('{"contract":"owner-records-v1","records":[]}', encoding='utf-8')
    external = tmp_path / 'different-owner-records.json'
    external.write_text('{"conflicting":"owner file"}', encoding='utf-8')
    args.owner_decisions = external
    with pytest.raises(ValueError, match='OWNER_DECISIONS_FILE_OR_DUPLICATE_INVALID'):
        state['stage'](args)
    assert original.read_text() == '{"contract":"owner-records-v1","records":[]}'
