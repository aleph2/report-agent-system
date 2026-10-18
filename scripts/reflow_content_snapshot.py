"""Offline layout smoke on a private database copy; never resumes a model trial."""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path

from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.content_export import export_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output must be new; preserve previous exports.')
    args.output.mkdir(parents=True)
    with sqlite3.connect(args.source.resolve().joinpath('state.db').as_uri()+'?mode=ro', uri=True) as original:
        with sqlite3.connect(args.output/'state.db') as copy:
            original.backup(copy)
    store = Store(args.output)
    workspace, contents = Workspace(store), ContentStore(store)
    snap = store.get('content_delivery')['snapshot_ref']
    snapshot = contents.read(snap)
    options = {'nodes': []}
    before = {tuple(ref.values()): contents.read(ref)['payload_digest'] for ref in snapshot['payload']['refs']}
    for ref in snapshot['payload']['refs']:
        if ref['type'] != 'ContentNode': continue
        node = contents.read(ref)['payload']
        spec = {'node_ref': ref}
        if node['kind'] == 'block':
            line = node['body']['text'].split('\n', 1)[0]
            match = re.match(r'^(\d+(?:\.\d+){1,4})\s', line)
            if match: spec['heading_level'] = min(6, match[1].count('.')+1)
        if node['kind'] == 'table':
            count = len(node['body']['columns'])
            scoring = '重要性排序' in node['body']['columns']
            spec['column_weights'] = ([1.5, .7, .8, .8, .8, 3.5] if scoring else [1]*count)
            if count == 6 and not scoring:
                spec['column_weights'] = [.45, 1.7, .8, .65, 1.5, 3]
            spec['landscape'] = count >= 6 and not scoring
            spec['keep_table_together'] = len(node['body']['rows']) <= 7
            if count >= 7:
                spec['table_font_size'] = 9
        if len(spec)>1: options['nodes'].append(spec)
    call = {'id':'layout-smoke', 'args': {'subagent_type':'layout',
        'description':'Offline presentation-only smoke; no model quality claim.', 'layout_snapshot_ref':snap}}
    with delegated_task(workspace, 'coordinator', call) as (_, actor):
        result = export_snapshot(contents, actor, 'layout-smoke-export', snap, options)['result']
    after = {tuple(ref.values()): contents.read(ref)['payload_digest'] for ref in snapshot['payload']['refs']}
    assert before == after
    output = args.output/'layout-preview.docx'
    shutil.copyfile(args.output/result['file_ref'], output)
    record = {'snapshot_ref': snap, 'export':result, 'layout':options,
        'unchanged_snapshot_objects':len(before), 'preview':str(output),
        'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'limitation':'Offline deterministic export. No model invoked, no acceptance or scoring repair.'}
    (args.output/'layout-evidence.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'preview':str(output),'unchanged_snapshot_objects':len(before)},ensure_ascii=False))


if __name__ == '__main__': main()
