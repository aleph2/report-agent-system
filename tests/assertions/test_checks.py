"""Trusted inputs for the immutable S2 review SQL."""
import json
import sqlite3

import pytest

from report_agent.assertions.evidence import evidence_projection
from report_agent.assertions.schema.kinds import Assertion


def assertion(identifier, kind, subject="A", grounds=(), **fields):
    return Assertion.model_validate(dict(
        id=identifier, subject=subject, claim=dict(kind=kind, **fields),
        grounds=grounds, was_attributed_to="writer", was_generated_by="activity",
        operation_id=identifier+"-operation", observed_at="2026-01-01T00:00:00Z",
        recorded_at="2026-01-01T00:00:00Z", schema_version="s2-proposal-1",
        check_version="s2-proposal-2"))


def db_with(*rows):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE assertions(id TEXT PRIMARY KEY,body TEXT)")
    db.executemany("INSERT INTO assertions VALUES(?,?)", [(r.id,r.model_dump_json()) for r in rows])
    return db


def test_citations_are_verified_against_exact_version_page_and_delivery():
    claim = dict(predicate="capacity", state="value", coverage="object", value=3,
                 citation=dict(source_version="v1", page=2, quote="Three spans"), evidence_receipts=["read2"])
    source = assertion("s", "source", **claim)
    resources = dict(sources={"v1":{"pages":{"1":"Other.", "2":"Three spans in use."}}},
                     receipts={"read2":dict(actor="writer",source_version="v1",page=2)})
    evidence_projection(db_with(),source,resources,{})
    for alteration in [dict(page=1),dict(source_version="v2"),dict(actor="other")]:
        with pytest.raises(ValueError, match="C2"):
            evidence_projection(db_with(), source, {**resources,"receipts":{"read2":resources["receipts"]["read2"]|alteration}}, {})
    with pytest.raises(ValueError, match="C2"):
        evidence_projection(db_with(), assertion("s","source",**(claim|dict(citation=dict(
            source_version="v1",page=1,quote="Three spans")))),resources,{})


def test_declared_method_applies_only_to_confirmed_current_records_and_cited_grounds():
    criterion = assertion("method","convention",rule="method",scope="case",criterion_version="v1")
    def fact(i, subject="A", **overrides):
        return assertion(i,"source",subject,**(dict(predicate="capacity",state="value",value=3,
            coverage="object",citation=dict(source_version="v1",page=2,quote="Three spans"))|overrides))
    grounds=[dict(assertion_id="s",purpose="classification",proposition="capacity")]
    judgment=assertion("j","judgment",grounds=grounds,basis="evidence",
               warrant=dict(criterion="method",criterion_version="v1",rationale="Three spans"),classification="low",value=12)
    method={"version":"v1","bands":{"low":{"min":"0","max":"24"}},"value_policy":"confirmed_midpoint",
            "readings":[[{"classification":"low","when":[{"predicate":"capacity","coverage":"object","value":3}]}]]}
    resources={"criteria":{"method":method}}
    db=db_with(criterion,fact("s"),fact("other","B"))
    states={i:dict(status="confirmed",stale=False) for i in ("method","s","other")}
    ctx=evidence_projection(db,judgment,resources,states)
    assert ctx["applicable_readings"]==["low"] and ctx["readings_exhaustive"]
    assert ctx["records"]["method"]["bands"]["low"]["midpoint"]=="12"
    assert ctx["records"]["s"]["supports"]==["capacity"]
    for changes in [dict(status="proposed"),dict(stale=True)]:
        ctx=evidence_projection(db,judgment,resources,{**states,"s":states["s"]|changes})
        assert not ctx["readings_exhaustive"]
    empty=judgment.model_copy(update={"grounds":()})
    assert not evidence_projection(db,empty,resources,states)["readings_exhaustive"]
    # A conflicting method interpretation leaves evidence ambiguous even if one reading agrees.
    method["readings"].append([{"classification":"moderate","when":[{"predicate":"capacity","value":3}]}])
    method["bands"]["moderate"]={"min":"25","max":"49"}
    assert set(evidence_projection(db,judgment,resources,states)["applicable_readings"])=={"low","moderate"}


def test_question_flags_and_refused_adjustment_preserve_the_supported_grade():
    from report_agent.assertions.evidence import normalize_judgment
    method = assertion("m","convention",rule="survey",scope="pilot",criterion_version="v1")
    question = assertion("q","question",text="Would the season change the grade?",affects="classification")
    fact = assertion("s","source",predicate="count",coverage="object",state="value",value=3,
                     citation={"source_version":"doc","page":1,"quote":"three"})
    judge = assertion("j","judgment",grounds=[
        dict(assertion_id="s",purpose="classification",proposition="count"),
        dict(assertion_id="s",purpose="adjustment",proposition="count")],
        basis="evidence",warrant=dict(criterion="m",criterion_version="v1",rationale="three"),
        classification="moderate",value="49", question="q",review_flags=["proposal"],
        adjustment=dict(proposed="49",disposition="accepted_with_flag",ground_ids=["s"],rationale="limited coverage"))
    methods={"m":dict(version="v1",bands={"moderate":{"min":"25","max":"49"}},
             value_policy="confirmed_midpoint",question_effect="value",
             readings=[[dict(classification="moderate",when=[dict(predicate="count",value=3)])]])}
    states = {i:dict(status="confirmed",stale=False) for i in ("m","s","q")}
    proj=evidence_projection(db_with(method,question,fact),judge,{"criteria":methods},states)
    claim=normalize_judgment(judge,proj)
    assert str(claim.value)=="37" and claim.classification=="moderate" and claim.question=="q"
    assert claim.adjustment.disposition=="refused_midpoint_retained" and str(claim.adjustment.proposed)=="49"
    assert {"QUESTION_EFFECT_CONFLICT","UNSUPPORTED_ADJUSTMENT_RETAINED_MIDPOINT"} <= set(claim.review_flags)
    assert claim.adjustment.rationale=="limited coverage"


def test_unquoted_fact_from_other_subject_is_neither_direct_nor_implicit_transfer():
    m = assertion("m","convention",rule="classify",scope="pilot",criterion_version="v1")
    a = assertion("a","source",subject="B",predicate="capacity",coverage="object",state="value",value=3,
                  citation=dict(source_version="doc",page=1,quote="three"))
    t = assertion("t","convention",rule="transfer",scope="B to A",criterion_version="v1")
    judge = assertion("j","judgment",basis="evidence",classification="L",value=4,
            grounds=[dict(assertion_id="a",purpose="classification",proposition="capacity",transfer_convention="t")],
            warrant=dict(criterion="m",criterion_version="v1",rationale="capacity"))
    resources = {"criteria":{"m":dict(version="v1",value_policy="criterion_range",bands={"L":{"min":0,"max":8}},
                   readings=[[dict(classification="L",when=[dict(predicate="capacity",value=3)])]])},
                 "conventions":{"t":dict(rule="transfer",scope="B to A",version="v1",
                                         **{"from":"B","to":"A","proposition":"capacity"})}}
    states={k:dict(status="confirmed",stale=False) for k in ("m","t","a")}
    db=db_with(m,t,a)
    assert evidence_projection(db,judge,resources,states)["readings_exhaustive"]
    assert not evidence_projection(db,judge,resources,{**states,"t":states["t"]|{"stale":True}})["readings_exhaustive"]
    resources["conventions"]["t"]["purposes"]=["context"]
    with pytest.raises(ValueError,match="C5"):
        evidence_projection(db,judge,resources,states)


def test_strength_tracks_current_confirmation_and_conflicts_require_the_preferred_ground():
    a = assertion("a","source",predicate="count",coverage="object",state="value",value=3,
                  citation=dict(source_version="doc",page=1,quote="three"))
    b = assertion("b","source",predicate="count",coverage="object",state="unknown")
    conv = assertion("p","convention",rule="precedence",scope="count",criterion_version="v1")
    conflict = assertion("c","conflict",observations=["a","b"],precedence_convention="p")
    d = assertion("d","derived",rule_version="v1",inputs=["a","b"],strength="undetermined")
    resources={"conventions":{"p":dict(rule="precedence",scope="count",version="v1",resolves="c",preferred="a")},
               "rules":{"v1":{"version":"v1"}}}
    states={k:dict(status="confirmed",stale=False) for k in ("a","b","p","c")}
    db=db_with(a,b,conv,conflict)
    ctx=evidence_projection(db,d,resources,states)
    assert ctx["records"]["a"]["strength_rank"]==2 and ctx["records"]["b"]["strength_rank"]==0
    assert ctx["records"]["a"]["conflicts"]==[{"id":"c","precedence":"p"}]
    assert ctx["records"]["p"]["preferred"]=="a"
    assert evidence_projection(db,d,resources,{**states,"a":states["a"]|{"stale":True}})["records"]["a"]["strength_rank"]==0
    bad_binding=resources|{"conventions":{"p":resources["conventions"]["p"]|{"version":"v2"}}}
    assert "preferred" not in evidence_projection(db,d,bad_binding,states)["records"]["p"]


def test_known_image_only_observation_needs_actual_image_receipt():
    material={"pages":{"1":"label 24 m"},"image_pages":[1]}
    claim=dict(predicate="label",coverage="object",state="value",value=24,
               citation=dict(source_version="drawing",page=1,quote="24 m"))
    source=assertion("s","source",**claim)
    with pytest.raises(ValueError,match="C2"):
        evidence_projection(db_with(),source,{"sources":{"drawing":material}},{})
    source=assertion("s","source",**claim,evidence_receipts=["image"])
    receipts={"image":dict(actor="writer",page=1,source_version="drawing",modality="text")}
    with pytest.raises(ValueError,match="C2"):
        evidence_projection(db_with(),source,{"sources":{"drawing":material},"receipts":receipts},{})
    receipts["image"]["modality"]="image"
    evidence_projection(db_with(),source,{"sources":{"drawing":material},"receipts":receipts},{})


def test_interpretation_cannot_be_cherry_picked_by_leaving_a_confirmed_measurement_out():
    method = assertion("m","convention",rule="classify",scope="case",criterion_version="v")
    def measurement(key,value):
        return assertion(key,"source",predicate="count",coverage="object",state="value",value=value,
                         citation=dict(source_version="page",page=1,quote=str(value)))
    row=assertion("j","judgment",basis="evidence",classification="low",value=1,
        warrant=dict(criterion="m",criterion_version="v",rationale="selected the first observation"),
        grounds=[dict(assertion_id="one",proposition="count",purpose="classification")])
    facts=db_with(method,measurement("one",1),measurement("two",2))
    states={k:dict(status="confirmed",stale=False) for k in ("m","one","two")}
    read=lambda label,n:dict(classification=label,when=[dict(predicate="count",value=n)])
    spec=dict(version="v",value_policy="criterion_range",bands={"low":{"min":0,"max":1},"high":{"min":2,"max":3}},
              readings=[[read("low",1),read("high",2)]])
    ctx=evidence_projection(facts,row,{"criteria":{"m":spec}},states)
    assert set(ctx["applicable_readings"])=={"low","high"}
    from test_s2_assertion_contract import check
    assert "C7" in check(row.model_dump(),ctx|dict(role="writer", action="save_judgment",packet=["m","one","two"]))


def test_confirmed_precedence_removes_displaced_observation_from_applicable_readings():
    method=assertion("m","convention",rule="classify",scope="case",criterion_version="v")
    preferred=assertion("p","convention",rule="prefer",scope="type",criterion_version="v")
    conflict=assertion("c","conflict",observations=["new","old"],precedence_convention="p")
    def obs(key,value):
        return assertion(key,"source",predicate="colour",coverage="object",state="value",value=value,
                         citation=dict(source_version=key,page=1,quote=value))
    db=db_with(method,preferred,conflict,obs("new","green"),obs("old","red"))
    row=assertion("j","judgment",basis="evidence",classification="go",value=1,
        warrant=dict(criterion="m",criterion_version="v",rationale="use new source"),
        grounds=[dict(assertion_id="new",proposition="colour",purpose="classification")])
    states={key:dict(status="confirmed",stale=False) for key in ("m","p","c","new","old")}
    fixed={"rule":"prefer","scope":"type","version":"v","resolves":"c","preferred":"new"}
    resources={"conventions":{"p":fixed},"criteria":{"m":dict(version="v",value_policy="criterion_range",
        bands={"go":{"min":1,"max":1},"stop":{"min":0,"max":0}},readings=[[
            dict(classification="go",when=[dict(predicate="colour",value="green")]),
            dict(classification="stop",when=[dict(predicate="colour",value="red")])]])}}
    assert evidence_projection(db,row,resources,states)["applicable_readings"]==["go"]
    states["p"]["status"]="proposed"
    assert set(evidence_projection(db,row,resources,states)["applicable_readings"])=={"go","stop"}
