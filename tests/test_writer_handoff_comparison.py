"""Offline regression for commission conventions across the two Writer handoff routes."""
from report_agent.catalog import Catalog
from report_agent.content_tasks import delegated_task
from report_agent.prompt_sources import NATIVE_REVIEW
from report_agent.writer_runtime import writer_tools
from test_m1_commission_plan import approve, save
from test_m1_g3_integration import method_commission


def test_both_writer_routes_preserve_the_same_confirmed_customer_record(method_commission):
    f = method_commission
    scope = 'Design prevails over survey. Customer indicator ranks: D=1, C=2, B=3, A=4.'
    source = Catalog(f.ws.store).import_file('scope-supplement.txt', scope.encode())['source']
    ref = f.cs.capture_sources(f.co, 'capture-supplement', [source['id']])['result']['source_refs'][0]
    with f.ws.store.connect() as db:
        locator = db.execute('SELECT locator FROM source_blocks WHERE source_id=?', (source['id'],)).fetchone()[0]
    roles = f.ws.store.get('commission_source_roles')
    roles['supplement'] = {'id': source['id'], 'purpose': 'commission'}
    f.ws.store.set('commission_source_roles', roles)
    citation = {'source_ref': ref, 'locator': locator, 'quote': scope}
    f.plan['conventions'].append({'interpretation': scope, 'source': citation})
    saved = save(f)
    approve(f, saved)
    f.ws.store.set('manifest', {**f.ws.store.manifest, 'assembly_contract': 'system-assembler-v1',
        'review_interface_profile': 'review-interfaces-v4', 'review_execution_mode': NATIVE_REVIEW,
        'review_entrypoint': 'delegated-reviewer-v1', 'delegation_prompt_profile': 'separate-description-v1',
        'operation_identity_profile': 'native-tool-runtime-v1'})

    goal = 'Assess S1 in section 4.'
    args = {'subagent_type': 'writer', 'description': goal, 'section_ids': ['4']}
    call = {'name': 'task', 'id': 'historical-section-handoff', 'args': args}
    with delegated_task(f.ws, 'coordinator', call) as (native, _):
        assert scope in native['args']['description']

    scoped = {**call, 'id': 'scoped-assessment-handoff', 'args': {**args, 'assessment_object_id': 'S1'}}
    with delegated_task(f.ws, 'coordinator', scoped) as (_, actor):
        tools = writer_tools(f.ws, actor, include_images=False, assessment_only=True)
        packet = next(t for t in tools if t.name == 'read_assignment').invoke({})
    observed = next(c for c in packet['owner_conventions'] if c['interpretation'] == scope)
    assert observed['source']['quote'] == scope
    assert observed['source']['location'] == locator
    assert packet['inventory_facts'][0]['values'][0]['value'] == '30 m'
    assert [v['indicator'] for v in packet['indicators']] == ['Indicator A', 'Indicator B', 'Indicator C', 'Indicator D']
