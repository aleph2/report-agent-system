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
    fact = write("coordinator", "assert_source", {
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
