"""Exercise native directory refresh on a prepared private real-report database copy."""
import json
from pathlib import Path
from report_agent import legacy_state as legacy
from report_agent.store import Store, encode
from report_agent.content_store import ContentStore
from report_agent.workspace import Workspace
from report_agent.content_tasks import delegated_task
from report_agent.content_export import export_snapshot, render_export

store=Store(Path('.analysis/layout-capabilities-v3'))
cs=ContentStore(store)
selected=legacy.get_content_delivery(store)
options=cs.read(selected['export_ref'])['payload']['export_config']['layout']
options['refresh_toc']=True
for item in options['nodes']:
    body=cs.read(item['node_ref'])['payload']['body']
    for line in body.get('text','').split('\n'):
        if line.startswith('4.3.1 '):
            item['paragraphs']=[{'text':line,'heading_level':3}]
call={'id':'native-ubuntu-check','args':{'subagent_type':'layout','description':'Offline native Ubuntu capability check, not an autonomous model trial','layout_snapshot_ref':selected['snapshot_ref']}}
with delegated_task(Workspace(store),'coordinator',call) as (_,actor):
    result=export_snapshot(cs,actor,'native-ubuntu-export',selected['snapshot_ref'],options)['result']
    rendered=render_export(cs,actor,'native-ubuntu-render',result['export_ref'])['result']
result['render']=rendered
(store.root/'result.json').write_text(encode(result),encoding='utf-8')
payload=cs.read(result['export_ref'])['payload']
receipt=payload['export_config']['finalization']
print(json.dumps({'directory':receipt['toc'],'pages':receipt['page_count'],'libreoffice':receipt['libreoffice'],
    'tables':receipt['tables'],'paragraphs':receipt['non_toc_paragraphs'],'export':result['export_ref'],
    'render_state':rendered['execution_state']},ensure_ascii=False),flush=True)
