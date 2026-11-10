"""Issue independent, owner-confirmed synthetic inputs for non-qualitative Writer tests."""
from uuid import NAMESPACE_URL, uuid5

from report_agent import assertions
from report_agent.assertion_host import AssertionHost, Grant
from report_agent.source_use import source_version_material
from report_agent.store import digest
from report_agent.writer_judgment_authority import grant_judgment_inputs, rule_pin


def install_test_judgment_inputs(f, subject, source_id, page, quote, *, classifications=None, section_id="4",
                                 observation=None):
    host = AssertionHost(f.cs.store.root)
    plan = digest(f.plan_ref)
    version, material = source_version_material(f.cs, source_id)
    if quote not in material["pages"][str(page)]:
        raise ValueError("Synthetic observation must occur on the original physical page")

    def write(role, action, claim, packet):
        principal = str(uuid5(NAMESPACE_URL, "synthetic-fixture/" + role))
        call = digest([subject, action, claim])
        grant = Grant(principal, role, "fixture-inputs", call, plan, frozenset({subject}),
                      frozenset(packet), frozenset({action}), resources={"sources": {version: material}})
        bound = host.issue_once(grant, action, call)
        return getattr(assertions, action)(bound, subject=subject, claim=claim)["id"]

    condition = observation or {"predicate": "synthetic_observation", "value": "present", "coverage": "object"}
    predicate = condition["predicate"]
    fact = write("owner", "assert_source", {
        "kind": "source", "state": "value", **condition,
        "citation": {"source_version": version, "page": page, "quote": quote},
    }, [version])
    write("owner", "confirm", {
        "kind": "act", "effect": "confirm", "target": fact,
        "reason": "Checked the fixture observation against the supplied page.",
    }, [fact])
    criteria = {}
    for rule in f.cs.read(f.plan_ref)["payload"]["method_pack"]["indicators"]:
        if classifications is not None and rule["id"] not in classifications:
            continue
        grade = classifications[rule["id"]] if classifications is not None else rule["grades"][1]["id"]
        criteria[rule["id"]] = {
            "rule_digest": rule_pin(rule),
            "readings": [[{"classification": grade, "when": [condition]}]],
            "purposes": {"classification": [predicate], "assumption": [predicate]},
        }
    grant_judgment_inputs(f.cs.store, f.plan_ref, subject, section_id, [fact, version], criteria)


def save_reviewed_score(f, actor, subject, quote):
    """Use the synthetic four-indicator method and the survey already commissioned for this slope."""
    from report_agent.assessment_refresh import refresh_selected_assessment
    from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
    host = AssertionHost(f.cs.store.root)
    for indicator in ('A', 'B', 'C', 'D'):
        step = read_indicator_step(f.cs, actor)
        assert step['indicator_id'] == indicator
        save_indicator_outcome(f.cs, actor, 'judge-' + subject + '-' + indicator, indicator, dict(
            kind='evidence', grade=step['grades'][1]['choice'], value='40', basis_kind='direct_evidence',
            rationale='The commissioned survey records the synthetic observation for ' + subject + '.', quotes=[quote]))
    for entry in read_indicator_step(f.cs, actor)['outcomes'].values():
        key = entry['assertion_id']
        grant = Grant(str(uuid5(NAMESPACE_URL, 'test/owner')), 'owner', 'review', key,
                      digest(f.plan_ref), {subject}, {key}, {'confirm'})
        assertions.confirm(host.issue(grant, 'confirm', 'review-' + key), subject=subject,
            claim=dict(kind='act', effect='confirm', target=key, reason='Verified synthetic input'))
    assert refresh_selected_assessment(f.cs, subject)['status'] == 'scored'
