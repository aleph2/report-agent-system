"""Exercise the normal proposal and owner checkpoint when a synthetic case needs a plan."""
from copy import deepcopy
from report_agent import commission_plan
from report_agent.store import encode


def save(fixture, plan=None, operation="save-plan"):
    return commission_plan.save_plan(fixture.cs, fixture.co, operation, plan or fixture.plan)["result"]


def approve(fixture, saved, *, reductions=(), requirements_ref=None):
    checkpoint = commission_plan.request_checkpoint(fixture.ws)
    decision = dict(plan_ref=saved["plan_ref"], approved=True, corrections="", reductions=list(reductions))
    if requirements_ref is not None:
        decision["requirements_ref"] = requirements_ref
    commission_plan.reply(fixture.ws, checkpoint["issue_id"], decision)
    return checkpoint, decision


def install_confirmed_plan(fixture, *, requirements_ref=None):
    saved = save(fixture)
    checkpoint, decision = approve(fixture, saved, requirements_ref=requirements_ref)
    return saved, checkpoint, decision


def confirmed_records(fixture):
    with fixture.cs.store.connect() as db:
        return commission_plan._confirmed(fixture.cs, db)


def plan_action_id(fixture, action, ref):
    import json
    import sqlite3
    from contextlib import closing

    field = "rule" if action == "record_convention" else "reason"
    with closing(sqlite3.connect(fixture.ws.store.root / "assertions.sqlite3")) as db:
        for identity, body in db.execute("SELECT id,body FROM assertions WHERE action=?", (action,)):
            if json.loads(body)["claim"][field] == encode(ref):
                return identity
    raise AssertionError(f"Missing {action} for {ref}")


def enroll_planning_file(fixture, filename, source_id, purpose):
    """Give this supplied fixture file its role in the commission intake."""
    from report_agent import commission_imports
    current = commission_imports.source_roles(fixture.ws.store, {})
    commission_imports.install_source_roles(fixture.ws.store, {
        **current, filename: {'id': source_id, 'purpose': purpose}})


def synthetic_pilot_plan(fixture, *, version=2, presentation_source='template'):
    """Synthetic reviewed presentation data; source transcription is tested separately."""
    plan = deepcopy(fixture.plan)
    pack = plan['method_pack']
    pack['version'] = version
    pack['presentation_sources'] = [fixture.cite(presentation_source)]
    pack['display_labels'] = {'total': '合计'}
    for indicator in pack['indicators']:
        indicator['display_label'] = '指标 ' + indicator['id'] if version == 2 else indicator['label']
        indicator['category_display_label'] = '地质条件'
        indicator['presentation_rows'] = []
        for grade in indicator['grades']:
            conditions = ['条件甲', '条件乙'] if indicator['id'] == 'C' and grade['id'] in ('g2', 'g3') else ['']
            for condition in conditions:
                indicator['presentation_rows'].append({'grade_id': grade['id'],
                    'description': grade['description'], 'condition': condition,
                    'description_group_id': grade['id']})
    from report_agent.method_pack import register_reviewed_method_pack
    register_reviewed_method_pack(fixture.cs.store, pack, 'Independent synthetic table contract fixture.')
    import json
    from importlib.resources import files
    specs = json.loads(files('report_agent').joinpath('methods/high_slope_tables.json').read_text())['table_specs']
    for role, spec in specs.items():
        spec.pop('source_pages')
        spec['sources'] = [fixture.cite(presentation_source)]
        spec['table_type'] = 'synthetic_rank' if role == 'ranking' else 'synthetic_evaluation'
    plan['table_specs'] = specs
    return plan
