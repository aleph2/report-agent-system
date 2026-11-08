"""Isolated continuation of saved report feedback, preserving the prior delivery."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
import sqlite3

from report_agent import legacy_state as legacy
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from report_agent.model_config import load_mixed_services
from report_agent.deep_runtime import run_report


INSTRUCTION = """用户于2026-10-02授权继续现有报告的内容整改、reviewer复审和排版优化。此前仅验证排版、禁止writer修改内容的试验范围已经结束，本轮允许原作者依据证据修订自己的内容，协调者维护标准与组装，reviewer独立核验；原始资料和历史版本保持不变。不要从零重写报告，不降低标准以求通过。
当前基线来自layout-live-v2，最终选定导出64557a7b-70d6-4492-b0b3-ef28134ba4a6 v1，冻结快照0b22e04b-11b2-4403-b17e-e303e93a4e61 v1。内容反馈见ReviewRecord a173d661-1952-4493-8720-68b47848037c v1；后续版式反馈见90f50c6f-c7cf-472c-8721-e92c61c2b61c v1及中间审核记录。这些是需核验处理的既有反馈，不是预设修复答案。
重点处理④⑤⑥X22条件与档位映射不一致、③段倾角比较论证不自洽、④段地勘和设计起点相差40m而披露不足。还需评估相关评分、等级、结论、措施和遗留事项是否受修订影响。自主核对已保存资料、指南文字/表格、计算与引用证据，决定哪些可修、哪些需人工确认。资料矛盾和方法选择不能靠猜测消除；可以准确补充不确定性、适用范围和具体待确认问题。不得把所有报告错误笼统推给资料缺失或原有冻结约束。
另有研发独立人工稿对照反馈（不是原reviewer结论）：⑥段已定性泥灰岩却因风化程度取X21=62、50—74档，而原指南表3-2将泥灰岩列于75—100，现有文字未提供换档的有效依据。请作为待核验线索与相关内容一起调查，不直接照抄研发计算作为新评分。人工参考稿也有乘法错误，不能把人工分数当作真值。原始对照记录为.ase/verification/060-human-report-comparison.md，需依靠项目内原资料独立核验上述线索。
原作者任务可通过resume_content_task_id恢复：第1—3章0be2f977-6573-434a-a560-31e0f49f3af1，第4章69ed7be1-f37d-4562-8ebe-ca5120b694a6，第5—6章953904e9-5ea4-46eb-b2ff-e176323228b0。根据实际对象所有权安排有价值的任务，不越权覆盖。新的内容版本需要新的完整快照、导出和相应复审；旧排版任务只获旧快照权限，新快照应获得明确的新排版任务授权。
延续已有效的排版改进。内部过程标识可由内容所有者评估并清理，但不能删除实质限定、来源说明或未解决问题来掩盖缺陷。版式遗留反馈应结合现有导出能力处理，工具缺口可提出具体能力请求，不能把请求当成已经实现。最终报告具体版本、已修复且复审确认的问题、仍未解决的问题及停止依据；结束运行不代表验收通过。
用户明确本轮先不增加或开展工程审图能力。不要开展平面图/断面图/赤平投影的工程图件核验；确实需要图件才能判断的问题保留待确认。已有报告页面的版式检查可以继续。ASE流程暂停。邮件由主会话单独管理，本运行不发送邮件、不部署、不更换模型、不购买服务。动作选择与是否继续由协调者依据实际反馈判断，不要求固定修订轮数。
"""


async def main(args):
    source, target = args.source.resolve(), args.output.resolve()
    if target.exists() or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('NEW_ISOLATED_DESTINATION_REQUIRED')
    settings = load_mixed_services(args.env_file)
    # Lock the source while copying to avoid inheriting an in-flight trial.
    origin = Store(source)
    with origin.run_lock():
        if origin.get('report_status') == 'running' or origin.get('checkpoint_resume'):
            raise RuntimeError('SOURCE_HAS_UNFINISHED_RUN')
        target.mkdir(parents=True)
        with sqlite3.connect((source/'state.db').as_uri()+'?mode=ro', uri=True) as old:
            with sqlite3.connect(target/'state.db') as new:
                old.backup(new)
                if new.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('COPY_INTEGRITY_FAILED')
        for directory in ('content-assets', 'sources'):
            if (source/directory).exists():
                shutil.copytree(source/directory, target/directory)
    store = Store(target)
    baseline = {
        'manifest': store.get('manifest'),
        'content_delivery': legacy.get_content_delivery(store),
        'content_execution_decision': store.get('content_execution_decision'),
        'report_status': store.get('report_status'),
        'agent_summary': store.get('agent_summary'),
        'role_model_services': store.get('role_model_services'),
    }
    intent = {'at': datetime.now(timezone.utc).isoformat(), 'source': str(source),
        'authorization': 'User approved continuation and subsequently excluded engineering drawing review.',
        'instruction': INSTRUCTION, 'settings': settings, 'baseline': baseline,
        'checkpoint_copied': False,
        'code_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in Path('src/report_agent').rglob('*') if p.suffix in {'.py', '.md'}}}
    (target/'correction-intent.json').write_text(encode(intent), encoding='utf-8')
    with store.connect() as db:
        for key in ('checkpoint_resume', 'agent_summary', 'report_error', 'native_interrupts',
                    'content_execution_decision'):
            db.execute('DELETE FROM state WHERE key=?', (key,))
    store.set('manifest', {**store.manifest, 'goal': INSTRUCTION, 'scope_instruction': INSTRUCTION})
    legacy.set_content_delivery(store, {**baseline['content_delivery'], 'trial_instruction': INSTRUCTION})
    store.set('knowledge_enabled', False)
    store.event('operator_content_correction_authorized', {'source': str(source), 'instruction': INSTRUCTION})
    print(encode({'state': 'starting', 'project': str(target), 'settings': settings}), flush=True)
    await run_report(Workspace(store))
    result = {
        'report_status': store.get('report_status'),
        'report_error': store.get('report_error'),
        'content_delivery': legacy.get_content_delivery(store),
        'content_execution_decision': store.get('content_execution_decision'),
        'content_final_review': legacy.get_content_final_review(store),
        'agent_summary': store.get('agent_summary'),
    }
    (target/'correction-result.json').write_text(encode(result), encoding='utf-8')
    print(encode({'status': result['report_status'], 'error': result['report_error']}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--env-file', type=Path, required=True)
    asyncio.run(main(p.parse_args()))
