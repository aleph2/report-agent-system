"""One isolated real-model layout feedback trial using the production runtime."""
import argparse
import asyncio
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from report_agent import legacy_state as legacy
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from report_agent.content_store import ContentStore
from report_agent.model_config import load_mixed_services
from report_agent.deep_runtime import run_report


async def main(args):
    source, target = args.source.resolve(), args.output.resolve()
    if (target.exists() and not args.prepared_db) or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('NEW_ISOLATED_DESTINATION_REQUIRED')
    settings = load_mixed_services(args.env_file)
    if args.prepared_db:
        if set(p.name for p in target.iterdir()) != {'state.db'}:
            raise ValueError('PREPARED_DATABASE_ONLY_REQUIRED')
        with sqlite3.connect(target/'state.db') as copied:
            if copied.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('PREPARED_DATABASE_INVALID')
    else:
        target.mkdir(parents=True)
        with sqlite3.connect((source/'state.db').as_uri()+'?mode=ro', uri=True) as original:
            with sqlite3.connect(target/'state.db') as copied:
                original.backup(copied)
    for directory in ('content-assets', 'sources'):
        if (source/directory).exists():
            shutil.copytree(source/directory, target/directory)
    store = Store(target)
    cs = ContentStore(store)
    selected = legacy.get_content_delivery(store)
    frozen = cs.read(selected['snapshot_ref'])
    before = {encode(r): cs.read(r)['payload_digest'] for r in frozen['payload']['refs']}
    instruction = '''本次唯一任务是对现有真实报告进行排版专家闭环实测。原报告内容和评估结论冻结，不重新生成报告，不修复评分，不调用 writer，不新增或修改 ContentNode、Criterion、Relation 或 DocumentSnapshot。
协调者负责把交付用途、排版问题和实际版本交给 layout，并以 layout_snapshot_ref 授予当前冻结快照；排版专家自主判断参数、调用导出器、查看真实渲染并优化；reviewer 对新导出物给出可定位的排版审核反馈。协调者根据反馈决定继续优化或明确终止，不需要人为制造固定轮数。达到排版要求即可结束；连续无改善或现有工具不能修复时保留问题并说明，不做无限循环。
目标读者是审阅施工安全风险评估阶段性报告的专业人员。要求标题层级清晰、正文可读、表格不裁切且列宽合理、表头可辨认、题注与表格对应、分页无孤立标题和不必要的大段留白；目录和页码应实用，不得虚构已更新页码。不得隐藏实质限定、未解决问题或来源说明来让页面好看。
已有人工反馈：标题、内部结构字段展示、表格列宽和跨页、目录及页面留白需要改善。这些只是调查线索，由模型查看实际成品判断。未提供脚本优化版或预设列宽。原先内容层面的遗留问题仍有效，但不要求本轮解决，不把排版通过说成报告整体或工程签审通过。reviewer 应明确实际查看页范围和未查范围，保存具体版本的排版检查结果；总体审核状态可以继续保留 changes_required。
仅开展本次排版实验，不部署、不发邮件。结束时返回选定 export/render 引用、具体修改、审核意见、轮次和未解决限制。'''
    with store.connect() as db:
        for key in ('role_model_services','checkpoint_resume','agent_summary','report_error','native_interrupts','content_execution_decision'):
            db.execute('DELETE FROM state WHERE key=?',(key,))
    manifest = store.manifest
    manifest['goal'] = instruction
    manifest['scope_instruction'] = instruction
    manifest['review_entrypoint'] = 'delegated-reviewer-v1'
    store.set('manifest', manifest)
    store.set('knowledge_enabled', False)
    legacy.set_content_delivery(store, {**selected, 'trial_instruction':instruction})
    settings['layout'] = settings['writer']
    intent = {'scope':'real model layout-only feedback loop', 'source':str(source),
        'snapshot_ref':selected['snapshot_ref'], 'baseline_export_ref':selected['export_ref'],
        'settings':settings, 'instruction':instruction, 'checkpoint_copied':False,
        'code_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('src/report_agent').rglob('*') if p.suffix in {'.py','.md'}},
        'frozen_before':before}
    (target/'layout-live-intent.json').write_text(encode(intent),encoding='utf-8')
    print(encode({'state':'starting','project':str(target),'settings':settings}),flush=True)
    result = await run_report(Workspace(store))
    after = {encode(r):cs.read(r)['payload_digest'] for r in frozen['payload']['refs']}
    summary = {'status':store.get('report_status'),'error':store.get('report_error'),
        'frozen_objects_unchanged':before==after,'frozen_object_count':len(before),
        'delivery':legacy.get_content_delivery(store),'final_review':legacy.get_content_final_review(store),
        'agent_summary':store.get('agent_summary')}
    (target/'layout-live-result.json').write_text(encode(summary),encoding='utf-8')
    print(encode({k:v for k,v in summary.items() if k not in {'agent_summary','final_review'}}),flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--env-file',type=Path,required=True)
    p.add_argument('--prepared-db',action='store_true')
    asyncio.run(main(p.parse_args()))
