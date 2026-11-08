"""C1–C10 from authenticated production entry points on an empty commission."""
from hashlib import sha256
from uuid import NAMESPACE_DNS, uuid5

import pytest

from report_agent.assertion_host import AssertionHost, Grant
from report_agent.assertions import actions, queries


class Case:
    def __init__(self,root):
        self.host=AssertionHost(root)
        self.packet={"edition","calc-v1"}
        self.resources={"sources":{"edition":{"pages":{"1":"4 points; no other visits."}}},
                        "rules":{"calc-v1":{"version":"calc-v1"}},"criteria":{}}
        self.number=0

    def ctx(self,role,action,snapshot=None):
        self.number+=1
        grant=Grant(principal=str(uuid5(NAMESPACE_DNS,role)),role=role,task=role,attempt=str(self.number),
                    plan="pilot",subjects=frozenset({"sample"}),packet=frozenset(self.packet),
                    actions=frozenset({action}),resources=self.resources,snapshot=snapshot)
        return self.host.issue(grant,action,"call-"+str(self.number))

    def apply(self,role,action,claim,grounds=(),snapshot=None):
        row=getattr(actions,action)(self.ctx(role,action,snapshot),subject="sample",claim=claim,grounds=grounds)
        self.packet.add(row["id"])
        return row["id"]

    def confirm(self,key):
        self.apply("owner","confirm",dict(kind="act",effect="confirm",reason="accepted",target=key))

    def fact(self,state="value",n=4):
        observation=dict(kind="source",predicate="points",value=n if state=="value" else None,
            state=state,coverage="sample",citation=dict(source_version="edition",page=1,quote="4 points"))
        key=self.apply("coordinator","assert_source",observation)
        self.confirm(key)
        return key

    def method(self,readings):
        key=self.apply("coordinator","record_convention",dict(kind="convention",rule="count",scope="sample",criterion_version="v1"))
        self.confirm(key)
        self.resources["criteria"][key]=dict(version="v1",bands={"some":{"min":1,"max":8},"none":{"min":0,"max":0}},
            readings=readings, value_policy="criterion_range",purposes={"classification":["points"],"assumption":["points"]})
        return key

    def judgment(self,m,**change):
        return dict(kind="judgment",basis="evidence",classification="some",value=4,
                    warrant=dict(criterion=m,criterion_version="v1",rationale="counted points"))|change


def test_public_integrity_and_error_codes(tmp_path):
    c=Case(tmp_path)
    with pytest.raises(ValueError,match="C1"):
        c.apply("writer","ask",dict(kind="source",predicate="missing",coverage="sample",state="unknown"))
    with pytest.raises(ValueError,match="C2"):
        c.apply("coordinator","assert_source",dict(kind="source",predicate="visits",state="no_value",
            coverage="sample",citation=dict(source_version="edition",page=1,quote="no prior visit")))
    m=c.method([[dict(classification="some",when=[dict(predicate="points",value=4)])]])
    def classify(fact_id):
        return [dict(assertion_id=fact_id,proposition="points",purpose="classification")]
    u=c.fact("unknown")
    with pytest.raises(ValueError,match="C3"):
        c.apply("writer","save_judgment",c.judgment(m),classify(u))
    f=c.fact()
    c.packet.remove(f)
    with pytest.raises(ValueError,match="C4"):
        c.apply("writer","save_judgment",c.judgment(m),classify(f))
    c.packet.add(f)
    with pytest.raises(ValueError,match="C6"):
        c.apply("writer","save_judgment",c.judgment(m,value=99),classify(f))
    with pytest.raises(ValueError,match="C8"):
        c.apply("writer","save_judgment",c.judgment(m,basis="assumption",alternatives=["none","some"]),classify(f))
    c.packet.add("does-not-exist")
    gap=c.judgment(m,basis="gap",classification=None,value=None,question="does-not-exist")
    with pytest.raises(ValueError,match="C4"):
        c.apply("writer","save_judgment",gap)
    with pytest.raises(ValueError,match="C4"):
        c.apply("writer","save_judgment",gap|{"question":f})
    with pytest.raises(ValueError,match="C4"):
        c.apply("calculator","derive_result",dict(kind="derived",rule_version="calc-v1",inputs=["does-not-exist"],strength="undetermined"))
    with pytest.raises(ValueError,match="C4"):
        c.apply("writer","save_recommendation",dict(kind="recommendation",statement="review",basis=["does-not-exist"]))
    q=c.apply("writer","ask",dict(kind="question",text="How many points?",affects="classification"))
    pending=c.apply("writer","save_judgment",gap|{"question":q})
    c.confirm(pending)
    with pytest.raises(ValueError,match="C10"):
        c.apply("calculator","derive_result",dict(kind="derived",rule_version="calc-v1",inputs=[pending],strength="determined",value=4))
    c.apply("calculator","derive_result",dict(kind="derived",rule_version="calc-v1",inputs=[pending],strength="undetermined"))
    j=c.apply("writer","save_judgment",c.judgment(m),classify(f))
    c.apply("writer","save_recommendation",dict(kind="recommendation",statement="recheck regularly",basis=[j]))
    word,excel=b"draft",b"sheet"
    c.resources["snapshots"]={"frozen":{"members":{"output":j},"word":word,"excel":excel}}
    c.packet.add("frozen")
    c.apply("reviewer","record_finding",dict(kind="finding",target=j,snapshot="frozen",conclusion="passed"),snapshot="frozen")
    c.apply("layout","record_presentation_check",dict(kind="presentation_check",snapshot="frozen",
            artifact_digest=sha256(word).hexdigest(),check="legend",outcome="passed"),snapshot="frozen")
    assert queries.status(c.ctx("writer","ask"),j)["status"]=="proposed"


def test_conflicting_observation_and_ambiguous_method_stop_direct_save(tmp_path):
    c=Case(tmp_path)
    f=c.fact()
    other=c.fact("unknown")
    m=c.method([[dict(classification="some",when=[dict(predicate="points",value=4)])]])
    grounds=[dict(assertion_id=f,proposition="points",purpose="classification")]
    c.resources["criteria"][m]["readings"].append([dict(classification="none",when=[dict(predicate="points",value=4)])])
    with pytest.raises(ValueError,match="C7"):
        c.apply("writer","save_judgment",c.judgment(m),grounds)
    direct = c.method([[dict(classification="some",when=[dict(predicate="points",value=4)])]])
    c.apply("coordinator","record_conflict",dict(kind="conflict",observations=[f,other]))
    with pytest.raises(ValueError,match="C9"):
        c.apply("writer","save_judgment",c.judgment(direct),grounds)


def test_foreign_ground_requires_a_matching_transfer_even_when_in_packet(tmp_path):
    c=Case(tmp_path)
    grant=Grant(principal=str(uuid5(NAMESPACE_DNS,"coordinator")),role="coordinator",task="observe",
                attempt="1",plan="pilot",subjects=frozenset({"other"}),packet=frozenset(c.packet),
                actions=frozenset({"assert_source"}),resources=c.resources)
    ctx=c.host.issue(grant,"assert_source","external-fact")
    external=actions.assert_source(ctx,subject="other",claim=dict(kind="source",predicate="points",state="value",
        value=4,coverage="other",citation=dict(source_version="edition",page=1,quote="4 points")))["id"]
    c.packet.add(external)
    with pytest.raises(ValueError,match="C5"):
        c.apply("writer","save_recommendation",dict(kind="recommendation",statement="copy score",basis=[external]))
