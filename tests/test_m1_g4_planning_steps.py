"""H2 source-bound planning tools; synthetic offline mechanics, not autonomy."""
from report_agent import issue_state
from copy import deepcopy
from importlib import import_module

import pytest

from report_agent import commission_imports, plan_authority
from report_agent.errors import ActionRejected
from report_agent.store import encode
from report_agent.catalog import Catalog
from test_m1_commission_plan import api, save, writer
from test_m1_g3_integration import method_commission, persist, persistence_input
from test_m1_g4_requirements import (
    anchored, required_case, requirements, saved_historical_bundle,
    assert_gap_exception, GATES, capture,
)


def planning():
    return import_module('report_agent.commission_planning')


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import httpx
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')

    def forbidden(*args, **kwargs):
        raise AssertionError('H2_PLANNING_NETWORK_FORBIDDEN')

    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)


def source_pins(fixture, payload):
    refs = {}

    def visit(value):
        if isinstance(value, dict):
            if 'source_ref' in value:
                ref = value['source_ref']
                refs[encode(ref)] = ref
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return [{'ref': refs[key], 'file_digest': fixture.cs.read(refs[key])['payload']['file_digest']}
        for key in sorted(refs)]


@pytest.fixture
def entries(required_case):
    fixture = required_case
    pack = fixture.plan['method_pack']
    strategy = fixture.plan['method_conventions'][0]['strategy_id']
    table = fixture.plan['table_specs']['evaluation']
    fixture.entries = [
        {'id': 'synthetic-method-v2', 'kind': 'method', 'label': '合成指南：评估方法（第1页）',
         'method_pack': deepcopy(pack), 'source_pins': source_pins(fixture, pack)},
        {'id': 'synthetic-weight-v2', 'kind': 'weight', 'label': '合成指南权重表：适用指标数对应行',
         'method_pack': deepcopy(pack), 'strategy_id': strategy, 'source_pins': source_pins(fixture, pack)},
        {'id': 'synthetic-evaluation-v1', 'kind': 'table', 'label': '合成模板：风险评价表',
         'table_specs': {'evaluation': deepcopy(table)}, 'source_pins': source_pins(fixture, table)},
    ]
    fixture.weight_anchor = next(a for a in fixture.anchors if 'rank-lookup weights' in a['source']['quote'])
    fixture.table_anchor = next(a for a in fixture.anchors if 'both the ranking' in a['source']['quote'])
    return fixture


def current_items(fixture):
    record = requirements().read_requirements(fixture.cs)
    return record, {i['anchor_id']: i for i in record['payload']['items']}


def link(fixture, anchor, entry_id, operation):
    receipt = planning().link_convention(fixture.cs, fixture.co, operation,
        anchor['id'], entry_id, '按照此已审查条目执行，保留客户原文。')
    fixture.requirements_ref = receipt['result']['requirements_ref']
    fixture.plan['requirements_ref'] = fixture.requirements_ref
    return receipt


@pytest.fixture
def linked(entries):
    fixture = entries
    planning().install_reviewed_entries(fixture.cs, fixture.entries)
    link(fixture, fixture.weight_anchor, 'synthetic-weight-v2', 'link-weight')
    link(fixture, fixture.table_anchor, 'synthetic-evaluation-v1', 'link-table')
    return fixture


def test_reviewed_catalogue_is_immutable_and_known_install_is_idempotent(entries):
    fixture = entries
    before = deepcopy(fixture.entries)
    first = planning().install_reviewed_entries(fixture.cs, fixture.entries)
    assert planning().install_reviewed_entries(fixture.cs, deepcopy(before)) == first
    changed = deepcopy(before)
    changed[1]['label'] = 'Silently replaced review label'
    with pytest.raises(ActionRejected):
        planning().install_reviewed_entries(fixture.cs, changed)
    assert planning().install_reviewed_entries(fixture.cs, before) == first
    assert fixture.entries == before


@pytest.mark.parametrize('fault', ['unreviewed-method', 'false-source-pin', 'missing-source-pin', 'duplicate-id'])
def test_reviewed_catalogue_rejects_unreviewed_or_unbound_entries(entries, fault):
    fixture = entries
    invalid = deepcopy(fixture.entries)
    if fault == 'unreviewed-method':
        invalid[0]['method_pack']['version'] += 1
    elif fault == 'false-source-pin':
        invalid[0]['source_pins'][0]['file_digest'] = '0' * 64
    elif fault == 'missing-source-pin':
        invalid[0]['source_pins'].pop()
    else:
        invalid[1]['id'] = invalid[0]['id']
    with pytest.raises((ActionRejected, ValueError)):
        planning().install_reviewed_entries(fixture.cs, invalid)
    # A rejected installation must not poison the trusted catalogue.
    planning().install_reviewed_entries(fixture.cs, fixture.entries)


def test_linked_entries_derive_caps_and_roles_without_changing_other_requirements(linked):
    fixture = linked
    record, items = current_items(fixture)
    weight = items[fixture.weight_anchor['id']]
    table = items[fixture.table_anchor['id']]
    assert weight['reviewed_entry_id'] == 'synthetic-weight-v2'
    assert set(weight['capabilities']) == {'method_pack', 'weight_binding'}
    assert table['reviewed_entry_id'] == 'synthetic-evaluation-v1'
    assert table['capabilities'] == ['table_specs'] and table['table_roles'] == ['evaluation']
    untouched = {i['anchor_id']: i for i in fixture.items
        if i['anchor_id'] not in {fixture.weight_anchor['id'], fixture.table_anchor['id']}}
    assert all(items[key] == value for key, value in untouched.items())
    assert record['payload']['anchors'] == fixture.anchors
    assert requirements().check_plan(fixture.cs, fixture.plan, fixture.requirements_ref) == []


def test_per_item_status_preserves_entry_derived_caps_and_other_items(linked):
    fixture = linked
    before, previous = current_items(fixture)
    receipt = planning().set_requirement_status(fixture.cs, fixture.co, 'status-weight',
        fixture.weight_anchor['id'], 'required', '新解释不改变已审查权重要求。', capabilities=['inventory'])
    record, items = current_items(fixture)
    assert record['ref'] == receipt['result']['requirements_ref']
    assert set(items[fixture.weight_anchor['id']]['capabilities']) == {'method_pack', 'weight_binding'}
    assert items[fixture.weight_anchor['id']]['reviewed_entry_id'] == 'synthetic-weight-v2'
    assert all(items[key] == value for key, value in previous.items() if key != fixture.weight_anchor['id'])
    assert fixture.cs.read(before['ref']) == before
    assert planning().set_requirement_status(fixture.cs, fixture.co, 'status-weight',
        fixture.weight_anchor['id'], 'required', '新解释不改变已审查权重要求。', capabilities=['inventory']) == receipt


def test_unchanged_status_does_not_create_a_new_requirement_version(linked):
    fixture = linked
    before, items = current_items(fixture)
    item = items[fixture.weight_anchor['id']]
    receipt = planning().set_requirement_status(fixture.cs, fixture.co, 'same-status',
        item['anchor_id'], item['status'], item['interpretation'])
    assert receipt['result']['requirements_ref'] == before['ref']
    assert requirements().read_requirements(fixture.cs) == before


def test_legacy_bulk_proposal_cannot_downgrade_linked_requirements(linked):
    fixture = linked
    before, _ = current_items(fixture)
    proposed = deepcopy(before['payload']['items'])
    for item in proposed:
        if item['anchor_id'] == fixture.weight_anchor['id']:
            item['capabilities'] = ['inventory']
        if item['anchor_id'] == fixture.table_anchor['id']:
            item['capabilities'] = ['deliverables']; item['table_roles'] = ['unrelated']
    receipt = requirements().propose_requirements(fixture.cs, fixture.co, 'bulk-downgrade', before['ref'], proposed)
    _, items = current_items(fixture)
    assert set(items[fixture.weight_anchor['id']]['capabilities']) == {'method_pack', 'weight_binding'}
    assert items[fixture.table_anchor['id']]['capabilities'] == ['table_specs']
    assert items[fixture.table_anchor['id']]['table_roles'] == ['evaluation']
    assert receipt['result']['requirements_ref'] == requirements().read_requirements(fixture.cs)['ref']


@pytest.mark.parametrize('replacement', [None, 'synthetic-method-v2'])
def test_bulk_status_cannot_remove_or_silently_replace_reviewed_entry_link(linked, replacement):
    fixture = linked
    before, _ = current_items(fixture)
    proposed = deepcopy(before['payload']['items'])
    item = next(i for i in proposed if i['anchor_id'] == fixture.weight_anchor['id'])
    if replacement is None:
        item.pop('reviewed_entry_id')
    else:
        item['reviewed_entry_id'] = replacement
    with pytest.raises(ActionRejected):
        requirements().propose_requirements(fixture.cs, fixture.co, 'bulk-relink', before['ref'], proposed)
    assert requirements().read_requirements(fixture.cs) == before


@pytest.mark.parametrize('fault', ['method-omitted', 'method-changed', 'strategy-changed', 'table-omitted', 'table-changed'])
def test_final_checker_requires_exact_linked_reviewed_data(linked, fault):
    fixture = linked
    assert requirements().check_plan(fixture.cs, fixture.plan, fixture.requirements_ref) == []
    plan = deepcopy(fixture.plan)
    anchor = fixture.weight_anchor
    if fault == 'method-omitted':
        plan.pop('method_pack')
    elif fault == 'method-changed':
        plan['method_pack']['display_labels']['total'] = 'Changed reviewed data'
    elif fault == 'strategy-changed':
        plan['method_conventions'][0]['strategy_id'] = 'not-the-linked-row'
    elif fault == 'table-omitted':
        plan['table_specs'].pop('evaluation'); anchor = fixture.table_anchor
    else:
        plan['table_specs']['evaluation']['caption_pattern'] = 'Changed ' + plan['table_specs']['evaluation']['caption_pattern']
        anchor = fixture.table_anchor
    gaps = requirements().check_plan(fixture.cs, plan, fixture.requirements_ref)
    assert any(g['anchor_id'] == anchor['id'] for g in gaps), gaps
    with pytest.raises(ActionRejected) as exc:
        save(fixture, plan)
    assert_gap_exception(exc, fixture)


@pytest.mark.parametrize('gate', GATES)
def test_every_authority_gate_rechecks_linked_table_payload(linked, gate):
    fixture = linked
    plan = deepcopy(fixture.plan)
    plan['table_specs']['evaluation']['caption_pattern'] = 'Changed ' + plan['table_specs']['evaluation']['caption_pattern']
    if gate != 'save':
        plan = api().CommissionPlan.model_validate(plan).model_dump()
        bundle = saved_historical_bundle(fixture, plan, answered=gate != 'approval')
    before = deepcopy(fixture.cs.list_objects())
    with pytest.raises(ActionRejected) as exc:
        if gate == 'save':
            save(fixture, plan)
        elif gate.startswith('approval'):
            api().reply(fixture.ws, bundle.issue_id, bundle.decision)
        elif gate == 'writer':
            with fixture.cs.store.connect() as db:
                api().assert_writing_allowed(fixture.cs, db, bundle.actor)
        elif gate == 'assessment':
            assessment = persistence_input(fixture); assessment['method_version'] = 2
            persist(fixture, bundle.actor, assessment)
        elif gate == 'outcome':
            api().record_outcome(fixture.cs, bundle.actor, 'blocked-linked-outcome', 'S1',
                bundle.root_ref, bundle.root_ref, bundle.root_ref, [], [])
        elif gate == 'word-export':
            from report_agent.content_export import export_snapshot
            export_snapshot(fixture.cs, fixture.co, 'blocked-linked-word', bundle.snapshot_ref)
        else:
            from report_agent.content_workbook import export_workbook
            export_workbook(fixture.cs, fixture.co, 'blocked-linked-excel', bundle.snapshot_ref,
                [{'name': 'Records', 'table_ref': bundle.table_ref}])
    assert_gap_exception(exc, fixture)
    assert any(g['anchor_id'] == fixture.table_anchor['id'] for g in exc.value.diagnostic['gaps'])
    assert fixture.cs.list_objects() == before


def test_reviewed_table_bundle_derives_every_role_and_cannot_lose_one(entries):
    fixture = entries
    entry = fixture.entries[2]
    entry['table_specs'] = deepcopy(fixture.plan['table_specs'])
    entry['source_pins'] = source_pins(fixture, entry['table_specs'])
    planning().install_reviewed_entries(fixture.cs, fixture.entries)
    link(fixture, fixture.table_anchor, entry['id'], 'link-both-tables')
    before, items = current_items(fixture)
    item = items[fixture.table_anchor['id']]
    assert set(item['table_roles']) == {'ranking', 'evaluation'}
    assert item['capabilities'] == ['table_specs']
    assert requirements().check_plan(fixture.cs, fixture.plan, fixture.requirements_ref) == []
    proposed = deepcopy(before['payload']['items'])
    next(i for i in proposed if i['anchor_id'] == fixture.table_anchor['id'])['table_roles'] = ['evaluation']
    receipt = requirements().propose_requirements(fixture.cs, fixture.co, 'reduce-table-role', before['ref'], proposed)
    after, items = current_items(fixture)
    assert set(items[fixture.table_anchor['id']]['table_roles']) == {'ranking', 'evaluation'}
    plan = deepcopy(fixture.plan); plan['requirements_ref'] = after['ref']
    plan['table_specs'].pop('ranking')
    assert any(g['anchor_id'] == fixture.table_anchor['id']
        for g in requirements().check_plan(fixture.cs, plan, receipt['result']['requirements_ref']))


def test_pre_h2_successful_requirement_proposal_retains_normalized_replay_identity(required_case):
    fixture = required_case
    before = requirements().read_requirements(fixture.cs)
    raw = deepcopy(before['payload']['items'])
    for item in raw:
        item.setdefault('table_roles', [])
    # H1 normalized model defaults before recording the operation request hash.
    normalized = [requirements().RequirementItem.model_validate(i).model_dump() for i in raw]
    assert raw != normalized
    receipt = fixture.cs.operation(fixture.co, 'historical-requirement-proposal',
        {'requirements_ref': before['ref'], 'items': normalized},
        lambda db: {'requirements_ref': before['ref']})
    replay = requirements().propose_requirements(fixture.cs, fixture.co,
        'historical-requirement-proposal', before['ref'], raw)
    assert replay == receipt
    assert requirements().read_requirements(fixture.cs) == before


PAGE_ONE = '''SYNTHETIC HEADER
Start sentence.

4.1 Boundary

A wrapped line
continues here.

风险评估
依据资料。

SYNTHETIC HEADER

Page one ends.
SYNTHETIC FOOTER
11'''
PAGE_TWO = '''SYNTHETIC HEADER
The next paragraph
continues.

End sentence.
SYNTHETIC FOOTER
12'''
NORMALIZED = '''Start sentence.

4.1 Boundary

A wrapped line continues here.

风险评估依据资料。

SYNTHETIC HEADER

Page one ends.

The next paragraph continues.

End sentence.'''


def paginated_source(fixture, name, pages):
    """Known synthetic extraction fixture, not a claim about PDF/OCR parsing."""
    ref = capture(fixture, name + '.txt', '\n\n'.join(pages).encode('utf-8'), name)
    record = fixture.cs.read(ref)
    source_id = record['payload']['source_id']
    with fixture.cs.store.connect() as db:
        db.execute('DELETE FROM source_blocks WHERE source_id=?', (source_id,))
        Catalog._blocks(db, source_id, [
            {'locator': f'page {page}', 'text': text} for page, text in enumerate(pages, 1)])
    roles = deepcopy(commission_imports.source_roles(fixture.ws.store))
    roles[name] = {'id': source_id, 'purpose': 'template'}
    commission_imports.install_source_roles(fixture.ws.store, roles)
    return ref


@pytest.fixture
def text_source(required_case):
    fixture = required_case
    fixture.text_ref = paginated_source(fixture, 'h2-synthetic-pages', [PAGE_ONE, PAGE_TWO])
    fixture.text_profile = {
        'id': 'synthetic-lines-v1', 'source_ref': fixture.text_ref,
        'file_digest': fixture.cs.read(fixture.text_ref)['payload']['file_digest'],
        'header_lines': ['SYNTHETIC HEADER'], 'footer_lines': ['SYNTHETIC FOOTER'],
        'page_number_offset': 10, 'join_lines': 'paragraph',
    }
    fixture.selection = {'source_ref': fixture.text_ref, 'start_page': 1, 'end_page': 2,
        'start_sentence': 'Start sentence.', 'end_sentence': 'End sentence.',
        'profile_id': 'synthetic-lines-v1'}
    return fixture


def test_source_span_normalizes_only_reviewed_page_furniture_and_retains_raw_provenance(text_source):
    fixture = text_source
    before = deepcopy(fixture.cs.read(fixture.text_ref))
    planning().install_text_profile(fixture.cs, fixture.text_profile)
    result = planning().resolve_source_span(fixture.cs, fixture.selection)
    assert result['text'] == NORMALIZED
    assert result['text'].count('SYNTHETIC HEADER') == 1, 'The body occurrence is not page furniture.'
    assert '4.1 Boundary' in result['text']
    sources = result['sources']
    assert len(sources) == 2
    assert [c['locator'].split(';')[0] for c in sources] == ['page 1', 'page 2']
    assert all(c['source_ref'] == fixture.text_ref for c in sources)
    assert sources[0]['quote'] == PAGE_ONE[PAGE_ONE.index('Start sentence.'):]
    assert sources[1]['quote'] == PAGE_TWO[:PAGE_TWO.index('End sentence.') + len('End sentence.')]
    assert 'SYNTHETIC FOOTER\n11' in sources[0]['quote']
    assert sources[1]['quote'].startswith('SYNTHETIC HEADER')
    proof = result['normalization']
    assert proof['profile_id'] == fixture.text_profile['id']
    assert len(proof['raw_digest']) == len(proof['output_digest']) == 64
    assert proof['raw_digest'] != proof['output_digest']
    assert planning().resolve_source_span(fixture.cs, fixture.selection) == result
    assert fixture.cs.read(fixture.text_ref) == before


def test_text_profile_is_immutable_and_hash_bound(text_source):
    fixture = text_source
    first = planning().install_text_profile(fixture.cs, fixture.text_profile)
    assert planning().install_text_profile(fixture.cs, deepcopy(fixture.text_profile)) == first
    changed = deepcopy(fixture.text_profile)
    changed['header_lines'].append('Delete this ordinary body sentence')
    with pytest.raises(ActionRejected):
        planning().install_text_profile(fixture.cs, changed)
    invalid = {**deepcopy(fixture.text_profile), 'id': 'wrong-file-pin', 'file_digest': '0' * 64}
    with pytest.raises(ActionRejected):
        planning().install_text_profile(fixture.cs, invalid)
    assert planning().resolve_source_span(fixture.cs, fixture.selection)['text'] == NORMALIZED


@pytest.mark.parametrize('fault', ['missing-start', 'missing-end', 'reversed-pages',
    'missing-page', 'unknown-profile', 'injected-text', 'injected-proof'])
def test_source_span_rejects_unknown_ranges_and_model_authored_output(text_source, fault):
    fixture = text_source
    planning().install_text_profile(fixture.cs, fixture.text_profile)
    selected = deepcopy(fixture.selection)
    if fault == 'missing-start':
        selected['start_sentence'] = 'This is not in the source.'
    elif fault == 'missing-end':
        selected['end_sentence'] = 'This ending was invented.'
    elif fault == 'reversed-pages':
        selected.update(start_page=2, end_page=1)
    elif fault == 'missing-page':
        selected['end_page'] = 3
    elif fault == 'unknown-profile':
        selected['profile_id'] = 'not-installed'
    elif fault == 'injected-text':
        selected['text'] = 'A model-authored replacement paragraph.'
    else:
        selected['normalization'] = {'profile_id': 'invented', 'output_digest': '0' * 64}
    with pytest.raises((ActionRejected, ValueError)):
        planning().resolve_source_span(fixture.cs, selected)


def test_text_profile_cannot_be_reused_for_another_source_version(text_source):
    fixture = text_source
    planning().install_text_profile(fixture.cs, fixture.text_profile)
    other = paginated_source(fixture, 'other-pages', [PAGE_ONE + '\nChanged original.', PAGE_TWO])
    selected = {**fixture.selection, 'source_ref': other}
    with pytest.raises(ActionRejected):
        planning().resolve_source_span(fixture.cs, selected)


@pytest.mark.parametrize('endpoint', ['start', 'end'])
def test_duplicate_endpoint_sentences_require_disambiguation(text_source, endpoint):
    fixture = text_source
    pages = [PAGE_ONE, PAGE_TWO]
    if endpoint == 'start':
        pages[0] = pages[0].replace('Page one ends.', 'Start sentence.\nPage one ends.')
    else:
        pages[1] = pages[1].replace('The next paragraph', 'End sentence.\nThe next paragraph')
    ref = paginated_source(fixture, 'duplicate-' + endpoint, pages)
    profile = {**fixture.text_profile, 'source_ref': ref,
        'file_digest': fixture.cs.read(ref)['payload']['file_digest']}
    planning().install_text_profile(fixture.cs, profile)
    with pytest.raises(ActionRejected):
        planning().resolve_source_span(fixture.cs, {**fixture.selection, 'source_ref': ref})


def enable_h2(fixture):
    fixture.ws.store.set('manifest', {**fixture.ws.store.manifest,
        'commission_planning_contract': 'commission-planning-v1'})


def classifications(fixture):
    rows = []
    for item in fixture.items:
        ids = []
        if item['anchor_id'] == fixture.weight_anchor['id']:
            ids = ['synthetic-weight-v2']
        elif item['anchor_id'] == fixture.table_anchor['id']:
            ids = ['synthetic-evaluation-v1']
        elif item['capabilities'] == ['method_pack']:
            ids = ['synthetic-method-v2']
        rows.append({'anchor_id': item['anchor_id'], 'entry_ids': ids,
            'capabilities': [] if ids else item['capabilities'],
            'table_roles': [] if ids else item.get('table_roles', [])})
    return rows


@pytest.fixture
def classified(entries):
    fixture = entries
    enable_h2(fixture)
    planning().install_reviewed_entries(fixture.cs, fixture.entries)
    fixture.classifications = classifications(fixture)
    planning().install_classifications(fixture.cs, fixture.classifications,
        'Independent synthetic source-anchor classification, before any model status selection.')
    return fixture


def link_other_reviewed_items(fixture):
    for row in fixture.classifications:
        if row['entry_ids'] and row['anchor_id'] != fixture.weight_anchor['id']:
            anchor = next(a for a in fixture.anchors if a['id'] == row['anchor_id'])
            link(fixture, anchor, row['entry_ids'][0], 'other-link-' + row['anchor_id'])


def weaken_unlinked_weight(fixture, route):
    link_other_reviewed_items(fixture)
    before, _ = current_items(fixture)
    if route == 'per-item':
        receipt = planning().set_requirement_status(fixture.cs, fixture.co, 'never-link-status',
            fixture.weight_anchor['id'], 'required', 'Attempt to classify weights as source priority.',
            capabilities=['source_priority'])
    else:
        items = deepcopy(before['payload']['items'])
        item = next(i for i in items if i['anchor_id'] == fixture.weight_anchor['id'])
        item.update(status='required', capabilities=['source_priority'])
        receipt = requirements().propose_requirements(fixture.cs, fixture.co, 'never-link-bulk', before['ref'], items)
    fixture.requirements_ref = receipt['result']['requirements_ref']
    fixture.plan['requirements_ref'] = fixture.requirements_ref
    return fixture


@pytest.mark.parametrize('route', ['per-item', 'bulk'])
def test_never_linked_weight_cannot_be_reclassified_as_a_weaker_requirement(classified, route):
    fixture = weaken_unlinked_weight(classified, route)
    _, items = current_items(fixture)
    item = items[fixture.weight_anchor['id']]
    assert not item.get('reviewed_entry_id')
    assert set(item['capabilities']) == {'method_pack', 'weight_binding'}
    # Even a manually complete payload cannot substitute for the required reviewed link.
    gaps = requirements().check_plan(fixture.cs, fixture.plan, fixture.requirements_ref)
    assert any(g['anchor_id'] == fixture.weight_anchor['id'] for g in gaps)
    plan = deepcopy(fixture.plan)
    for name in ('method_pack', 'method_conventions', 'table_specs'):
        plan.pop(name, None)
    with pytest.raises(ActionRejected) as exc:
        save(fixture, plan)
    assert_gap_exception(exc, fixture)
    assert any(g['anchor_id'] == fixture.weight_anchor['id'] for g in exc.value.diagnostic['gaps'])


def test_classification_refuses_an_unrelated_reviewed_entry_choice(classified):
    fixture = classified
    before = requirements().read_requirements(fixture.cs)
    with pytest.raises(ActionRejected):
        link(fixture, fixture.weight_anchor, 'synthetic-method-v2', 'wrong-allowed-entry')
    assert requirements().read_requirements(fixture.cs) == before


def test_missing_classification_cannot_be_filled_by_model_selected_capabilities(entries):
    fixture = entries
    enable_h2(fixture)
    planning().install_reviewed_entries(fixture.cs, fixture.entries)
    known = [r for r in classifications(fixture) if r['anchor_id'] != fixture.weight_anchor['id']]
    planning().install_classifications(fixture.cs, known, 'Weight meaning is explicitly not classified.')
    gaps = requirements().check_plan(fixture.cs, fixture.plan, fixture.requirements_ref)
    assert any(g['anchor_id'] == fixture.weight_anchor['id'] for g in gaps)
    before = requirements().read_requirements(fixture.cs)
    with pytest.raises(ActionRejected):
        planning().set_requirement_status(fixture.cs, fixture.co, 'invent-classification',
            fixture.weight_anchor['id'], 'required', 'Invent an ordinary classification.',
            capabilities=['source_priority'])
    assert requirements().read_requirements(fixture.cs) == before


@pytest.mark.parametrize('gate', GATES)
def test_all_authority_gates_refuse_the_never_linked_escape(classified, gate):
    fixture = weaken_unlinked_weight(classified, 'bulk')
    plan = deepcopy(fixture.plan)
    if gate != 'save':
        plan = api().CommissionPlan.model_validate(plan).model_dump()
        bundle = saved_historical_bundle(fixture, plan, answered=gate != 'approval')
    before = deepcopy(fixture.cs.list_objects())
    with pytest.raises(ActionRejected) as exc:
        if gate == 'save':
            save(fixture, plan)
        elif gate.startswith('approval'):
            api().reply(fixture.ws, bundle.issue_id, bundle.decision)
        elif gate == 'writer':
            with fixture.cs.store.connect() as db:
                api().assert_writing_allowed(fixture.cs, db, bundle.actor)
        elif gate == 'assessment':
            assessment = persistence_input(fixture); assessment['method_version'] = 2
            persist(fixture, bundle.actor, assessment)
        elif gate == 'outcome':
            api().record_outcome(fixture.cs, bundle.actor, 'never-link-outcome', 'S1',
                bundle.root_ref, bundle.root_ref, bundle.root_ref, [], [])
        elif gate == 'word-export':
            from report_agent.content_export import export_snapshot
            export_snapshot(fixture.cs, fixture.co, 'never-link-word', bundle.snapshot_ref)
        else:
            from report_agent.content_workbook import export_workbook
            export_workbook(fixture.cs, fixture.co, 'never-link-excel', bundle.snapshot_ref,
                [{'name': 'Records', 'table_ref': bundle.table_ref}])
    assert_gap_exception(exc, fixture)
    assert any(g['anchor_id'] == fixture.weight_anchor['id'] for g in exc.value.diagnostic['gaps'])
    assert fixture.cs.list_objects() == before


def test_trusted_ordinary_required_convention_is_not_forced_to_nonapplicable(anchored):
    fixture = anchored
    scope = capture(fixture, 'ordinary-h2-scope.md', b'''# Descriptive commission
## 1. Objects
Describe the supplied S1 inspection record.
## 4. Scope
Use the supplied record set.
## 5. Conventions
1. Retain material issues in the descriptive report; no scoring is commissioned.
''', 'ordinary-h2-scope')
    roles = deepcopy(commission_imports.source_roles(fixture.ws.store))
    roles['ordinary-h2'] = {'id': fixture.cs.read(scope)['payload']['source_id'], 'purpose': 'commission'}
    commission_imports.install_source_roles(fixture.ws.store, roles)
    root = requirements().install_requirements(fixture.cs, scope, fixture.outline_ref)
    enable_h2(fixture)
    record = requirements().read_requirements(fixture.cs, root)
    fixture.anchors = record['payload']['anchors']
    rows = [{'anchor_id': a['id'], 'entry_ids': [], 'table_roles': [],
        'capabilities': ['section'] if a['kind'] == 'section' else
            ['inventory'] if a['kind'] == 'scope' else
            ['material_issues'] if a['kind'] == 'convention' else []}
        for a in fixture.anchors]
    planning().install_classifications(fixture.cs, rows, 'Reviewed descriptive source, ordinary non-scoring obligations.')
    for anchor in fixture.anchors:
        receipt = planning().set_requirement_status(fixture.cs, fixture.co, 'ordinary-' + anchor['id'],
            anchor['id'], 'required', 'Retain this descriptive requirement as applicable.')
    fixture.requirements_ref = receipt['result']['requirements_ref']
    plan = deepcopy(fixture.plan)
    for name in ('method_pack', 'method_conventions', 'table_specs'):
        plan.pop(name, None)
    plan['requirements_ref'] = fixture.requirements_ref
    plan['conventions'] = [{'requirement_anchor_id': a['id'], 'source': a['source'],
        'interpretation': 'Retain the commissioned descriptive issues.'}
        for a in fixture.anchors if a['kind'] == 'convention']
    for section in plan['sections']:
        section['outline'] = next(a['source'] for a in fixture.anchors
            if a['kind'] == 'section' and a['section_id'] == section['section_id'])
    fixture.plan = plan
    _, items = current_items(fixture)
    assert all(i['status'] == 'required' for i in items.values())
    assert requirements().check_plan(fixture.cs, plan, fixture.requirements_ref) == []
    saved = save(fixture)
    checkpoint = api().request_checkpoint(fixture.ws)
    api().reply(fixture.ws, checkpoint['issue_id'], {'plan_ref': saved['plan_ref'],
        'requirements_ref': fixture.requirements_ref, 'approved': True, 'corrections': '', 'reductions': []})
    assigned = writer(fixture, saved)
    with fixture.cs.store.connect() as db:
        assert api().assert_writing_allowed(fixture.cs, db, assigned)
    assert not fixture.cs.list_objects('Assessment')


@pytest.fixture
def draft_case(entries):
    fixture = entries
    fixture.entries[2]['table_specs'] = deepcopy(fixture.plan['table_specs'])
    fixture.entries[2]['source_pins'] = source_pins(fixture, fixture.entries[2]['table_specs'])
    enable_h2(fixture)
    planning().install_reviewed_entries(fixture.cs, fixture.entries)
    fixture.classifications = classifications(fixture)
    planning().install_classifications(fixture.cs, fixture.classifications, 'Reviewed complete synthetic planning fixture.')
    for row in fixture.classifications:
        if row['entry_ids']:
            anchor = next(a for a in fixture.anchors if a['id'] == row['anchor_id'])
            link(fixture, anchor, row['entry_ids'][0], 'draft-link-' + row['anchor_id'])
    return fixture


def save_draft_parts(fixture, *, sections=None):
    planner = planning()
    planner.save_item(fixture.cs, fixture.co, 'draft-details', 'details',
        {k: deepcopy(fixture.plan[k]) for k in ('inventory_attributes', 'deliverables')})
    planner.save_item(fixture.cs, fixture.co, 'draft-boundary', 'boundary', fixture.plan['scope_boundary'])
    for obj in fixture.plan['objects']:
        planner.save_item(fixture.cs, fixture.co, 'draft-object-' + obj['object_id'], 'object', obj)
    for index, reconciliation in enumerate(fixture.plan['reconciliations']):
        planner.save_item(fixture.cs, fixture.co, 'draft-reconcile-' + str(index), 'reconciliation',
            {'reconciliation_id': 'pair-' + str(index), **reconciliation})
    # Explicit reverse order: no mandatory section/tool choreography.
    for section in reversed(sections if sections is not None else fixture.plan['sections']):
        planner.save_item(fixture.cs, fixture.co, 'draft-section-' + section['section_id'], 'section', section)
    return planner.read_draft(fixture.cs, fixture.co)


def test_small_items_submit_exact_server_attached_data_without_approving_plan(draft_case):
    fixture = draft_case
    view = save_draft_parts(fixture)
    assert not view['gaps'], view['gaps']
    assert [s['section_id'] for s in view['plan']['sections']] == [
        a['section_id'] for a in fixture.anchors if a['kind'] == 'section']
    assert not fixture.cs.list_objects('CommissionPlan')
    receipt = planning().submit_plan(fixture.cs, fixture.co, 'submit-complete-draft')
    saved = fixture.cs.read(receipt['result']['plan_ref'])['payload']
    from report_agent.method_pack import MethodPack
    from report_agent.table_spec import validate_table_specs
    assert saved['method_pack'] == MethodPack.model_validate(fixture.plan['method_pack']).model_dump(mode='json')
    assert saved['table_specs'] == validate_table_specs(fixture.plan['table_specs'])
    assert saved['method_conventions'][0]['strategy_id'] == fixture.entries[1]['strategy_id']
    assert saved['method_conventions'][0]['source'] == fixture.weight_anchor['source']
    assert planning().submit_plan(fixture.cs, fixture.co, 'submit-complete-draft') == receipt
    assert plan_authority.decision_ref(fixture.ws.store) is None
    checkpoint = api().request_checkpoint(fixture.ws)
    brief = (fixture.ws.store.root / checkpoint['brief_path']).read_text(encoding='utf-8')
    assert fixture.entries[1]['label'] in brief and fixture.entries[2]['label'] in brief
    assert '权重' in brief and f"{len(fixture.plan['method_pack']['indicators'])}项行" in brief


def test_empty_draft_reports_all_remaining_parts_together(draft_case):
    fixture = draft_case
    with pytest.raises(ActionRejected) as exc:
        planning().submit_plan(fixture.cs, fixture.co, 'submit-empty-draft')
    gaps = exc.value.diagnostic['gaps']
    paths = ' '.join(g['path'] for g in gaps)
    assert all(part in paths for part in ('sections.4', 'sections.5', 'objects',
        'scope_boundary', 'reconciliations', 'inventory_attributes', 'deliverables'))
    assert not fixture.cs.list_objects('CommissionPlan')


def test_stable_item_ids_replace_reconciliation_and_resolve_question(draft_case):
    fixture = draft_case
    first = {'reconciliation_id': 'design-survey', **deepcopy(fixture.plan['reconciliations'][0])}
    receipt = planning().save_item(fixture.cs, fixture.co, 'reconcile-first', 'reconciliation', first)
    changed = {**first, 'result': 'Corrected comparison after inspecting both source records.'}
    planning().save_item(fixture.cs, fixture.co, 'reconcile-correct', 'reconciliation', changed)
    question = {'question_id': 'count-check', 'text': 'Confirm the source inventory count.', 'resolved': False}
    planning().save_item(fixture.cs, fixture.co, 'question-open', 'question', question)
    assert question['text'] in planning().read_draft(fixture.cs, fixture.co)['plan']['open_questions']
    planning().save_item(fixture.cs, fixture.co, 'question-resolved', 'question', {**question, 'resolved': True})
    view = planning().read_draft(fixture.cs, fixture.co)
    assert view['plan']['open_questions'] == []
    assert len(view['plan']['reconciliations']) == 1
    assert view['plan']['reconciliations'][0]['result'] == changed['result']
    assert 'reconciliation_id' not in view['plan']['reconciliations'][0]
    assert planning().save_item(fixture.cs, fixture.co, 'reconcile-first', 'reconciliation', first) == receipt
    assert planning().read_draft(fixture.cs, fixture.co)['plan']['reconciliations'][0]['result'] == changed['result']


def test_item_receipts_and_noop_revision_are_distinct_from_real_edit(draft_case):
    fixture = draft_case
    obj = fixture.plan['objects'][0]
    first = planning().save_item(fixture.cs, fixture.co, 'one-object', 'object', obj)
    assert first['result']['changed']
    assert planning().save_item(fixture.cs, fixture.co, 'one-object', 'object', obj) == first
    same = planning().save_item(fixture.cs, fixture.co, 'same-object-new-call', 'object', obj)
    assert not same['result']['changed'] and same['result']['revision'] == first['result']['revision']
    with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
        planning().save_item(fixture.cs, fixture.co, 'one-object', 'object', {**obj, 'label': 'Different intent'})


def test_details_tool_cannot_hide_sections_or_an_entire_plan(draft_case):
    fixture = draft_case
    with pytest.raises((ActionRejected, ValueError)):
        planning().save_item(fixture.cs, fixture.co, 'hidden-plan', 'details', {
            'inventory_attributes': ['height'], 'deliverables': ['Word'], 'sections': fixture.plan['sections']})


def attach_text_fixture(fixture):
    fixture.text_ref = paginated_source(fixture, 'draft-source-pages', [PAGE_ONE, PAGE_TWO])
    fixture.selection = {'source_ref': fixture.text_ref, 'start_page': 1, 'end_page': 2,
        'start_sentence': 'Start sentence.', 'end_sentence': 'End sentence.', 'profile_id': 'draft-lines-v1'}
    planning().install_text_profile(fixture.cs, {'id': 'draft-lines-v1', 'source_ref': fixture.text_ref,
        'file_digest': fixture.cs.read(fixture.text_ref)['payload']['file_digest'],
        'header_lines': ['SYNTHETIC HEADER'], 'footer_lines': ['SYNTHETIC FOOTER'],
        'page_number_offset': 10, 'join_lines': 'paragraph'})
    section = deepcopy(fixture.plan['sections'][1])
    for field in ('sources', 'text', 'extraction'):
        section.pop(field, None)
    section.update(kind='fixed', source_span=fixture.selection, derived_from=[], rule='',
        result_bindings=[{'old': 'End sentence.', 'object_id': 'S1', 'field': 'assessment_text'}])
    return section


def test_section_selector_materializes_fixed_text_and_structured_result_slot(draft_case):
    fixture = draft_case
    section = attach_text_fixture(fixture)
    view = save_draft_parts(fixture, sections=[fixture.plan['sections'][0], section])
    assert not view['gaps'], view['gaps']
    value = next(s for s in view['plan']['sections'] if s['section_id'] == '5')
    assert value['text'] == NORMALIZED
    assert api().fixed_section_text(value) == NORMALIZED
    assert value['extraction']['selection'] == fixture.selection
    assert value['result_bindings'] == [api().ResultBinding.model_validate(binding).model_dump()
        for binding in section['result_bindings']]
    assert any('SYNTHETIC FOOTER' in s['quote'] for s in value['sources'])
    saved = planning().submit_plan(fixture.cs, fixture.co, 'submit-extracted-section')
    assert fixture.cs.read(saved['result']['plan_ref'])['payload']['sections'] == view['plan']['sections']


@pytest.mark.parametrize('field', ['text', 'extraction', 'sources'])
def test_small_section_tool_rejects_model_authored_extraction_outputs(draft_case, field):
    fixture = draft_case
    section = attach_text_fixture(fixture)
    section[field] = {'selection': fixture.selection} if field == 'extraction' else [] if field == 'sources' else 'Invented text.'
    with pytest.raises(ActionRejected, match='SECTION_OUTPUT_IS_SYSTEM_OWNED'):
        planning().save_item(fixture.cs, fixture.co, 'inject-output-' + field, 'section', section)


@pytest.mark.parametrize('gate', ['save', 'approval', 'word-export', 'excel-export'])
def test_extraction_proof_is_rechecked_at_downstream_authority(draft_case, gate):
    fixture = draft_case
    section = attach_text_fixture(fixture)
    view = save_draft_parts(fixture, sections=[fixture.plan['sections'][0], section])
    plan = deepcopy(view['plan'])
    target = next(s for s in plan['sections'] if s['section_id'] == '5')
    target['extraction']['text'] = target['text'] = 'Forged normalized body.'
    if gate != 'save':
        plan = api().CommissionPlan.model_validate(plan).model_dump()
        bundle = saved_historical_bundle(fixture, plan, answered=gate != 'approval')
    with pytest.raises(ActionRejected) as exc:
        if gate == 'save':
            save(fixture, plan)
        elif gate == 'approval':
            api().reply(fixture.ws, bundle.issue_id, bundle.decision)
        elif gate == 'word-export':
            from report_agent.content_export import export_snapshot
            export_snapshot(fixture.cs, fixture.co, 'forged-text-word', bundle.snapshot_ref)
        else:
            from report_agent.content_workbook import export_workbook
            export_workbook(fixture.cs, fixture.co, 'forged-text-excel', bundle.snapshot_ref,
                [{'name': 'Records', 'table_ref': bundle.table_ref}])
    assert_gap_exception(exc, fixture)
    assert any('extraction' in g['path'] for g in exc.value.diagnostic['gaps'])


@pytest.fixture
def resolution_case(anchored):
    from io import BytesIO
    from docx import Document
    fixture = anchored
    doc = Document()
    doc.add_heading('4 Assessment', level=1)
    doc.add_table(rows=1, cols=1).cell(0, 0).text = 'Retain this table-contained instruction for structural review.'
    output = BytesIO(); doc.save(output)
    outline = capture(fixture, 'operator-outline.docx', output.getvalue(), 'operator-outline')
    requirements().install_requirements(fixture.cs, fixture.scope_ref, outline)
    enable_h2(fixture)
    record = requirements().read_requirements(fixture.cs)
    fixture.parse_anchor = next(a for a in record['payload']['anchors'] if a.get('parse_error'))
    planning().install_classifications(fixture.cs, [{'anchor_id': fixture.parse_anchor['id'],
        'entry_ids': [], 'capabilities': [], 'table_roles': []}], 'The body instruction has no calculation obligation; structure still requires owner review.')
    fixture.before_resolution = requirements().read_requirements(fixture.cs)
    fixture.checkpoint = planning().request_requirements_checkpoint(fixture.ws)
    fixture.resolution = {'decision': 'resolve_requirements',
        'requirements_ref': fixture.checkpoint['requirements_ref'],
        'resolutions': [{'anchor_id': fixture.parse_anchor['id'],
            'note': 'Reviewed the table-contained instruction; preserve it and confirm no section heading is hidden.'}]}
    return fixture


def test_requirements_owner_redo_after_case_save(resolution_case, monkeypatch):
    from report_agent import commission_assertions
    f = resolution_case
    issue_id = f.checkpoint['issue_id']
    assert commission_assertions.checkpoint(f.ws.store, 'requirements', issue_id)['requirements_ref'] == f.before_resolution['ref']
    assert f.ws.store.get('commission_requirements_checkpoint:' + issue_id) is None
    with monkeypatch.context() as patch:
        def interrupt(*args):
            raise RuntimeError('interrupted before owner answer')
        patch.setattr(commission_assertions, 'answer_checkpoint', interrupt)
        with pytest.raises(RuntimeError, match='interrupted before owner answer'):
            api().reply(f.ws, issue_id, f.resolution)
    pending = [r for r in f.cs.list_objects('CommissionRequirements') if r['owner_id'] == 'operator']
    assert len(pending) == 1
    assert requirements().read_requirements(f.cs)['ref'] == f.before_resolution['ref']
    assert not next(i for i in issue_state.get_report_issues(f.ws.store) if i['id'] == issue_id)['resolved']
    issue = api().reply(f.ws, issue_id, f.resolution)
    assert issue['requirements_result_ref'] == pending[0]['ref']
    assert commission_assertions.checkpoint_answer(f.ws.store, 'requirements', issue_id) == pending[0]['ref']
    assert api().reply(f.ws, issue_id, f.resolution) == issue


def test_owner_parse_resolution_preserves_sources_and_does_not_approve_plan(resolution_case):
    fixture = resolution_case
    for status in ('required', 'not_applicable'):
        with pytest.raises(ActionRejected):
            planning().set_requirement_status(fixture.cs, fixture.co, 'agent-parse-' + status,
                fixture.parse_anchor['id'], status, 'Agent cannot settle structural uncertainty.')
    issue = api().reply(fixture.ws, fixture.checkpoint['issue_id'], fixture.resolution)
    record = requirements().read_requirements(fixture.cs)
    assert record['ref'] == issue['requirements_result_ref'] != fixture.before_resolution['ref']
    for field in ('anchors', 'source_pins'):
        assert record['payload'][field] == fixture.before_resolution['payload'][field]
    assert record['payload']['parse_resolutions'][fixture.parse_anchor['id']] == {
        'origin': 'operator', 'issue_id': fixture.checkpoint['issue_id'],
        'note': fixture.resolution['resolutions'][0]['note']}
    assert api().reply(fixture.ws, fixture.checkpoint['issue_id'], fixture.resolution) == issue
    assert requirements().read_requirements(fixture.cs)['ref'] == record['ref']
    assert not fixture.cs.list_objects('CommissionDecision')
    assert plan_authority.decision_ref(fixture.ws.store) is None
    assert requirements().check_plan(fixture.cs, {'requirements_ref': record['ref']}, record['ref'])
    changed = deepcopy(fixture.resolution)
    changed['resolutions'][0]['note'] = 'A different decision is not the old receipt.'
    with pytest.raises(ActionRejected, match='ALREADY_ANSWERED'):
        api().reply(fixture.ws, fixture.checkpoint['issue_id'], changed)


@pytest.mark.parametrize('fault', ['stale-ref', 'unknown-anchor', 'duplicate-anchor', 'blank-note', 'wrong-classification-target'])
def test_requirement_resolution_rejects_unbound_owner_payload(resolution_case, fault):
    fixture = resolution_case
    decision = deepcopy(fixture.resolution)
    item = decision['resolutions'][0]
    if fault == 'stale-ref':
        decision['requirements_ref']['version'] += 1
    elif fault == 'unknown-anchor':
        item['anchor_id'] = 'not-in-this-source'
    elif fault == 'duplicate-anchor':
        decision['resolutions'].append(deepcopy(item))
    elif fault == 'blank-note':
        item['note'] = '   '
    else:
        item['classification'] = {'anchor_id': 'different-anchor', 'entry_ids': [], 'capabilities': [], 'table_roles': []}
    with pytest.raises((ActionRejected, ValueError)):
        api().reply(fixture.ws, fixture.checkpoint['issue_id'], decision)
    assert requirements().read_requirements(fixture.cs)['ref'] == fixture.before_resolution['ref']
    assert not next(i for i in issue_state.get_report_issues(fixture.ws.store) if i['id'] == fixture.checkpoint['issue_id'])['resolved']


def test_unknown_requirement_needs_explicit_owner_classification(resolution_case):
    fixture = resolution_case
    unknown = next(a for a in fixture.before_resolution['payload']['anchors']
        if a['id'] not in fixture.before_resolution['payload'].get('classifications', {}))
    decision = deepcopy(fixture.resolution)
    decision['resolutions'] = [{'anchor_id': unknown['id'], 'note': 'Reviewed this ordinary descriptive requirement.'}]
    with pytest.raises(ActionRejected, match='CLASSIFICATION_REQUIRED'):
        api().reply(fixture.ws, fixture.checkpoint['issue_id'], decision)
    decision['resolutions'][0]['classification'] = {'anchor_id': unknown['id'],
        'entry_ids': [], 'capabilities': ['source_priority'], 'table_roles': []}
    result = api().reply(fixture.ws, fixture.checkpoint['issue_id'], decision)
    record = requirements().read_requirements(fixture.cs)
    classified = record['payload']['classifications'][unknown['id']]
    assert classified['origin'] == 'operator' and classified['issue_id'] == result['id']
    assert classified['capabilities'] == ['source_priority']
    assert next(i for i in record['payload']['items'] if i['anchor_id'] == unknown['id'])['status'] == 'unresolved'
    assert plan_authority.decision_ref(fixture.ws.store) is None


def test_requirement_reply_sidecar_exposes_exact_pending_sources_and_unapproved_shape(resolution_case):
    import json
    fixture = resolution_case
    path = fixture.ws.store.root / fixture.checkpoint['brief_path']
    sidecar = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    assert sidecar['issue_id'] == fixture.checkpoint['issue_id']
    assert sidecar['requirements_ref'] == fixture.before_resolution['ref']
    pending = {a['anchor_id']: a for a in sidecar['pending']}
    assert set(pending) == set(fixture.checkpoint['anchor_ids'])
    for anchor in fixture.before_resolution['payload']['anchors']:
        if anchor['id'] in pending:
            assert pending[anchor['id']]['source'] == anchor['source']
    assert sidecar['decision_shape']['requirements_ref'] == sidecar['requirements_ref']
    assert sidecar['decision_shape']['decision'] == 'resolve_requirements'
    assert 'approved' not in sidecar['decision_shape']
    assert 'commission-reply' in sidecar['reply_command'] and sidecar['issue_id'] in sidecar['reply_command']
    with pytest.raises(ValueError):
        planning().RequirementDecision.model_validate(sidecar['decision_shape'])


@pytest.mark.parametrize('resolve_all', [True, False])
async def test_native_requirement_checkpoint_resume_keeps_original_issue_and_decision(resolution_case, resolve_all):
    import json
    from langchain_core.messages import AIMessage
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver, call, observation, run, snapshot
    fixture = resolution_case
    current_native_profiles(fixture)
    first = Driver(coordinator=[AIMessage(content='', tool_calls=[
        call('request_requirement_resolution', {}, 'owner-requirement-call')])])
    result = await run(fixture.ws, first)
    assert result['status'] == 'needs_human' and len(first.calls) == 1, result
    pending = await snapshot(fixture.ws, first)
    issue_id = pending.interrupts[0].value['issue_id']
    checkpoint = planning().commission_assertions.checkpoint(fixture.ws.store, 'requirements', issue_id)
    record = requirements().read_requirements(fixture.cs)
    selected = checkpoint['anchor_ids'] if resolve_all else [fixture.parse_anchor['id']]
    resolutions = []
    for identity in selected:
        anchor = next(a for a in record['payload']['anchors'] if a['id'] == identity)
        item = {'anchor_id': identity, 'note': 'Owner reviewed this exact synthetic source requirement.'}
        if identity not in record['payload'].get('classifications', {}):
            item['classification'] = {'anchor_id': identity, 'entry_ids': [],
                'capabilities': ['section'] if anchor['kind'] == 'section' else [], 'table_roles': []}
        resolutions.append(item)
    decision = {'decision': 'resolve_requirements', 'requirements_ref': checkpoint['requirements_ref'],
        'resolutions': resolutions}
    answered = api().reply(fixture.ws, issue_id, decision)
    issue_ids = [i['id'] for i in issue_state.get_report_issues(fixture.ws.store)]

    def after_owner(messages):
        observed = observation(messages, 'request_requirement_resolution')
        delivered = observed.get('issue', observed)
        assert delivered['id'] == issue_id, observed
        exact = observed.get('human_decision', delivered.get('decision'))
        assert json.loads(exact) == json.loads(answered['decision'])
        return AIMessage(content='The exact requirement decision was observed; no report plan is approved.')

    reopened = Workspace(Store(fixture.ws.store.root))
    fresh = Driver(coordinator=[None, after_owner])
    resumed = await run(reopened, fresh)
    assert resumed['last_error'] is None, resumed
    assert len(fresh.calls) == 1
    # H3.3 refuses this deliberate final answer without a report-plan approval;
    # the original requirement checkpoint and its delivered decision remain intact.
    completion = reopened.store.get('commission_planning_completion_wait')
    assert completion and completion['issue_id'] not in issue_ids
    issues = issue_state.get_report_issues(reopened.store)
    assert [i['id'] for i in issues] == [*issue_ids, completion['issue_id']]
    original = next(i for i in issues if i['id'] == issue_id)
    assert original['decision'] == answered['decision'] and original['decision_origin'] == 'operator'
    assert planning().commission_assertions.checkpoint(reopened.store, 'requirements', issue_id) == checkpoint
    assert requirements().requirements_ref(reopened.store) == answered['requirements_result_ref']
    final_wait = await snapshot(reopened, fresh)
    assert resumed['status'] == 'needs_human'
    assert final_wait.interrupts[0].value['issue_id'] == completion['issue_id']
    assert final_wait.interrupts[0].value['kind'] == 'planning_completion'
    assert plan_authority.decision_ref(reopened.store) is None


def guard():
    return import_module('report_agent.planning_guard')


def reject_planning(fixture, identity, *, tool='add_section', code='SYNTHETIC_SCHEMA_REJECTED'):
    return guard().record_planning_result(fixture.ws, 'coordinator', tool, identity,
        rejected=True, error_code=code)


def test_planning_counter_persists_deduplicates_and_only_real_edit_resets(draft_case):
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    fixture = draft_case
    assert reject_planning(fixture, 'rejected-1')['consecutive_rejections'] == 1
    assert reject_planning(fixture, 'rejected-1')['consecutive_rejections'] == 1
    fixture.ws = Workspace(Store(fixture.ws.store.root))
    assert reject_planning(fixture, 'rejected-2')['consecutive_rejections'] == 2
    for tool, changed in [('read_planning_draft', True), ('add_section', False)]:
        result = guard().record_planning_result(fixture.ws, 'coordinator', tool, 'non-reset-' + tool,
            rejected=False, changed=changed)
        assert result['consecutive_rejections'] == 2
    result = guard().record_planning_result(fixture.ws, 'coordinator', 'add_section', 'real-edit',
        rejected=False, changed=True)
    assert result['consecutive_rejections'] == 0 and not result['waiting']
    assert reject_planning(fixture, 'rejected-3')['consecutive_rejections'] == 1
    assert guard().record_planning_result(fixture.ws, 'coordinator', 'add_section', 'real-edit',
        rejected=False, changed=True)['consecutive_rejections'] == 1


def test_fifth_rejection_latches_until_exact_owner_resume_even_with_valid_sibling(draft_case):
    fixture = draft_case
    for number in range(5):
        state = reject_planning(fixture, 'reject-' + str(number))
    assert state['waiting'] and state['consecutive_rejections'] == 5
    issue_id = state['issue_id']
    sibling = guard().record_planning_result(fixture.ws, 'coordinator', 'add_object', 'valid-sibling',
        rejected=False, changed=True)
    assert sibling['waiting'] and sibling['consecutive_rejections'] == 5
    fixture.ws.decide_issue(issue_id, 'Generic issue resolution is not planning resume.', resolved=True)
    assert fixture.ws.store.get(guard().KEY)['waiting']
    with pytest.raises(ActionRejected):
        api().reply(fixture.ws, 'another-issue', {'decision': 'resume_planning', 'note': 'Reviewed.'})
    with pytest.raises(ActionRejected):
        api().reply(fixture.ws, issue_id, {'decision': 'resume_planning', 'note': ' '})
    decision = {'decision': 'resume_planning', 'note': 'Reviewed the five preserved failures; retry corrected planning.'}
    receipt = api().reply(fixture.ws, issue_id, decision)
    assert receipt['decision_origin'] == 'operator'
    assert not fixture.ws.store.get(guard().KEY)['waiting']
    assert fixture.ws.store.get(guard().KEY)['consecutive_rejections'] == 0
    assert api().reply(fixture.ws, issue_id, decision) == receipt
    assert reject_planning(fixture, 'next-error')['consecutive_rejections'] == 1


def test_counter_ignores_nonplanning_and_other_roles(draft_case):
    fixture = draft_case
    reject_planning(fixture, 'one-error')
    guard().record_planning_result(fixture.ws, 'writer', 'add_section', 'writer-error', rejected=True)
    guard().record_planning_result(fixture.ws, 'coordinator', 'read_source_page', 'read-error', rejected=True)
    assert fixture.ws.store.get(guard().KEY)['consecutive_rejections'] == 1


def current_native_profiles(fixture):
    import json
    from pathlib import Path
    profiles = json.loads((Path(__file__).resolve().parents[1] / 'config/current.json').read_text())['manifest_profiles']
    fixture.ws.store.set('manifest', {**fixture.ws.store.manifest, **profiles,
        'commission_planning_contract': 'commission-planning-v1', 'synthetic': True})


def native_rejections(*, sibling=False):
    from langchain_core.messages import AIMessage
    from test_deep_runtime import call
    malformed = lambda identity: AIMessage(content='', invalid_tool_calls=[{
        'name': 'add_section', 'id': identity, 'args': '{', 'error': 'Incomplete JSON'}])
    scripts = [malformed('bad-json-1'),
        AIMessage(content='', tool_calls=[call('add_section', {}, 'missing-schema-2')]),
        AIMessage(content='', tool_calls=[call('set_requirement_status', {'items': [{'anchor_id': 'not-in-source',
            'status': 'required', 'interpretation': 'This identity is deliberately invalid.'}]}, 'domain-3')]),
        malformed('bad-json-4')]
    final = malformed('bad-json-5')
    if sibling:
        final.tool_calls.append(call('add_question', {'items': [{'question_id': 'sibling',
            'text': 'A valid sibling must not reset an already reached cap.', 'resolved': False}]}, 'valid-sibling'))
    return [*scripts, final]


@pytest.mark.parametrize('sibling', [False, True])
async def test_native_mixed_rejections_stop_before_sixth_model_call_and_survive_reopen(draft_case, sibling, monkeypatch):
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.messages import ToolMessage
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver, run, snapshot
    fixture = draft_case
    current_native_profiles(fixture)
    summary_checks = []

    class SummaryBoundaryProbe(AgentMiddleware):
        async def abefore_model(self, state, runtime):
            waiting = fixture.ws.store.get(guard().KEY, {}).get('waiting', False)
            summary_checks.append(waiting)
            assert not waiting, 'A summary could start after the planning wait was latched.'

    # Test middleware ordering at the summary invocation boundary, without sending
    # a summary request or modifying either planning enforcement middleware.
    summary_module = import_module('report_agent.working_summary')
    monkeypatch.setattr(summary_module, 'working_summary', lambda *args, **kwargs: SummaryBoundaryProbe())
    driver = Driver(coordinator=native_rejections(sibling=sibling))
    result = await run(fixture.ws, driver)
    assert result['status'] == 'needs_human' and result['last_error'] is None, result
    assert len(driver.calls) == 5
    assert summary_checks and not any(summary_checks)
    state = fixture.ws.store.get(guard().KEY)
    assert state['waiting'] and state['consecutive_rejections'] == 5
    saved = await snapshot(fixture.ws, driver)
    assert saved.interrupts and saved.interrupts[0].value['issue_id'] == state['issue_id']
    import json
    reply = json.loads((fixture.ws.store.root / 'outputs' / ('planning-resume-' + state['issue_id'] + '.json')).read_text())
    assert reply['issue_id'] == state['issue_id'] and reply['consecutive_rejections'] == 5
    assert reply['decision_shape'] == {'decision': 'resume_planning', 'note': ''}
    assert state['issue_id'] in reply['reply_command'] and 'commission-reply' in reply['reply_command']
    feedback = {message.tool_call_id: message for message in saved.values['messages'] if isinstance(message, ToolMessage)}
    for identity in ('bad-json-1', 'missing-schema-2', 'domain-3', 'bad-json-4', 'bad-json-5'):
        assert feedback[identity].status == 'error', (identity, feedback)
    assert 'INVALID_TOOL_ARGUMENT_JSON' in feedback['bad-json-1'].content
    assert 'not-in-source' in feedback['domain-3'].content or 'ANCHOR' in feedback['domain-3'].content
    reopened = Workspace(Store(fixture.ws.store.root))
    fresh = Driver(coordinator=[])
    waiting = await run(reopened, fresh)
    assert waiting['status'] == 'needs_human' and fresh.calls == []
    assert reopened.store.get(guard().KEY)['consecutive_rejections'] == 5


async def test_raw_graph_resume_cannot_authorize_a_planning_wait(draft_case):
    from langgraph.types import Command
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, run
    fixture = draft_case
    current_native_profiles(fixture)
    first = Driver(coordinator=native_rejections())
    assert (await run(fixture.ws, first))['status'] == 'needs_human'
    state = fixture.ws.store.get(guard().KEY)
    fresh = Driver(coordinator=[])
    async with deep_runtime.project_agent(fixture.ws, fresh) as agent:
        with pytest.raises(ActionRejected, match='PLANNING_OPERATOR_RESUME_REQUIRED'):
            await agent.ainvoke(Command(resume='An untrusted raw graph value.'),
                {'configurable': {'thread_id': 'report'}})
    assert fresh.calls == []
    assert fixture.ws.store.get(guard().KEY)['waiting']
    assert fixture.ws.store.get(guard().KEY)['issue_id'] == state['issue_id']


async def test_native_real_edit_resets_but_read_and_same_value_edit_do_not(draft_case):
    from langchain_core.messages import AIMessage
    from test_deep_runtime import Driver, call, run
    fixture = draft_case
    current_native_profiles(fixture)
    question = {'question_id': 'known', 'text': 'A genuinely saved planning edit.', 'resolved': False}
    error = lambda identity: AIMessage(content='', tool_calls=[call('add_section', {}, identity)])
    write = lambda identity: AIMessage(content='', tool_calls=[call('add_question', {'items': [question]}, identity)])
    scripts = [error('before-1'), error('before-2'), write('actual-edit'),
        error('after-1'), error('after-2'), write('same-value'),
        AIMessage(content='', tool_calls=[call('read_planning_draft', {}, 'read-only')]),
        error('after-3'), error('after-4'), error('after-5')]
    driver = Driver(coordinator=scripts)
    result = await run(fixture.ws, driver)
    assert result['status'] == 'needs_human' and result['last_error'] is None, result
    assert len(driver.calls) == len(scripts) == 10
    assert fixture.ws.store.get(guard().KEY)['consecutive_rejections'] == 5
    view = planning().read_draft(fixture.cs, fixture.co)
    assert view['revision'] == 1 and view['plan']['open_questions'] == [question['text']]


def test_header_order_page_numbers_and_fixed_source_views_share_exact_normalization(draft_case):
    fixture = draft_case
    pages = ['SYNTHETIC HEADER\n11\nStart sentence.\n\n4.1 Numbered heading\n\nA wrapped line\ncontinues.\nSYNTHETIC FOOTER',
        'SYNTHETIC HEADER\n12\n(1) Preserve list heading\n\n12\n\nEnd sentence.\nSYNTHETIC FOOTER']
    ref = paginated_source(fixture, 'header-number-pages', pages)
    profile = {'id': 'header-order-v1', 'source_ref': ref,
        'file_digest': fixture.cs.read(ref)['payload']['file_digest'],
        'header_lines': ['SYNTHETIC HEADER'], 'footer_lines': ['SYNTHETIC FOOTER'],
        'page_number_offset': 10, 'page_number_position': 'header', 'join_lines': 'paragraph'}
    planning().install_text_profile(fixture.cs, profile)
    selection = {'source_ref': ref, 'start_page': 1, 'end_page': 2,
        'start_sentence': 'Start sentence.', 'end_sentence': 'End sentence.', 'profile_id': profile['id']}
    section = deepcopy(fixture.plan['sections'][1])
    for field in ('sources', 'text', 'extraction'):
        section.pop(field, None)
    section.update(kind='fixed', source_span=selection, derived_from=[], rule='', result_bindings=[],
        source_views=[{'source_indexes': [1], 'page': 2, 'crop': [0.0, 0.0, 1.0, 1.0]}])
    planning().save_item(fixture.cs, fixture.co, 'header-view-section', 'section', section)
    value = planning().read_draft(fixture.cs, fixture.co)['plan']['sections'][0]
    expected = 'Start sentence.\n\n4.1 Numbered heading\n\nA wrapped line continues.\n\n(1) Preserve list heading\n\n12\n\nEnd sentence.'
    assert value['text'] == api().fixed_section_text(value) == expected
    view = api().fixed_source_views(value)[0]
    assert view['text'] == '(1) Preserve list heading\n\n12\n\nEnd sentence.'
    assert value['text'].count(view['text']) == 1
    assert value['sources'][1]['quote'].startswith('SYNTHETIC HEADER\n12\n')
    assert value['extraction']['normalization']['profile']['page_number_position'] == 'header'


async def test_current_native_planning_wire_has_small_inputs_and_no_operator_authority(draft_case):
    from langchain_core.messages import AIMessage
    from test_deep_runtime import Driver, call, run
    fixture = draft_case
    current_native_profiles(fixture)
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[
        call('read_planning_draft', {'collection': 'requirements', 'full': True}, 'read-small-contract')]), AIMessage(content='Synthetic schema inspection complete.')])
    result = await run(fixture.ws, driver)
    assert result['last_error'] is None, result
    from test_deep_runtime import observation
    import json
    tail = driver.calls[-1][2][-1].content
    packet = json.loads(tail.split('\n', 1)[1])
    assert packet['current_state']['planning_ids'] == planning().planning_ids(fixture.cs)
    view = observation(driver.calls[-1][2], 'read_planning_draft')
    assert view['full_read']['complete'] and view['page_data']['complete_page'], view
    schemas = {s['name']: s for batch in driver.bindings['coordinator'] for s in batch}
    expected = {'read_planning_draft', 'set_requirement_status', 'link_convention', 'set_scope_boundary',
        'add_section', 'add_object', 'add_substitution', 'add_reconciliation', 'add_question',
        'set_planning_details', 'submit_plan', 'request_requirement_resolution'}
    assert expected <= schemas.keys()
    assert not ({'save_commission_plan', 'propose_commission_requirements', 'reply_requirements',
        'resume_planning', 'install_classifications', 'install_reviewed_entries', 'install_text_profile'} & schemas.keys())
    assert 'capabilities' not in schemas['set_requirement_status']['parameters']['properties']['items']['items']['properties']
    for name in ('set_requirement_status', 'add_section', 'add_object', 'add_reconciliation', 'add_question'):
        assert set(schemas[name]['parameters']['properties']) == {'items'}
    section = schemas['add_section']['parameters']['properties']['items']['items']['properties']
    assert {'section_id', 'outline_anchor_id', 'source_span'} <= section.keys()
    assert not {'text', 'extraction', 'method_pack', 'table_specs'} & section.keys()
    assert 'operation_id' not in section  # Current native runtime owns operation identity.


@pytest.mark.parametrize('fault', ['unknown-capability', 'duplicate-capability', 'ordinary-table-role'])
def test_classification_contract_rejects_unreviewed_capability_or_role_payload(entries, fault):
    fixture = entries
    enable_h2(fixture)
    before = requirements().read_requirements(fixture.cs)['ref']
    value = {'anchor_id': fixture.weight_anchor['id'], 'entry_ids': [],
        'capabilities': ['source_priority'], 'table_roles': []}
    if fault == 'unknown-capability':
        value['capabilities'] = ['arbitrary.new.capability']
    elif fault == 'duplicate-capability':
        value['capabilities'] *= 2
    else:
        value['table_roles'] = ['evaluation']
    with pytest.raises((ActionRejected, ValueError)):
        planning().install_classifications(fixture.cs, [value], 'Invalid classification must not become authoritative.')
    assert requirements().read_requirements(fixture.cs)['ref'] == before


@pytest.mark.parametrize('fifth_kind', ['malformed-json', 'schema', 'domain'])
async def test_fifth_rejection_blocks_paid_sibling_until_typed_owner_resume(draft_case, monkeypatch, fifth_kind):
    from langchain_core.messages import AIMessage, ToolMessage
    from report_agent import deep_runtime
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver, call, run, snapshot
    fixture = draft_case
    current_native_profiles(fixture)
    starts = []

    async def offline_analysis(*args, **kwargs):
        starts.append('helper-started')
        return {'operation': 'synthetic-helper', 'analysis': 'Offline recording stub.',
            'evidence': [{'kind': 'synthetic_test', 'observation': {}}], 'usage': None}

    monkeypatch.setattr(deep_runtime, 'analyze_selected_evidence', offline_analysis)
    scripts = native_rejections()
    if fifth_kind == 'schema':
        scripts[-1] = AIMessage(content='', tool_calls=[call('add_section', {}, 'fifth-reject')])
    elif fifth_kind == 'domain':
        scripts[-1] = AIMessage(content='', tool_calls=[call('set_requirement_status', {'items': [{
            'anchor_id': 'missing-final-anchor', 'status': 'required',
            'interpretation': 'This is a source-bound domain rejection.'}]}, 'fifth-reject')])
    else:
        scripts[-1].invalid_tool_calls[0]['id'] = 'fifth-reject'
    source_id = fixture.cs.read(fixture.scope_ref)['payload']['source_id']
    scripts[-1].tool_calls.append(call('analyze_text', {'source_id': source_id,
        'purpose': 'An optional analysis must wait behind the reached planning cap.'}, 'paid-sibling'))
    driver = Driver(coordinator=scripts)
    paused = await run(fixture.ws, driver)
    assert paused['status'] == 'needs_human' and paused['last_error'] is None, paused
    assert starts == [] and len(driver.calls) == 5
    state = fixture.ws.store.get(guard().KEY)
    assert state['waiting'] and state['consecutive_rejections'] == 5
    saved = await snapshot(fixture.ws, driver)
    feedback = {m.tool_call_id: m for m in saved.values['messages'] if isinstance(m, ToolMessage)}
    for identity in ('bad-json-1', 'missing-schema-2', 'domain-3', 'bad-json-4', 'fifth-reject'):
        assert identity in feedback and feedback[identity].status == 'error', (identity, feedback)
    reopened = Workspace(Store(fixture.ws.store.root))
    quiet = Driver(coordinator=[])
    assert (await run(reopened, quiet))['status'] == 'needs_human'
    assert starts == [] and quiet.calls == []
    assert reopened.store.get(guard().KEY)['issue_id'] == state['issue_id']
    api().reply(reopened, state['issue_id'], {'decision': 'resume_planning',
        'note': 'Reviewed the errors and explicitly permit the queued optional analysis to continue.'})
    resumed_driver = Driver(coordinator=[None] * 5 + [AIMessage(content='The queued offline helper completed after explicit resume.')])
    resumed = await run(reopened, resumed_driver)
    assert resumed['last_error'] is None, resumed
    assert starts == ['helper-started'] and len(resumed_driver.calls) == 1
    assert not reopened.store.get(guard().KEY)['waiting']


def test_planning_item_batch_is_atomic_and_pins_the_whole_request(draft_case):
    fixture = draft_case
    items = [dict(question_id='batch-a', text='Check first source.', resolved=False),
             dict(question_id='batch-b', text='Check second source.', resolved=False)]
    result = planning().save_items(fixture.cs, fixture.co, 'question-batch', 'question', items)
    saved = planning().read_draft(fixture.cs, fixture.co)
    assert saved['plan']['open_questions'] == [item['text'] for item in items]
    assert planning().save_items(fixture.cs, fixture.co, 'question-batch', 'question', deepcopy(items)) == result
    with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
        planning().save_items(fixture.cs, fixture.co, 'question-batch', 'question',
            items + [dict(question_id='batch-c', text='An appended item.', resolved=False)])
    assert planning().read_draft(fixture.cs, fixture.co) == saved


def test_planning_item_batch_reports_each_bad_index_and_rolls_back_prefix(draft_case):
    fixture = draft_case
    before = planning().read_draft(fixture.cs, fixture.co)
    items = [dict(question_id='batch-a', text='A valid prefix.', resolved=False),
             dict(question_id='batch-b', text='', resolved=False),
             dict(question_id='batch-c', text='Wrong resolved type.', resolved='yes'),
             dict(question_id='batch-a', text='Duplicate ID.', resolved=False)]
    with pytest.raises(ActionRejected) as exc:
        planning().save_items(fixture.cs, fixture.co, 'bad-question-batch', 'question', items)
    assert {error['index'] for error in exc.value.diagnostic['items']} == {1, 2, 3}
    assert planning().read_draft(fixture.cs, fixture.co) == before


def test_requirement_status_batch_preserves_unmentioned_items_and_rejects_prefix(draft_case):
    fixture = draft_case
    before, by_id = current_items(fixture)
    chosen = list(by_id)[:2]
    items = [dict(anchor_id=identity, status=by_id[identity]['status'], interpretation='Current source interpretation.')
             for identity in chosen]
    result = planning().set_requirement_statuses(fixture.cs, fixture.co, 'status-batch', items)
    after, updated = current_items(fixture)
    assert after['ref'] == result['result']['requirements_ref']
    assert all(updated[key] == by_id[key] for key in by_id if key not in chosen)
    assert all(updated[key]['interpretation'] == 'Current source interpretation.' for key in chosen)
    assert planning().set_requirement_statuses(fixture.cs, fixture.co, 'status-batch', deepcopy(items)) == result
    bad = [dict(items[0], interpretation='This must roll back.'),
           dict(items[1], anchor_id='missing-one'), dict(items[1], anchor_id='missing-two')]
    with pytest.raises(ActionRejected) as exc:
        planning().set_requirement_statuses(fixture.cs, fixture.co, 'bad-status-batch', bad)
    assert {error['index'] for error in exc.value.diagnostic['items']} == {1, 2}
    assert requirements().read_requirements(fixture.cs) == after


@pytest.mark.parametrize('collection', ['requirements', 'objects', 'sections', 'questions', 'reconciliations'])
def test_full_collection_uses_exact_view_and_outer_result_allowance(draft_case, collection):
    import json
    f = draft_case
    planning().save_item(f.cs, f.co, 'full-read-question', 'question',
        {'question_id': 'full-read', 'text': 'Synthetic question', 'resolved': False})
    checked = []
    def fits(result):
        checked.append(deepcopy(result))
        return True
    value = planning().read_draft_page(f.cs, f.co, collection, full=True, result_fits=fits)
    assert checked == [value], 'Measure the entire returned envelope, including escaped text.'
    assert value['full_read'] == {'complete': True}
    data = value['page_data']
    assert data['complete_page'] and data['next_page'] is data['next_offset'] is None
    assert len(json.loads(data['text'])) == value['counts'][collection] == data['total_items']
    fallback = planning().read_draft_page(f.cs, f.co, collection, full=True, result_fits=lambda _: False)
    assert fallback['full_read'] == {'complete': False, 'reason': 'PLANNING_COLLECTION_EXCEEDS_OBSERVATION_ALLOWANCE'}
    assert fallback['page_data'] == planning().read_draft_page(f.cs, f.co, collection)['page_data']
    planning().save_item(f.cs, f.co, 'change-full-read', 'question',
        {'question_id': 'full-read', 'text': 'Changed synthetic question', 'resolved': False})
    with pytest.raises(ActionRejected, match='PLANNING_VIEW_CHANGED'):
        planning().read_draft_page(f.cs, f.co, collection, view_ref=value['view_ref'], full=True, result_fits=fits)


def test_planning_ids_follow_draft_and_pin_published_binding_ids(draft_case):
    f = draft_case
    before = planning().planning_ids(f.cs)
    assert before['draft']['objects'] == before['draft']['sections'] == []
    assert before['published'] is None
    assert {r['id'] for r in before['draft']['indicators']} == {r['id'] for r in f.plan['method_pack']['indicators']}
    saved = save_draft_parts(f)
    current = planning().planning_ids(f.cs)
    assert current['draft']['revision'] == saved['revision']
    assert current['draft']['objects'] == [{'id': o['object_id'], 'label': o['label']} for o in saved['plan']['objects']]
    published = planning().submit_plan(f.cs, f.co, 'ids-publish')['result']['plan_ref']
    pinned = planning().planning_ids(f.cs)
    assert pinned['published'] == {'plan_ref': published, 'same_as_draft': True}
    obj = deepcopy(f.plan['objects'][0]); obj['label'] = 'Updated synthetic label'
    planning().save_item(f.cs, f.co, 'ids-revise', 'object', obj)
    changed = planning().planning_ids(f.cs)
    assert changed['draft']['objects'][0]['label'] == obj['label']
    assert changed['published']['plan_ref'] == published
    assert changed['published']['objects'][0]['label'] != obj['label']
    assert 'source' not in encode(changed) and 'attributes' not in encode(changed)


def test_numeric_warnings_are_record_local_literal_checks():
    from report_agent.planning_inputs import numeric_literal_warnings
    value = {'objects': [
        {'label': 'Quoted 18%, 1200 and 30°', 'sources': [{'quote': '１８.００％，１,２００；３０度'}],
         'attributes': [{'name': 'Derived', 'values': [{'value': '53.13°', 'reason': 'Computed 14.6%', 'source': None}]}]},
        {'label': 'Uncited 18%', 'sources': []}],
        'reconciliations': [{'result': 'Quoted 18% but unexplained 14.6%', 'sources': [{'quote': '18%'}]}]}
    rows = numeric_literal_warnings(value)
    actual = {(r['field'], r['number']) for r in rows}
    assert actual == {('objects.0.attributes.0.values.0.value', '53.13°'),
        ('objects.0.attributes.0.values.0.reason', '14.6%'), ('objects.1.label', '18%'),
        ('reconciliations.0.result', '14.6%')}
    assert all(r['status'] == '待核' for r in rows)
    nested = numeric_literal_warnings({'source': {'quote': '18%'}, 'child': {'object_id': 'other', 'text': '18%'},
        'replacements': [{'old': '18%', 'new': '14.6%'}],
        'owner_records': [{'text': '99%'}], 'carried_items': [{'text': '88%'}]})
    assert {(r['field'], r['number']) for r in nested} == {('child.text', '18%'), ('replacements.0.new', '14.6%')}
    from report_agent.planning_inputs import requirement_numeric_warnings
    requirement_warnings = requirement_numeric_warnings({'anchors': [
        {'id': 'a', 'source': {'quote': '18%'}}, {'id': 'b', 'source': {'quote': '14.6%'}}],
        'items': [{'anchor_id': 'a', 'interpretation': '14.6%'}, {'anchor_id': 'b', 'interpretation': '14.6%'}]})
    assert [(w['field'], w['number']) for w in requirement_warnings] == [('requirements.a.interpretation', '14.6%')]
    assert numeric_literal_warnings({'text': '12, 30%', 'source': {'quote': '1,2 30'}})[-1]['number'] == '30%'
    assert numeric_literal_warnings({'text': 'Height 14.6m', 'source': {'quote': 'Height 18m'}})[0]['number'] == '14.6'
    assert not numeric_literal_warnings({'text': '10 - 15m', 'source': {'quote': '10–15m'}})
    assert numeric_literal_warnings({'text': '0.1234567890123456789012345678901',
        'source': {'quote': '0.1234567890123456789012345678902'}})


def test_numeric_warnings_reach_write_result_and_exact_owner_checkpoint(draft_case):
    import json
    f = draft_case
    save_draft_parts(f)
    item = {'reconciliation_id': 'pair-0', **deepcopy(f.plan['reconciliations'][0])}
    item['differences'].append('Unexplained 14.6%; derived 53.13° needs checking.')
    tool = next(fx for fx in planning().planning_tools(f.cs, lambda: f.co) if fx.__name__ == 'add_reconciliation')
    result = tool(operation_id='number-warning', items=[item])
    assert {'14.6%', '53.13°'} <= {r['number'] for r in result['result']['numeric_warnings']}
    audit = f.cs.receipt(f.co, 'number-warning')['response']
    assert audit['result']['items'][0]['numeric_warnings']
    assert result['result']['saved_item_ids'] == ['pair-0']
    assert 'items' not in result['result'] and 'citation_resolutions' not in result['result']
    plan_ref = planning().submit_plan(f.cs, f.co, 'number-warning-plan')['result']['plan_ref']
    checkpoint = api().request_checkpoint(f.ws)
    path = f.ws.store.root / checkpoint['brief_path']
    metadata = json.loads(path.with_suffix('.json').read_text())
    assert metadata['plan_ref'] == plan_ref
    assert {'14.6%', '53.13°'} <= {r['number'] for r in metadata['numeric_warnings']}
    assert '待核' in path.read_text() and '14.6%' in path.read_text()
    assert f.cs.read(plan_ref)['payload']['reconciliations'][0]['differences'] == item['differences']
    assert plan_authority.decision_ref(f.ws.store) is None
