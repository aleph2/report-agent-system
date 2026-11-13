"""Scripted full draft plumbing; never a model-quality or paid-run result."""
from pathlib import Path
import json
import pytest
from test_fake_verification_launcher import packet
from test_fake_fresh_comparison import pair
from test_fake_planning_probe import planning_packet

PROFILES = json.loads((Path(__file__).parents[1]/"config/current.json").read_text())["manifest_profiles"]


def test_live_preparation_has_no_scripted_plan_or_facts(tmp_path):
    from report_agent.fake_draft_flow import prepare
    from report_agent.content_store import ContentStore
    from report_agent.store import Store
    from report_agent import plan_authority
    inputs = Path(__file__).parent / "fake_data/mini_commission/inputs"
    prepared = prepare(inputs, tmp_path / "case", PROFILES)
    store = Store(Path(prepared["case_path"]))
    cs = ContentStore(store)
    assert not plan_authority.plan_ref(store)
    assert not cs.list_objects("CommissionDecision")
    assert not (store.root / "assertions.sqlite3").exists()
    assert prepared["coordinator"] == "live_pending"
    assert prepared["assessment_outcomes_supplied"] == 0


def scripted_plan(ws):
    # Scripted model-answer construction only; no saved plan, approval or fact assertions.
    from report_agent.mini_commission import _plan, _method_material, INPUT_SHA256, METHOD_SOURCE_NAME
    from report_agent.content_store import ContentStore
    from report_agent.catalog import Catalog
    from report_agent.hierarchical_tools import actor_for
    cs, catalog = ContentStore(ws.store), Catalog(ws.store)
    sources = ws.store.source_catalog()
    ids = {name:next(s["id"] for s in sources if s["title"] in {name,Path(name).stem}) for name in [*INPUT_SHA256, METHOD_SOURCE_NAME]}
    refs = {r["payload"]["source_id"]:r["ref"] for r in cs.list_objects("SourceArtifact")}
    refs = {name:refs[sid] for name,sid in ids.items()}
    before=cs.list_objects()
    proposal=_plan(ws,cs,actor_for("coordinator"),ids,refs,catalog,_method_material()[0],interpret=False)[0]
    assert cs.list_objects()==before
    return proposal,ids


PAGES = {
    "X11": [("01_initial.pdf", None),("04_design.pdf",1),("06_drawing.pdf",1)],
    "X12": [("04_design.pdf",1),("05_survey.pdf",1),("06_drawing.pdf",1)],
    "X21": [("04_design.pdf",1)], "X22": [("04_design.pdf",1),("06_drawing.pdf",1)],
    "X23": [("01_initial.pdf",None),("05_survey.pdf",1)],
    "X31": [("07_region.pdf",1),("02_revision.pdf",1)], "X32": [("07_region.pdf",1)],
    "X41": [("04_design.pdf",1),("06_drawing.pdf",1)],
    "X42": [("04_design.pdf",1),("06_drawing.pdf",1)],
    "X51": [("05_survey.pdf",1)], "X52": [("04_design.pdf",1),("06_drawing.pdf",1)]}


def coordinator_script(ws):
    from report_agent.content_store import ContentStore
    from test_deep_runtime import Driver, invoke, observation
    proposal,ids = scripted_plan(ws)
    from report_agent.commission_requirements import read_requirements
    cs=ContentStore(ws.store)
    raw=read_requirements(cs)["payload"]
    scripts = [invoke("read_source_page",source_id=sid) for sid in ids.values()]
    scripts.append(invoke("read_planning_draft"))
    for page in (1,2,3):
        def read_page(messages,page=page):
            response=invoke("read_planning_draft",collection="requirements",page=page,
                view_ref=observation(messages,"read_planning_draft")["view_ref"])
            response.tool_calls[0]["id"]="requirements-page-"+str(page)
            return response
        scripts.append(read_page)
    scripts.append(invoke("read_planning_draft",collection="settings"))
    statuses = [dict(anchor_id=a['id'], status='required', interpretation=a['source']['quote'])
                for a in raw['anchors'] if not raw['classifications'][a['id']]['entry_ids']]
    if statuses:
        scripts.append(invoke('set_requirement_status', items=statuses))
    for anchor in raw['anchors']:
        classification = raw['classifications'][anchor['id']]
        if classification['entry_ids']:
            scripts.append(invoke('link_convention', anchor_id=anchor['id'],
                entry_id=classification['entry_ids'][0], interpretation=anchor['source']['quote']))
    scripts.append(invoke("set_planning_details",details={k:proposal[k] for k in ["report_title","inventory_attributes","deliverables"]}))
    boundary=proposal["scope_boundary"]
    scripts.append(invoke("set_scope_boundary",boundary=dict(start_meter=boundary["start_meter"],end_meter=boundary["end_meter"],source=boundary["source"],
        customer_basis_anchor_id=next(a["id"] for a in raw["anchors"] if a.get("scope_section")=="4"))))
    scripts.append(invoke('add_section', items=[dict(section_id=section['section_id'],
        title=section['title'], kind=section['kind'], sources=section['sources'],
        outline_anchor_id=next(a['id'] for a in raw['anchors'] if a['kind']=='section' and a['section_id']==section['section_id']))
        for section in proposal['sections']]))
    scripts.append(invoke('add_object', items=proposal['objects']))
    scripts.append(invoke('add_reconciliation', items=[{**row, 'reconciliation_id':str(i)}
        for i,row in enumerate(proposal['reconciliations'])]))
    scripts.append(invoke("publish_planning_draft"))
    groups = {}
    for oid in ('A','B'):
        for rule in proposal['method_pack']['indicators']:
            pages = [(ids[name], page or (1 if oid=='A' else 2)) for name,page in PAGES[rule['id']]
                     if oid=='B' or name!='06_drawing.pdf']
            group = groups.setdefault((oid, tuple(pages)), dict(subject=oid, indicator_ids=[],
                pages=[dict(source_id=source, page=page) for source,page in pages]))
            group['indicator_ids'].append(rule['id'])
    scripts.append(invoke('propose_page_binding', items=list(groups.values())))
    scripts.append(invoke("submit_plan"))
    driver=Driver(coordinator=scripts)
    for i,message in enumerate(scripts):
        if not callable(message):message.tool_calls[0]["id"] = "planning-"+str(i)
    return driver,proposal


async def checkpoint(tmp_path):
    import json
    from report_agent.fake_draft_flow import prepare, plan
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.content_store import ContentStore
    from report_agent import plan_authority, page_bindings
    from test_deep_runtime import Driver, invoke, observation
    prepared = prepare(Path(__file__).parent / "fake_data/mini_commission/inputs",tmp_path / "case", PROFILES)
    ws = Workspace(Store(Path(prepared["case_path"])))
    driver,proposal = coordinator_script(ws)
    result=await plan(ws,driver)
    offered={t["name"]:t for t in driver.bindings["coordinator"][0]}
    assert "operation_id" not in offered["publish_planning_draft"]["parameters"]["properties"]
    from langchain_core.messages import ToolMessage
    errors=[m.content for _,_,batch in driver.calls for m in batch if isinstance(m,ToolMessage) and m.status=="error"]
    assert not errors, "\n".join(dict.fromkeys(errors))
    assert result["status"] == "needs_human", result
    cs=ContentStore(ws.store)
    assert not cs.list_objects("CommissionDecision") and not cs.list_objects("DelegatedTask")
    assert all(role == "coordinator" for role,_,_ in driver.calls)
    ref=plan_authority.plan_ref(ws.store)
    bindings=page_bindings.records(ws.store,ref)
    assert len(bindings)==22 and all(s["status"]=="proposed" for _,s in bindings)
    calls=len(driver.calls)
    assert (await plan(ws,driver))["status"]=="needs_human"
    assert len(driver.calls)==calls
    return ws,result,driver,proposal


async def test_native_coordinator_pauses_before_writer_spend(tmp_path):
    await checkpoint(tmp_path)


@pytest.mark.parametrize("partial_review",[False,True],ids=["complete","review-incomplete"])
async def test_complete_native_draft_flow(tmp_path,partial_review,monkeypatch,planning_packet):
    from report_agent.fake_draft_flow import complete
    from report_agent.commission_plan import reply
    from report_agent.content_store import ContentStore
    from report_agent import plan_authority, page_bindings
    from report_agent.store import digest
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from test_deep_runtime import Driver, ScriptedChat, invoke, observation
    from report_agent.errors import ActionRejected
    import pytest
    ws,paused,planner,proposal = await checkpoint(tmp_path)
    cs=ContentStore(ws.store)
    calls=[]
    criteria=json.loads((Path(__file__).parent/"fake_data/mini_commission/writer-conventions.json").read_text())["criteria"]
    class TextChat(ScriptedChat):
        profile:dict = {"image_inputs":False}
    class FlowDriver(Driver):
        def __call__(self,role):
            return TextChat(role=role,driver=self)
        async def respond(self,role,messages):
            calls.append(role)
            self.calls.append((role,0,list(messages)))
            step=None
            for message in messages:
                if isinstance(message,HumanMessage):
                    try: candidate=json.loads(message.content)
                    except (ValueError,TypeError):continue
                    if "indicator_id" in candidate:step=candidate;break
            number=sum(isinstance(m,AIMessage) for m in messages)
            if role=="text_tool":
                sid,citation=active_prose["section"]
                packet=json.loads(messages[-1].content)
                assert packet["actor"]["role"]=="writer"
                answer=AIMessage(json.dumps({"payloads":[dict(kind="block",body=dict(text=citation["quote"],section_id=sid),
                    qualifiers={},claim_kind="fact",citations=[citation])]},ensure_ascii=False))
            elif role=="reviewer" and partial_review:
                answer=AIMessage("尚未逐项复核。")
            elif role=="reviewer":
                if number==0: answer=invoke("read_qualitative_row")
                elif number%2==1:
                    index=(number-1)//2
                    rows=observation(messages,"read_qualitative_row")["rows"] if number==1 else self.review_rows
                    self.review_rows=rows
                    if index==len(rows):answer=AIMessage("已逐项记录独立复核。")
                    else:answer=invoke("read_qualitative_row",indicator_id=list(rows)[index])
                else:
                    row=observation(messages,"read_qualitative_row")
                    answer=invoke("record_qualitative_finding",indicator_id=row["indicator_id"],finding="离线脚本复核：已核对冻结判断、引文和待核理由；不代表工程签认。")
            elif step:
                oid="A" if step["object_label"]=="坡段 A" else "B"
                ind=step["indicator_id"]
                positive=oid=="A" and ind in {"X21","X41"}
                quote=("坡段 A 位于 K0+120，岩质，整体风化程度为强风化。" if ind=="X21" else "防护采用锚杆框架梁，设置截排水沟。")
                if positive and number==0:
                    source=next(s for s in step["sources"] if "04_design" in s["title"])
                    answer=invoke("read_assigned_page",source_handle=source["source_handle"],page=1)
                elif positive and number==1:
                    source=next(s for s in step["sources"] if "04_design" in s["title"])
                    answer=invoke("assert_source",source_handle=source["source_handle"],page=1,quote=quote,
                        predicate="weathering" if ind=="X21" else "engineering_measure",state="value",coverage="A",
                        value="强风化" if ind=="X21" else "锚杆框架梁")
                elif positive:
                    grade=next(g["choice"] for g in step["grades"] if g["min_value"]==("25" if ind=="X21" else "50"))
                    answer=invoke("save_evidence",basis_kind="direct_evidence",grade=grade,value="37" if ind=="X21" else "62",
                        rationale="按设计记载及指南分级，取该分值区间中点。",quotes=[quote])
                else:answer=invoke("save_gap",missing="现有资料或本轮计算范围不足以完成本指标评定。",question="请复核本指标所需资料或计算条件。")
            else:
                if number<len(prose):answer=prose[number]
                else:answer=AIMessage("中文正文与规划冲突已保存。")
            if answer.tool_calls:
                answer.tool_calls[0]["id"]="flow-"+str(len(calls))
            return ChatResult(generations=[ChatGeneration(message=answer)])
    models=FlowDriver()
    with pytest.raises(ActionRejected):await complete(ws,models,{},criteria)
    assert calls==[]
    ref=plan_authority.plan_ref(ws.store)
    pending=next(i for i in paused["issues"] if not i.get("resolved"))
    import hashlib
    planning_authority = tmp_path / "planning-authority.json"
    planning_authority.write_text(json.dumps(dict(case_path=str(ws.store.root),
        confirmers={"delegate": dict(name="Fixture delegate", acting_for="Fixture owner")})))
    planning_pin = hashlib.sha256(planning_authority.read_bytes()).hexdigest()
    reply(ws,pending["id"],dict(plan_ref=ref,requirements_ref=cs.read(ref)["payload"]["requirements_ref"],approved=True,corrections="",
        reductions=[dict(object_id="C",reason="界外对象按委托范围排除。")],
        confirmer=dict(id="delegate",name="Fixture delegate",acting_for="Fixture owner",authority_sha256=planning_pin)),
        authority_path=planning_authority,authority_sha256=planning_pin)
    assert len(page_bindings.confirmed(ws.store,ref,"A"))==11
    assert not [r for r,s in page_bindings.records(ws.store,ref) if r["claim"]["kind"]=="source"]
    decision=cs.read(plan_authority.decision_ref(ws.store))["payload"]
    required=decision["required_material_issues"]
    reconciliations=[digest([ref,["reconciliation",i,0]]) for i in range(2)]
    routes={reconciliations[0]:dict(section_id="3",reason="坡率差异随评估披露。"),
            reconciliations[1]:dict(section_id="2",reason="更正日期随资料说明披露。")}
    # Real launch guards and SDK clients use only synthetic authority, ledger and HTTP.
    from report_agent import fake_full_flow as entry, deep_models, model_config
    from report_agent.workspace import Workspace
    from report_agent.store import Store
    from test_fake_verification_launcher import write_json
    import httpx
    from langchain_openai.chat_models.base import _convert_dict_to_message, _convert_message_to_dict
    original_ws = ws
    original_decision = plan_authority.decision_ref(ws.store)
    path, _, authority = planning_packet
    case = Path(authority['grant_dir']) / 'runs' / authority['run_id'] / 'case'
    env = tmp_path / 'services.env';env.write_text('synthetic configuration only')
    url='https://offline.invalid/v1';vision_url='https://synthetic.maas.aliyuncs.com/v1'
    sha=lambda text:hashlib.sha256(text.encode()).hexdigest()
    authority.update(workflow=entry.WORKFLOW,case_path=str(case),issue_routes=routes,
        candidate_tag='offline-candidate',criteria_sha256=entry.host._sha(entry._CRITERIA),
        confirmers={'delegate':dict(name='Fixture delegate',acting_for='Fixture owner')},
        roles={**{role:authority['model'] for role in ('writer','reviewer','text_tool')},'vision':authority['vision_model']},
        approved_input=dict(case_path=str(ws.store.root),case_seal=entry.host._seal(ws.store.root),
            plan_ref=ref,decision_ref=original_decision,planning_authority=str(planning_authority),planning_authority_sha256=planning_pin),
        request_bound_proof=dict(model=authority['model'],input_limit=1_048_576,output_limit=131_072,
            basis='documented_model_ceiling_not_measured_request_fit',env_sha256=entry.host._sha(env),
            base_url_sha256=sha(url),request_url_sha256=sha(url+'/chat/completions'),
            sources=['https://docs.z.ai/guides/llm/glm-5.3','https://help.aliyun.com/zh/model-studio/glm-5-3']))
    authority['vision_request_bound_proof']=dict(model=authority['vision_model'],input_limit=1_000_000,output_limit=8202,
        wire_output_limit=8192,image_max_edge=1024,basis='documented_service_ceiling_not_measured_request_fit',
        env_sha256=entry.host._sha(env),base_url_sha256=sha(vision_url),request_url_sha256=sha(vision_url+'/chat/completions'),
        sources=['https://help.aliyun.com/zh/model-studio/deepseek-v4-1-flash','https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions'])
    git_output=entry.subprocess.check_output
    def frozen_tag(args,**kwargs):
        if args[0]=='git' and 'rev-parse' in args:return authority['candidate_commit']+'\n'
        return git_output(args,**kwargs)
    monkeypatch.setattr(entry.subprocess,'check_output',frozen_tag)
    pin=write_json(path,authority)
    assert entry.preflight(path,pin)==authority
    with pytest.raises(ValueError,match='FAKE_AUTHORITY_PIN_MISMATCH'):entry.preflight(path,'0'*64)
    prepared=entry.prepare(path,pin)
    assert entry.check_prepared(path,pin,prepared['prepared_sha256'])==prepared
    with pytest.raises(ValueError,match='FAKE_FULL_FLOW_PREPARED_CASE_CHANGED'):
        entry.check_prepared(path,pin,'wrong-pin')
    ws = Workspace(Store(case))
    cs = ContentStore(ws.store)
    assert cs.read(original_decision) == ContentStore(original_ws.store).read(original_decision)
    assert page_bindings.records(ws.store, ref) == page_bindings.records(original_ws.store, ref)
    assert entry.completion_inputs(ws, authority) == criteria
    with monkeypatch.context() as patch:
        patch.setattr(page_bindings, "confirmed", lambda *args: [])
        with pytest.raises(ValueError, match="FAKE_DRAFT_CONFIRMED_PAGE_SHEET_REQUIRED"):
            entry.completion_inputs(ws, authority)
    assert calls == []
    prose=[]
    nodes={}
    active_prose={}
    for section in proposal["sections"]:
        sid=section["section_id"]
        if section["kind"]!="extracted":continue
        citation=section["sources"][0]
        def produce(messages,sid=sid,citation=citation):
            active_prose["section"]=(sid,citation)
            source=cs.read(citation["source_ref"])["payload"]["source_id"]
            return invoke("process_report_content",object_type="ContentNode",objective="编写所分配第"+sid+"章的简明中文资料说明，保留不确定性。",
                input_refs=[citation["source_ref"]],source_selections=[dict(source_id=source)])
        def save(messages,sid=sid,citation=citation):
            work=observation(messages,"process_report_content")
            assert work.get("ok",True),work
            return invoke("save_section_prose",section_id=sid,text_work_id=work["text_work_id"])
        def retain(messages,sid=sid):
            response=observation(messages,"save_section_prose")
            assert response.get("ok"), response
            nodes[sid]=response["result"]["refs"]["prose"]
            return invoke("read_commission_plan")
        prose.extend([produce,save,retain])
    for item in required:
        sid=routes.get(item["id"],dict(section_id="3"))["section_id"]
        def issue(messages,item=item,sid=sid):
            return invoke("propose_material_issue",node_ref=nodes[sid],issue={**item,"adopted_value":proposal["reconciliations"][0 if sid=="3" else 1]["result"],"affects_level":False})
        prose.append(issue)
    # Resolve scripted functions at the actual model boundary, not by calling business writes directly.
    original=models.respond
    async def respond(role,messages):
        number=sum(isinstance(m,AIMessage) for m in messages)
        if role=="writer" and not any(isinstance(m,HumanMessage) and '"indicator_id"' in str(m.content) for m in messages) and number<len(prose) and callable(prose[number]):
            action=prose[number](messages)
            calls.append(role)
            models.calls.append((role,number,list(messages)))
            if action.tool_calls:action.tool_calls[0]["id"]="flow-"+str(len(calls))
            return ChatResult(generations=[ChatGeneration(message=action)])
        return await original(role,messages)
    models.respond=respond
    for role,model,endpoint in [('WRITER',authority['model'],url),('VISION',authority['vision_model'],vision_url)]:
        for key,value in [('MODEL',model),('BASE_URL',endpoint),('API_KEY','synthetic')]:monkeypatch.setenv('REPORT_'+role+'_'+key,value)
    monkeypatch.setenv('REPORT_SDK_RETRIES','0');monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    monkeypatch.setattr(model_config,'load_mixed_services',lambda _:None)
    configured_model=deep_models.configured_model
    sent=[];clients=[];unknown=False
    def configured(store,role):
        model=configured_model(store,role)
        clients.extend([model.http_client,model.http_async_client])
        async def provider(request):
            body=json.loads(request.content);sent.append((role,body))
            if unknown:raise httpx.ReadError('synthetic unknown delivery')
            messages=[_convert_dict_to_message(m) for m in body['messages']]
            names={c['id']:c['name'] for m in messages for c in getattr(m,'tool_calls',[])}
            for message in messages:
                if isinstance(message,ToolMessage) and not message.name:message.name=names.get(message.tool_call_id)
            answer=await models.respond(role,messages)
            wire=_convert_message_to_dict(answer.generations[0].message)
            return httpx.Response(200,json=dict(id='offline-'+str(len(sent)),object='chat.completion',created=1,
                model=body['model'],choices=[dict(index=0,finish_reason='tool_calls' if wire.get('tool_calls') else 'stop',message=wire)],
                usage=dict(prompt_tokens=6,completion_tokens=4,total_tokens=10)))
        monkeypatch.setattr(model.http_async_client._transport,'handle_async_request',provider)
        return model
    monkeypatch.setattr(deep_models,'configured_model',configured)
    if partial_review:
        with pytest.raises(ActionRejected,match="FAKE_DRAFT_REVIEW_INCOMPLETE"):
            await entry.launch(path,pin,prepared['prepared_sha256'],env)
        terminal=json.loads((case.parent/'result.json').read_text())
        assert terminal['status']=='stopped' and terminal['budget']['held']==0
        assert not cs.list_objects("ExportArtifact")
        # A separate fresh offline run proves unknown delivery is held without retry.
        authority.update(run_id='unknown',case_path=str(Path(authority['grant_dir'])/'runs'/'unknown'/'case'),
            fresh_comparison={**authority['fresh_comparison'],'run_ids':['unknown']})
        pin=write_json(path,authority);prepared=entry.prepare(path,pin);unknown=True;before=len(sent)
        with pytest.raises(Exception):await entry.launch(path,pin,prepared['prepared_sha256'],env)
        terminal=json.loads((Path(authority['case_path']).parent/'result.json').read_text())
        assert len(sent)==before+1 and terminal['status']=='unknown_outcome_held'
        assert terminal['budget']['held']==entry.host.BOUND
        with pytest.raises(FileExistsError):await entry.launch(path,pin,prepared['prepared_sha256'],env)
        assert len(sent)==before+1 and all(client.is_closed for client in clients)
        return
    try:
        terminal=await entry.launch(path,pin,prepared['prepared_sha256'],env)
        result=terminal['completion']
        assert terminal['budget']['settled']==10*len(sent) and terminal['budget']['held']==0
        assert terminal['campaign_budget']['reserved_or_unknown_upper_bounds']==entry.host.BOUND
        assert set(role for role,_ in sent)=={'writer','reviewer','text_tool'}
        assert all(client.is_closed for client in clients)
        before=len(sent)
        with pytest.raises(FileExistsError):await entry.launch(path,pin,prepared['prepared_sha256'],env)
        assert len(sent)==before
    except ActionRejected as error:
        errors=list(dict.fromkeys(m.content for _,_,batch in models.calls for m in batch if isinstance(m,ToolMessage) and m.status=="error"))
        pytest.fail(str(error)+"\n"+str(error.diagnostic)+"\n"+"\n".join(errors))
    assert result["status"]=="draft_exported" and not result["formal_release"]
    assert len(cs.list_objects("QualitativeRowFinding"))==22
    assert set(calls)=={"writer","reviewer","text_tool"}
    sources=[(r,s) for r,s in page_bindings.records(ws.store,ref) if r["claim"]["kind"]=="source"]
    assert len(sources)==2 and all(s["status"]=="proposed" for r,s in sources)
    assert all(row["progress"]["progress"]["recorded"]==11 for row in result["slopes"])
    from docx import Document
    from openpyxl import load_workbook
    exports=result["exports"]
    doc=Document(ws.store.root/exports["file_ref"])
    book=load_workbook(ws.store.root/exports["workbook"]["file_ref"])
    comments=[c for c in doc.comments if c.author=="待核"]
    assert len(comments)==book["资料澄清清单"].max_row-1
    assert len(comments)>=len(required)
    assert cs.read(exports["workbook"]["export_ref"])["payload"]["snapshot_ref"]==result["snapshot_ref"]
    errors=[m.content for _,_,batch in models.calls for m in batch if isinstance(m,ToolMessage) and m.status=="error"]
    assert not errors,errors

    import os,shutil,hashlib
    from collections import Counter
    if destination:=os.environ.get("FAKE03_FULL_FLOW_ARTIFACT_DIR"):
        out=Path(destination)
        out.mkdir(parents=True,exist_ok=True)
        for name,relative in [("fake03-offline.docx",exports["file_ref"]),("fake03-offline.xlsx",exports["workbook"]["file_ref"])]:
            shutil.copyfile(ws.store.root/relative,out/name)
        active,anchors={},{}
        for node in doc.element.body.iter():
            if node.tag.endswith("}commentRangeStart"):active[node.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id")]=[]
            elif node.tag.endswith("}t"):
                for text in active.values():text.append(node.text or "")
            elif node.tag.endswith("}commentRangeEnd"):
                key=node.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id")
                anchors[key]="".join(active.pop(key,[]))
        listing=[dict(author=c.author,anchor=anchors.get(str(c.comment_id),""),text=c.text) for c in doc.comments]
        (out/"comments.json").write_text(json.dumps(listing,ensure_ascii=False,indent=2))
        from report_agent.writer_judgments import read_progress
        with ws.store.connect() as db:
            assignments=[key for key, in db.execute("SELECT DISTINCT assignment FROM writer_step_receipts")]
            saved={key:read_progress(ws.store,key,db) for key in assignments}
        (out/"saved-rows.json").write_text(json.dumps(saved,ensure_ascii=False,indent=2))
        (out/"reviewer-findings.json").write_text(json.dumps([r["payload"] for r in cs.list_objects("QualitativeRowFinding")],ensure_ascii=False,indent=2))
        evidence=dict(status="scripted_offline_plumbing_passed",semantic_quality_measured=False,provider_requests=0,tokens=0,
            coordinator_calls=len(planner.calls),role_calls=dict(Counter(calls)),
            rows_saved=22,independent_findings=22,fresh_extracted_facts=len(sources),fact_status="proposed",
            word_open_comments=len(comments),excel_issue_rows=book["资料澄清清单"].max_row-1,
            source_comments=sum(c.author=="来源" for c in doc.comments),formal_release=False,
            hashes={})
        evidence["hashes"]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.suffix in {".docx",".xlsx"}}
        (out/"verification.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2))


@pytest.mark.parametrize("filename", ["manifest-v2.json", "manifest-v3-vision.json"])
def test_key_and_fixture_are_frozen_outside_live_inputs(filename):
    import hashlib
    base=Path(__file__).parents[1]/"docs/verification/fake03-post-9a"
    manifest=json.loads((base/filename).read_text())
    key=json.loads((base/manifest["answer_key_file"]).read_text())
    assert hashlib.sha256((base/manifest["answer_key_file"]).read_bytes()).hexdigest()==manifest["answer_key_sha256"]
    assert len(key["coordinator"]["bindings"])==22
    assert {(b["object_id"],b["indicator_id"]) for b in key["coordinator"]["bindings"]}=={(o,i) for o in ("A","B") for i in key["rank_order"]}
    root=Path(__file__).parent/"fake_data/mini_commission"
    assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==expected for name,expected in manifest["fixture_files_sha256"].items())


async def test_unchanged_submission_keeps_bindings_and_changed_retry_conflicts(tmp_path):
    from report_agent.commission_planning import submit_plan, save_item
    from report_agent.content_store import ContentStore
    from report_agent.hierarchical_tools import actor_for
    from report_agent import plan_authority
    ws,_,_,proposal=await checkpoint(tmp_path)
    cs=ContentStore(ws.store)
    actor=actor_for("coordinator")
    original=plan_authority.plan_ref(ws.store)
    assert submit_plan(cs,actor,"one-command")["result"]["plan_ref"]==original
    save_item(cs,actor,"changed-title","details",dict(report_title="修订标题",inventory_attributes=proposal["inventory_attributes"],deliverables=proposal["deliverables"]))
    from report_agent.errors import ActionRejected
    with pytest.raises(ActionRejected,match="OPERATION_CONFLICT"):
        submit_plan(cs,actor,"one-command")
    assert plan_authority.plan_ref(ws.store)==original


def test_binding_does_not_publish_an_unsubmitted_plan(tmp_path):
    from report_agent.fake_draft_flow import prepare
    from report_agent.content_store import ContentStore
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.commission_planning import save_item
    from report_agent.hierarchical_tools import actor_for
    from report_agent import page_bindings,plan_authority
    from report_agent.errors import ActionRejected
    prepared=prepare(Path(__file__).parent/"fake_data/mini_commission/inputs",tmp_path/"case",PROFILES)
    ws=Workspace(Store(Path(prepared["case_path"])))
    cs=ContentStore(ws.store)
    proposal,ids=scripted_plan(ws)
    actor=actor_for("coordinator")
    save_item(cs,actor,"object","object",proposal["objects"][0])
    with pytest.raises(ActionRejected,match="PAGE_BINDING_SAVED_PLAN_OBJECT_REQUIRED"):
        page_bindings.propose(cs,actor,"binding","A","X11",[dict(source_id=ids["04_design.pdf"],page=1)])
    assert plan_authority.plan_ref(ws.store) is None
