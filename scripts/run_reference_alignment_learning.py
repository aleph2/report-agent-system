"""Bounded native coordinator trial on a fork of the existing complete draft.

Only new-system state is forked. Originals and historical assessments stay intact.
"""
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from report_agent import legacy_state as legacy
from report_agent import report_state
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.deep_runtime import run_report
from report_agent.deep_models import configured_model, error_data
from report_agent.model_config import load_mixed_services
from report_agent.request_budget import RequestBudget, request_budget

ROOT = Path('.runs/reference-alignment-learning-20261006')
OLD = Path('.runs/content-corrections-v1')


async def main():
    if ROOT.exists():
        raise RuntimeError('TRIAL_ALREADY_EXISTS_INSPECT_BEFORE_RESUMING')
    ROOT.mkdir()
    with sqlite3.connect(f'file:{OLD}/state.db?mode=ro',uri=True) as source, sqlite3.connect(ROOT/'state.db') as target:
        source.backup(target)
    for folder in ('sources','content-assets'):
        shutil.copytree(OLD/folder,ROOT/folder)
    store = Store(ROOT)
    prior = legacy.get_content_delivery(store)
    inputs = json.loads(Path('.runs/learning-real-report-pilot-20261004/input/runtime-input.json').read_text(encoding='utf-8'))
    reference = next(s for s in inputs['manifest']['sources'] if s['id'].startswith('pilot-human'))
    source_file = Path('.runs/learning-real-report-pilot-20261004/baseline')/reference['copied_path']
    target = ROOT/'sources'/'human-layout-reference.pdf'
    shutil.copyfile(source_file,target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == reference['sha256']
    reference = {**reference,'copied_path':'sources/human-layout-reference.pdf'}
    manifest = store.manifest
    manifest['sources'].append(reference)
    manifest['presentation_references']=[{'source_id':reference['id'],'instruction':'这份已有报告是版式参考，请按它的布局和排版完善当前报告。'}]
    manifest['goal'] = ('用户已授权：将已有完整评估报告工作稿在排版和布局上对齐所提供的人工报告参考。'
        '本次交付是完整报告的新版排版工作稿，不是单个工点摘要或问题台账。'
        f'已有完整内容快照和导出为 {json.dumps(prior,ensure_ascii=False)}。'
        '内容及既有未决事实保留，不改变工程结论或将changes_required宣称通过；本轮不审工程图。'
        '请交付按参考布局和排版完善后的完整报告，并如实说明审核状态和未决事项。'
        '已有Excel继续承载事实确认，不新增重复清单。'
        '本轮所有异步模型HTTP请求共用60次硬上限（含视觉和重试），最多15分钟；优先形成可交付完整版本。')
    store.set('manifest',manifest)
    store.set('reference_alignment_parent',{'project':str(OLD),'delivery':prior,'original_review_preserved':True})
    report_state.set_content_delivery(store,None)
    report_state.set_content_final_review(store,None)
    store.set('checkpoint_resume',False)
    store.set('agent_summary',None)
    store.set('knowledge_enabled',False)
    from report_agent.catalog import Catalog
    Catalog(store)
    with store.connect() as db:
        db.execute('DELETE FROM source_blocks WHERE source_id=?',(reference['id'],))
        Catalog._blocks(db,reference['id'],[b for b in inputs['report_blocks'] if b['source_id']==reference['id']])
    # Isolated copy: candidate availability is the sole intended treatment.
    from report_agent.learning import binding
    library_root = ROOT / 'trial-library'
    library_root.mkdir()
    origin = Path('.runs/reference-reflection-20261006/library/state.db')
    with sqlite3.connect(f'file:{origin}?mode=ro', uri=True) as src, sqlite3.connect(library_root/'state.db') as dst:
        src.backup(dst)
    store.set('learning_config', {'library_path':str(library_root.resolve()), 'customer_id':'reference-reflection-isolated'})
    library, scope = binding(Workspace(store))
    candidates = library.list_versions(scope)
    assert len(candidates) == 3
    for candidate in candidates:
        library.release(scope,candidate['id'],candidate['version'],'User-authorized isolated application test only; no production endorsement')
    with store.connect() as db:
        start_sequence = db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
    load_mixed_services(Path(__file__).resolve().parents[1]/'.env')
    os.environ['REPORT_DEEPSEEK_STRICT']='0'
    os.environ['REPORT_REASONING_EFFORT']='low'
    for role in ('WRITER','REVIEWER','COORDINATOR','TEXT_TOOL','RUBRIC_GRADER','LAYOUT'):
        for key in ('MODEL','BASE_URL','API_KEY'):
            os.environ['REPORT_'+role+'_'+key]=os.environ['REPORT_'+key]
    def factory(role):
        model=configured_model(store,role)
        model.max_tokens=8192
        model.max_retries=0
        return model
    budget=RequestBudget(60)
    result={'state':'running','started_at':datetime.now(timezone.utc).isoformat(),'scope':'complete existing draft presentation alignment','authorization':'2026-10-06 user: 那就验证吧','baseline':'.runs/reference-alignment-20261006-v2/alignment-result.json','start_sequence':start_sequence,'treatment':'three unchanged candidate versions available through existing experience tools','limit':60,'timeout_seconds':900,'parent':str(OLD)}
    path=ROOT/'alignment-result.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        with request_budget(budget):
            await asyncio.wait_for(run_report(Workspace(store),model_factory=factory),900)
        result.update(state=store.get('report_status'),error=store.get('report_error'))
    except Exception as exc:
        result.update(state='interrupted_or_failed',error=error_data(exc))
    finally:
        for candidate in candidates:
            library.release(scope,candidate['id'],None,'Isolated test ended; no production promotion')
        result['candidates_after_test'] = library.list_versions(scope)
        result.update(finished_at=datetime.now(timezone.utc).isoformat(),http_request_attempts=budget.count,
                      delivery=legacy.get_content_delivery(store),summary=store.get('agent_summary'))
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    asyncio.run(main())
