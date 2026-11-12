"""Trusted Fake03 operator stages; models and spending authority belong to the caller."""
from .mini_commission import prepare_mini_commission


def prepare(inputs, destination, runtime_profiles):
    """Import originals without a scripted plan, owner approval or extracted facts."""
    from pathlib import Path
    from .content_store import ContentStore
    from .store import Store
    from .catalog import Catalog
    from .mini_commission import prepare_method, _method_material, METHOD_SOURCE_NAME
    from .commission_requirements import install_requirements, read_requirements
    from .commission_planning import install_reviewed_entries, install_classifications
    result = prepare_mini_commission(inputs,destination,planning_only=True,
        runtime_profiles={**runtime_profiles,"commission_planning_contract":"commission-planning-v1"})
    cs = ContentStore(Store(Path(result["case_path"])))
    sources = Catalog(cs.store).sources()
    ids = {source["filename"]:source["id"] for source in sources}
    refs = {r["payload"]["source_id"]:r["ref"] for r in cs.list_objects("SourceArtifact")}
    install_requirements(cs,refs[ids["00_scope.md"]],refs[ids["08_template.docx"]])
    def cite(name,quote):
        ref=refs[ids[name]]
        block=next(b for b in Catalog(cs.store).read(ids[name],0,50)["blocks"] if quote in b["text"])
        return dict(source_ref=ref,locator=block["locator"],quote=quote)
    pack,tables=prepare_method(cs,cite,_method_material()[0])
    pin=dict(ref=refs[ids[METHOD_SOURCE_NAME]],file_digest=cs.read(refs[ids[METHOD_SOURCE_NAME]])["payload"]["file_digest"])
    install_reviewed_entries(cs,[
        dict(id="mini-weight",kind="weight",label="委托指南及十一指标权重",method_pack=pack,strategy_id="A.3-1",source_pins=[pin]),
        dict(id="mini-tables",kind="table",label="指南评估表和权重表格式",table_specs=tables,source_pins=[pin])])
    classifications=[]
    for anchor in read_requirements(cs)["payload"]["anchors"]:
        kind,quote=anchor["kind"],anchor["source"]["quote"]
        entry="mini-tables" if kind=="convention" and "交付" in quote else "mini-weight" if kind=="convention" and "重要性顺序" in quote else None
        caps=(["fixed_text" if anchor["section_id"]=="1" else "section"] if kind=="section" else
              ["scope_boundary" if anchor.get("scope_section")=="4" else "inventory"] if kind=="scope" else
              ["source_priority" if "设计与地勘" in quote else "deliverables" if "交付" in quote else "assumptions"] if kind=="convention" else
              ["fixed_text"] if anchor.get("section_id")=="1" else [])
        classifications.append(dict(anchor_id=anchor["id"],entry_ids=[entry],capabilities=[]) if entry else dict(anchor_id=anchor["id"],capabilities=caps))
    install_classifications(cs,classifications,"Reviewed synthetic fixture requirements; the Coordinator still proposes every status, link, object, section and binding.")
    return result


async def plan(workspace, model_factory):
    """Use the native Coordinator and its durable owner checkpoint, before any Writer."""
    from .deep_runtime import run_report
    return await run_report(workspace, model_factory)


async def complete(workspace, model_factory, issue_routes, criteria):
    """After the owner's saved page-sheet reply, run fresh Writers, Reviewer and draft export.

    This operator entry does not resume or retry an unknown model request. The caller
    owns launch authority and applies its spending guard to every supplied model.
    """
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from . import page_bindings
    from .commission_plan import _confirmed
    from .content_store import Actor, ContentStore
    from .content_tasks import delegated_task
    from .deep_runtime import BusinessBoundary, business_tools
    from .hierarchical_tools import actor_for, role_prompt
    from .writer_runtime import writer_session
    from .writer_judgment_authority import grant_judgment_inputs
    from .prompt_provenance import AgentPromptBoundary
    from .qualitative_review import qualitative_reviewer_session
    from .context_editing import ToolResultEditing
    from .system_assembler import record_issue_routes, assemble_current_report
    from .content_export import export_snapshot
    from .errors import ActionRejected
    cs = ContentStore(workspace.store)
    with workspace.store.connect() as db:
        plan, decision = _confirmed(cs,db)
    objects = [o for o in plan["payload"]["objects"] if o["included"] and
               o["object_id"] not in {r["object_id"] for r in decision["payload"]["reductions"]}]
    required = {r["id"] for r in plan["payload"]["method_pack"]["indicators"]}
    for obj in objects:
        approved = {r["claim"]["page_binding"]["indicator_id"]
                    for r in page_bindings.confirmed(workspace.store,plan["ref"],obj["object_id"])}
        if required - approved:
            raise ActionRejected("FAKE_DRAFT_CONFIRMED_PAGE_SHEET_REQUIRED")
    sections = [s["section_id"] for s in plan["payload"]["sections"] if s["kind"] == "extracted"]
    assessment_section = next(s["section_id"] for s in plan["payload"]["sections"]
                              if s["kind"] == "extracted" and s["section_id"] == "3")
    rows = []
    for obj in objects:
        grant_judgment_inputs(workspace.store,plan["ref"],obj["object_id"],assessment_section,[],criteria)
        with writer_session(workspace,obj["label"],model_factory("writer"),assessment_only=True,
                            indicator_steps=True,section_id=assessment_section) as writer:
            progress = await writer.run()
            if progress["interrupted_indicators"] or not progress["assessment_ref"]:
                raise ActionRejected("FAKE_DRAFT_WRITER_INCOMPLETE",diagnostic=dict(object_id=obj["object_id"],progress=progress,refusals=writer.refusals))
            task = dict(type="DelegatedTask",id=writer.actor.task_id,version=1)
            rows.append(dict(object_id=obj["object_id"],writer_task_ref=task,progress=progress))
        with qualitative_reviewer_session(workspace,task) as tools:
            assigned = tools["read_qualitative_row"]()
            review = create_agent(model_factory("reviewer"),list(tools.values()),
                system_prompt=role_prompt("reviewer"),middleware=[ToolResultEditing(workspace,"reviewer"), BusinessBoundary(workspace,"reviewer"), AgentPromptBoundary(workspace,"reviewer")])
            await review.ainvoke({"messages":[HumanMessage(
                "逐项独立核对本任务全部已保存指标、原文引述、依据、假设及问题，逐项记录中文复核发现。不得修改 Writer 判断或声明正式发布。") ]}, {"recursion_limit":100})
            findings = {r["payload"]["indicator_id"] for r in cs.list_objects("QualitativeRowFinding")
                        if r["payload"]["review_task_ref"] == assigned["review_task_ref"]}
            if set(assigned["rows"]) - findings:
                raise ActionRejected("FAKE_DRAFT_REVIEW_INCOMPLETE")
    call = dict(name="task",id="fake-draft-prose",args=dict(subagent_type="writer",section_ids=sections,
                description="Write source-grounded draft section prose and preserve every approved planning conflict as a material issue; do not change judgments."))
    with delegated_task(workspace,"coordinator",call):
        prose = create_agent(model_factory("writer"),business_tools(workspace,"writer",None,model_factory("text_tool")),
            system_prompt=role_prompt("writer"),middleware=[ToolResultEditing(workspace,"writer"), BusinessBoundary(workspace,"writer"), AgentPromptBoundary(workspace,"writer")])
        await prose.ainvoke({"messages":[HumanMessage(
            "读取已批准计划，保存各提取章节的中文报告正文及引用，并为批准计划的每一项必需待核事项保存问题。只写本任务章节；不得重新评分、批准计划或导出。") ]})
    record_issue_routes(cs,Actor("operator","operator","fake-draft-routing"),"fake-draft-routes",issue_routes,
                        note="Trusted operator routing of the owner-approved planning conflicts; no change to judgments.")
    snapshot = assemble_current_report(cs,actor_for("coordinator"),"fake-draft-assembly")["result"]["snapshot_ref"]
    exported = export_snapshot(cs,actor_for("coordinator"),"fake-draft-pair",snapshot,{"toc":True})["result"]
    return dict(status="draft_exported",plan_ref=plan["ref"],decision_ref=decision["ref"],
                snapshot_ref=snapshot,slopes=rows,exports=exported,formal_release=False)
