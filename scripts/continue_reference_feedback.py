"""Deliver the user's new reference-layout feedback to the existing coordinator."""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from report_agent import legacy_state as legacy
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.deep_runtime import run_report
from report_agent.deep_models import configured_model
from report_agent.model_config import load_mixed_services

ROOT = Path('.runs/reference-alignment-learning-20261006')

async def main():
    output = ROOT/'user-followup-result.json'
    if output.exists():
        raise RuntimeError('FOLLOWUP_EXISTS_INSPECT_BEFORE_RETRY')
    store = Store(ROOT)
    manifest = store.manifest
    previous = manifest['goal']
    manifest['goal'] = (
        '用户最新反馈：排版还需要跟参考的报告对齐。请继续完成现有完整报告的排版对齐工作。'
        '用户最新执行决定：先验证功能和完整交付是否正确，再考虑计费和执行效率；'
        '之前开发者添加的60次调用、15分钟整轮时限撤销，不作为本轮决策条件。'
        '原有参考资料、完整报告与未决事实保留；本轮不审工程图，不改变工程结论。')
    store.set('manifest', manifest)
    store.event('operator_followup', {'message':'排版还需要跟参考的报告对齐。',
                                    'previous_goal':previous,'current_goal':manifest['goal']})
    load_mixed_services(Path(__file__).resolve().parents[1]/'.env')
    os.environ['REPORT_DEEPSEEK_STRICT']='0'
    os.environ['REPORT_REASONING_EFFORT']='low'
    for role in ('WRITER','REVIEWER','COORDINATOR','TEXT_TOOL','RUBRIC_GRADER','LAYOUT'):
        for key in ('MODEL','BASE_URL','API_KEY'):
            os.environ['REPORT_'+role+'_'+key] = os.environ['REPORT_'+key]
    def factory(role):
        model = configured_model(store,role)
        model.max_tokens=8192
        model.max_retries=0
        return model
    with store.connect() as db:
        sequence=db.execute('SELECT MAX(sequence) FROM events').fetchone()[0]
    result={'state':'running','started_at':datetime.now(timezone.utc).isoformat(),
            'start_sequence':sequence,'user_feedback':'排版还需要跟参考的报告对齐。',
            'cumulative_call_budget':None,'whole_run_timeout':None}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        await run_report(Workspace(store),model_factory=factory)
    finally:
        result.update(state=store.get('report_status'),error=store.get('report_error'),
                      finished_at=datetime.now(timezone.utc).isoformat(),
                      delivery=legacy.get_content_delivery(store),summary=store.get('agent_summary'))
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    asyncio.run(main())
