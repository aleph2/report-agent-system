"""H3.2 offline planning contracts and canonical evidence."""
from copy import deepcopy
import pytest
from report_agent import commission_planning as planning
from report_agent import commission_plan
from report_agent.errors import ActionRejected
from report_agent.content_models import SourceCitation

from test_m1_g4_planning_steps import (method_commission, anchored, required_case, entries, linked, draft_case, text_source, offline_only)


def boundary(fixture):
    anchor = next(a for a in fixture.anchors if a['kind'] == 'scope' and 'K1+000' in a['source']['quote'])
    return {'start_meter': 'K1+000', 'end_meter': 'K2+000+12.5',
            'source': {k: v for k, v in anchor['source'].items() if k != 'locator'},
            'customer_basis_anchor_id': anchor['id']}


def test_boundary_resolves_chainage_anchor_and_unique_quote(linked):
    value = boundary(linked)
    receipt = planning.save_item(linked.cs, linked.co, 'h32-boundary', 'boundary', value)
    saved = planning.read_draft(linked.cs, linked.co)['plan']['scope_boundary']
    assert saved['start_meter'] == '1000' and saved['end_meter'] == '2012.5'
    assert saved['customer_basis'] == next(a['source'] for a in linked.anchors if a['id'] == value['customer_basis_anchor_id'])
    assert saved['source']['locator'] == saved['customer_basis']['locator']
    assert receipt['result']['citation_resolutions'][0]['field'] == 'boundary.source.locator'
    assert receipt == planning.save_item(linked.cs, linked.co, 'h32-boundary', 'boundary', value)
    assert 'K2+000+12.5' in commission_plan.boundary_display(saved)
    assert '2012.5' in commission_plan.boundary_display(saved)


@pytest.mark.parametrize('quote,reason', [('absent quoted words', 'quote_not_found'), ('the', 'quote_ambiguous')])
def test_quote_failure_names_exact_field_and_choices(linked, quote, reason):
    value = boundary(linked); value['source']['quote'] = quote
    with pytest.raises(ActionRejected) as caught:
        planning.save_item(linked.cs, linked.co, 'h32-' + reason, 'boundary', value)
    issue = caught.value.diagnostic['fields'][0]
    assert issue['field'] == 'boundary.source.quote'
    assert issue['reason'] == reason
    assert isinstance(issue['choices'], list)
    assert bool(issue['choices']) == (reason == 'quote_ambiguous')
    assert 'scope_boundary' not in planning.read_draft(linked.cs, linked.co)['plan']


def test_boundary_schema_forbids_free_customer_basis_and_requires_quote(linked):
    fn = next(f for f in planning.planning_tools(linked.cs, lambda: linked.co) if f.__name__ == 'set_scope_boundary')
    model = fn.message_model
    value = boundary(linked)
    assert model.model_validate({'boundary': value})
    value['customer_basis'] = value['source']
    with pytest.raises(ValueError): model.model_validate({'boundary': value})
    value.pop('customer_basis'); value['source'].pop('quote')
    with pytest.raises(ValueError): model.model_validate({'boundary': value})
    with pytest.raises(ValueError): SourceCitation.model_validate({'source_ref': linked.scope_ref, 'quote': 'test'})


def test_unknown_anchor_names_field_and_offers_only_scope_anchors(linked):
    value = boundary(linked); value['customer_basis_anchor_id'] = 'invented'
    with pytest.raises(ActionRejected) as caught:
        planning.save_item(linked.cs, linked.co, 'h32-anchor', 'boundary', value)
    issue = caught.value.diagnostic['fields'][0]
    assert issue['field'] == 'boundary.customer_basis_anchor_id'
    assert set(issue['choices']) == {a['id'] for a in linked.anchors if a['kind'] == 'scope'}


def test_authority_validation_never_repairs_saved_citation(linked):
    citation = deepcopy(boundary(linked)['source']); citation['locator'] = 'invented'
    before = deepcopy(citation)
    with linked.cs.store.connect() as db:
        with pytest.raises(ActionRejected) as caught:
            commission_plan._validate_sources(linked.cs, db, linked.co, {'boundary': {'source': citation}})
    assert citation == before
    assert caught.value.diagnostic['fields'][0]['field'] == 'boundary.source.locator'


@pytest.mark.parametrize('notation,expected', [('K1310+000', '1310000'), ('K1326+320+12.5', '1326332.5'), ('0.125', '0.125'), ('-5.25', '-5.25')])
def test_chainage_conversion_is_decimal_exact(notation, expected):
    from report_agent.planning_inputs import metres
    assert metres(notation) == expected


@pytest.mark.parametrize('notation', ['K1+1000', 'K1+20-10', 'K1+20+3+4', 'NaN', 'Infinity', '1e6', 'K1.5+000', ' 1000 '])
def test_ambiguous_chainage_is_rejected(notation):
    from report_agent.planning_inputs import metres
    with pytest.raises(ValueError): metres(notation)


def test_wrong_locator_with_unique_quote_is_resolved_and_audited(linked):
    value = boundary(linked)
    value['source']['locator'] = 'typed section label'
    receipt = planning.save_item(linked.cs, linked.co, 'h32-wrong-locator', 'boundary', value)
    resolution = receipt['result']['citation_resolutions'][0]
    assert resolution['original_locator'] == 'typed section label'
    assert resolution['resolved_locator'] != resolution['original_locator']
    assert receipt['result']['customer_basis_binding']['anchor_id'] == value['customer_basis_anchor_id']
    assert receipt['result']['customer_basis_binding']['requirements_ref'] == linked.requirements_ref


def test_repeated_quote_in_one_block_is_ambiguous_and_explicit_locator_disambiguates(linked):
    value = boundary(linked)
    value['source']['quote'] = 'e'
    with pytest.raises(ActionRejected) as caught:
        planning.save_item(linked.cs, linked.co, 'h32-repeat', 'boundary', value)
    choices = caught.value.diagnostic['fields'][0]['choices']
    assert len(choices) > len(set(choices))
    value['source']['locator'] = choices[0]
    assert planning.save_item(linked.cs, linked.co, 'h32-explicit', 'boundary', value)['ok'] is True


def test_ingress_keeps_original_chainage_in_operation_request(linked):
    functions = {f.__name__: f for f in planning.planning_tools(linked.cs, lambda: linked.co)}
    value = boundary(linked)
    model = functions['set_scope_boundary'].message_model
    # The same model validates exposed input without prematurely normalizing away the caller's notation.
    parsed = model.model_validate({'boundary': value})
    assert parsed.boundary.start_meter == 'K1+000'
    assert parsed.boundary.end_meter == 'K2+000+12.5'


def test_chainage_arithmetic_does_not_round_long_fraction():
    from report_agent.planning_inputs import metres
    fraction = '123456789012345678901234567890123456789'
    assert metres('K1+000+0.' + fraction) == '1000.' + fraction
    assert 'K1+000.' + fraction in commission_plan.boundary_display({'start_meter': '1000.' + fraction, 'end_meter': '2000'})


def test_operation_digest_retains_raw_chainage_and_caller_locator(linked):
    from report_agent.store import digest
    value = boundary(linked); value['source']['locator'] = 'caller locator'
    expected = digest({'actor': linked.co.__dict__, 'request': {'kind': 'boundary', 'item': value}})
    planning.save_item(linked.cs, linked.co, 'h32-raw-receipt', 'boundary', value)
    assert linked.cs.receipt(linked.co, 'h32-raw-receipt')['request_digest'] == expected


def test_current_anchor_pin_mismatch_is_refused(linked):
    from report_agent.commission_requirements import read_requirements, KEY
    value = boundary(linked)
    record = read_requirements(linked.cs)
    payload = deepcopy(record['payload'])
    for pin in payload['source_pins']: pin['file_digest'] = '0' * 64
    with linked.cs.store.connect() as db:
        ref = linked.cs._insert(db, linked.co, 'CommissionRequirements', payload,
                               id=record['ref']['id'], version=record['ref']['version'] + 1,
                               previous_ref=record['ref'])
    linked.cs.store.set(KEY, ref)
    with pytest.raises(ActionRejected) as caught:
        planning.save_item(linked.cs, linked.co, 'h32-bad-pin', 'boundary', value)
    assert caught.value.diagnostic['fields'][0]['reason'] == 'requirement_source_pin_mismatch'


def test_bad_end_sentence_identifies_end_not_valid_start(text_source):
    planning.install_text_profile(text_source.cs, text_source.text_profile)
    selection = {**text_source.selection, 'end_sentence': 'Not in this source.'}
    with pytest.raises(ActionRejected) as caught:
        planning.resolve_source_span(text_source.cs, selection)
    assert caught.value.diagnostic['fields'][0]['field'] == 'source_span.end_sentence'


def test_missing_end_page_identifies_actual_missing_page(text_source):
    planning.install_text_profile(text_source.cs, text_source.text_profile)
    selection = {**text_source.selection, 'end_page': 3}
    with pytest.raises(ActionRejected) as caught:
        planning.resolve_source_span(text_source.cs, selection)
    issue = caught.value.diagnostic['fields'][0]
    assert issue['field'] == 'source_span.end_page'
    assert '3' in issue['reason']
    assert issue['choices'] == [1, 2]


@pytest.mark.parametrize('primary', ['design', 'survey'])
def test_recorded_failure_shape_valid_primary_and_wrong_customer_locator(linked, primary):
    value = deepcopy(linked.plan['scope_boundary'])
    if primary == 'design':
        value['source'] = linked.cite(primary)
    else:
        from test_m1_g4_requirements import capture
        quote = 'Alternate survey evidence for the first contract.'
        ref = capture(linked, 'h32-alternate-survey.txt', quote.encode(), 'h32-survey-input')
        source_id = linked.cs.read(ref)['payload']['source_id']
        with linked.cs.store.connect() as db:
            locator = db.execute('SELECT locator FROM source_blocks WHERE source_id=? ORDER BY ordinal', (source_id,)).fetchone()[0]
        value['source'] = {'source_ref': ref, 'locator': locator, 'quote': quote}
    anchor = next(a for a in linked.anchors if a['kind'] == 'scope' and 'K1+000' in a['source']['quote'])
    value['customer_basis'] = {**anchor['source'], 'locator': 'scope.md section 4'}
    receipt = planning.save_item(linked.cs, linked.co, 'h32-replay-' + primary, 'boundary', value)
    saved = planning.read_draft(linked.cs, linked.co)['plan']['scope_boundary']
    assert saved['source'] == value['source']
    assert saved['customer_basis'] == anchor['source']
    assert receipt['result']['citation_resolutions'] == [{
        'field': 'boundary.customer_basis.locator', 'original_locator': 'scope.md section 4',
        'resolved_locator': anchor['source']['locator'], 'reason': 'unique_exact_quote',
        'source_ref': anchor['source']['source_ref']}]



def test_source_wide_uniqueness_includes_a_second_cross_block_occurrence():
    from report_agent.planning_inputs import quote_locations
    rows = [('line 1', 'needle'), ('line 2', 'nee'), ('line 3', 'dle')]
    assert len(quote_locations(rows, 'needle')) == 2


def test_unique_quote_spanning_same_page_blocks_has_canonical_page_locator():
    from report_agent.planning_inputs import quote_locations
    rows = [('page 1; chars 1-3', 'nee'), ('page 1; chars 4-6', 'dle')]
    assert quote_locations(rows, 'needle') == ['page 1']


def test_legacy_scientific_boundary_still_renders_without_decimal_rounding():
    displayed = commission_plan.boundary_display({'start_meter': '1e100', 'end_meter': '2e100'})
    assert '1e100' in displayed and '2e100' in displayed



from test_m1_commission_plan import commission


@pytest.mark.parametrize('case', ['no-extracted', 'unrelated', 'template', 'missing-customer'])
def test_boundary_membership_errors_identify_plan_fields_not_quote(commission, case):
    plan = deepcopy(commission.plan)
    commission.ws.store.set('commission_source_roles', {
        'scope': {'id': 'scope', 'purpose': 'commission'},
        'design': {'id': 'design', 'purpose': 'source_or_applicable_standard'},
        'survey': {'id': 'survey', 'purpose': 'source_or_applicable_standard'},
        'template': {'id': 'template', 'purpose': 'template'}})
    plan['scope_boundary'] = {'start_meter': '1000', 'end_meter': '2000',
        'source': commission.cite('design'), 'customer_basis': commission.cite('scope')}
    if case == 'no-extracted':
        for section in plan['sections']:
            if section['kind'] == 'extracted': section.update(kind='fixed', text='Fixed synthetic text')
    elif case == 'unrelated':
        for section in plan['sections']:
            if section['kind'] == 'extracted': section['sources'] = [commission.cite('survey')]
    elif case == 'template':
        plan['scope_boundary']['source'] = commission.cite('template')
        next(section for section in plan['sections'] if section['kind'] == 'extracted')['sources'].append(commission.cite('template'))
    else:
        plan['scope_boundary'].pop('customer_basis')
    with pytest.raises(ActionRejected) as caught:
        commission_plan.save_plan(commission.cs, commission.co, 'h32-membership-' + case, plan)
    diagnostic = caught.value.diagnostic
    assert diagnostic and diagnostic['fields']
    fields = diagnostic['fields']
    if case == 'missing-customer':
        assert fields[0]['field'] == 'scope_boundary.customer_basis'
        assert commission.sources['scope'] in fields[0]['choices']
    else:
        assert fields[0]['field'] == 'scope_boundary.source.source_ref'
        assert 'quote' not in fields[0]['field']
        assert 'sections[].kind' in fields[0]['related_fields']
        assert 'sections[].sources' in fields[0]['related_fields']
        assert 'quote' in fields[0]['message'].lower()
        assert commission.sources['template'] not in fields[0]['choices']
        if case == 'no-extracted': assert fields[0]['choices'] == []
        if case == 'unrelated': assert fields[0]['choices'] == [commission.sources['survey']]
    assert commission_plan.read_plan(commission.ws.store) is None


def test_valid_boundary_membership_still_passes(commission):
    commission.ws.store.set('commission_source_roles', {'scope': {'id': 'scope', 'purpose': 'commission'}})
    plan = deepcopy(commission.plan)
    plan['scope_boundary'] = {'start_meter': '1000', 'end_meter': '2000',
        'source': commission.cite('design'), 'customer_basis': commission.cite('scope')}
    assert commission_plan.save_plan(commission.cs, commission.co, 'h32-valid-membership', plan)['ok']



def test_exposed_section_schema_explains_anchor_and_exclusive_source_modes(linked):
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from report_agent.native_operation_tools import native_write_tools
    from test_m1_g4_planning_steps import current_native_profiles
    current_native_profiles(linked)
    tools = native_write_tools(linked.ws, 'coordinator', planning.planning_tools(linked.cs, lambda: linked.co))
    tool = next(tool for tool in tools if getattr(tool, 'name', None) == 'add_section')
    properties = convert_to_openai_tool(tool)['function']['parameters']['properties']
    assert 'ID' in properties['outline_anchor_id']['description']
    assert 'locator' in properties['outline_anchor_id']['description']
    assert 'sources' in properties['source_span']['description']
    assert 'source_span' in properties['sources']['description']
    assert 'extracted' in properties['sources']['description']


def test_both_section_source_modes_explain_exact_exclusive_choice(linked):
    fn = next(f for f in planning.planning_tools(linked.cs, lambda: linked.co) if f.__name__ == 'add_section')
    anchor = next(a for a in linked.anchors if a['kind'] == 'section' and a['section_id'] == '4')
    with pytest.raises(ActionRejected) as caught:
        fn(operation_id='h32-both-source-modes', section_id='4', title='Assessment', kind='extracted',
           outline_anchor_id=anchor['id'], sources=[linked.cite('design')],
           source_span={'source_ref': linked.cite('design')['source_ref'], 'start_page': 1, 'end_page': 1,
                        'start_sentence': 'start', 'end_sentence': 'end', 'profile_id': 'profile'})
    issue = caught.value.diagnostic['fields'][0]
    assert issue['field'] == 'sources'
    assert issue['choices'] == ['source_span', 'sources']
    assert issue['related_fields'] == ['source_span']
    assert 'omit source_span' in issue['message']


def test_profile_for_another_source_explains_extracted_citation_alternative(text_source):
    planning.install_text_profile(text_source.cs, text_source.text_profile)
    selection = {**text_source.selection, 'source_ref': text_source.cite('design')['source_ref']}
    with pytest.raises(ActionRejected) as caught:
        planning.resolve_source_span(text_source.cs, selection)
    issue = caught.value.diagnostic['fields'][0]
    assert issue['field'] == 'source_span.profile_id' and issue['choices'] == []
    assert 'extracted' in issue['message'] and 'omit source_span' in issue['message']
    assert 'fixed' in issue['message']


def test_typed_outline_locator_is_rejected_with_actual_anchor_ids(linked):
    fn = next(f for f in planning.planning_tools(linked.cs, lambda: linked.co) if f.__name__ == 'add_section')
    anchor = next(a for a in linked.anchors if a['kind'] == 'section' and a['section_id'] == '4')
    with pytest.raises(ActionRejected) as caught:
        fn(operation_id='h32-locator-as-anchor', section_id='4', title='Assessment', kind='extracted',
           outline_anchor_id=anchor['source']['locator'], sources=[linked.cite('design')])
    issue = caught.value.diagnostic['fields'][0]
    assert issue['field'] == 'outline_anchor_id'
    assert issue['choices'] == [anchor['id']]
    assert 'locator' in issue['message'] and 'ID' in issue['message']


def inventory_mismatch(plan):
    result = deepcopy(plan)
    result['inventory_attributes'] = ['height', 'length']
    base = deepcopy(result['objects'][0]['attributes'][0])
    result['objects'] = [deepcopy(result['objects'][0]), deepcopy(result['objects'][0])]
    result['objects'][0]['object_id'] = 'S1'
    result['objects'][1]['object_id'] = 'S2'
    for obj, names in zip(result['objects'], [['height', 'height', 'width'], ['height ', 'length']]):
        obj['attributes'] = [{**deepcopy(base), 'name': name} for name in names]
    return result


def assert_inventory_fields(fields):
    assert [f['field'] for f in fields] == ['objects[0].attributes', 'objects[1].attributes']
    assert [f['object_id'] for f in fields] == ['S1', 'S2']
    assert fields[0]['expected'] == ['height', 'length']
    assert fields[0]['actual'] == ['height', 'height', 'width']
    assert fields[0]['missing'] == ['length'] and fields[0]['extra'] == ['width']
    assert fields[0]['duplicates'] == ['height']
    assert fields[1]['missing'] == ['height'] and fields[1]['extra'] == ['height ']
    assert fields[1]['duplicates'] == []


def test_inventory_model_reports_every_object_without_normalizing_names(commission):
    from report_agent.planning_inputs import model_value
    value = inventory_mismatch(commission.plan)
    before = deepcopy(value)
    with pytest.raises(ActionRejected) as caught:
        model_value(commission_plan.CommissionPlan, value)
    assert_inventory_fields(caught.value.diagnostic['fields'])
    assert str(caught.value).startswith('PLANNING_FIELDS_INVALID: ')
    assert 'objects[0].attributes: COMMISSION_INVENTORY_ATTRIBUTES_INCOMPLETE' in str(caught.value)
    assert 'objects[1].attributes: COMMISSION_INVENTORY_ATTRIBUTES_INCOMPLETE' in str(caught.value)
    assert 'width' not in str(caught.value), 'Do not serialize values, choices, or raw model input into the outer summary.'
    assert value == before


def test_inventory_direct_save_has_same_fields_and_no_write(commission):
    before = commission.cs.list_objects()
    with pytest.raises(ActionRejected) as caught:
        commission_plan.save_plan(commission.cs, commission.co, 'h32-inventory-direct', inventory_mismatch(commission.plan))
    assert_inventory_fields(caught.value.diagnostic['fields'])
    assert commission.cs.list_objects() == before


def test_inventory_draft_and_submit_show_each_object(draft_case):
    from test_m1_g4_planning_steps import save_draft_parts
    draft_case.plan = inventory_mismatch(draft_case.plan)
    view = save_draft_parts(draft_case)
    gaps = [g for g in view['gaps'] if g['code'] == 'COMMISSION_INVENTORY_ATTRIBUTES_INCOMPLETE']
    assert_inventory_fields([{**g, 'field': g['path']} for g in gaps])
    with pytest.raises(ActionRejected) as caught:
        planning.submit_plan(draft_case.cs, draft_case.co, 'h32-inventory-submit')
    actual = [g for g in caught.value.diagnostic['gaps'] if g['code'] == 'COMMISSION_INVENTORY_ATTRIBUTES_INCOMPLETE']
    assert actual == gaps
    assert not draft_case.cs.list_objects('CommissionPlan')


def test_inventory_order_remains_set_based_and_bad_contract_precedes_objects(commission):
    from pydantic import ValidationError
    value = inventory_mismatch(commission.plan)
    for obj in value['objects']:
        base = obj['attributes'][0]
        obj['attributes'] = [{**deepcopy(base), 'name': n} for n in ['length', 'height']]
    assert commission_plan.CommissionPlan.model_validate(value)
    value['inventory_attributes'] = ['height', 'height']
    with pytest.raises(ValidationError, match='COMMISSION_INVENTORY_ATTRIBUTE_CONTRACT_INVALID'):
        commission_plan.CommissionPlan.model_validate(value)


@pytest.mark.parametrize('locator', ['typed nonexistent locator', None])
def test_strict_quote_error_preserves_legacy_code_and_fields(linked, locator):
    cite = deepcopy(next(a['source'] for a in linked.anchors if a['kind'] == 'scope'))
    if locator is not None: cite['locator'] = locator
    cite['quote'] = 'This fabricated assertion is absent.'
    with linked.cs.store.connect() as db:
        with pytest.raises(ActionRejected) as caught:
            commission_plan._validate_sources(linked.cs, db, linked.co, {'source': cite})
    assert str(caught.value) == 'COMMISSION_QUOTE_NOT_AT_SOURCE_LOCATION'
    field = caught.value.diagnostic['fields'][0]
    assert field['field'] == ('source.locator' if locator else 'source.quote')
    assert field['choices'] == []


@pytest.mark.parametrize('kind', ['artifact', 'location', 'page'])
def test_other_strict_source_codes_remain_exact(text_source, kind, monkeypatch):
    from types import SimpleNamespace
    fixture = text_source
    citation = {'source_ref': deepcopy(fixture.text_ref), 'locator': 'page 999', 'quote': ''}
    cs = fixture.cs
    if kind == 'artifact':
        citation['source_ref']['type'] = 'ContentNode'
        cs = SimpleNamespace(_read=lambda db, ref: {'payload': {'source_id': 'unused'}})
        code, field = 'COMMISSION_SOURCE_ARTIFACT_REQUIRED', 'source.source_ref'
    elif kind == 'location':
        citation['locator'] = 'unknown locator'
        code, field = 'COMMISSION_SOURCE_LOCATION_UNAVAILABLE', 'source.locator'
    else:
        from io import BytesIO
        from pypdf import PdfWriter
        import report_agent.document_tools as documents
        pdf = PdfWriter(); pdf.add_blank_page(width=100, height=100)
        stream = BytesIO(); pdf.write(stream)
        monkeypatch.setattr(documents, '_original', lambda *args: ('synthetic.pdf', stream.getvalue()))
        code, field = 'COMMISSION_SOURCE_PAGE_OUTSIDE_DOCUMENT', 'source.locator'
    with fixture.cs.store.connect() as db:
        with pytest.raises(ActionRejected) as caught:
            commission_plan._validate_sources(cs, db, fixture.co, {'source': citation})
    assert str(caught.value) == code
    assert caught.value.diagnostic['fields'][0]['field'] == field
