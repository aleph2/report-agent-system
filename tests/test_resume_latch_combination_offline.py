import httpx
import pytest
from report_agent.model_recovery import activate_recovery
from report_agent.store import Store
from test_task_supervision import ws

@pytest.mark.asyncio
async def test_latch_resume_preserves_completed_unknown_and_held(ws, monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke
    from test_text_work import writer_call
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
    preserved = {f'synthetic_completed_{i}': {'state': 'completed', 'result': f'artifact-{i}'} for i in range(3)}
    for key, value in preserved.items():
        ws.store.set(key, value)
    seen=[]
    async def timeout(request):
        seen.append(1)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",20000,{"glm-5.3":10000})
    def interrupted(messages):
        enforce_host_admission(used_plus_held=budget.snapshot()["reserved_or_unknown_upper_bounds"], limit=20000, unknown=False, failed=True)
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[invoke("process_report_content",operation_id="unknown",objective="Describe source",
            object_type="ContentNode",source_selections=[{"source_id":"s"}]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        second=Driver(coordinator=[AIMessage(content="unused"),AIMessage(content="continued")],writer=[AIMessage(content="unused"),AIMessage(content="No result adopted")])
        with token_budget(budget):
            resumed=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=="text_tool" else second(role))
        assert seen==[1] and budget.snapshot()==initial
        assert {k: ws.store.get(k) for k in preserved} == preserved
        assert resumed["last_error"] is None
        print("RESERVED_EVENTS", [e["data"] for e in ws.store.events() if e["kind"]=="native_delegation_reserved"])
        from langchain_core.messages import ToolMessage
        assert any(role == "writer" and any(isinstance(m, ToolMessage) and "EVIDENCE_ANALYSIS_OUTCOME_UNRESOLVED" in str(m.content) for m in messages) for role,_,messages in second.calls)
        assert ContentStore(ws.store).list_objects("ContentNode")==[]
    finally:
        await close_model(model)



@pytest.mark.asyncio
async def test_fresh_v4_without_authorization_remains_blocked(ws, monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke
    from test_text_work import writer_call
    ws.store.set('manifest', {**ws.store.manifest,
        'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2',
        'review_plan_contract':'optional-v1',
        'history_projection_profile':'exact-history-v1',
        'tool_discovery_profile':'agent-search-v2',
        'context_policy':'stateful-tools-v2',
        'context_projection':'review-materials-v2',
        'operation_identity_profile':'native-tool-runtime-v1',
        'content_input_profile':'relation-endpoints-v2',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1',
        'delegation_prompt_profile':'separate-description-v1',
        'review_submission_contract':'task-scope-selectors-v1',
        'execution_progress_policy':{'version':1,'window':64,'repeats':3,'after_notice':2}})
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
    preserved = {f'synthetic_completed_{i}': {'state': 'completed', 'result': f'artifact-{i}'} for i in range(3)}
    for key, value in preserved.items():
        ws.store.set(key, value)
    seen=[]
    async def timeout(request):
        seen.append(1)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",20000,{"glm-5.3":10000})
    def interrupted(messages):
        enforce_host_admission(used_plus_held=budget.snapshot()["reserved_or_unknown_upper_bounds"], limit=20000, unknown=False, failed=True)
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[invoke("process_report_content",operation_id="unknown",objective="Describe source",
            object_type="ContentNode",source_selections=[{"source_id":"s"}]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        second=Driver(coordinator=[AIMessage(content="unused"),AIMessage(content="continued")],writer=[AIMessage(content="unused"),AIMessage(content="No result adopted")])
        with token_budget(budget):
            resumed=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=="text_tool" else second(role))
        assert seen==[1] and budget.snapshot()==initial
        assert {k: ws.store.get(k) for k in preserved} == preserved
        assert resumed["last_error"] is None
        print("RESERVED_EVENTS", [e["data"] for e in ws.store.events() if e["kind"]=="native_delegation_reserved"])
        from langchain_core.messages import ToolMessage
        assert not any(role == "writer" for role,_,_ in second.calls)
        assert any(isinstance(m,ToolMessage) and "NATIVE_DELEGATION_OUTCOME_UNRESOLVED" in str(m.content) for _,_,messages in second.calls for m in messages)
        assert ContentStore(ws.store).list_objects("ContentNode")==[]
    finally:
        await close_model(model)



@pytest.mark.asyncio
async def test_fresh_v4_authorized_unknown_child_resumes_without_resend(ws, monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke
    from test_text_work import writer_call
    ws.store.set('manifest', {**ws.store.manifest,
        'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2',
        'review_plan_contract':'optional-v1',
        'history_projection_profile':'exact-history-v1',
        'tool_discovery_profile':'agent-search-v2',
        'context_policy':'stateful-tools-v2',
        'context_projection':'review-materials-v2',
        'operation_identity_profile':'native-tool-runtime-v1',
        'content_input_profile':'relation-endpoints-v2',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1',
        'delegation_prompt_profile':'separate-description-v1',
        'review_submission_contract':'task-scope-selectors-v1',
        'execution_progress_policy':{'version':1,'window':64,'repeats':3,'after_notice':2}})
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
    preserved = {f'synthetic_completed_{i}': {'state': 'completed', 'result': f'artifact-{i}'} for i in range(3)}
    for key, value in preserved.items():
        ws.store.set(key, value)
    seen=[]
    async def timeout(request):
        seen.append(1)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",20000,{"glm-5.3":10000})
    def interrupted(messages):
        enforce_host_admission(used_plus_held=budget.snapshot()["reserved_or_unknown_upper_bounds"], limit=20000, unknown=False, failed=True)
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[invoke("process_report_content",operation_id="unknown",objective="Describe source",
            object_type="ContentNode",source_selections=[{"source_id":"s"}]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        second=Driver(coordinator=[AIMessage(content="unused"),AIMessage(content="continued")],writer=[AIMessage(content="unused"),AIMessage(content="No result adopted")])
        import hashlib
        from report_agent.supervision_plugins import unknown_child_resume
        event=next(e['data'] for e in ws.store.events() if e['kind']=='native_delegation_reserved')
        diagnostic_id=result['last_error']['diagnostic_id']
        diagnostic=ws.store.root/'diagnostics'/'private'/(diagnostic_id+'.json')
        import sqlite3, json
        with sqlite3.connect(ws.store.root/'checkpoints.db') as db:
            checkpoint_id, metadata = db.execute("select checkpoint_id,metadata from checkpoints where checkpoint_ns like 'tools:%' order by checkpoint_id desc limit 1").fetchone()
        parent_checkpoint_id=json.loads(metadata)['parents']['']
        with unknown_child_resume(ws.store, call_id=event['native_tool_call_id'], task_id=event['task_id'],
                diagnostic_id=diagnostic_id, diagnostic_sha256=hashlib.sha256(diagnostic.read_bytes()).hexdigest(),
                checkpoint_id=checkpoint_id, parent_checkpoint_id=parent_checkpoint_id):
            with token_budget(budget):
                resumed=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=="text_tool" else second(role))
        assert seen==[1] and budget.snapshot()==initial
        assert {k: ws.store.get(k) for k in preserved} == preserved
        assert resumed["last_error"] is None
        print("RESERVED_EVENTS", [e["data"] for e in ws.store.events() if e["kind"]=="native_delegation_reserved"])
        from langchain_core.messages import ToolMessage
        assert any(role == "writer" and any(isinstance(m, ToolMessage) and "EVIDENCE_ANALYSIS_OUTCOME_UNRESOLVED" in str(m.content) for m in messages) for role,_,messages in second.calls)
        assert ContentStore(ws.store).list_objects("ContentNode")==[]
    finally:
        await close_model(model)



@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['wrong_call','wrong_task','wrong_head','wrong_parent'])
async def test_v4_unknown_resume_rejects_wrong_identity(ws, monkeypatch, tmp_path, mutation):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke
    from test_text_work import writer_call
    ws.store.set('manifest', {**ws.store.manifest,
        'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2',
        'review_plan_contract':'optional-v1',
        'history_projection_profile':'exact-history-v1',
        'tool_discovery_profile':'agent-search-v2',
        'context_policy':'stateful-tools-v2',
        'context_projection':'review-materials-v2',
        'operation_identity_profile':'native-tool-runtime-v1',
        'content_input_profile':'relation-endpoints-v2',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1',
        'delegation_prompt_profile':'separate-description-v1',
        'review_submission_contract':'task-scope-selectors-v1',
        'execution_progress_policy':{'version':1,'window':64,'repeats':3,'after_notice':2}})
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
    preserved = {f'synthetic_completed_{i}': {'state': 'completed', 'result': f'artifact-{i}'} for i in range(3)}
    for key, value in preserved.items():
        ws.store.set(key, value)
    seen=[]
    async def timeout(request):
        seen.append(1)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",20000,{"glm-5.3":10000})
    def interrupted(messages):
        enforce_host_admission(used_plus_held=budget.snapshot()["reserved_or_unknown_upper_bounds"], limit=20000, unknown=False, failed=True)
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[invoke("process_report_content",operation_id="unknown",objective="Describe source",
            object_type="ContentNode",source_selections=[{"source_id":"s"}]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        second=Driver(coordinator=[AIMessage(content="unused"),AIMessage(content="continued")],writer=[AIMessage(content="unused"),AIMessage(content="No result adopted")])
        import hashlib
        from report_agent.supervision_plugins import unknown_child_resume
        event=next(e['data'] for e in ws.store.events() if e['kind']=='native_delegation_reserved')
        diagnostic_id=result['last_error']['diagnostic_id']
        diagnostic=ws.store.root/'diagnostics'/'private'/(diagnostic_id+'.json')
        import sqlite3, json
        with sqlite3.connect(ws.store.root/'checkpoints.db') as db:
            checkpoint_id, metadata = db.execute("select checkpoint_id,metadata from checkpoints where checkpoint_ns like 'tools:%' order by checkpoint_id desc limit 1").fetchone()
        parent_checkpoint_id=json.loads(metadata)['parents']['']
        if mutation=='wrong_call': event['native_tool_call_id']='different'
        if mutation=='wrong_task': event['task_id']='different'
        if mutation=='wrong_head': checkpoint_id='different'
        if mutation=='wrong_parent': parent_checkpoint_id='different'
        with unknown_child_resume(ws.store, call_id=event['native_tool_call_id'], task_id=event['task_id'],
                diagnostic_id=diagnostic_id, diagnostic_sha256=hashlib.sha256(diagnostic.read_bytes()).hexdigest(),
                checkpoint_id=checkpoint_id, parent_checkpoint_id=parent_checkpoint_id):
            with token_budget(budget):
                resumed=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=="text_tool" else second(role))
        assert seen==[1] and budget.snapshot()==initial
        assert {k: ws.store.get(k) for k in preserved} == preserved
        assert resumed["last_error"] is None
        print("RESERVED_EVENTS", [e["data"] for e in ws.store.events() if e["kind"]=="native_delegation_reserved"])
        from langchain_core.messages import ToolMessage
        assert not any(role == "writer" for role,_,_ in second.calls)
        assert any(isinstance(m,ToolMessage) and "NATIVE_DELEGATION_OUTCOME_UNRESOLVED" in str(m.content) for _,_,messages in second.calls for m in messages)
        assert ContentStore(ws.store).list_objects("ContentNode")==[]
    finally:
        await close_model(model)



@pytest.mark.asyncio
async def test_v4_old_registry_exact_upgrade_resumes_same_unknown_child(ws, monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke
    from test_text_work import writer_call
    ws.store.set('manifest', {**ws.store.manifest,
        'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2',
        'review_plan_contract':'optional-v1',
        'history_projection_profile':'exact-history-v1',
        'tool_discovery_profile':'agent-search-v2',
        'context_policy':'stateful-tools-v2',
        'context_projection':'review-materials-v2',
        'operation_identity_profile':'native-tool-runtime-v1',
        'content_input_profile':'relation-endpoints-v2',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1',
        'delegation_prompt_profile':'separate-description-v1',
        'review_submission_contract':'task-scope-selectors-v1',
        'execution_progress_policy':{'version':1,'window':64,'repeats':3,'after_notice':2}})
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
    preserved = {f'synthetic_completed_{i}': {'state': 'completed', 'result': f'artifact-{i}'} for i in range(3)}
    for key, value in preserved.items():
        ws.store.set(key, value)
    seen=[]
    async def timeout(request):
        seen.append(1)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",20000,{"glm-5.3":10000})
    def interrupted(messages):
        enforce_host_admission(used_plus_held=budget.snapshot()["reserved_or_unknown_upper_bounds"], limit=20000, unknown=False, failed=True)
    import report_agent.tool_discovery as discovery
    captured=[]
    original_bind=discovery.bind_registry
    def capture_bind(store, fingerprints, *, runtime_ref=None):
        captured.append((fingerprints,runtime_ref))
        return original_bind(store,fingerprints,runtime_ref=runtime_ref)
    monkeypatch.setattr(discovery,'bind_registry',capture_bind)
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[invoke("process_report_content",operation_id="unknown",objective="Describe source",
            object_type="ContentNode",source_selections=[{"source_id":"s"}]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        second=Driver(coordinator=[AIMessage(content="unused"),AIMessage(content="continued")],writer=[AIMessage(content="unused"),AIMessage(content="No result adopted")])
        import hashlib
        from report_agent.supervision_plugins import unknown_child_resume
        event=next(e['data'] for e in ws.store.events() if e['kind']=='native_delegation_reserved')
        diagnostic_id=result['last_error']['diagnostic_id']
        diagnostic=ws.store.root/'diagnostics'/'private'/(diagnostic_id+'.json')
        import sqlite3, json
        with sqlite3.connect(ws.store.root/'checkpoints.db') as db:
            checkpoint_id, metadata, metadata_namespace = db.execute("select checkpoint_id,metadata,checkpoint_ns from checkpoints where checkpoint_ns like 'tools:%' order by checkpoint_id desc limit 1").fetchone()
        parent_checkpoint_id=json.loads(metadata)['parents']['']
        from importlib import metadata as package_metadata
        from report_agent.tool_discovery import exact_registry_compatibility
        fingerprints,new_ref=captured[0]
        new_capture=ws.store.get(new_ref)
        new_files=new_capture['source_files']
        changes={'supervision_plugins.py':{'old':'a'*64,'new':new_files['supervision_plugins.py']},
                 'tool_discovery.py':{'old':'b'*64,'new':new_files['tool_discovery.py']}}
        old_files={**new_files,**{k:v['old'] for k,v in changes.items()}}
        old_capture={**new_capture,'source_files':old_files}
        old_ref='synthetic-old-runtime-capture'
        ws.store.set(old_ref,old_capture)
        versions={name:package_metadata.version(name) for name in ('deepagents','langchain','langchain-core','langgraph','langgraph-checkpoint','langchain-openai')}
        identity={'source_files':old_files,'project_file_sha256':old_capture['project_file_sha256'],'framework_versions':versions}
        old_registry=hashlib.sha256(json.dumps({'tools':fingerprints,'runtime':identity},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        new_registry=ws.store.get('tool_discovery_registry')
        ws.store.set('tool_discovery_registry',old_registry)
        compatibility=exact_registry_compatibility(ws.store,old_runtime_ref=old_ref,changes=changes,
            checkpoint_ns=metadata_namespace,
            checkpoint_id=checkpoint_id,parent_checkpoint_id=parent_checkpoint_id,diagnostic_id=diagnostic_id,
            diagnostic_sha256=hashlib.sha256(diagnostic.read_bytes()).hexdigest(),expected_new_registry_digest=new_registry)
        with compatibility, unknown_child_resume(ws.store, call_id=event['native_tool_call_id'], task_id=event['task_id'],
                diagnostic_id=diagnostic_id, diagnostic_sha256=hashlib.sha256(diagnostic.read_bytes()).hexdigest(),
                checkpoint_id=checkpoint_id, parent_checkpoint_id=parent_checkpoint_id):
            with token_budget(budget):
                resumed=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=="text_tool" else second(role))
        assert seen==[1] and budget.snapshot()==initial
        assert ws.store.get('tool_discovery_registry')==old_registry
        assert ws.store.get(old_ref)==old_capture
        assert len([e for e in ws.store.events() if e['kind']=='tool_discovery_exact_compatibility'])==1
        assert {k: ws.store.get(k) for k in preserved} == preserved
        assert resumed["last_error"] is None
        print("RESERVED_EVENTS", [e["data"] for e in ws.store.events() if e["kind"]=="native_delegation_reserved"])
        from langchain_core.messages import ToolMessage
        assert any(role == "writer" and any(isinstance(m, ToolMessage) and "EVIDENCE_ANALYSIS_OUTCOME_UNRESOLVED" in str(m.content) for m in messages) for role,_,messages in second.calls)
        assert ContentStore(ws.store).list_objects("ContentNode")==[]
    finally:
        await close_model(model)



@pytest.mark.asyncio
async def test_v4_co_autonomously_continues_original_writer_task_after_unresolved(ws, monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke
    from test_text_work import writer_call
    ws.store.set('manifest', {**ws.store.manifest,
        'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2',
        'review_plan_contract':'optional-v1',
        'history_projection_profile':'exact-history-v1',
        'tool_discovery_profile':'agent-search-v2',
        'context_policy':'stateful-tools-v2',
        'context_projection':'review-materials-v2',
        'operation_identity_profile':'native-tool-runtime-v1',
        'content_input_profile':'relation-endpoints-v2',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1',
        'delegation_prompt_profile':'separate-description-v1',
        'review_submission_contract':'task-scope-selectors-v1',
        'execution_progress_policy':{'version':1,'window':64,'repeats':3,'after_notice':2}})
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
    preserved = {f'synthetic_completed_{i}': {'state': 'completed', 'result': f'artifact-{i}'} for i in range(3)}
    for key, value in preserved.items():
        ws.store.set(key, value)
    seen=[]
    async def timeout(request):
        seen.append(1)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",20000,{"glm-5.3":10000})
    def interrupted(messages):
        enforce_host_admission(used_plus_held=budget.snapshot()["reserved_or_unknown_upper_bounds"], limit=20000, unknown=False, failed=True)
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[invoke("process_report_content",operation_id="unknown",objective="Describe source",
            object_type="ContentNode",source_selections=[{"source_id":"s"}]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        from langchain_core.messages import ToolMessage
        reservation=next(e['data'] for e in ws.store.events() if e['kind']=='native_delegation_reserved')
        task_id=reservation['task_id']
        def co_choice(messages):
            assert any(isinstance(m,ToolMessage) and 'NATIVE_DELEGATION_OUTCOME_UNRESOLVED' in str(m.content) for m in messages)
            return invoke('task',subagent_type='writer',resume_content_task_id=task_id,
                          description='Continue the original scoped task; inspect saved work and keep unresolved results unadopted.')
        second=Driver(coordinator=[AIMessage(content="unused"),co_choice,AIMessage(content="continued")],writer=[AIMessage(content="No unresolved output adopted")])
        with token_budget(budget):
            resumed=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=="text_tool" else second(role))
        assert seen==[1] and budget.snapshot()==initial
        assert {k: ws.store.get(k) for k in preserved} == preserved
        assert resumed["last_error"] is None
        print("RESERVED_EVENTS", [e["data"] for e in ws.store.events() if e["kind"]=="native_delegation_reserved"])
        from langchain_core.messages import ToolMessage
        assert any(role == 'writer' for role,_,_ in second.calls)
        assert len([x for x in ContentStore(ws.store).list_objects('DelegatedTask') if x['ref']['id']==task_id])==1
        assert ContentStore(ws.store).list_objects("ContentNode")==[]
    finally:
        await close_model(model)



@pytest.mark.asyncio
async def test_v4_current_root_fact_update_preserves_pending_model_and_old_messages(ws, monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke
    from test_text_work import writer_call
    ws.store.set('manifest', {**ws.store.manifest,
        'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2',
        'review_plan_contract':'optional-v1',
        'history_projection_profile':'exact-history-v1',
        'tool_discovery_profile':'agent-search-v2',
        'context_policy':'stateful-tools-v2',
        'context_projection':'review-materials-v2',
        'operation_identity_profile':'native-tool-runtime-v1',
        'content_input_profile':'relation-endpoints-v2',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1',
        'delegation_prompt_profile':'separate-description-v1',
        'review_submission_contract':'task-scope-selectors-v1',
        'execution_progress_policy':{'version':1,'window':64,'repeats':3,'after_notice':2}})
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
    preserved = {f'synthetic_completed_{i}': {'state': 'completed', 'result': f'artifact-{i}'} for i in range(3)}
    for key, value in preserved.items():
        ws.store.set(key, value)
    seen=[]
    async def timeout(request):
        seen.append(1)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",20000,{"glm-5.3":10000})
    def interrupted(messages):
        enforce_host_admission(used_plus_held=budget.snapshot()["reserved_or_unknown_upper_bounds"], limit=20000, unknown=False, failed=True)
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[invoke("process_report_content",operation_id="unknown",objective="Describe source",
            object_type="ContentNode",source_selections=[{"source_id":"s"}]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        def failed_co(messages):
            raise RequestBudgetExceeded('HOST_TECHNICAL_FAILURE_PENDING')
        second=Driver(coordinator=[AIMessage(content='unused'),failed_co],writer=[])
        with token_budget(budget):
            blocked=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=='text_tool' else second(role))
        assert blocked['last_error'] is not None
        from report_agent.deep_runtime import project_agent
        from langchain_core.messages import HumanMessage, ToolMessage
        third=Driver(coordinator=[],writer=[],reviewer=[],layout=[])
        async with project_agent(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=='text_tool' else third(role)) as agent:
            config={'configurable':{'thread_id':'report'}}
            before=await agent.aget_state(config)
            assert before.next==('model',)
            original_messages=before.values['messages']
            assert any(isinstance(m,ToolMessage) and 'NATIVE_DELEGATION_OUTCOME_UNRESOLVED' in str(m.content) for m in original_messages)
            changed=await agent.aupdate_state(before.config,{'messages':[HumanMessage(content='Recovery facts: original task is unresolved; preserve saved outputs.',id='recovery-fact')]},as_node='WorkingSummary.before_model')
            after=await agent.aget_state(changed)
            assert after.next==('model',)
            assert [m.id for m in after.values['messages'][:-1]]==[m.id for m in original_messages]
            assert after.values['messages'][-1].id=='recovery-fact'
            assert seen==[1] and budget.snapshot()==initial
    finally:
        await close_model(model)



@pytest.mark.asyncio
async def test_v4_root_update_preserves_three_completed_real_work_receipts(ws, monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke, call
    from test_text_work import writer_call
    ws.store.set('manifest', {**ws.store.manifest,
        'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2',
        'review_plan_contract':'optional-v1',
        'history_projection_profile':'exact-history-v1',
        'tool_discovery_profile':'agent-search-v2',
        'context_policy':'stateful-tools-v2',
        'context_projection':'review-materials-v2',
        'operation_identity_profile':'native-tool-runtime-v1',
        'content_input_profile':'relation-endpoints-v2',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1',
        'delegation_prompt_profile':'separate-description-v1',
        'review_submission_contract':'task-scope-selectors-v1',
        'execution_progress_policy':{'version':1,'window':64,'repeats':3,'after_notice':2}})
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
    preserved = {f'synthetic_completed_{i}': {'state': 'completed', 'result': f'artifact-{i}'} for i in range(3)}
    for key, value in preserved.items():
        ws.store.set(key, value)
    seen=[]
    import json
    from test_transport_observation import body as sdk_body
    from test_text_work import content
    async def timeout(request):
        seen.append(1)
        if len(seen)<=3:
            response=sdk_body(model='glm-5.3')
            response['choices'][0]['message']['content']=json.dumps(content())
            return httpx.Response(200,json=response)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",20000,{"glm-5.3":10000})
    def interrupted(messages):
        enforce_host_admission(used_plus_held=budget.snapshot()["reserved_or_unknown_upper_bounds"], limit=20000, unknown=False, failed=True)
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[*[AIMessage(content='',tool_calls=[call('process_report_content',{'operation_id':'done-'+str(i),'objective':'Describe source '+str(i),'object_type':'ContentNode','source_selections':[{'source_id':'s'}]},identity='call-'+str(i))]) for i in range(3)],
            AIMessage(content='',tool_calls=[call('process_report_content',{'operation_id':'unknown','objective':'Describe source final','object_type':'ContentNode','source_selections':[{'source_id':'s'}]},identity='unknown-call')]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1,1,1,1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        with ws.store.read_only() as db:
            import json
            completed={k:json.loads(v) for k,v in db.execute("select key,value from state where key like 'text_work:%'") if json.loads(v).get('state')=='completed'}
        assert len(completed)==3
        def failed_co(messages):
            raise RequestBudgetExceeded('HOST_TECHNICAL_FAILURE_PENDING')
        second=Driver(coordinator=[AIMessage(content='unused'),failed_co],writer=[])
        with token_budget(budget):
            blocked=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=='text_tool' else second(role))
        assert blocked['last_error'] is not None
        from report_agent.deep_runtime import project_agent
        from langchain_core.messages import HumanMessage, ToolMessage
        third=Driver(coordinator=[],writer=[],reviewer=[],layout=[])
        async with project_agent(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=='text_tool' else third(role)) as agent:
            config={'configurable':{'thread_id':'report'}}
            before=await agent.aget_state(config)
            assert before.next==('model',)
            original_messages=before.values['messages']
            assert any(isinstance(m,ToolMessage) and 'NATIVE_DELEGATION_OUTCOME_UNRESOLVED' in str(m.content) for m in original_messages)
            changed=await agent.aupdate_state(before.config,{'messages':[HumanMessage(content='Recovery facts: original task is unresolved; preserve saved outputs.',id='recovery-fact')]},as_node='WorkingSummary.before_model')
            after=await agent.aget_state(changed)
            assert after.next==('model',)
            assert [m.id for m in after.values['messages'][:-1]]==[m.id for m in original_messages]
            assert after.values['messages'][-1].id=='recovery-fact'
            assert seen==[1,1,1,1] and budget.snapshot()==initial
            assert {k:ws.store.get(k) for k in completed}==completed
    finally:
        await close_model(model)



@pytest.mark.asyncio
async def test_v4_root_fact_sdk_choice_reuses_writer_task_without_unknown_resend(ws, monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke, call
    from test_text_work import writer_call
    ws.store.set('manifest', {**ws.store.manifest,
        'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2',
        'review_plan_contract':'optional-v1',
        'history_projection_profile':'exact-history-v1',
        'tool_discovery_profile':'agent-search-v2',
        'context_policy':'stateful-tools-v2',
        'context_projection':'review-materials-v2',
        'operation_identity_profile':'native-tool-runtime-v1',
        'content_input_profile':'relation-endpoints-v2',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1',
        'delegation_prompt_profile':'separate-description-v1',
        'review_submission_contract':'task-scope-selectors-v1',
        'execution_progress_policy':{'version':1,'window':64,'repeats':3,'after_notice':2}})
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
    preserved = {f'synthetic_completed_{i}': {'state': 'completed', 'result': f'artifact-{i}'} for i in range(3)}
    for key, value in preserved.items():
        ws.store.set(key, value)
    seen=[]; unknown_wires=[]
    import json
    from test_transport_observation import body as sdk_body
    from test_text_work import content
    async def timeout(request):
        seen.append(1)
        if len(seen)<=3:
            response=sdk_body(model='glm-5.3')
            response['choices'][0]['message']['content']=json.dumps(content())
            return httpx.Response(200,json=response)
        unknown_wires.append(request.content)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",50000,{"glm-5.3":10000,"deepseek-v4.1-flash":10000})
    def interrupted(messages):
        enforce_host_admission(used_plus_held=budget.snapshot()["reserved_or_unknown_upper_bounds"], limit=50000, unknown=False, failed=True)
    from report_agent.deep_models import configured_model
    for suffix,value in [('MODEL','deepseek-v4.1-flash'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','fake')]:
        monkeypatch.setenv('REPORT_COORDINATOR_'+suffix,value)
    monkeypatch.setenv('REPORT_SDK_RETRIES','0');monkeypatch.setenv('REPORT_CONNECT_RETRIES','0')
    co=configured_model(ws.store,'coordinator')
    co.root_async_client.max_retries=0;co.root_client.max_retries=0
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[*[AIMessage(content='',tool_calls=[call('process_report_content',{'operation_id':'done-'+str(i),'objective':'Describe source '+str(i),'object_type':'ContentNode','source_selections':[{'source_id':'s'}]},identity='call-'+str(i))]) for i in range(3)],
            AIMessage(content='',tool_calls=[call('process_report_content',{'operation_id':'unknown','objective':'Describe source final','object_type':'ContentNode','source_selections':[{'source_id':'s'}]},identity='unknown-call')]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1,1,1,1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        with ws.store.read_only() as db:
            import json
            completed={k:json.loads(v) for k,v in db.execute("select key,value from state where key like 'text_work:%'") if json.loads(v).get('state')=='completed'}
        assert len(completed)==3
        old_co_physical=[]
        async def impossible_transport(request):
            old_co_physical.append(1)
            raise AssertionError('old coordinator request must not be sent')
        co.http_async_client._transport=httpx.MockTransport(impossible_transport);co.http_async_client._mounts.clear()
        async def previous_unproven_fence(request):
            raise RequestBudgetExceeded('HOST_RESUME_PROOF_REQUIRED')
        co.http_async_client.event_hooks['request'].insert(0,previous_unproven_fence)
        second=Driver(coordinator=[],writer=[])
        with token_budget(budget):
            blocked=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:co if role=='coordinator' else model if role=='text_tool' else second(role))
        co.http_async_client.event_hooks['request'].remove(previous_unproven_fence)
        assert blocked['last_error'] is not None and old_co_physical==[] and budget.snapshot()==initial
        with ws.store.read_only() as db:
            old_co={k:json.loads(v) for k,v in db.execute("select key,value from state where key like 'model_recovery_call:%'") if json.loads(v).get('role')=='coordinator' and json.loads(v).get('state')=='unknown'}
        assert len(old_co)==1
        from report_agent.deep_runtime import project_agent
        from langchain_core.messages import HumanMessage, ToolMessage, messages_to_dict
        task_id=next(e['data']['task_id'] for e in ws.store.events() if e['kind']=='native_delegation_reserved')
        co_wires=[]
        async def co_transport(request):
            co_wires.append(json.loads(request.content))
            response=sdk_body(model='deepseek-v4.1-flash')
            if len(co_wires)==1:
                response['choices'][0]['finish_reason']='tool_calls'
                response['choices'][0]['message']={'role':'assistant','content':'','tool_calls':[{'id':'resume-writer','type':'function','function':{'name':'task','arguments':json.dumps({'subagent_type':'writer','description':'Continue original task; inspect saved work and do not adopt unresolved outputs.','resume_content_task_id':task_id})}}]}
            return httpx.Response(200,json=response)
        co.http_async_client._transport=httpx.MockTransport(co_transport);co.http_async_client._mounts.clear()
        import importlib.util, hashlib
        spec=importlib.util.spec_from_file_location('resume_host_guards',str(__import__('pathlib').Path(__file__).parent / 'fixtures' / 'resume_host_guards.py'))
        assert hashlib.sha256(__import__('pathlib').Path(spec.origin).read_bytes()).hexdigest() == '43516f41f8ce6ed106b6eed273fae1616f4fbae256b6302ddda070a70b241d21'
        guards=importlib.util.module_from_spec(spec);spec.loader.exec_module(guards)
        old_raw=hashlib.sha256(unknown_wires[0]).hexdigest();old_canonical=guards.canonical_wire_sha256(unknown_wires[0])
        async def fence(request): guards.guard_unknown_wire(request,old_raw,old_canonical)
        co.http_async_client.event_hooks['request'].insert(0,fence)
        from report_agent.request_budget import request_reservation_observer
        admissions=[]
        def admission():
            current=budget.snapshot();admissions.append((current['recorded_tokens'],current['reserved_or_unknown_upper_bounds']))
            enforce_host_admission(used_plus_held=current['recorded_tokens']+current['reserved_or_unknown_upper_bounds'],limit=50000,unknown=False,failed=False)
        receipt_ops=['native:process_report_content:'+k.rsplit(':native:process_report_content:',1)[1] for k in sorted(completed)]
        writer_script=[]; inspected=[]
        for i,op in enumerate(receipt_ops):
            writer_script.append(AIMessage(content='',tool_calls=[call('select_tools',{'names':['get_operation_receipt']},identity='select-'+str(i))]))
            writer_script.append(AIMessage(content='',tool_calls=[call('get_operation_receipt',{'operation_id':op},identity='receipt-'+str(i))]))
        def finish_writer(messages):
            receipts=[json.loads(m.content) for m in messages if isinstance(m,ToolMessage) and m.name=='get_operation_receipt']
            assert len(receipts)==3 and all(x.get('text_work',{}).get('state')=='completed' for x in receipts)
            inspected.append(True)
            return AIMessage(content='Inspected the three saved text-work receipts; no unresolved output adopted.')
        writer_script.append(finish_writer)
        third=Driver(coordinator=[],writer=writer_script,reviewer=[],layout=[])
        async with project_agent(Workspace(Store(ws.store.root)),model_factory=lambda role:co if role=='coordinator' else model if role=='text_tool' else third(role)) as agent:
            config={'configurable':{'thread_id':'report'}}
            before=await agent.aget_state(config)
            assert before.next==('model',)
            original_messages=before.values['messages']
            assert any(isinstance(m,ToolMessage) and 'NATIVE_DELEGATION_OUTCOME_UNRESOLVED' in str(m.content) for m in original_messages)
            recovery_fact='[系统恢复通知：由宿主生成，并非用户指令]'+json.dumps({'task_id':task_id,'native_task':'unresolved','text_call':'unknown','completed_text_work_ids':[v['result']['text_work_id'] for v in completed.values()],'co_call':'local_fence_not_dispatched','permissions':'unchanged'},ensure_ascii=False)
            changed=await agent.aupdate_state(before.config,{'messages':[HumanMessage(content=recovery_fact,id='recovery-fact',name='host_recovery_observation')]},as_node='WorkingSummary.before_model')
            after=await agent.aget_state(changed)
            assert after.next==('model',)
            assert messages_to_dict(after.values['messages'][:-1])==messages_to_dict(original_messages)
            assert after.values['messages'][-1].id=='recovery-fact'
            assert seen==[1,1,1,1] and budget.snapshot()==initial
            assert {k:ws.store.get(k) for k in completed}==completed
            with token_budget(budget),request_reservation_observer(admission):
                await agent.ainvoke(None,changed)
            assert len(co_wires)==2 and admissions and all(held>=10000 for _,held in admissions)
            with token_budget(budget),request_reservation_observer(admission):
                with pytest.raises(RequestBudgetExceeded,match='HOST_PRIOR_UNKNOWN_WIRE_FENCED'):
                    await co.http_async_client.post('https://offline.invalid/v1/chat/completions',content=unknown_wires[0])
            assert len(co_wires)==2
            first_wire=json.dumps(co_wires[0],ensure_ascii=False)
            assert '[系统恢复通知：由宿主生成，并非用户指令]' in first_wire
            assert all(v['result']['text_work_id'] in first_wire for v in completed.values())
            assert any(m.get('role')=='user' and m.get('name')=='host_recovery_observation' for m in co_wires[0]['messages'])
            assert 'NATIVE_DELEGATION_OUTCOME_UNRESOLVED' in first_wire
            assert any(role=='writer' for role,_,_ in third.calls) and inspected==[True]
            assert len([x for x in ContentStore(ws.store).list_objects('DelegatedTask') if x['ref']['id']==task_id])==1
            assert seen==[1,1,1,1]
            assert {k:ws.store.get(k) for k in completed}==completed
            assert {k:ws.store.get(k) for k in old_co}==old_co
            assert budget.snapshot()['reserved_or_unknown_upper_bounds']==10000
    finally:
        await close_model(co)
        await close_model(model)



@pytest.mark.asyncio
async def test_v4_system_recovery_notice_wire_role_and_original_task(ws, monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke, call
    from test_text_work import writer_call
    ws.store.set('manifest', {**ws.store.manifest,
        'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2',
        'review_plan_contract':'optional-v1',
        'history_projection_profile':'exact-history-v1',
        'tool_discovery_profile':'agent-search-v2',
        'context_policy':'stateful-tools-v2',
        'context_projection':'review-materials-v2',
        'operation_identity_profile':'native-tool-runtime-v1',
        'content_input_profile':'relation-endpoints-v2',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1',
        'delegation_prompt_profile':'separate-description-v1',
        'review_submission_contract':'task-scope-selectors-v1',
        'execution_progress_policy':{'version':1,'window':64,'repeats':3,'after_notice':2}})
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
    preserved = {f'synthetic_completed_{i}': {'state': 'completed', 'result': f'artifact-{i}'} for i in range(3)}
    for key, value in preserved.items():
        ws.store.set(key, value)
    seen=[]; unknown_wires=[]
    import json
    from test_transport_observation import body as sdk_body
    from test_text_work import content
    async def timeout(request):
        seen.append(1)
        if len(seen)<=3:
            response=sdk_body(model='glm-5.3')
            response['choices'][0]['message']['content']=json.dumps(content())
            return httpx.Response(200,json=response)
        unknown_wires.append(request.content)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",50000,{"glm-5.3":10000,"deepseek-v4.1-flash":10000})
    def interrupted(messages):
        enforce_host_admission(used_plus_held=budget.snapshot()["reserved_or_unknown_upper_bounds"], limit=50000, unknown=False, failed=True)
    from report_agent.deep_models import configured_model
    for suffix,value in [('MODEL','deepseek-v4.1-flash'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','fake')]:
        monkeypatch.setenv('REPORT_COORDINATOR_'+suffix,value)
    monkeypatch.setenv('REPORT_SDK_RETRIES','0');monkeypatch.setenv('REPORT_CONNECT_RETRIES','0')
    co=configured_model(ws.store,'coordinator')
    co.root_async_client.max_retries=0;co.root_client.max_retries=0
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[*[AIMessage(content='',tool_calls=[call('process_report_content',{'operation_id':'done-'+str(i),'objective':'Describe source '+str(i),'object_type':'ContentNode','source_selections':[{'source_id':'s'}]},identity='call-'+str(i))]) for i in range(3)],
            AIMessage(content='',tool_calls=[call('process_report_content',{'operation_id':'unknown','objective':'Describe source final','object_type':'ContentNode','source_selections':[{'source_id':'s'}]},identity='unknown-call')]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1,1,1,1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        with ws.store.read_only() as db:
            import json
            completed={k:json.loads(v) for k,v in db.execute("select key,value from state where key like 'text_work:%'") if json.loads(v).get('state')=='completed'}
        assert len(completed)==3
        old_co_physical=[]
        async def impossible_transport(request):
            old_co_physical.append(1)
            raise AssertionError('old coordinator request must not be sent')
        co.http_async_client._transport=httpx.MockTransport(impossible_transport);co.http_async_client._mounts.clear()
        async def previous_unproven_fence(request):
            raise RequestBudgetExceeded('HOST_RESUME_PROOF_REQUIRED')
        co.http_async_client.event_hooks['request'].insert(0,previous_unproven_fence)
        second=Driver(coordinator=[],writer=[])
        with token_budget(budget):
            blocked=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:co if role=='coordinator' else model if role=='text_tool' else second(role))
        co.http_async_client.event_hooks['request'].remove(previous_unproven_fence)
        assert blocked['last_error'] is not None and old_co_physical==[] and budget.snapshot()==initial
        with ws.store.read_only() as db:
            old_co={k:json.loads(v) for k,v in db.execute("select key,value from state where key like 'model_recovery_call:%'") if json.loads(v).get('role')=='coordinator' and json.loads(v).get('state')=='unknown'}
        assert len(old_co)==1
        from report_agent.deep_runtime import project_agent
        from langchain_core.messages import SystemMessage, ToolMessage, messages_to_dict
        task_id=next(e['data']['task_id'] for e in ws.store.events() if e['kind']=='native_delegation_reserved')
        co_wires=[]
        async def co_transport(request):
            co_wires.append(json.loads(request.content))
            response=sdk_body(model='deepseek-v4.1-flash')
            if len(co_wires)==1:
                response['choices'][0]['finish_reason']='tool_calls'
                response['choices'][0]['message']={'role':'assistant','content':'','tool_calls':[{'id':'resume-writer','type':'function','function':{'name':'task','arguments':json.dumps({'subagent_type':'writer','description':'Continue original task; inspect saved work and do not adopt unresolved outputs.','resume_content_task_id':task_id})}}]}
            return httpx.Response(200,json=response)
        co.http_async_client._transport=httpx.MockTransport(co_transport);co.http_async_client._mounts.clear()
        import importlib.util, hashlib
        spec=importlib.util.spec_from_file_location('resume_host_guards',str(__import__('pathlib').Path(__file__).parent / 'fixtures' / 'resume_host_guards.py'))
        assert hashlib.sha256(__import__('pathlib').Path(spec.origin).read_bytes()).hexdigest() == '43516f41f8ce6ed106b6eed273fae1616f4fbae256b6302ddda070a70b241d21'
        guards=importlib.util.module_from_spec(spec);spec.loader.exec_module(guards)
        old_raw=hashlib.sha256(unknown_wires[0]).hexdigest();old_canonical=guards.canonical_wire_sha256(unknown_wires[0])
        async def fence(request): guards.guard_unknown_wire(request,old_raw,old_canonical)
        co.http_async_client.event_hooks['request'].insert(0,fence)
        from report_agent.request_budget import request_reservation_observer
        admissions=[]
        def admission():
            current=budget.snapshot();admissions.append((current['recorded_tokens'],current['reserved_or_unknown_upper_bounds']))
            enforce_host_admission(used_plus_held=current['recorded_tokens']+current['reserved_or_unknown_upper_bounds'],limit=50000,unknown=False,failed=False)
        receipt_ops=['native:process_report_content:'+k.rsplit(':native:process_report_content:',1)[1] for k in sorted(completed)]
        writer_script=[]; inspected=[]
        for i,op in enumerate(receipt_ops):
            writer_script.append(AIMessage(content='',tool_calls=[call('select_tools',{'names':['get_operation_receipt']},identity='select-'+str(i))]))
            writer_script.append(AIMessage(content='',tool_calls=[call('get_operation_receipt',{'operation_id':op},identity='receipt-'+str(i))]))
        def finish_writer(messages):
            receipts=[json.loads(m.content) for m in messages if isinstance(m,ToolMessage) and m.name=='get_operation_receipt']
            assert len(receipts)==3 and all(x.get('text_work',{}).get('state')=='completed' for x in receipts)
            inspected.append(True)
            return AIMessage(content='Inspected the three saved text-work receipts; no unresolved output adopted.')
        writer_script.append(finish_writer)
        third=Driver(coordinator=[],writer=writer_script,reviewer=[],layout=[])
        async with project_agent(Workspace(Store(ws.store.root)),model_factory=lambda role:co if role=='coordinator' else model if role=='text_tool' else third(role)) as agent:
            config={'configurable':{'thread_id':'report'}}
            before=await agent.aget_state(config)
            assert before.next==('model',)
            original_messages=before.values['messages']
            assert any(isinstance(m,ToolMessage) and 'NATIVE_DELEGATION_OUTCOME_UNRESOLVED' in str(m.content) for m in original_messages)
            changed=await agent.aupdate_state(before.config,{'messages':[SystemMessage(content='Recovery facts: original task is unresolved; preserve saved outputs.',id='recovery-fact')]},as_node='WorkingSummary.before_model')
            after=await agent.aget_state(changed)
            assert after.next==('model',)
            assert messages_to_dict(after.values['messages'][:-1])==messages_to_dict(original_messages)
            assert after.values['messages'][-1].id=='recovery-fact'
            assert seen==[1,1,1,1] and budget.snapshot()==initial
            assert {k:ws.store.get(k) for k in completed}==completed
            with token_budget(budget),request_reservation_observer(admission):
                await agent.ainvoke(None,changed)
            assert len(co_wires)==2 and admissions and all(held>=10000 for _,held in admissions)
            with token_budget(budget),request_reservation_observer(admission):
                with pytest.raises(RequestBudgetExceeded,match='HOST_PRIOR_UNKNOWN_WIRE_FENCED'):
                    await co.http_async_client.post('https://offline.invalid/v1/chat/completions',content=unknown_wires[0])
            assert len(co_wires)==2
            first_wire=json.dumps(co_wires[0],ensure_ascii=False)
            assert 'Recovery facts: original task is unresolved' in first_wire
            assert any(m.get('role')=='system' and 'Recovery facts: original task is unresolved' in str(m.get('content')) for m in co_wires[0]['messages'])
            assert 'NATIVE_DELEGATION_OUTCOME_UNRESOLVED' in first_wire
            assert any(role=='writer' for role,_,_ in third.calls) and inspected==[True]
            assert len([x for x in ContentStore(ws.store).list_objects('DelegatedTask') if x['ref']['id']==task_id])==1
            assert seen==[1,1,1,1]
            assert {k:ws.store.get(k) for k in completed}==completed
            assert {k:ws.store.get(k) for k in old_co}==old_co
            assert budget.snapshot()['reserved_or_unknown_upper_bounds']==10000
    finally:
        await close_model(co)
        await close_model(model)

