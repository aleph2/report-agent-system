"""Resume the completed layout trial with developer capability evidence and reviewer feedback."""
import argparse
import asyncio
import json
from pathlib import Path

from report_agent import legacy_state as legacy
from report_agent import report_state
from report_agent.store import Store, encode
from report_agent.content_store import ContentStore, Actor
from report_agent.workspace import Workspace
from report_agent.model_config import load_mixed_services
from report_agent.layout_capabilities import capabilities
from report_agent.deep_runtime import run_report


async def main(args):
    store=Store(args.project)
    if store.get('report_status')=='running':
        raise RuntimeError('PROJECT_ALREADY_RUNNING')
    intent=args.project/'layout-capability-continuation-intent.json'
    if intent.exists():
        raise RuntimeError('CONTINUATION_ALREADY_STARTED')
    settings=load_mixed_services(args.env_file)
    cs=ContentStore(store); delivery=legacy.get_content_delivery(store)
    snapshot=cs.read(delivery['snapshot_ref'])
    before={encode(r):cs.read(r)['payload_digest'] for r in snapshot['payload']['refs']}
    cap=capabilities()
    instruction='''用户要求继续上次排版反馈任务，重新评估“无改进空间”的判断。开发已补齐新的呈现能力，详情请查询 read_layout_capabilities。现有工具能对文本节点内部的原文行设置标题/段落样式，原始正文和数值不变；可调用原生 Linux LibreOffice 刷新目录实际页码；段落间距、分页、整表保持、横页隔离仍可自主选择。能力验证已在真实报告副本完成：572个非目录段落、11张表保持一致，4.3.1能进入带页码的目录。
继续依据上一轮 reviewer 073301e3-1aa0-4a98-9c9b-d5e771c6943c v1 的具体意见，决定有价值的改进；将新能力和反馈交给排版专家（原任务 988a188b-0146-43c5-805d-23f0cf5c9bc0 可恢复所有权），对新版本再安排独立审核。不要把旧能力限制当成永久结论，不需要固定迭代次数，不提供预设排版参数或假装必须通过。原内容、评分、实质限定与证据保持冻结，但保留原文的布局调整允许进行。工具仍不能完成的操作，可记录具体能力扩展请求；请求本身不等于已经实现。
本轮改为原生 Ubuntu 渲染，字体/排版环境与上一轮 Windows 不同，比较时如实说明。页面视觉反馈是工具观察，不是独立审核结论。最终说明哪些 reviewer 意见推动了哪些调整、哪些仍未解决、停止依据。不得重跑报告生成、改评分、部署或发邮件。'''
    receipt=cs.handoff(Actor('development:main','development','layout-v3-capability-release'),'layout-v3-capability-release',delivery['snapshot_ref'],
        'Layout capability update available', ['docs/reviews/layout-capabilities-v3.md', '.analysis/layout-capabilities-v3/result.json'],
        'Reassess previous inability claims using current tools and actual reviewer feedback.',handling_state='handled',
        details={'kind':'layout_capability_update','capability_version':cap['engine_digest'],
                 'verification':'Native Ubuntu refresh/render succeeded; 572 paragraphs and 11 tables preserved.',
                 'resume_task_id':'988a188b-0146-43c5-805d-23f0cf5c9bc0'})
    intent.write_text(encode({'settings':settings,'capability':cap,'feedback':receipt,
        'before':before,'prior_decision':store.get('content_execution_decision'),'instruction':instruction}),encoding='utf-8')
    manifest=store.manifest
    manifest.update(goal=instruction,scope_instruction=instruction)
    store.set('manifest',manifest)
    report_state.set_content_delivery(store,{**delivery,'trial_instruction':instruction})
    store.event('layout_capability_continuation',{'capability_version':cap['engine_digest'],'feedback':receipt})
    print(encode({'state':'starting','capability':cap['version'],'native_directory_available':cap['directory_refresh']}),flush=True)
    await run_report(Workspace(store))
    after={encode(r):cs.read(r)['payload_digest'] for r in snapshot['payload']['refs']}
    result={'status':store.get('report_status'),'error':store.get('report_error'),
        'content_unchanged':before==after,'delivery':legacy.get_content_delivery(store),
        'decision':store.get('content_execution_decision'),'summary':store.get('agent_summary')}
    (args.project/'layout-capability-continuation-result.json').write_text(encode(result),encoding='utf-8')
    print(encode({'status':result['status'],'content_unchanged':result['content_unchanged']}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,required=True)
    p.add_argument('--env-file',type=Path,required=True)
    asyncio.run(main(p.parse_args()))
