"""H1 only: immutable source anchors and shared commission authority checks.

Synthetic source files exercise the real import/parser boundaries. No H2 planning
tools, auto-attachment, rejection policy, real model calls or engineering judgment.
"""
from copy import deepcopy
from importlib import import_module
from io import BytesIO
from types import SimpleNamespace
import json

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from report_agent.catalog import Catalog
from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import digest, encode
from test_m1_commission_plan import api, save, writer
from test_m1_g3_integration import method_commission, persist, persistence_input
from test_m1_g3_followup import synthetic_pilot_plan


CONTRACT = 'commission-requirements-v1'
SCOPE = '''# Synthetic commission

## 1. Objects
Assess the supplied design inventory, including S1.

## 4. Boundary
First contract K1+000-K2+000. Expected one object; retain contrary evidence.

## 5. Conventions
1. Use the supplied synthetic method for assessment.
2. Use rank-lookup weights from the supplied synthetic guideline.
3. Render both the ranking and evaluation tables.
4. Reconcile every candidate against design and survey sources.

## 6. Contacts
1. This numbered contact is not a section five convention.
'''


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import httpx
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')

    def forbidden(*args, **kwargs):
        raise AssertionError('H1_REQUIREMENTS_TEST_NETWORK_FORBIDDEN')

    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)


def requirements():
    # Allow complete RED collection before this new production module exists.
    return import_module('report_agent.commission_requirements')


def outline_bytes(*, ambiguous=False, numbered_style=False):
    doc = Document()
    if numbered_style:
        for name, style_id, level in [('Synthetic major', '2', 0), ('Synthetic minor', '3', 1)]:
            style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
            style.element.set(qn('w:styleId'), style_id)
            outline = OxmlElement('w:outlineLvl'); outline.set(qn('w:val'), str(level))
            style.element.get_or_add_pPr().append(outline)
        doc.add_paragraph('4 Assessment', style='Synthetic major')
    else:
        doc.add_heading('4 Assessment', level=1)
    doc.add_paragraph('Use the design and retained survey conflicts.')
    if ambiguous:
        doc.add_paragraph('4.1 Special instruction: preserve this normal-style subsection.')
    doc.add_paragraph('5 Conclusion', style='Synthetic minor' if numbered_style else 'Heading 1')
    doc.add_paragraph('Summarize the saved section 4 results.')
    result = BytesIO(); doc.save(result)
    return result.getvalue()


def capture(fixture, filename, data, operation):
    source_id = Catalog(fixture.ws.store).import_file(filename, data)['source']['id']
    ref = fixture.cs.import_inputs(fixture.co, operation, [source_id])['result']['source_refs'][0]
    return ref


@pytest.fixture
def anchored(method_commission):
    fixture = method_commission
    fixture.scope_ref = capture(fixture, 'synthetic-scope.md', SCOPE.encode(), 'h1-scope')
    fixture.outline_ref = capture(fixture, 'synthetic-outline.docx', outline_bytes(), 'h1-outline')
    roles = deepcopy(fixture.ws.store.get('commission_source_roles'))
    source_id = fixture.cs.read(fixture.scope_ref)['payload']['source_id']
    roles['h1-scope'] = {'id': source_id, 'purpose': 'commission'}
    fixture.ws.store.set('commission_source_roles', roles)
    return fixture


def capability_items(anchors):
    items = []
    for anchor in anchors:
        quote = anchor['source']['quote']
        if anchor['kind'] == 'section':
            capabilities = ['section']
        elif anchor['kind'] == 'scope':
            capabilities = ['scope_boundary'] if 'K1+000' in quote else ['inventory']
        elif anchor['kind'] == 'instruction':
            capabilities = []
        elif 'rank-lookup weights' in quote:
            capabilities = ['weight_binding']
        elif 'both the ranking' in quote:
            capabilities = ['table_specs']
        elif 'Reconcile every' in quote:
            capabilities = ['inventory_reconciliation']
        else:
            capabilities = ['method_pack']
        items.append({'anchor_id': anchor['id'], 'status': 'required',
            'interpretation': 'Synthetic interpretation separate from the quoted requirement.',
            'capabilities': capabilities,
            **({'table_roles': ['ranking', 'evaluation']} if 'table_specs' in capabilities else {})})
    return items


def linked_plan(fixture, ref, anchors):
    plan = synthetic_pilot_plan(fixture)
    plan['requirements_ref'] = ref
    conventions = [anchor for anchor in anchors if anchor['kind'] == 'convention']
    plan['conventions'] = [{'requirement_anchor_id': anchor['id'], 'source': anchor['source'],
        'interpretation': 'Apply this separately retained synthetic convention.'} for anchor in conventions]
    weight = next(a for a in conventions if 'rank-lookup weights' in a['source']['quote'])
    plan['method_conventions'][0]['source'] = weight['source']
    boundary = next(a for a in anchors if a['kind'] == 'scope' and 'K1+000' in a['source']['quote'])
    plan['scope_boundary'] = {'start_meter': '1000', 'end_meter': '2000',
        'source': boundary['source'], 'expected_object_count': 1}
    for section in plan['sections']:
        anchor = next(a for a in anchors if a['kind'] == 'section' and a['section_id'] == section['section_id'])
        section['outline'] = anchor['source']
    return plan


@pytest.fixture
def required_case(anchored):
    fixture = anchored
    root = requirements().install_requirements(fixture.cs, fixture.scope_ref, fixture.outline_ref)
    record = requirements().read_requirements(fixture.cs, root)
    fixture.initial_requirements = deepcopy(record)
    fixture.items = capability_items(record['payload']['anchors'])
    proposed = requirements().propose_requirements(fixture.cs, fixture.co, 'propose-h1', root, fixture.items)
    fixture.requirements_ref = proposed['result']['requirements_ref']
    fixture.anchors = record['payload']['anchors']
    fixture.plan = linked_plan(fixture, fixture.requirements_ref, fixture.anchors)
    return fixture


def test_extracts_each_numbered_convention_scope_statement_and_word_heading(anchored):
    anchors = requirements().extract_anchors(anchored.cs, anchored.scope_ref, anchored.outline_ref)
    assert len([a for a in anchors if a['kind'] == 'convention']) == 4
    assert {a['section_id'] for a in anchors if a['kind'] == 'section'} == {'4', '5'}
    scope_quotes = [a['source']['quote'] for a in anchors if a['kind'] == 'scope']
    assert any('Assess the supplied' in quote for quote in scope_quotes)
    assert any('First contract K1+000' in quote for quote in scope_quotes)
    assert not any('numbered contact' in a['source']['quote'] for a in anchors if a['kind'] == 'convention')
    assert len({a['id'] for a in anchors}) == len(anchors)
    assert anchors == requirements().extract_anchors(anchored.cs, anchored.scope_ref, anchored.outline_ref)


def test_custom_word_heading_styles_and_normal_numbered_instruction_are_not_silently_lost(anchored):
    outline = capture(anchored, 'custom-styles.docx',
        outline_bytes(ambiguous=True, numbered_style=True), 'custom-outline')
    anchors = requirements().extract_anchors(anchored.cs, anchored.scope_ref, outline)
    assert {a['section_id'] for a in anchors if a['kind'] == 'section'} >= {'4', '5'}
    assert any('4.1 Special instruction' in a['source']['quote'] for a in anchors)
    ref = requirements().install_requirements(anchored.cs, anchored.scope_ref, outline)
    record = requirements().read_requirements(anchored.cs, ref)
    assert all(item['status'] == 'unresolved' for item in record['payload']['items'])


def test_table_contained_outline_text_is_retained_as_unresolved_instead_of_silently_skipped(anchored):
    doc = Document()
    doc.add_heading('4 Assessment', level=1)
    doc.add_paragraph('Supported body instruction.')
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).paragraphs[0].text = '4.1 Table-contained heading'
    table.cell(0, 0).paragraphs[0].style = 'Heading 2'
    table.cell(0, 0).add_paragraph('Table-contained instruction must remain visible.')
    output = BytesIO(); doc.save(output)
    ref = capture(anchored, 'table-outline.docx', output.getvalue(), 'table-outline')
    initial_ref = requirements().install_requirements(anchored.cs, anchored.scope_ref, ref)
    record = requirements().read_requirements(anchored.cs, initial_ref)
    table_anchors = [anchor for anchor in record['payload']['anchors']
        if 'table' in anchor['source']['locator']]
    text = '\n'.join(anchor['source']['quote'] for anchor in table_anchors)
    assert '4.1 Table-contained heading' in text
    assert 'Table-contained instruction must remain visible.' in text
    assert table_anchors and all(anchor.get('parse_error') for anchor in table_anchors)
    items = capability_items(record['payload']['anchors'])
    table_ids = {anchor['id'] for anchor in table_anchors}
    for item in items:
        if item['anchor_id'] in table_ids:
            item.update(status='not_applicable', interpretation='Agent attempts to dismiss unread structure.')
    with pytest.raises(ActionRejected, match='(?i)(parse|structur|unresolved)'):
        requirements().propose_requirements(anchored.cs, anchored.co, 'dismiss-table-structure', initial_ref, items)


def test_host_anchor_snapshot_is_immutable_and_initially_unresolved(required_case):
    fixture = required_case
    assert all(item['status'] == 'unresolved' for item in fixture.initial_requirements['payload']['items'])
    assert requirements().read_requirements(fixture.cs, fixture.initial_requirements['ref']) == fixture.initial_requirements
    current = requirements().read_requirements(fixture.cs)
    assert current['ref'] == fixture.requirements_ref
    assert current['payload']['anchors'] == fixture.initial_requirements['payload']['anchors']
    assert current['payload']['items'] == fixture.items


@pytest.mark.parametrize('fault', ['omit', 'duplicate', 'unknown-anchor', 'inject-source'])
def test_status_proposal_cannot_omit_or_replace_host_anchors(anchored, fault):
    root = requirements().install_requirements(anchored.cs, anchored.scope_ref, anchored.outline_ref)
    before = requirements().read_requirements(anchored.cs, root)
    items = capability_items(before['payload']['anchors'])
    if fault == 'omit':
        items.pop()
    elif fault == 'duplicate':
        items.append(deepcopy(items[0]))
    elif fault == 'unknown-anchor':
        items[0]['anchor_id'] = 'agent-invented-anchor'
    else:
        items[0]['source'] = anchored.cite('template')
    with pytest.raises((ActionRejected, ValueError)):
        requirements().propose_requirements(anchored.cs, anchored.co, 'bad-statuses', root, items)
    assert requirements().read_requirements(anchored.cs) == before


FAULTS = ('method', 'tables', 'weights', 'boundary', 'whole-group', 'unlinked-convention', 'missing-heading')


def omit(plan, fault):
    result = deepcopy(plan)
    for name in {'method': ['method_pack'], 'tables': ['table_specs'],
                 'weights': ['method_conventions'], 'boundary': ['scope_boundary'],
                 'whole-group': ['method_pack', 'table_specs', 'method_conventions', 'scope_boundary']}.get(fault, []):
        result.pop(name, None)
    if fault == 'unlinked-convention':
        result['conventions'][0].pop('requirement_anchor_id')
    elif fault == 'missing-heading':
        result['sections'] = [s for s in result['sections'] if s['section_id'] != '5']
    return result


@pytest.mark.parametrize('fault', FAULTS)
def test_independent_check_returns_source_anchored_gaps_for_each_omission(required_case, fault):
    fixture = required_case
    assert not requirements().check_plan(fixture.cs, fixture.plan, fixture.requirements_ref)
    gaps = requirements().check_plan(fixture.cs, omit(fixture.plan, fault), fixture.requirements_ref)
    assert gaps
    assert all({'anchor_id', 'path', 'code', 'message'} <= gap.keys() for gap in gaps)
    assert {g['anchor_id'] for g in gaps} <= {a['id'] for a in fixture.anchors}
    if fault == 'whole-group':
        joined = ' '.join(g['path'] for g in gaps)
        assert all(name in joined for name in ('method_pack', 'table_specs', 'method_conventions', 'scope_boundary'))


def test_new_contract_without_requirement_record_fails_closed(anchored):
    anchored.ws.store.set('manifest', {**anchored.ws.store.manifest,
        'commission_requirements_contract': CONTRACT})
    with pytest.raises(ActionRejected, match='(?i)requirement'):
        save(anchored)
    assert not anchored.cs.list_objects('CommissionPlan')


def test_missing_outline_is_unresolved_instead_of_empty_success(anchored):
    ref = requirements().install_requirements(anchored.cs, anchored.scope_ref, None)
    record = requirements().read_requirements(anchored.cs, ref)
    assert record['payload']['anchors']
    assert any(item['status'] == 'unresolved' for item in record['payload']['items'])
    assert requirements().check_plan(anchored.cs, anchored.plan, ref)


def test_word_automatic_numbering_supplies_heading_identity(anchored):
    doc = Document()
    numbering = doc.part.numbering_part.element
    abstract = OxmlElement('w:abstractNum'); abstract.set(qn('w:abstractNumId'), '42')
    level = OxmlElement('w:lvl'); level.set(qn('w:ilvl'), '0')
    for tag, value in [('start', '4'), ('numFmt', 'decimal'), ('lvlText', '%1')]:
        child = OxmlElement('w:' + tag); child.set(qn('w:val'), value); level.append(child)
    abstract.append(level); numbering.append(abstract)
    number = OxmlElement('w:num'); number.set(qn('w:numId'), '42')
    definition = OxmlElement('w:abstractNumId'); definition.set(qn('w:val'), '42')
    number.append(definition); numbering.append(number)
    for text in ('Assessment', 'Conclusion'):
        paragraph = doc.add_paragraph(text, style='Heading 1')
        num = paragraph._p.get_or_add_pPr().get_or_add_numPr()
        num.get_or_add_ilvl().val = 0
        num.get_or_add_numId().val = 42
        doc.add_paragraph('Preserve this section instruction.')
    output = BytesIO(); doc.save(output)
    ref = capture(anchored, 'automatic-numbering.docx', output.getvalue(), 'numbered-outline')
    anchors = requirements().extract_anchors(anchored.cs, anchored.scope_ref, ref)
    assert {a['section_id'] for a in anchors if a['kind'] == 'section'} == {'4', '5'}
    assert any('Preserve this section instruction.' in a['source']['quote'] for a in anchors)


@pytest.mark.parametrize('numbered', [False, True], ids=['plain-subheadings', 'decimal-subheadings'])
def test_nested_markdown_headings_do_not_hide_scope_statements_or_numbered_conventions(anchored, numbered):
    text = '''# Commission
## 1. Objects
Retain the primary object.
### Additional object evidence
Retain the second object candidate too.
## 4. Boundary
Use the main contract boundary.
### Boundary qualification
Preserve the unresolved boundary qualification.
## 5. Conventions
1. Apply the primary convention.
### Further convention details
2. Apply the numbered convention below the subheading too.
## 6. Contacts
3. This contact is outside the convention section.
'''
    if numbered:
        text = (text.replace('### Additional', '### 1.1 Additional')
                .replace('### Boundary', '### 4.1 Boundary')
                .replace('### Further', '### 5.1 Further'))
    scope = capture(anchored, 'nested-scope.md', text.encode(), 'nested-scope')
    anchors = requirements().extract_anchors(anchored.cs, scope, anchored.outline_ref)
    conventions = [a['source']['quote'] for a in anchors if a['kind'] == 'convention']
    assert len(conventions) == 2
    assert any('below the subheading' in quote for quote in conventions)
    assert not any('outside the convention' in quote for quote in conventions)
    scopes = [a['source']['quote'] for a in anchors if a['kind'] == 'scope']
    assert 'Retain the second object candidate too.' in scopes
    assert 'Preserve the unresolved boundary qualification.' in scopes


@pytest.mark.parametrize('status', ['required', 'not_applicable'])
def test_missing_parser_input_cannot_be_laundered_into_empty_capability_success(anchored, status):
    root = requirements().install_requirements(anchored.cs, anchored.scope_ref, None)
    initial = requirements().read_requirements(anchored.cs, root)
    items = capability_items(initial['payload']['anchors'])
    malformed = {anchor['id'] for anchor in initial['payload']['anchors'] if anchor.get('parse_error')}
    assert malformed
    for item in items:
        if item['anchor_id'] in malformed:
            item.update(status=status, interpretation='Agent says no problem.', capabilities=[])
    with pytest.raises(ActionRejected, match='(?i)(parser|unresolved|source|outline|anchor)'):
        requirements().propose_requirements(anchored.cs, anchored.co, 'waive-parser-failure', root, items)
    assert requirements().read_requirements(anchored.cs) == initial


def assert_gap_exception(exc, fixture, fault=None):
    assert str(exc.value).startswith('COMMISSION_REQUIREMENTS_INCOMPLETE'), str(exc.value)
    gaps = exc.value.diagnostic['gaps']
    assert gaps and all({'anchor_id', 'path', 'code', 'message'} <= g.keys() for g in gaps)
    assert {g['anchor_id'] for g in gaps} <= {a['id'] for a in fixture.anchors}
    if fault == 'whole-group':
        joined = ' '.join(g['path'] for g in gaps)
        assert all(name in joined for name in ('method_pack', 'table_specs', 'method_conventions', 'scope_boundary'))


def saved_historical_bundle(fixture, plan, *, answered=True):
    """Seed immutable historical input to test each gate, without bypassing that gate.

    This deliberately does not call new-plan validation: that would mask a missing
    guard on approval/writing/export. It never changes an existing saved record.
    """
    cs = fixture.cs
    issue = fixture.ws.issue('requirement', 'Synthetic historical checkpoint', [])
    with cs.store.connect() as db:
        plan_ref = cs._insert(db, fixture.co, 'CommissionPlan', {**deepcopy(plan), 'inventory_refs': []})
        decision = {'plan_ref': plan_ref, 'requirements_ref': fixture.requirements_ref,
            'approved': True, 'corrections': '', 'reductions': []}
        operator = Actor('operator', 'operator', 'commission-checkpoint:' + issue['id'])
        decision_ref = cs._insert(db, operator, 'CommissionDecision', {**decision,
            'required_material_issues': [], 'confirmed_rules': {}})
        task_ref = cs._insert(db, fixture.co, 'DelegatedTask', {'role': 'writer',
            'commission_plan_ref': plan_ref, 'section_ids': ['4'],
            'goal': 'Synthetic historical assigned writing', 'write_scope': 'Own nodes only',
            'delegated_by': fixture.co.id})
        root = cs._insert(db, fixture.co, 'ContentNode', {'kind': 'report',
            'body': {'text': 'Historical report snapshot'}, 'qualifiers': {}, 'claim_kind': 'structure'})
        table = cs._insert(db, fixture.co, 'ContentNode', {'kind': 'table',
            'body': {'columns': ['Record'], 'rows': [['Synthetic']]}, 'qualifiers': {}, 'claim_kind': 'structure'})
        edge = cs._insert(db, fixture.co, 'Relation', {'subject_ref': root, 'object_ref': table,
            'predicate': 'contains', 'position': 0, 'provenance_kind': 'adopted_during_generation'})
        snapshot = cs._insert(db, fixture.co, 'DocumentSnapshot', {'root_ref': root,
            'refs': [root, table, edge, plan_ref, decision_ref, fixture.requirements_ref],
            'commission_plan_ref': plan_ref, 'commission_confirmation_ref': decision_ref})
        api()._set(db, 'commission_plan', plan_ref)
        api()._set(db, 'commission_confirmation', decision_ref if answered else None)
        api()._set(db, 'commission_checkpoint:' + issue['id'], {'plan_ref': plan_ref,
            'requirements_ref': fixture.requirements_ref, 'brief_path': 'outputs/synthetic-historical.md'})
        if answered:
            issues = api()._state(db, 'report_issues', [])
            matching = next(item for item in issues if item['id'] == issue['id'])
            matching.update(decision_origin='operator', decision=encode(decision), resolved=True)
            api()._set(db, 'report_issues', issues)
    return SimpleNamespace(plan_ref=plan_ref, decision=decision, issue_id=issue['id'],
        actor=Actor('content:writer:' + task_ref['id'], 'writer', task_ref['id']),
        root_ref=root, snapshot_ref=snapshot, table_ref=table)


GATES = ('save', 'approval', 'approval-replay', 'writer', 'assessment', 'outcome', 'word-export', 'excel-export')


@pytest.mark.parametrize('fault', FAULTS)
@pytest.mark.parametrize('gate', GATES)
def test_all_five_authority_families_refuse_every_omission(required_case, fault, gate):
    fixture = required_case
    incomplete = omit(fixture.plan, fault)
    if gate != 'save':
        bundle = saved_historical_bundle(fixture, incomplete, answered=gate != 'approval')
    before = deepcopy(fixture.cs.list_objects())
    with pytest.raises(ActionRejected) as exc:
        if gate == 'save':
            save(fixture, incomplete, operation='incomplete-h1-save')
        elif gate.startswith('approval'):
            api().reply(fixture.ws, bundle.issue_id, bundle.decision)
        elif gate == 'writer':
            with fixture.cs.store.connect() as db:
                api().assert_writing_allowed(fixture.cs, db, bundle.actor)
        elif gate == 'assessment':
            assessment = persistence_input(fixture); assessment['method_version'] = 2
            persist(fixture, bundle.actor, assessment)
        elif gate == 'outcome':
            api().record_outcome(fixture.cs, bundle.actor, 'blocked-outcome', 'S1',
                bundle.root_ref, bundle.root_ref, bundle.root_ref, [], [])
        elif gate == 'word-export':
            from report_agent.content_export import export_snapshot
            export_snapshot(fixture.cs, fixture.co, 'blocked-word', bundle.snapshot_ref)
        else:
            from report_agent.content_workbook import export_workbook
            export_workbook(fixture.cs, fixture.co, 'blocked-excel', bundle.snapshot_ref,
                [{'name': 'Records', 'table_ref': bundle.table_ref}])
    assert_gap_exception(exc, fixture, fault)
    assert fixture.cs.list_objects() == before
    assert not fixture.cs.list_objects('ExportArtifact')


def confirm(fixture, saved, *, ref=None):
    checkpoint = api().request_checkpoint(fixture.ws)
    decision = {'plan_ref': saved['plan_ref'], 'requirements_ref': ref or fixture.requirements_ref,
        'approved': True, 'corrections': '', 'reductions': []}
    api().reply(fixture.ws, checkpoint['issue_id'], decision)
    return checkpoint, decision


def test_complete_scoring_plan_confirms_exact_requirements_and_allows_calculation(required_case):
    fixture = required_case
    saved = save(fixture)
    checkpoint, _ = confirm(fixture, saved)
    assert checkpoint['requirements_ref'] == fixture.requirements_ref
    accepted = fixture.cs.read(fixture.ws.store.get('commission_confirmation'))
    assert accepted['payload']['requirements_ref'] == fixture.requirements_ref
    actor = writer(fixture, saved)
    with fixture.cs.store.connect() as db:
        assert api().assert_writing_allowed(fixture.cs, db, actor)['ref'] == saved['plan_ref']
    assessment = persistence_input(fixture); assessment['method_version'] = 2
    receipt = persist(fixture, actor, assessment)
    assert fixture.cs.read(receipt['assessment_ref'])['payload']['commission_plan_ref'] == saved['plan_ref']


@pytest.mark.parametrize('fault', ['missing', 'old'])
def test_approval_must_name_exact_latest_requirement_version(required_case, fault):
    fixture = required_case
    saved = save(fixture)
    checkpoint = api().request_checkpoint(fixture.ws)
    decision = {'plan_ref': saved['plan_ref'], 'approved': True, 'corrections': '', 'reductions': []}
    if fault == 'old':
        decision['requirements_ref'] = fixture.initial_requirements['ref']
    with pytest.raises((ActionRejected, ValueError), match='(?i)requirement'):
        api().reply(fixture.ws, checkpoint['issue_id'], decision)
    assert fixture.ws.store.get('commission_confirmation') is None


@pytest.mark.parametrize('gate', ['approval', 'writer'])
def test_new_requirement_revision_invalidates_prior_plan_authority_without_rewriting(required_case, gate):
    fixture = required_case
    saved = save(fixture)
    checkpoint, decision = confirm(fixture, saved)
    actor = writer(fixture, saved)
    before = deepcopy(fixture.cs.read(saved['plan_ref']))
    items = deepcopy(fixture.items); items[0]['interpretation'] += ' Revised by coordinator.'
    revised = requirements().propose_requirements(fixture.cs, fixture.co, 'revise-requirements',
        fixture.requirements_ref, items)['result']['requirements_ref']
    assert revised != fixture.requirements_ref
    with pytest.raises(ActionRejected, match='(?i)requirement'):
        if gate == 'approval':
            api().reply(fixture.ws, checkpoint['issue_id'], decision)
        else:
            with fixture.cs.store.connect() as db:
                api().assert_writing_allowed(fixture.cs, db, actor)
    assert fixture.cs.read(saved['plan_ref']) == before


@pytest.mark.parametrize('fault', ['source-ref', 'quote', 'duplicate-link'])
def test_convention_link_is_exact_source_bound_not_just_an_anchor_label(required_case, fault):
    fixture = required_case
    plan = deepcopy(fixture.plan)
    if fault == 'source-ref':
        plan['conventions'][0]['source']['source_ref'] = fixture.sources['template']
    elif fault == 'quote':
        plan['conventions'][0]['source']['quote'] = 'Agent invented this convention.'
    else:
        plan['conventions'][1]['requirement_anchor_id'] = plan['conventions'][0]['requirement_anchor_id']
    with pytest.raises(ActionRejected) as exc:
        save(fixture, plan)
    assert_gap_exception(exc, fixture)


@pytest.mark.parametrize('fault', ['unrelated-convention', 'default-unagreed'])
@pytest.mark.parametrize('gate', ['save', 'approval'])
def test_required_weight_binding_uses_its_own_source_anchor(required_case, fault, gate):
    fixture = required_case
    assert requirements().check_plan(fixture.cs, fixture.plan, fixture.requirements_ref) == []
    plan = deepcopy(fixture.plan)
    weight = next(a for a in fixture.anchors if 'rank-lookup weights' in a['source']['quote'])
    binding = plan['method_conventions'][0]
    if fault == 'unrelated-convention':
        # A real customer convention is still the wrong basis for this obligation.
        binding['source'] = next(c['source'] for c in plan['conventions']
            if c['requirement_anchor_id'] != weight['id'])
    else:
        binding.update(status='default_unagreed', source=None)
    api().MethodConvention.model_validate(binding)
    assert api().method_questions(plan) == [], 'The old structural method check alone misses this gap.'
    with pytest.raises(ActionRejected) as exc:
        if gate == 'save':
            save(fixture, plan)
        else:
            # Historical saved plans contain schema defaults such as pending_sources.
            normalized = api().CommissionPlan.model_validate(plan).model_dump()
            historical = saved_historical_bundle(fixture, normalized, answered=False)
            api().reply(fixture.ws, historical.issue_id, historical.decision)
    assert_gap_exception(exc, fixture)
    assert any(g['anchor_id'] == weight['id'] and g['path'] == 'method_conventions'
        for g in exc.value.diagnostic['gaps'])


@pytest.mark.parametrize('gate', ['approval', 'writer'])
def test_unresolved_requirement_blocks_even_a_structurally_complete_plan(required_case, gate):
    fixture = required_case
    items = deepcopy(fixture.items); items[0]['status'] = 'unresolved'
    ref = requirements().propose_requirements(fixture.cs, fixture.co, 'unresolved-proposal',
        fixture.requirements_ref, items)['result']['requirements_ref']
    fixture.requirements_ref = ref
    plan = deepcopy(fixture.plan); plan['requirements_ref'] = ref
    bundle = saved_historical_bundle(fixture, plan, answered=gate == 'writer')
    with pytest.raises(ActionRejected) as exc:
        if gate == 'approval':
            api().reply(fixture.ws, bundle.issue_id, bundle.decision)
        else:
            with fixture.cs.store.connect() as db:
                api().assert_writing_allowed(fixture.cs, db, bundle.actor)
    assert_gap_exception(exc, fixture)


@pytest.fixture
def non_scoring(anchored):
    fixture = anchored
    text = '''# Non-scoring commission
## 1. Objects
Describe the supplied S1 inspection record.
## 4. Scope
Use the supplied record set; no engineering boundary calculation is commissioned.
## 5. Conventions
1. Scoring methods, weight strategies and assessment tables are not commissioned for this descriptive report.
'''
    scope = capture(fixture, 'non-scoring-commission.md', text.encode(), 'non-scoring-scope')
    roles = deepcopy(fixture.ws.store.get('commission_source_roles'))
    roles['non-scoring'] = {'id': fixture.cs.read(scope)['payload']['source_id'], 'purpose': 'commission'}
    fixture.ws.store.set('commission_source_roles', roles)
    initial = requirements().install_requirements(fixture.cs, scope, fixture.outline_ref)
    record = requirements().read_requirements(fixture.cs, initial)
    anchors = record['payload']['anchors']
    items = []
    for anchor in anchors:
        not_applicable = anchor['kind'] == 'convention'
        items.append({'anchor_id': anchor['id'],
            'status': 'not_applicable' if not_applicable else 'required',
            'interpretation': ('Source explicitly excludes scoring; owner must confirm this interpretation.'
                if not_applicable else 'Describe supplied records under the provided outline.'),
            'capabilities': (['method_pack', 'weight_binding', 'table_specs'] if not_applicable else
                ['section'] if anchor['kind'] == 'section' else ['inventory']),
            **({'table_roles': ['ranking', 'evaluation']} if not_applicable else {})})
    proposed = requirements().propose_requirements(fixture.cs, fixture.co, 'non-scoring-statuses', initial, items)
    fixture.requirements_ref = proposed['result']['requirements_ref']
    fixture.anchors = anchors
    plan = deepcopy(fixture.plan)
    plan.pop('method_pack'); plan.pop('method_conventions')
    plan['requirements_ref'] = fixture.requirements_ref
    plan['conventions'] = [{'requirement_anchor_id': a['id'], 'source': a['source'],
        'interpretation': 'No scoring requested; subject to owner confirmation.'}
        for a in anchors if a['kind'] == 'convention']
    for section in plan['sections']:
        section['outline'] = next(a['source'] for a in anchors
            if a['kind'] == 'section' and a['section_id'] == section['section_id'])
    scope_anchor = next(a for a in anchors if a['kind'] == 'scope')
    plan['reconciliations'] = [{'sources': [fixture.cite('design'), scope_anchor['source']],
        'result': 'Retain the supplied S1 inspection record.', 'differences': []}]
    fixture.plan = plan
    assert not requirements().check_plan(fixture.cs, plan, fixture.requirements_ref)
    saved = save(fixture)
    actor = writer(fixture, saved)
    with fixture.cs.store.connect() as db, pytest.raises(ActionRejected, match='(?i)(confirm|checkpoint)'):
        api().assert_writing_allowed(fixture.cs, db, actor)
    checkpoint, _ = confirm(fixture, saved)
    assert checkpoint['requirements_ref'] == fixture.requirements_ref
    accepted = fixture.cs.read(fixture.ws.store.get('commission_confirmation'))['payload']
    assert accepted['requirements_ref'] == fixture.requirements_ref
    with fixture.cs.store.connect() as db:
        assert api().assert_writing_allowed(fixture.cs, db, actor)
    objects = [
        {'client_key': 'root', 'type': 'ContentNode', 'payload': {'kind': 'report',
            'body': {'text': 'Descriptive inspection record'}, 'claim_kind': 'structure', 'qualifiers': {}}},
        {'client_key': 'table', 'type': 'ContentNode', 'payload': {'kind': 'table',
            'body': {'columns': ['Record'], 'rows': [['S1']]}, 'claim_kind': 'structure', 'qualifiers': {}}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'root'},
            'object_ref': {'client_key': 'table'}, 'predicate': 'contains', 'position': 0,
            'provenance_kind': 'adopted_during_generation'}}]
    refs = fixture.cs.commit(actor, 'descriptive-content', objects)['result']['refs']
    snapshot = fixture.cs.freeze(fixture.co, 'descriptive-snapshot', refs['root'],
        list(refs.values()))['result']['snapshot_ref']
    from report_agent.content_export import export_snapshot
    from report_agent.content_workbook import export_workbook
    word = export_snapshot(fixture.cs, fixture.co, 'descriptive-word', snapshot, {'toc': False})['result']
    excel = export_workbook(fixture.cs, fixture.co, 'descriptive-excel', snapshot,
        [{'name': 'Records', 'table_ref': refs['table']}])['result']
    assert (fixture.ws.store.root / word['file_ref']).is_file()
    assert (fixture.ws.store.root / excel['file_ref']).is_file()
    assert not fixture.cs.list_objects('Assessment')
    return SimpleNamespace(fixture=fixture, snapshot_ref=snapshot, table_ref=refs['table'], word=word, excel=excel)


def test_explicit_non_scoring_requirement_is_valid_only_after_owner_confirms_waivers(non_scoring):
    case = non_scoring
    assert case.word['export_ref']['type'] == 'ExportArtifact'
    assert case.excel['export_ref']['type'] == 'ExportArtifact'
    record = requirements().read_requirements(case.fixture.cs)
    assert any(item['status'] == 'not_applicable' and 'method_pack' in item['capabilities']
        for item in record['payload']['items'])


def test_prepare_installs_frozen_unresolved_requirements_before_any_coordinator(tmp_path, monkeypatch):
    from test_pilot_m1_preparation import host_case
    from report_agent.store import Store
    state = host_case(tmp_path, monkeypatch)
    filename = 'synthetic-outline.docx'
    (state['INPUT'] / filename).write_bytes(outline_bytes())
    state['CONFIG']['commission_outline_input'] = filename
    pins = {p.relative_to(state['INPUT']).as_posix(): state['sha'](p)
        for p in sorted(state['INPUT'].rglob('*')) if p.is_file()}
    (state['HERE'] / 'approved-input-hashes.json').write_text(json.dumps(pins), encoding='utf-8')
    state['prepare']()
    store = Store(state['CASE'])
    assert store.manifest['commission_requirements_contract'] == CONTRACT
    cs = ContentStore(store)
    record = requirements().read_requirements(cs)
    assert record['ref']['type'] == 'CommissionRequirements'
    assert record['payload']['anchors']
    assert all(item['status'] == 'unresolved' for item in record['payload']['items'])
    assert not cs.list_objects('CommissionPlan')
    assert store.get('commission_confirmation') is None


def test_generic_commit_cannot_forge_host_requirement_records(required_case):
    fixture = required_case
    before = requirements().read_requirements(fixture.cs)
    with pytest.raises((ActionRejected, ActionForbidden, ValueError)):
        fixture.cs.commit(fixture.co, 'forge-requirements', [{'client_key': 'forged',
            'type': 'CommissionRequirements', 'payload': {'anchors': [], 'items': []}}])
    assert requirements().read_requirements(fixture.cs) == before


@pytest.mark.parametrize('cached', [False, True], ids=['fresh-call', 'known-success-replay'])
@pytest.mark.parametrize('format', ['word', 'excel'])
def test_stale_snapshot_export_cannot_bypass_requirements_via_cached_success(non_scoring, format, cached):
    case = non_scoring; fixture = case.fixture
    before = deepcopy(fixture.cs.read(case.word['export_ref']))
    previous = requirements().read_requirements(fixture.cs)
    items = deepcopy(previous['payload']['items'])
    items[0]['interpretation'] += ' Revised commission interpretation awaiting confirmation.'
    latest = requirements().propose_requirements(fixture.cs, fixture.co, 'change-after-export',
        previous['ref'], items)['result']['requirements_ref']
    assert latest != previous['ref']
    with pytest.raises(ActionRejected, match='(?i)requirement'):
        if format == 'word':
            from report_agent.content_export import export_snapshot
            export_snapshot(fixture.cs, fixture.co, 'descriptive-word' if cached else 'stale-word',
                case.snapshot_ref, {'toc': False})
        else:
            from report_agent.content_workbook import export_workbook
            export_workbook(fixture.cs, fixture.co, 'descriptive-excel' if cached else 'stale-excel',
                case.snapshot_ref, [{'name': 'Records', 'table_ref': case.table_ref}])
    # Reading the already-created historical artifact remains valid and unchanged.
    assert fixture.cs.read(case.word['export_ref']) == before


def test_table_role_requirement_comes_from_record_instead_of_one_report_constant(required_case):
    fixture = required_case
    items = deepcopy(fixture.items)
    table_item = next(item for item in items if 'table_specs' in item['capabilities'])
    table_item['table_roles'] = ['inspection_summary']
    proposed = requirements().propose_requirements(fixture.cs, fixture.co, 'different-table-role',
        fixture.requirements_ref, items)['result']['requirements_ref']
    plan = deepcopy(fixture.plan); plan['requirements_ref'] = proposed
    plan['table_specs'] = {'inspection_summary': deepcopy(plan['table_specs']['ranking'])}
    # H1 checks the declaration; this does not claim a new runtime calculation/table type is implemented.
    assert not requirements().check_plan(fixture.cs, plan, proposed)
    plan['table_specs'] = {'ranking': plan['table_specs']['inspection_summary']}
    gaps = requirements().check_plan(fixture.cs, plan, proposed)
    assert any(g['path'].startswith('table_specs') for g in gaps)


def test_required_tables_cannot_hide_required_roles_in_empty_list(required_case):
    fixture = required_case
    items = deepcopy(fixture.items)
    next(item for item in items if 'table_specs' in item['capabilities'])['table_roles'] = []
    with pytest.raises((ActionRejected, ValueError), match='(?i)(table|role)'):
        requirements().propose_requirements(fixture.cs, fixture.co, 'empty-table-roles',
            fixture.requirements_ref, items)


@pytest.mark.parametrize('capability', ['fixed_text', 'result_bindings'])
def test_section_capabilities_require_template_provenance_not_just_nonempty_fields(required_case, capability):
    fixture = required_case
    items = deepcopy(fixture.items)
    anchor = next(a for a in fixture.anchors if a['kind'] == 'section' and a['section_id'] == '5')
    next(item for item in items if item['anchor_id'] == anchor['id'])['capabilities'].append(capability)
    ref = requirements().propose_requirements(fixture.cs, fixture.co, 'section-capability',
        fixture.requirements_ref, items)['result']['requirements_ref']
    plan = deepcopy(fixture.plan); plan['requirements_ref'] = ref
    section = next(s for s in plan['sections'] if s['section_id'] == '5')
    section['sources'] = [fixture.cite('design')]
    if capability == 'fixed_text':
        section.update(kind='fixed', text='Agent-written replacement of template.')
    else:
        section['result_bindings'] = [{'old': '{SUMMARY}', 'object_id': 'S1', 'field': 'assessment_text'}]
    assert any(g['anchor_id'] == anchor['id'] for g in requirements().check_plan(fixture.cs, plan, ref))


def test_requirement_source_pin_mismatch_is_explicit_before_new_authority(required_case):
    fixture = required_case
    source = fixture.cs.read(fixture.scope_ref)
    corrupted = deepcopy(source)
    corrupted['payload']['file_digest'] = '0' * 64
    # Isolated corruption test only: actual host/source storage is never changed by a proposal.
    with fixture.cs.store.connect() as db:
        db.execute('UPDATE content_versions SET data=? WHERE type=? AND id=? AND version=?',
            (encode(corrupted), fixture.scope_ref['type'], fixture.scope_ref['id'], fixture.scope_ref['version']))
    gaps = requirements().check_plan(fixture.cs, fixture.plan, fixture.requirements_ref)
    assert any('source' in g['path'].lower() or 'pin' in g['code'].lower() for g in gaps)
    with pytest.raises(ActionRejected) as exc:
        save(fixture)
    assert_gap_exception(exc, fixture)


def outcome_inputs(fixture, *, h1):
    saved = save(fixture)
    if h1:
        confirm(fixture, saved)
    else:
        from test_m1_commission_plan import approve
        approve(fixture, saved)
    actor = writer(fixture, saved)
    assessment = persistence_input(fixture)
    assessment['method_version'] = fixture.plan['method_pack']['version']
    receipt = persist(fixture, actor, assessment)
    section = fixture.cs.commit(actor, 'outcome-section', [{'client_key': 'section',
        'type': 'ContentNode', 'payload': {'kind': 'chapter', 'body': {'text': 'S1 assessment'},
            'qualifiers': {}, 'claim_kind': 'structure'}}])['result']['refs']['section']
    request = {'object_id': 'S1', 'section_ref': section,
        'score_ref': receipt['evaluation_ref'], 'level_ref': receipt['level_ref'],
        'basis_refs': [receipt['evidence_ref']], 'unresolved': []}
    return saved, actor, receipt, request


def test_historical_successful_outcome_receipt_keeps_its_original_replay_identity(method_commission):
    fixture = method_commission
    saved, actor, receipt, request = outcome_inputs(fixture, h1=False)
    plan = fixture.cs.read(saved['plan_ref'])['payload']

    def old_save(db):
        # Exact pre-H1 operation envelope: no binding_identity was part of its digest.
        ref = fixture.cs._insert(db, actor, 'CommissionOutcome', {**request,
            'commission_plan_ref': saved['plan_ref'], 'object_ref': plan['inventory_refs'][0],
            'assessment_ref': receipt['assessment_ref']})
        api()._set(db, 'commission_outcome:' + digest([saved['plan_ref'], 'S1']) + ':' + digest(actor.id), ref)
        return {'outcome_ref': ref}

    historical = fixture.cs.operation(actor, 'pre-h1-outcome', {'commission_outcome': request}, old_save)
    before = deepcopy(fixture.cs.read(historical['result']['outcome_ref']))
    replay = api().record_outcome(fixture.cs, actor, 'pre-h1-outcome', **request)
    assert replay == historical
    assert fixture.cs.read(historical['result']['outcome_ref']) == before
    assert len(fixture.cs.list_objects('CommissionOutcome')) == 1


def test_h1_successful_outcome_replay_rechecks_revised_requirement_authority(required_case):
    fixture = required_case
    _, actor, _, request = outcome_inputs(fixture, h1=True)
    historical = api().record_outcome(fixture.cs, actor, 'h1-outcome', **request)
    before = deepcopy(fixture.cs.read(historical['result']['outcome_ref']))
    items = deepcopy(fixture.items); items[0]['interpretation'] += ' Requires a new owner review.'
    requirements().propose_requirements(fixture.cs, fixture.co, 'revise-after-outcome',
        fixture.requirements_ref, items)
    with pytest.raises(ActionRejected) as exc:
        api().record_outcome(fixture.cs, actor, 'h1-outcome', **request)
    assert_gap_exception(exc, fixture)
    assert fixture.cs.read(historical['result']['outcome_ref']) == before
