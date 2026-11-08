"""Replay the archived business proposals through production actions, with pinned source material."""
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from pypdf import PdfReader

from report_agent.assertion_host import AssertionHost, Grant
from report_agent.assertions import actions, queries
from report_agent.fake03_fact_register import REGISTER, TYPED_REGISTER, load_attestations
from report_agent.mini_commission import INPUT_SHA256
from report_agent.writer_assessment import _grade

from .cases import CASES, CURRENT_X51, RULES, historical_action


METHOD_FILE = files("report_agent").joinpath("methods/high_slope_guideline.assertions.proposal.json")
TRANSCRIPTION = json.loads(METHOD_FILE.read_bytes())
VERSION = sha256(METHOD_FILE.read_bytes()).hexdigest()


def method_definition(indicator, *, deferred):
    """The synthetic assignment's versioned bands, observation purposes and applicable readings."""
    criterion = next(x for x in TRANSCRIPTION["criteria"] if x["id"] == indicator)
    required = criterion["interpretation"]["required_purposes"]
    method = dict(version=VERSION, value_policy="confirmed_midpoint",
                  bands={s["grade"]:{"min":s["min"],"max":s["max"]} for s in criterion["source_assertions"]},
                  purposes={"classification":required,"assumption":required})
    if indicator == "X21":
        method["readings"] = [[dict(classification="moderate",when=[dict(predicate="weathering",value="强风化")])]]
    if indicator == "X41":
        method["readings"] = [[dict(classification="high",when=[dict(predicate="engineering_measure",value="锚杆框架梁")])]]
    if indicator == "X32":
        method["purposes"]["classification"] = required+["hazard_event"]
        method["purposes"]["assumption"] = ["hazard_event","location"]
        method["adjustments"] = [dict(direction="lower",when=[
            dict(predicate="hazard_event", coverage="region"),dict(predicate="location",coverage="region")])]
        method["question_effect"] = "value"
    if indicator == "X51":
        counts = [dict(predicate="survey_section_count",value=1), dict(predicate="borehole_count",value=3)]
        moderate = dict(classification="moderate",when=counts)
        method["readings"] = [[moderate]]
        if deferred:
            method["readings"].append([dict(classification="low",when=counts)])
    return method


class Commission:
    def __init__(self, root, deferred=False):
        self.host = AssertionHost(root)
        self.packet = set()
        self.resources = dict(sources={}, criteria={}, conventions={})
        self.facts = {}
        self.transfers = {}
        self.methods = {}
        self.calls = 0
        folder = REGISTER.parent/"inputs"
        observed=load_attestations(TYPED_REGISTER)
        for f in observed:
            name = f["document"]
            version = INPUT_SHA256[name]
            if version not in self.packet:
                source = folder/name
                assert sha256(source.read_bytes()).hexdigest() == version
                pages = {str(i):p.extract_text() for i,p in enumerate(PdfReader(source).pages,1)}
                self.resources["sources"][version] = dict(pages=pages)
                self.packet.add(version)
            source_id = self.save_confirmed("assert_source", f["subject"],dict(
                kind="source", predicate=f["purpose"], coverage=f["coverage"],
                state={"known":"value","unknown":"unknown","explicit_absence":"no_value"}[f["state"]],
                value=f["value"] if f["state"]=="known" else None,unit=f.get("unit"),
                citation=dict(source_version=version,page=f["page"],quote=f["quote"])))
            self.facts[f["fact_id"]] = source_id, f
            for target in set(f["related_to"]+f["applies_to"]) - {f["subject"]}:
                key = f["subject"], target, f["purpose"]
                if key in self.transfers:
                    continue
                transfer = self.convention("transfer "+f["purpose"],f["subject"]+" to "+target)
                self.resources["conventions"][transfer] = dict(rule="transfer "+f["purpose"],
                      scope=f["subject"]+" to "+target,version=VERSION, **{"from":f["subject"],"to":target,
                      "proposition":f["purpose"]})
                self.transfers[key] = transfer
        # The old importer attached background quotes from another slope to gap rows.
        # Model those as documentary context. They confer no evidentiary transfer.
        self.documentary_transfer=self.convention("document_scope_context","A to B")
        self.resources["conventions"][self.documentary_transfer] = {
            "rule":"document_scope_context","scope":"A to B","version":VERSION,
            "from":"A","to":"B","proposition":"document_scope_context","purposes":["context"]}
        for indicator in {s.split("/")[1] for s in CASES}:
            key = self.convention(indicator,"pilot")
            self.resources["criteria"][key]=method_definition(indicator,deferred=deferred)
            self.methods[indicator]=key

    def save_confirmed(self, action, subject, claim):
        row=self.call("coordinator",action,subject,claim)
        self.call("owner","confirm",subject,dict(kind="act",effect="confirm",target=row["id"],reason="Fake03 confirmation"))
        return row["id"]

    def convention(self, rule, scope):
        return self.save_confirmed("record_convention","pilot",dict(
            kind="convention",rule=rule,scope=scope,criterion_version=VERSION))

    def call(self, role, action, subject, claim, grounds=()):
        self.calls += 1
        grant=Grant(principal=str(uuid5(NAMESPACE_URL,"fake03/"+role)),role=role,task=role+"-task",
            attempt=role+"-attempt-"+str(self.calls),plan="fake03",subjects=frozenset({subject}),
            packet=frozenset(self.packet),actions=frozenset({action}),resources=self.resources)
        ctx=self.host.issue(grant,action,"call-"+str(self.calls))
        row=getattr(actions,action)(ctx,subject=subject,claim=claim,grounds=grounds)
        self.packet.add(row["id"])
        return row

    def reviewer_rows(self):
        grant = Grant(principal=str(uuid5(NAMESPACE_URL,"fake03/reviewer")),role="reviewer",
                      task="review",attempt="review-"+str(self.calls),plan="fake03",
                      subjects=frozenset({"A","B","Region","Project","C","pilot"}),
                      packet=frozenset(self.packet),actions=frozenset({"record_finding"}))
        ctx = self.host.issue(grant,"record_finding","review-"+str(self.calls))
        return {row["id"]:row for row in queries.packet(ctx) if row["claim"]["kind"]=="judgment"}

    def submit(self, label, pending=False):
        action, original=historical_action(label)
        subject,indicator=label.split("/")
        proposal=action.proposal
        grade_ids={_grade(g):g["id"] for g in RULES[indicator]["grades"]}
        kind="gap" if pending else original["kind"]
        question = ("Which X51 low-band convention applies?" if pending else original["question"])
        grounds=[]
        def attach(ids, purpose):
            for key in ids:
                i,f=self.facts[key]
                transfer=self.transfers.get((f["subject"],subject,f["purpose"]))
                proposition=f["purpose"]
                if not transfer and purpose=="context" and (f["subject"],subject)==("A","B"):
                    proposition,transfer="document_scope_context",self.documentary_transfer
                grounds.append(dict(assertion_id=i,purpose=purpose,proposition=proposition,transfer_convention=transfer))
        if kind == "gap":
            # The historical gap's exact question and warrant carry its missing information.
            attach(proposal.get("fact_ids",[]),"context")
        else:
            attach(proposal["grade_claim"]["fact_ids"],"classification")
            attach(proposal.get("assumption_basis",{}).get("fact_ids",[]),"assumption")
            attach(proposal.get("adjustment_claim",{}).get("fact_ids",[]),"adjustment")
        qid=None
        if question:
            qid=self.call("writer","ask",subject,dict(kind="question",text=question,
                affects="classification" if proposal.get("question_effect")=="grade" else "other"))["id"]
        claim=dict(kind="judgment",basis=kind,warrant=dict(criterion=self.methods[indicator],
            criterion_version=VERSION,rationale=original["rationale"] or original["missing"] or question),
            question=qid)
        if kind != "gap":
            claim.update(classification=grade_ids[original["grade"]],value=original["value"])
            if kind == "assumption":
                claim.update(alternatives=[grade_ids[g] for g in original["plausible_grades"]],
                             defeaters=[original["question"] or proposal["assumption_basis"]["narrowing"]])
            if prop := proposal.get("adjustment_claim"):
                claim.update(adjustment=dict(proposed=original["value"],disposition="accepted_with_flag",
                    rationale=original["value_reason"],ground_ids=[self.facts[f][0] for f in prop["fact_ids"]]),
                    review_flags=["ADJUSTMENT_REQUIRES_SEMANTIC_REVIEW"])
        if pending:
            claim["alternatives"]=CURRENT_X51["conditional_grades"]
        return self.call("writer","save_judgment",subject,claim,grounds)


@pytest.fixture(scope="module")
def commission(tmp_path_factory):
    return Commission(tmp_path_factory.mktemp("production-fake03"))


@pytest.mark.parametrize("label",CASES)
def test_production_replays_saved_fake03_business_fields(commission,label):
    original=historical_action(label)[1]
    verdict,flag=CASES[label]
    if verdict=="refused":
        before = commission.reviewer_rows()
        with pytest.raises(ValueError,match="C[357]"):
            commission.submit(label)
        assert commission.reviewer_rows() == before
        return
    row=commission.submit(label)
    claim=commission.reviewer_rows()[row["id"]]["claim"]
    assert claim==row["claim"]
    assert claim["basis"]==original["kind"] and bool(claim["question"])==bool(original["question"])
    grade_ids={_grade(g):g["id"] for g in RULES[label.split("/")[1]]["grades"]}
    assert claim["classification"] == grade_ids.get(original["grade"])
    assert claim["warrant"]["rationale"] == (original["rationale"] or original["missing"] or original["question"])
    if flag:
        assert flag in claim["review_flags"]
    if label=="A/X51":
        assert claim["classification"]=="moderate" and claim["value"]=="37"
        assert claim["adjustment"]["proposed"]=="49" and claim["adjustment"]["rationale"]==original["value_reason"]
    else:
        assert claim["value"]==original["value"]
    if label=="A/X32":
        assert claim["value"]=="27" and claim["classification"]=="moderate" and claim["question"]


def test_current_x51_stays_unscored_on_production_path(tmp_path):
    case=Commission(tmp_path,deferred=True)
    with pytest.raises(ValueError,match="C7"):
        case.submit("A/X51")
    claim=case.submit("A/X51",pending=True)["claim"]
    assert claim["basis"]=="gap" and claim["value"] is None and claim["classification"] is None
    assert claim["alternatives"]==["low","moderate"] and claim["question"]
