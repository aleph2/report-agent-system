# Fresh report host; effective non-secret settings come from config/current.json.
# Reuses the verified native host; no old checkpoint or unknown is replayed.
import asyncio,fcntl,hashlib,json,os,sqlite3,sys,time
from urllib.parse import urlsplit
from contextlib import closing
from pathlib import Path

HERE=Path(__file__).resolve().parent
DEPLOYMENT=json.loads((HERE/"deployment.json").read_text()) if (HERE/"deployment.json").is_file() else None
HOME_ROOT=Path(DEPLOYMENT["repository"]) if DEPLOYMENT else HERE.parent
SOURCE=HERE/"source" if DEPLOYMENT else HOME_ROOT
CONFIG=json.loads((SOURCE/"config/current.json").read_text())
INPUT=HERE/"inputs"
CASE=HERE/"case"
CANONICAL=HOME_ROOT/".financial-records/token-budget.db"
LEDGER=Path(DEPLOYMENT["ledger"]) if DEPLOYMENT else None
ENV=HOME_ROOT/".env"
LOCK=HOME_ROOT/".runs/shared-model-validation.lock"
LIMIT=CONFIG["round_token_limit"]
TOTAL_LIMIT=CONFIG.get("m1_token_limit",LIMIT)
ROLE_MODELS=CONFIG["models"]
MODEL_BOUNDS={model:CONFIG["reserved_tokens_per_attempt"] for model in set(ROLE_MODELS.values())}
sys.path.insert(0,str(SOURCE/"src"))
from report_agent import issue_state

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding="utf8"))
def save(p,data):
 with Path(p).open("x",encoding="utf8") as f:
  json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
def source_pins():
 files=sorted(p for p in (SOURCE/"src/report_agent").rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
 files.extend(SOURCE/name for name in ("pyproject.toml","requirements.lock","config/current.json","scripts/report_host.py","scripts/stage_report.py","scripts/prepare_report.py","scripts/launch_report.py"))
 return {str(p.relative_to(SOURCE)):sha(p) for p in files}
def input_files():
 root=INPUT.resolve(strict=True)
 files=sorted(p for p in root.rglob("*") if p.is_file() and not p.name.startswith("~$"))
 result={}
 for p in files:
  if p.is_symlink() or not p.resolve().is_relative_to(root) or (p.suffix.lower() not in (".pdf",".md",".docx") and p.relative_to(root).as_posix() not in ("owner-decisions.json","carryover-judgments.json")):raise RuntimeError("INPUT_ESCAPE_OR_TYPE")
  if p.stat().st_size>CONFIG["input_max_bytes"]:raise RuntimeError("INPUT_RESOURCE_LIMIT")
  result[str(p.relative_to(root))]=sha(p)
 return result

def read_finance(path):
 with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
  db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
  auth=db.execute("select maximum,bounds from authorization where id=1").fetchone()
  rows=list(db.execute("select id,model,reserved,used,state,response_id,reason,at from attempts order by id"))
  db.rollback()
 if auth is None:raise ValueError("AUTH_MISSING")
 return {"auth":list(auth),"rows":[list(x) for x in rows]}
def canonical_baseline():
 if not CANONICAL.exists():return None
 records=read_finance(CANONICAL); rows=records["rows"]
 return {"sha256":sha(CANONICAL),"rows_sha256":hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
 "attempt_count":len(rows),"used":sum(x[3] or 0 for x in rows),
 "held":sum(x[2] for x in rows if x[4] in ("reserved","unknown")),
 "bounds":json.loads(records["auth"][1])}
def finance():return read_finance(LEDGER)

def validate_budget_authority():
 if not DEPLOYMENT or not DEPLOYMENT.get("budget_authority"):
  if DEPLOYMENT and DEPLOYMENT.get("reuse_ledger"):raise RuntimeError("M1_BUDGET_AUTHORITY_REQUIRED")
  return
 path=Path(DEPLOYMENT["budget_authority"])
 if sha(path)!=DEPLOYMENT["budget_authority_sha256"]:raise RuntimeError("M1_BUDGET_AUTHORITY_CHANGED")
 authority=load(path)
 if (Path(authority.get("ledger","")).resolve()!=LEDGER.resolve()
     or authority.get("maximum_tokens")!=TOTAL_LIMIT or authority.get("model_bounds")!=MODEL_BOUNDS
     or any(not isinstance(authority.get(k),str) or not authority[k].strip() for k in ("authorization_id","user_authority"))):
  raise RuntimeError("M1_BUDGET_AUTHORITY_MISMATCH")
 grant=authority.get('grant_scope')
 if CONFIG.get('grant_token_limit'):
  if (not isinstance(grant,dict) or grant.get('maximum_tokens')!=CONFIG['grant_token_limit']
      or grant.get('baseline_sha256')!=hashlib.sha256(json.dumps(grant.get('baseline'),sort_keys=True,separators=(',',':')).encode()).hexdigest()
      or grant.get('baseline',{}).get('auth')!=finance()['auth']):raise RuntimeError('G5_GRANT_SCOPE_REQUIRED')
  used,held,_=budget_scope_cost(grant['baseline'],finance())
  if used+held>grant['maximum_tokens']:raise RuntimeError('G5_GRANT_EXHAUSTED')

from report_agent.planning_budget import budget_scope_cost


def endpoint_pins():
 from report_agent.model_config import load_mixed_services,role_service
 load_mixed_services(ENV)
 if role_service("layout")!=role_service("writer"):raise RuntimeError("LAYOUT_SERVICE_OVERRIDE_FORBIDDEN")
 result={}
 for role,expected in ROLE_MODELS.items():
  model,url,key=role_service(role)
  parsed=urlsplit(url)
  if model!=expected or not key or parsed.scheme!="https" or not parsed.hostname:raise RuntimeError("MODEL_ENDPOINT_CONFIG_MISMATCH")
  result[role]=hashlib.sha256(url.rstrip("/").encode()).hexdigest()
 return result

def prepare():
 from report_agent.storage_preflight import require_native_storage
 if LEDGER is None:raise RuntimeError("STAGED_DEPLOYMENT_REQUIRED")
 require_native_storage(HERE,CASE,CASE/"state.db",CASE/"checkpoints.db",CASE/"experience-library/state.db",LEDGER)
 import resource
 resource.setrlimit(resource.RLIMIT_AS,(CONFIG["prepare_memory_bytes"],CONFIG["prepare_memory_bytes"]))
 from report_agent.store import Store
 from report_agent.workspace import Workspace
 from report_agent.catalog import Catalog
 from report_agent.content_store import ContentStore
 from report_agent.learning import LearningLibrary
 from report_agent.token_budget import TokenBudget
 import report_agent.ingestion as ingestion
 if LEDGER is None:raise RuntimeError("STAGED_DEPLOYMENT_REQUIRED")
 reuse=bool(DEPLOYMENT and DEPLOYMENT.get("reuse_ledger"))
 if CASE.exists() or (LEDGER.exists() and not reuse) or (HERE/"prepared.json").exists():raise RuntimeError("CASE_EXISTS")
 validate_budget_authority()
 if reuse and (not LEDGER.is_file() or finance()!=load(HERE/"stage-receipt.json")["ledger_baseline"]):raise RuntimeError("M1_LEDGER_BASELINE_CHANGED")
 canonical=canonical_baseline();bounds=MODEL_BOUNDS
 if bounds!=MODEL_BOUNDS:raise RuntimeError("MODEL_BOUND_NOT_REGISTERED")
 settings=endpoint_pins();pins=input_files()
 if settings!=load(HERE/"approved-endpoint-pins.json") or pins!=load(HERE/"approved-input-hashes.json"):raise RuntimeError("APPROVED_INPUT_OR_ENDPOINT_DRIFT")
 profiles={x["path"]:x for x in load(HERE/"pdf-limits.json")}
 if {n for n in pins if n.lower().endswith(".pdf")}!=set(profiles):raise RuntimeError("PDF_PROFILE_SET_MISMATCH")
 if any(pins[n]!=v["sha256"] or (INPUT/n).stat().st_size!=v["input_bytes"] or v["pages"]>ingestion.MAX_PDF_PAGES for n,v in profiles.items()):raise RuntimeError("PDF_PROFILE_INPUT_MISMATCH")
 scope_names=[n for n in pins if Path(n).name=="报告编写范围说明.md"]
 references=[n for n in pins if Path(n).parts[0]=="成果报告" and n.lower().endswith(".pdf")]
 if len(scope_names)!=1:raise RuntimeError("COMMISSION_OR_REFERENCE_AMBIGUOUS")
 scope=(INPUT/scope_names[0]).read_text(encoding="utf-8-sig")
 instruction="根据委托要求编写报告，以所提供资料及适用规范为事实和评估依据。报告内容、结构、风格及交付形式由委托要求确定。明确说明无法确认的事项，不得编造。记录资料间的冲突，并按委托要求处理。"
 goal=instruction+"\n\n"+scope
 manifest={"synthetic":CONFIG["synthetic"],"goal":goal,"scope_instruction":instruction,"commission_checkpoint_required":True,"assessment_presentation":"table-spec-v1","commission_requirements_contract":"commission-requirements-v1","commission_planning_contract":"commission-planning-v1","sources":[{"id":"commission","title":"用户委托及编写范围","content":goal,"coverage":"complete"}],
   **CONFIG["manifest_profiles"]}
 budget=TokenBudget(LEDGER,TOTAL_LIMIT,bounds)
 ledger_baseline=finance()
 if not reuse and ledger_baseline["rows"]:raise RuntimeError("LEDGER_NOT_FRESH")
 store=Store(CASE);store.initialize(manifest);ws=Workspace(store);ws.initialize();cat=Catalog(store)
 original_limits=(ingestion.MAX_UPLOAD_BYTES,ingestion.MAX_PDF_PAGE_CONTENT_BYTES,ingestion.MAX_PDF_TOTAL_CONTENT_BYTES)
 ids=[];inputs={}
 try:
  for name,digest in pins.items():
   if name in ("owner-decisions.json","carryover-judgments.json"):continue
   path=INPUT/name;data=path.read_bytes();profile=profiles.get(name)
   if hashlib.sha256(data).hexdigest()!=digest:raise RuntimeError("INPUT_CHANGED_DURING_PREPARE")
   ingestion.MAX_UPLOAD_BYTES=max(original_limits[0],len(data))
   ingestion.MAX_PDF_PAGE_CONTENT_BYTES=max(original_limits[1],profile["largest_page_bytes"]) if profile else original_limits[1]
   ingestion.MAX_PDF_TOTAL_CONTENT_BYTES=max(original_limits[2],profile["total_decoded_bytes"]) if profile else original_limits[2]
   record=cat.import_file(path.name,data)["source"];ids.append(record["id"])
   inputs[name]={"id":record["id"],"sha256":digest,"bytes":len(data),"pages":profile["pages"] if profile else None,"purpose":"template" if name in references else "commission" if name in scope_names else "source_or_applicable_standard"}
   print(json.dumps({"imported":name,"bytes":len(data),"pages":profile["pages"] if profile else None},ensure_ascii=False),flush=True)
 finally:
  ingestion.MAX_UPLOAD_BYTES,ingestion.MAX_PDF_PAGE_CONTENT_BYTES,ingestion.MAX_PDF_TOTAL_CONTENT_BYTES=original_limits
 from report_agent.commission_imports import install_source_roles
 install_source_roles(store,inputs)
 store.set("knowledge_enabled",False);LearningLibrary(CASE/"experience-library")
 store.set("learning_config",{"library_path":str(CASE/"experience-library"),"customer_id":"real-project-isolated"})
 from report_agent.model_recovery import activate_recovery
 recovery=activate_recovery(store,authorization=load(HERE/"authorization.json")["authority"],extra_per_call=CONFIG["maximum_attempts_per_call"]-1,extra_per_case=None,extra_token_ceiling=None,backoff_seconds=CONFIG["retry_backoff_seconds"])
 from report_agent.commission_imports import TYPES as intake_types
 if any(r["ref"]["type"] not in intake_types for r in ContentStore(store).list_objects()) or (CASE/"checkpoints.db").exists():raise RuntimeError("CASE_HAS_SEEDED_RESULTS")
 from report_agent.commission_requirements import install_requirements
 from report_agent.content_store import Actor
 contents=ContentStore(store)
 outline=inputs.get(CONFIG.get("commission_outline_input"))
 requirement_source_ids=[inputs[scope_names[0]]["id"],*([outline["id"]] if outline else [])]
 captured=contents.capture_sources(Actor("host","host","commission-requirements"),"host-commission-sources",requirement_source_ids)["result"]["source_refs"]
 requirements_ref=install_requirements(contents,captured[0],captured[1] if outline else None)
 from importlib.resources import files
 from report_agent.commission_planning import install_prepared_planning
 prepared_hashes=json.loads(files('report_agent').joinpath('methods/high_slope_tables.json').read_text(encoding='utf-8'))['source_hashes'].values()
 prepared_ids=[value['id'] for value in inputs.values() if value['sha256'] in prepared_hashes]
 prepared_refs=(contents.capture_sources(Actor('host','host','commission-prepared-data'),'host-prepared-planning-sources',prepared_ids)['result']['source_refs'] if prepared_ids else [])
 planning_preparation=install_prepared_planning(contents,[*captured,*prepared_refs])
 requirements_ref=planning_preparation['requirements_ref']
 owner_records_digest=None
 skeleton_digest=None
 if 'owner-decisions.json' in pins:
  from report_agent.commission_owner_records import install_owner_records
  owner_refs=contents.capture_sources(Actor('host','host','owner-record-sources'),'host-owner-record-sources',ids)['result']['source_refs']
  by_hash={}
  for ref in [*captured,*prepared_refs,*owner_refs]:by_hash.setdefault(contents.read(ref)['payload']['file_digest'],ref)
  owner_bytes=(INPUT/'owner-decisions.json').read_bytes()
  if hashlib.sha256(owner_bytes).hexdigest()!=pins['owner-decisions.json']:raise RuntimeError('OWNER_RECORDS_CHANGED_DURING_PREPARE')
  owner_records_digest=install_owner_records(contents,json.loads(owner_bytes),list(by_hash.values()))
  from report_agent.commission_skeleton import prepare_skeleton
  skeleton=prepare_skeleton(contents,list(by_hash.values()))
  requirements_ref=skeleton["requirements_ref"];skeleton_digest=skeleton["digest"]
 carryover_digest=None
 if 'carryover-judgments.json' in pins:
  if not skeleton_digest:raise RuntimeError('CARRYOVER_OWNER_SKELETON_REQUIRED')
  from report_agent.commission_carryover import install_carryover
  carryover_bytes=(INPUT/'carryover-judgments.json').read_bytes()
  if hashlib.sha256(carryover_bytes).hexdigest()!=pins['carryover-judgments.json']:raise RuntimeError('CARRYOVER_CHANGED_DURING_PREPARE')
  carryover_digest=install_carryover(contents,json.loads(carryover_bytes),list(by_hash.values()))
 from report_agent.blob_store import verify_case_blobs
 verify_case_blobs(CASE)
 save(HERE/"prepared.json",{"case":str(CASE),"input_hashes":pins,"source_pins":source_pins(),"host_sha256":sha(__file__),
    "deployment_sha256":sha(HERE/"deployment.json"),"authorization_sha256":sha(HERE/"authorization.json"),
    "source_ids":ids,"source_files":inputs,"format_references":references,"goal":goal,"state_sha256":sha(CASE/"state.db"),"library_sha256":sha(CASE/"experience-library/state.db"),
    "pdf_limits_sha256":sha(HERE/"pdf-limits.json"),"carryover_digest":carryover_digest,"owner_records_digest":owner_records_digest,"skeleton_digest":skeleton_digest,"requirements_ref":requirements_ref,"recovery_policy":recovery,"endpoint_pins":settings,"synthetic":CONFIG["synthetic"],"scope_limit":LIMIT,"timeout_seconds":CONFIG["timeout_seconds"],"canonical_baseline":canonical,
    "authority":load(HERE/"authorization.json")["authority"],
    "financial_authority_path":str(LEDGER),"m1_token_limit":TOTAL_LIMIT,"ledger_baseline":ledger_baseline,"maximum_attempts_per_call":CONFIG["maximum_attempts_per_call"],"sdk_retries":CONFIG["sdk_retries"],"connect_retries":CONFIG["connect_retries"],
    "resource_limit_note":"Reuse previously measured per-SHA PDF limits under8GiB prepare address-space and256MiB per original; no general product upload-limit change.",
    "template_limitation":"Template is registered material; exact permitted reuse follows the owner-confirmed section plan. Source and export checks remain necessary."})
 print("real case prepared; no model requests sent",flush=True)

async def run_with_owner_checkpoint(workspace, runner):
 while True:
  result=await runner(workspace)
  if workspace.store.get('report_status')!='needs_human':return result
  pending=workspace.store.get('native_interrupts',[])
  if not pending or any(not item.get('value',{}).get('issue_id') for item in pending):
   workspace.store.set('report_status','needs_attention')
   return workspace.status()
  ids={item['value']['issue_id'] for item in pending}
  while True:
   issues={item['id']:item for item in issue_state.get_report_issues(workspace.store,[])}
   if all(issues.get(key,{}).get('decision_origin')=='operator' for key in ids):break
   await asyncio.sleep(1)


async def run():
 from report_agent.storage_preflight import require_native_storage
 if LEDGER is None:raise RuntimeError("STAGED_DEPLOYMENT_REQUIRED")
 require_native_storage(HERE,CASE,CASE/"state.db",CASE/"checkpoints.db",CASE/"experience-library/state.db",LEDGER)
 import report_agent.deep_runtime as runtime
 import report_agent.deep_models as dm
 import report_agent.vision as vision
 import report_agent.model_invocation as inv
 import report_agent.token_budget as tb
 import report_agent.request_budget as rb
 from report_agent.model_config import load_mixed_services,bind_role_services,role_service
 from report_agent.store import Store
 from report_agent.workspace import Workspace
 from report_agent.model_recovery import load_recovery_policy
 from report_agent.token_budget import TokenBudget,token_budget
 prep=load(HERE/"prepared.json");approval=load(HERE/"neo-approval.json")
 if DEPLOYMENT and (prep.get("deployment_sha256")!=sha(HERE/"deployment.json") or prep.get("authorization_sha256")!=sha(HERE/"authorization.json")):raise RuntimeError("DEPLOYMENT_OR_AUTHORITY_DRIFT")
 if not approval.get("approved") or approval.get("host_sha256")!=sha(__file__) or approval.get("prepared_sha256")!=sha(HERE/"prepared.json"):raise RuntimeError("EXACT_REVIEW_REQUIRED")
 if prep["host_sha256"]!=sha(__file__) or prep["source_pins"]!=source_pins() or prep["input_hashes"]!=input_files():raise RuntimeError("PIN_DRIFT")
 if (HERE/"started.json").exists() or (CASE/"checkpoints.db").exists() or sha(CASE/"state.db")!=prep["state_sha256"] or sha(CASE/"experience-library/state.db")!=prep["library_sha256"]:raise RuntimeError("CASE_NOT_FRESH")
 from report_agent.blob_store import verify_case_blobs
 verify_case_blobs(CASE)
 with LOCK.open("a") as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  validate_budget_authority()
  if canonical_baseline()!=prep["canonical_baseline"]:raise RuntimeError("CANONICAL_BASELINE_CHANGED")
  before=finance()
  bounds=json.loads(before["auth"][1])
  if before["auth"][0]!=TOTAL_LIMIT or before!=prep["ledger_baseline"] or bounds!=MODEL_BOUNDS:raise RuntimeError("M1_LEDGER_BASELINE_CHANGED")
  if bounds!=MODEL_BOUNDS:raise RuntimeError("MODEL_BOUND_NOT_REGISTERED")
  os.environ.update(REPORT_SDK_RETRIES=str(CONFIG["sdk_retries"]),REPORT_CONNECT_RETRIES=str(CONFIG["connect_retries"]),REPORT_REASONING_EFFORT=CONFIG["reasoning_effort"],REPORT_COORDINATOR_REASONING_EFFORT=CONFIG["reasoning_effort"],REPORT_REVIEWER_REASONING_EFFORT=CONFIG["reasoning_effort"])
  load_mixed_services(ENV)
  if role_service("layout")!=role_service("writer"):raise RuntimeError("LAYOUT_SERVICE_OVERRIDE_FORBIDDEN")
  for role,model in ROLE_MODELS.items():
   name,url,key=role_service(role)
   if name!=model or not key or urlsplit(url).scheme!="https" or hashlib.sha256(url.rstrip("/").encode()).hexdigest()!=prep["endpoint_pins"].get(role):raise RuntimeError("MODEL_OR_CREDENTIAL_MISMATCH")
  if inv.MODEL_REQUEST_DEADLINE_SECONDS!=CONFIG["timeout_seconds"]:raise RuntimeError("SOURCE_TIMEOUT_MISMATCH")
  store=Store(CASE);workspace=Workspace(store)
  policy=load_recovery_policy(store)
  if (policy!=prep["recovery_policy"] or policy["extra_per_call"]!=CONFIG["maximum_attempts_per_call"]-1 or policy["extra_per_case"] is not None or policy["extra_token_ceiling"] is not None):raise RuntimeError("RECOVERY_DRIFT")
  bind_role_services(store)
  budget=TokenBudget(LEDGER,TOTAL_LIMIT,bounds);failed={"seen":False}
  from report_agent.planning_budget import PlanningBudget, approvable_plan, watch_planning
  def planning_alert(record):
   store.event('planning_budget_alert',record)
   print(json.dumps({'event':'planning_budget_alert',**record}),file=sys.stderr,flush=True)
  planning_guard=PlanningBudget(HERE/'planning-budget.json',finance,before,
   CONFIG['planning_alert_tokens'],CONFIG['planning_stop_tokens'],on_alert=planning_alert)
  grant=load(DEPLOYMENT['budget_authority']).get('grant_scope') if DEPLOYMENT and DEPLOYMENT.get('budget_authority') else None
  if CONFIG.get('grant_token_limit') and DEPLOYMENT and DEPLOYMENT.get('reuse_ledger') and not grant:raise RuntimeError('G5_GRANT_SCOPE_REQUIRED')

  def scope_cost():
   return budget_scope_cost(before,finance())
  def observation():
   used,held,_=scope_cost()
   return {"scope_id":"report-run","maximum_tokens":LIMIT,"recorded_tokens":used,
     "reserved_or_unknown_upper_bounds":held,"remaining_for_new_reservations":max(0,LIMIT-used-held),
     "model_reservation_bounds":bounds,"includes_original_phases":True}
  def observer():
   used,held,unknown=scope_cost()
   planning_guard.check(approvable_plan(workspace))
   if grant:
    grant_used,grant_held,_=budget_scope_cost(grant['baseline'],finance())
    rb.enforce_host_admission(used_plus_held=grant_used+grant_held,limit=grant['maximum_tokens'],unknown=False,failed=False)
   # Unresolved attempts remain in held; the explicit policy owns new inference attempts.
   # A transient model/vision failure is a task observation, not a global host latch.
   rb.enforce_host_admission(used_plus_held=used+held,limit=LIMIT,unknown=False,failed=failed["seen"])
  def precheck(request,role):
   if tb._active.get() is not budget or not any(x[0] is observer for x in rb._reservation_observer.get()):raise rb.RequestBudgetExceeded("HOST_BUDGET_CONTEXT_REQUIRED")
   payload=json.loads(request.content)
   output=payload.get("max_completion_tokens",payload.get("max_tokens"))
   limit=CONFIG["vision_output_tokens"] if role=="vision" else CONFIG["text_output_tokens"]
   if (payload.get("model")!=ROLE_MODELS[role] or payload.get("n",1)!=1 or payload.get("stream",False)
       or request.extensions["timeout"]["read"]!=CONFIG["timeout_seconds"] or request.url.scheme!="https"
       or request.url.host!=urlsplit(role_service(role)[1]).hostname
       or (request.url.port or 443)!=(urlsplit(role_service(role)[1]).port or 443)
       or request.headers.get("x-stainless-retry-count","0")!="0"
       or type(output) is not int or not 0<output<=limit
       or (role!="vision" and payload.get("reasoning_effort")!=CONFIG["reasoning_effort"])):
    raise rb.RequestBudgetExceeded("HOST_WIRE_POLICY")
  def postcheck(request):
   item=request.extensions.get("report_token_budget")
   if not item or item[0] is not budget:raise rb.RequestBudgetExceeded("HOST_RESERVATION_REQUIRED")
   payload=json.loads(request.content)
   record={"at":time.time(),"attempt_id":item[1],"model":payload.get("model"),"request_sha256":hashlib.sha256(request.content).hexdigest(),"read_timeout":request.extensions["timeout"]["read"]}
   fd=os.open(HERE/"physical-requests.jsonl",os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
   try:os.write(fd,(json.dumps(record)+"\n").encode())
   finally:os.close(fd)
  original=runtime.configured_model;original_vision=vision.configured_vision_client;original_deep_vision=dm.configured_vision_client
  original_event=Store.event
  # Full public request captures already have immutable prompt_capture records;
  # do not duplicate complete histories into the events table on every call.
  class Audit(dm.RuntimeStatus):
   def on_llm_error(self,error,*,run_id,**kwargs):
    code=dm.error_data(error).get("message")
    if code in {"MODEL_AUTHENTICATION_FAILED","MODEL_PERMISSION_DENIED","TOKEN_LEDGER_SETTLEMENT_FAILED","TOKEN_BOUND_VIOLATION_REQUIRES_DIAGNOSIS","HOST_BASELINE_CHANGED"}:failed["seen"]=True
    return super().on_llm_error(error,run_id=run_id,**kwargs)
  def mirror(bound_store,kind,data):
   value=original_event(bound_store,kind,data)
   if bound_store.root.resolve()==CASE.resolve() and kind in {"deep_model_request","deep_model_response","deep_model_error","model_invocation_outcome","vision_request","vision_response","vision_error","deep_run_started","deep_run_finished","deep_run_error","content_delegation_returned","content_delegation_failed"}:
    fields={k:v for k,v in (data.items() if isinstance(data,dict) else ()) if k in {"role","status","duration_seconds","elapsed_seconds","http_status","task_id"} and isinstance(v,(str,int,float,bool,type(None)))}
    fd=os.open(HERE/"events.jsonl",os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
    try:os.write(fd,(json.dumps({"kind":kind,**fields})+"\n").encode())
    finally:os.close(fd)
   return value
  def factory(bound_store,role):
   model=original(bound_store,role)
   if model.model_name!=ROLE_MODELS[role] or model.reasoning_effort!=CONFIG["reasoning_effort"] or model.root_async_client.max_retries!=0 or model.root_client.max_retries!=0:raise RuntimeError("MODEL_CONFIG_MISMATCH")
   async def first(req):precheck(req,role)
   async def last(req):postcheck(req)
   model.http_async_client.event_hooks["request"].insert(0,first);model.http_async_client.event_hooks["request"].append(last)
   model.callbacks=[Audit(bound_store,role),*(model.callbacks or [])]
   def sync_first(req):precheck(req,role)
   model.http_client.event_hooks["request"].insert(0,sync_first);model.http_client.event_hooks["request"].append(postcheck)
   return model
  def vision_factory():
   client=original_vision()
   if client.max_retries!=0 or client.timeout.read!=CONFIG["timeout_seconds"]:raise RuntimeError("VISION_CONFIG_MISMATCH")
   async def first(req):precheck(req,"vision")
   async def last(req):postcheck(req)
   client._client.event_hooks["request"].insert(0,first);client._client.event_hooks["request"].append(last)
   return client
  runtime.configured_model=factory;vision.configured_vision_client=vision_factory;dm.configured_vision_client=vision_factory;Store.event=mirror
  save(HERE/"started.json",{"pid":os.getpid(),"host_sha256":sha(__file__),"canonical_baseline":prep["canonical_baseline"]})
  try:
   with token_budget(budget),rb.request_reservation_observer(observer,observation=observation):result=await watch_planning(run_with_owner_checkpoint(workspace,runtime.run_report),planning_guard,lambda:approvable_plan(workspace))
   save(HERE/"result.json",{"status":"incomplete" if store.get("report_status")=="incomplete" else "finished_pending_independent_review","report_status":store.get("report_status"),"scope_cost":scope_cost()})
  except BaseException as exc:
   failed["seen"]=True
   save(HERE/"failure.json",{"status":"failed","exception_type":type(exc).__name__,"reason":"HOST_PLANNING_STOP_LOSS" if str(exc)=="HOST_PLANNING_STOP_LOSS" else "host_failure","scope_cost":scope_cost()})
   raise
  finally:
   runtime.configured_model=original;vision.configured_vision_client=original_vision;dm.configured_vision_client=original_deep_vision;Store.event=original_event
   save(HERE/"cleanup.json",{"cleanup_complete":True,"canonical_baseline_after":canonical_baseline(),"canonical_unchanged":canonical_baseline()==prep["canonical_baseline"]})

if __name__=="__main__":
 if len(sys.argv)!=2:raise SystemExit("prepare or run")
 if sys.argv[1]=="prepare":prepare()
 elif sys.argv[1]=="run":asyncio.run(run())
 else:raise SystemExit("prepare or run")
