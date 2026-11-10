"""Part a: a bound quote is eligible without pretending its value was confirmed."""
from uuid import NAMESPACE_URL, uuid5
import pytest
from report_agent import assertions
from report_agent.assertion_host import AssertionHost, Grant


def issue(host, role, action, call, packet=(), resources=None):
    grant = Grant(str(uuid5(NAMESPACE_URL, role)), role, role, call, "plan",
                  {"A"}, set(packet), {action}, resources=resources or {})
    return host.issue_once(grant, action, call)


def test_bound_quote_and_method_evaluate_without_confirming_the_value(tmp_path):
    host = AssertionHost(tmp_path)
    page = dict(source_version="design-v1", page=1)
    binding = assertions.record_convention(
        issue(host, "coordinator", "record_convention", "bind", ["design-v1"]),
        subject="A", claim=dict(kind="convention", scope="source_page_binding",
        rule="plan", page_binding=dict(indicator_id="height", pages=[page])))
    def confirm(key, call):
        return assertions.confirm(issue(host,"owner","confirm",call,[key]), subject="A",
            claim=dict(kind="act",effect="confirm",target=key,reason="One sheet reply"))
    source_claim = dict(kind="source",predicate="height",state="value",value=18,
                        coverage="A",citation={**page,"quote":"Height 18 m"})
    ground = [dict(assertion_id=binding["id"],purpose="context",proposition="source_page_binding")]
    resources = {"sources":{"design-v1":{"pages":{"1":"Height 18 m","2":"Height 18 m"}}}}
    def extract(call, claim=source_claim):
        return assertions.assert_source(issue(host,"writer","assert_source",call,
            [binding["id"],"design-v1"],resources), subject="A",claim=claim,grounds=ground)
    with pytest.raises(ValueError,match="C3"):
        extract("unconfirmed")
    confirm(binding["id"],"confirm-binding")
    source = extract("extract")
    assert source["claim"]["value"] == 18
    bad = {**source_claim,"citation":{**page,"page":2,"quote":"Height 18 m"}}
    with pytest.raises(ValueError,match="C3"):
        extract("wrong-page",bad)
    criterion = assertions.record_convention(issue(host,"coordinator","record_convention","criterion"),
        subject="A",claim=dict(kind="convention",scope="criterion",rule="height",criterion_version="v1"))
    confirm(criterion["id"],"confirm-criterion")
    method = dict(version="v1", bands={"low":{"min":"0","max":"24"}},
        value_policy="confirmed_midpoint",purposes={"classification":["height"],"adjustment":["height"]},
        adjustments=[dict(direction="higher",when=[dict(predicate="height",value=18)])],
        readings=[[dict(classification="low",when=[dict(predicate="height",value=18)])]])
    row = assertions.save_judgment(issue(host,"writer","save_judgment","save",
        [source["id"],criterion["id"]],{"criteria":{criterion["id"]:method}}),
        subject="A", claim=dict(kind="judgment",basis="evidence",classification="low",value="12",
        warrant=dict(criterion=criterion["id"],criterion_version="v1",rationale="Height quoted")),
        grounds=[dict(assertion_id=source["id"],purpose="classification",proposition="height")])
    adjusted = assertions.save_judgment(issue(host,"writer","save_judgment","adjust",
        [source["id"],criterion["id"]],{"criteria":{criterion["id"]:method}}),subject="A",
        claim={**row["claim"],"value":"13","review_flags":["REVIEW_ADJUSTMENT"],
               "adjustment":dict(proposed="13",disposition="accepted_with_flag",
                    rationale="Supported direction",ground_ids=[source["id"]])},
        grounds=[*row["grounds"],dict(assertion_id=source["id"],purpose="adjustment",proposition="height")])
    assert adjusted["claim"]["value"] == "13"
    view = assertions.packet(issue(host,"writer","ask","read",[source["id"],row["id"]]))
    assert assertions.status(issue(host,"writer","ask","status",[source["id"]]),source["id"])["status"] == "proposed"
    assertions.retract(issue(host,"owner","retract","withdraw",[binding["id"]]),subject="A",
        claim=dict(kind="act",effect="retract",target=binding["id"],reason="Wrong page applicability"))
    with pytest.raises(ValueError,match="C3"):
        assertions.save_judgment(issue(host,"writer","save_judgment","save-again",
            [source["id"],criterion["id"]],{"criteria":{criterion["id"]:method}}),
            subject="A",claim=row["claim"],grounds=row["grounds"])


def test_page_binding_sources_are_packet_checked(tmp_path):
    host=AssertionHost(tmp_path)
    with pytest.raises(ValueError,match="C4"):
        assertions.record_convention(issue(host,"coordinator","record_convention","escape"),
            subject="A",claim=dict(kind="convention",scope="source_page_binding",rule="plan",
            page_binding=dict(indicator_id="height",pages=[dict(source_version="unissued",page=1)])))


def test_single_saved_reply_redoes_missing_confirmations_only(tmp_path, monkeypatch):
    from report_agent import commission_assertions as records, page_bindings
    from report_agent.content_store import Actor, ContentStore
    from report_agent.store import Store, encode
    store=Store(tmp_path)
    cs=ContentStore(store)
    co=Actor("content:coordinator","coordinator","coord")
    owner=Actor("operator","operator","checkpoint:one")
    with store.connect() as db:
        plan=cs._insert(db,co,"CommissionPlan",{})
        decision=cs._insert(db,owner,"CommissionDecision",
            dict(plan_ref=plan,approved=True,unconfirmed_page_bindings=[]))
    host=AssertionHost(tmp_path)
    def binding(call):
        return assertions.record_convention(issue(host,"coordinator","record_convention",call,["v1"]),
            subject="A",claim=dict(kind="convention",scope="source_page_binding",rule=encode(plan),
                page_binding=dict(indicator_id=call,pages=[dict(source_version="v1",page=1)])))["id"]
    first,second=binding("X1"),binding("X2")
    checkpoint=dict(plan_ref=plan,page_bindings=[first,second])
    records.ask_checkpoint(store,co,"sheet","plan","sheet",checkpoint)
    records.answer_checkpoint(store,owner,"answer","plan","sheet",decision)
    actual=assertions.confirm
    calls=[]
    def interrupt(*args,**kwargs):
        calls.append(kwargs["claim"]["target"])
        if len(calls)==2: raise RuntimeError("stopped between confirm acts")
        return actual(*args,**kwargs)
    monkeypatch.setattr(assertions,"confirm",interrupt)
    with pytest.raises(RuntimeError,match="between"):
        page_bindings.confirm_reply(store,owner,"sheet",checkpoint,decision)
    later=binding("X3")
    monkeypatch.setattr(assertions,"confirm",actual)
    page_bindings.confirm_reply(store,owner,"sheet",checkpoint,decision)
    page_bindings.confirm_reply(store,owner,"sheet",checkpoint,decision)
    states=host.commission.current_references(tmp_path,[first,second,later])
    assert [states[k]["status"] for k in (first,second,later)]==["confirmed","confirmed","proposed"]
    assert len([row for row in page_bindings.records(store,plan) if row[0]["id"] in (first,second)])==2
