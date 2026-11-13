"""Native Writer extraction from owner-bound pages, with no confirmed-value register."""
import json
import pytest
from test_fake03_qualitative_steps import mini
from report_agent import assertions
from report_agent.assertion_host import AssertionHost
from report_agent.content_store import ContentStore
from report_agent.source_use import immutable_version_digest
from report_agent.store import encode
from report_agent.writer_assignments import bound_assignment
from report_agent.writer_runtime import writer_session
from test_9a_page_bindings import issue


def test_writer_tool_saves_quote_with_native_identity_without_confirming_value(mini):
    ws,binding,_=mini
    cs=ContentStore(ws.store)
    with writer_session(ws,"坡段 A",None,assessment_only=True,indicator_steps=True,section_id="3") as run:
        from report_agent.writer_assessment import read_indicator_step
        step=read_indicator_step(cs,run.actor)
        with ws.store.connect() as db:
            scope=bound_assignment(cs,db,run.actor)
            ref=next(r for r in scope["sources"] if "design" in cs._read(db,r)["payload"]["source_metadata"].get("title","").lower())
            payload=cs._read(db,ref)["payload"]
            quote=db.execute("SELECT text FROM source_blocks WHERE source_id=? AND locator LIKE 'page 1%'",
                             (payload["source_id"],)).fetchone()[0].strip()
        version=immutable_version_digest(payload)
        host=AssertionHost(ws.store.root)
        # Trusted fixture confirmation; the production fan-out has its own interrupted-reply test.
        grant=issue(host,"coordinator","record_convention","page-proposal",[version])
        proposal=assertions.record_convention(grant,subject="A",claim=dict(kind="convention",
            scope="source_page_binding",rule=encode(binding.plan_ref),
            page_binding=dict(indicator_id=step["indicator_id"],pages=[dict(source_version=version,page=1)])))
        assertions.confirm(issue(host,"owner","confirm","approve-page",[proposal["id"]]),subject="A",
            claim=dict(kind="act",effect="confirm",target=proposal["id"],reason="Fixture owner page approval"))
        from report_agent.writer_runtime import writer_tools
        tools={t.name:t for t in writer_tools(ws,run.actor,include_images=False,assessment_only=True)}
        assert "assert_source" in tools
        schema=tools["assert_source"].tool_call_schema.model_json_schema()
        assert not {"operation_id","actor","subject","source_version","runtime","indicator_id"} & schema["properties"].keys()
        handle=next(s["source_handle"] for s in step["sources"] if s["title"]==payload["source_metadata"]["title"])
        tools["read_assigned_page"].invoke(dict(type="tool_call",id="read-page",name="read_assigned_page",
            args=dict(source_handle=handle,page=1)))
        result=tools["assert_source"].invoke(dict(type="tool_call",id="extract-page",name="assert_source",
            args=dict(source_handle=handle,page=1,quote=quote,predicate="height",state="value",
                      value=18,unit="m",coverage="A")))
        body=json.loads(result.content)
        assert body["claim"]["citation"]==dict(source_version=version,page=1,quote=quote)
        assert body["was_generated_by"]==run.actor.task_id
        assert host.commission.current_references(ws.store.root,[body["id"]])[body["id"]]["status"]=="proposed"
        from report_agent.page_bindings import records
        assert any(r["id"]==body["id"] for r,s in records(ws.store,binding.plan_ref,"A"))
        current_step=read_indicator_step(cs,run.actor)
        assert current_step["object_facts"]["applicable_pages"][0]["pages"]==[dict(source_handle=handle,page=1)]
        assert len(current_step["object_facts"]["extracted_values"])==1
        assert "extracted_facts" not in current_step
        from report_agent.writer_assessment import save_indicator_outcome
        from report_agent.qualitative_review import freeze_writer_rows
        save_indicator_outcome(cs,run.actor,"gap-for-review",step["indicator_id"],
            dict(kind="gap",missing="Bench heights not given",question="Supply bench heights?",quotes=[quote]))
        with ws.store.connect() as db:
            review=freeze_writer_rows(cs,db,scope["task_ref"])
        frozen=ws.store.get("qualitative_reviewer_snapshot:"+review["qualitative_review_digest"])
        values=frozen["object_facts"]["extracted_values"]
        assert next(r for r in values if r["assertion_id"]==body["id"])["status"]=="proposed"
        assert frozen["rows"][step["indicator_id"]]["ground_details"][0]["status"]=="proposed"



def test_coordinator_page_tool_binds_versions_and_never_extracts_values(mini):
    from types import SimpleNamespace
    from report_agent.planning_assertions import planning_assertion_tools
    from report_agent.hierarchical_tools import actor_for
    from report_agent import page_bindings
    ws,binding,_=mini
    cs=ContentStore(ws.store)
    plan=cs.read(binding.plan_ref)["payload"]
    source=next(s for s in ws.store.source_catalog() if "design" in s.get("title","").lower())
    co=actor_for("coordinator")
    tools={f.__name__:f for f in planning_assertion_tools(cs,lambda:co)}
    assert "assert_source" not in tools
    args=dict(items=[dict(subject="A",indicator_ids=["X11"],pages=[dict(source_id=source["id"],page=1)])])
    row=tools["propose_page_binding"](**args,runtime=SimpleNamespace(tool_call_id="propose"))
    assert set(row) == {"binding_ids"}
    binding_row=next(r for r, _ in page_bindings.records(ws.store, binding.plan_ref) if r["id"] == row["binding_ids"][0])
    assert binding_row["claim"]["rule"]==encode(binding.plan_ref)
    assert binding_row["claim"]["page_binding"]["pages"][0]["page"]==1
    assert "value" not in binding_row["claim"]
    assert tools["propose_page_binding"](**args,runtime=SimpleNamespace(tool_call_id="propose"))==row
    from report_agent.errors import ActionRejected
    with pytest.raises(ActionRejected,match="PHYSICAL_PAGE"):
        tools["propose_page_binding"](**dict(items=[{**args["items"][0],"pages":[dict(source_id=source["id"],page=900)]}]),
                                      runtime=SimpleNamespace(tool_call_id="bad-page"))
    with pytest.raises(ActionRejected,match="INDICATOR"):
        tools["propose_page_binding"](**dict(items=[{**args["items"][0],"indicator_ids":["outside"]}]),
                                      runtime=SimpleNamespace(tool_call_id="bad-indicator"))


def test_extracted_page_disambiguates_quote_repeated_elsewhere(mini):
    from report_agent.catalog import Catalog
    from report_agent.commission_imports import install_source_roles, source_roles
    from report_agent.hierarchical_tools import actor_for
    from report_agent.writer_assessment import resolve_judgment_sources
    from test_ingestion import pdf_bytes
    from report_agent.source_use import source_version_material
    ws,binding,_=mini
    cs=ContentStore(ws.store)
    co=actor_for("coordinator")
    quote="Height is 18 m."
    source_id=Catalog(ws.store).import_file("repeat.pdf",pdf_bytes([quote,quote]))["source"]["id"]
    install_source_roles(ws.store,{**source_roles(ws.store,{}),"repeat.pdf":{"id":source_id,"purpose":"test"}})
    ref=cs.capture_sources(co,"repeat-capture",[source_id])["result"]["source_refs"][0]
    version,material=source_version_material(cs,source_id)
    host=AssertionHost(ws.store.root)
    row=assertions.record_convention(issue(host,"coordinator","record_convention","bind-repeat",[version]),
        subject="A",claim=dict(kind="convention",scope="source_page_binding",rule=encode(binding.plan_ref),
        page_binding=dict(indicator_id="X11",pages=[dict(source_version=version,page=1)])))
    assertions.confirm(issue(host,"owner","confirm","confirm-repeat",[row["id"]]),subject="A",
        claim=dict(kind="act",effect="confirm",target=row["id"],reason="Only page 1 applies"))
    assertions.assert_source(issue(host,"writer","assert_source","extract-repeat",[version,row["id"]],
        {"sources":{version:material}}),subject="A",
        claim=dict(kind="source",predicate="height",state="value",value=18,coverage="A",
                   citation=dict(source_version=version,page=1,quote=quote)),
        grounds=[dict(assertion_id=row["id"],purpose="context",proposition="source_page_binding")])
    context=dict(plan=cs.read(binding.plan_ref),object={"object_id":"A"},indicator_id="X11",sources=[ref])
    with ws.store.connect() as db:
        result=resolve_judgment_sources(cs,db,co,context,[quote])
    assert len(result)==1 and result[0]["locator"].startswith("page 1")


def test_native_writer_records_conflict_and_quote_refusal_without_a_receipt(mini):
    from uuid import NAMESPACE_URL, uuid5
    from report_agent.operation_identity import bound_native_id
    from report_agent.errors import ActionRejected
    from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
    from report_agent.writer_runtime import writer_tools
    ws, binding, _ = mini
    cs, host = ContentStore(ws.store), AssertionHost(ws.store.root)
    with writer_session(ws, "坡段 A", None, assessment_only=True, indicator_steps=True, section_id="3") as run:
        first = read_indicator_step(cs, run.actor)
        save_indicator_outcome(cs, run.actor, "height-open", first["indicator_id"],
            dict(kind="gap", missing="Bench heights unavailable", question="Provide the bench heights?"))
        step = read_indicator_step(cs, run.actor)
        assert step["indicator_id"] == "X12"
        tools = {t.name: t for t in writer_tools(ws, run.actor, include_images=False, assessment_only=True)}
        principal = str(uuid5(NAMESPACE_URL, run.actor.id))
        facts = []
        for title, value in [("design", "1:0.75"), ("survey", "1:1.0")]:
            offered = next(s for s in step["sources"] if title in s["title"].lower())
            with ws.store.connect() as db:
                scope = bound_assignment(cs, db, run.actor)
                ref = next(r for r in scope["sources"] if title in cs._read(db, r)["payload"]["source_metadata"].get("title", "").lower())
                payload = cs._read(db, ref)["payload"]
                quote = db.execute("SELECT text FROM source_blocks WHERE source_id=? AND locator LIKE 'page 1%'",
                                   (payload["source_id"],)).fetchone()[0].strip()
            assert value in quote
            version = immutable_version_digest(payload)
            proposal = assertions.record_convention(issue(host, "coordinator", "record_convention", "bind-" + title, [version]),
                subject="A", claim=dict(kind="convention", scope="source_page_binding", rule=encode(binding.plan_ref),
                page_binding=dict(indicator_id="X12", pages=[dict(source_version=version, page=1)])))
            assertions.confirm(issue(host, "owner", "confirm", "confirm-" + title, [proposal["id"]]), subject="A",
                claim=dict(kind="act", effect="confirm", target=proposal["id"], reason="Synthetic page confirmation"))
            def invoke(name, call, args):
                return tools[name].invoke(dict(type="tool_call", id=call, name=name, args=args))
            invoke("read_assigned_page", "read-" + title, dict(source_handle=offered["source_handle"], page=1))
            args = dict(source_handle=offered["source_handle"], page=1, quote=quote,
                        predicate="slope_ratio", state="value", coverage="A", value=value)
            result = invoke("assert_source", "extract-" + title, args)
            saved = json.loads(result.content)
            assert host.recover_receipt(bound_native_id(principal, "assert_source", "extract-" + title))["result"] == saved
            assert json.loads(invoke("assert_source", "extract-" + title, args).content) == saved
            facts.append(saved["id"])
            with pytest.raises(ActionRejected, match="C2"):
                invoke("assert_source", "bad-quote-" + title, {**args, "quote": "This text is not in the supplied page."})
            assert host.recover_receipt(bound_native_id(principal, "assert_source", "bad-quote-" + title)) is None
        conflict = json.loads(invoke("record_conflict", "compare", dict(observations=facts)).content)
        assert conflict["claim"]["observations"] == facts
        assert host.recover_receipt(bound_native_id(principal, "record_conflict", "compare"))["result"] == conflict
        with pytest.raises(ActionRejected, match="C4"):
            invoke("record_conflict", "foreign-conflict", dict(observations=[facts[0], "outside"]))
        assert host.recover_receipt(bound_native_id(principal, "record_conflict", "foreign-conflict")) is None
