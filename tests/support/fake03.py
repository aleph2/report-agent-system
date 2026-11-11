"""The two-slope fixture, including its excluded object and scripted owner decisions."""
import hashlib
import json
from pathlib import Path

from report_agent.fact_attestations import attestations_for, load_attestations
from report_agent.scripted_fact_import import install_facts, reviewed_register

REGISTER = Path(__file__).resolve().parents[1] / "fake_data/mini_commission/confirmed-facts.json"
TYPED_REGISTER = REGISTER.with_name("attestations.json")


def qualitative_profile(pin):
    register, typed, reviews, _ = reviewed_register(REGISTER.parent, pin)
    return {"facts": {oid:dict(source_roles=register["source_roles"], scope=register["scope"],
                engineering_reviews=reviews.get(oid,{}), attestations=attestations_for(typed,oid),
                observations=[r for r in register["facts"] if r["applies_to"] in (oid,"A, B","Region")],
                unresolved=unknowns) for oid,unknowns in register["unresolved"].items()},
            "midpoint_convention":register["midpoint_convention"], "register_sha256":pin}


def install(ws, plan, profile=None, section_id="3"):
    pin = hashlib.sha256(REGISTER.read_bytes()).hexdigest()
    register, typed, reviews, selection = reviewed_register(REGISTER.parent, pin)
    from report_agent.content_store import ContentStore
    from report_agent.writer_judgment_authority import rule_pin
    rules = {r['id']:r for r in ContentStore(ws.store).read(plan)['payload']['method_pack']['indicators']}
    for key, interpretation in selection.get('criteria', {}).items():
        rule = rules[key]
        semantics = {k:v for k,v in rule.items() if k not in
                     {'display_label', 'category_display_label', 'presentation_rows'}}
        assert rule_pin(semantics) == interpretation['rule_digest'], 'Synthetic criterion semantics changed'
        interpretation['rule_digest'] = rule_pin(rule)
    if profile is None:
        return install_facts(ws.store, plan, section_id, register, typed, reviews, selection, pin)
    facts = profile["facts"]
    observations = {oid:f["observations"] for oid,f in facts.items()}
    observed = {json.dumps(row,sort_keys=True):row for rows in observations.values() for row in rows}
    assigned = {oid:f.get("attestations") for oid,f in facts.items()}
    chosen = {r["fact_id"]:r for rows in assigned.values() for r in rows or ()}
    canonical = {r["fact_id"] for r in typed}
    if chosen.keys() <= canonical and chosen:
        # The out-of-scope location is still registered, never offered to these Writers.
        chosen.update({r["fact_id"]:r for r in typed if r["subject"]=="C"})
    register["facts"] = [*observed.values(), *(r for r in register["facts"] if r["applies_to"]=="C")]
    reviews = ({oid:f.get("engineering_reviews",{}) for oid,f in facts.items()}
               if any("engineering_reviews" in f for f in facts.values()) else None)
    available = set(chosen)
    selection["conflicts"] = [c for c in selection["conflicts"] if set(c["observations"]) <= available]
    return install_facts(ws.store,plan,section_id,register,list(chosen.values()),reviews,selection,pin,
                         assigned_observations=observations,assigned_attestations=assigned)
