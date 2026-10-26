import sys,os,pathlib,importlib.util,json,time
ROOT=pathlib.Path(__file__).resolve().parents[2]
GUARD=pathlib.Path(__file__).parent/'offline-guard'
for k in list(os.environ):
 if any(x in k.upper()for x in ['API_KEY','ACCESS_TOKEN','SECRET_KEY']):os.environ.pop(k,None)
os.environ['LANGSMITH_TRACING']='false';os.environ['LANGCHAIN_TRACING_V2']='false'
os.environ['PYTHONPATH']=os.pathsep.join([str(GUARD),str(ROOT/'src'),str(ROOT/'tests')])
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
spec=importlib.util.spec_from_file_location('offline_network_guard',GUARD/'sitecustomize.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
os.chdir(ROOT)
import pytest
class PhaseRecord:
 def __init__(self):self.results=[];self.collection=[];self.nodes=[]
 def pytest_collection_finish(self,session):self.nodes=[i.nodeid for i in session.items]
 def pytest_collectreport(self,report):
  if report.outcome!='passed':self.collection.append({'nodeid':report.nodeid,'outcome':report.outcome,'error':str(report.longrepr)})
 def pytest_runtest_logreport(self,report):
  row={'nodeid':report.nodeid,'when':report.when,'outcome':report.outcome,'duration':report.duration,'error':str(report.longrepr) if report.failed else None}
  self.results.append(row)
  if os.environ.get('REPORT_OFFLINE_PHASE_REPORT'):
   with open(os.environ['REPORT_OFFLINE_PHASE_REPORT']+'.jsonl','a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
record=PhaseRecord();code=2;started=time.time()
try:code=int(pytest.main(sys.argv[1:],plugins=[record]))
finally:
 if os.environ.get('REPORT_OFFLINE_PHASE_REPORT'):
  pathlib.Path(os.environ['REPORT_OFFLINE_PHASE_REPORT']).write_text(json.dumps({'exit_code':code,'elapsed_seconds':time.time()-started,'collected_nodes':record.nodes,'collection_reports':record.collection,'results':record.results},ensure_ascii=False,indent=2),encoding='utf-8')
raise SystemExit(code)
