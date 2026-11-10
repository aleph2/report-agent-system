"""Rebuild the c review tables from private SDK observations; no model or database access."""
import argparse
import ast
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
NATIVE = 'native-tool-runtime-v1'

def write(name, rows, columns):
    with (OUT / name).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)

def fields(node, root, path='', seen=()):
    if '$ref' in node:
        ref = node['$ref']
        if ref not in seen:
            target = root
            for part in ref.removeprefix('#/').split('/'):
                target = target[part]
            yield from fields(target, root, path, (*seen, ref))
        return
    for name, value in node.get('properties', {}).items():
        key = path + '.' + name if path else name
        yield key, name in node.get('required', []), value
        yield from fields(value, root, key, seen)
    if isinstance(node.get('items'), dict):
        yield from fields(node['items'], root, path + '[]', seen)
    if isinstance(node.get('additionalProperties'), dict):
        yield from fields(node['additionalProperties'], root, path + '.*', seen)
    for branch in ('anyOf', 'oneOf', 'allOf'):
        for index, value in enumerate(node.get(branch, [])):
            yield from fields(value, root, path + f'[{branch}:{index}]', seen)

# Parsing self-check: references, optional unions and arrays must not hide nested inputs.
_sample = {'$defs': {'R': {'properties': {'id': {'type': 'string'}}, 'required':['id']}},
           'properties': {'rows': {'anyOf':[{'type':'array', 'items':{'$ref':'#/$defs/R'}}, {'type':'null'}]}}}
assert [p for p, _, _ in fields(_sample, _sample)] == ['rows', 'rows[anyOf:0][].id']

def requirement(path, code=''):
    text = (path + ' ' + code).lower()
    if '/assertions/' in path:
        return 'S2 approved actions/checks; M1-M3 assertions; 9a-a C3', 'assertion transaction and read-only status'
    if any(w in text for w in ('budget', 'token_', 'request_', 'model_', 'recovery', 'invocation')):
        return 'AGENTS section 1: launch caps, holds, unknown outcomes; exact recovery', 'model admission/reconciliation'
    if any(w in text for w in ('source', 'citation', 'catalog', 'ingestion', 'blob_', 'document_', 'vision')):
        return 'AGENTS section 3 originals; 9a-a case/page boundary; retained image delivery', 'source access and evidence verification'
    if any(w in text for w in ('writer', 'claim_', 'assessment', 'scoring', 'method_', 'calculat')):
        return 'M2/M3 judgment/producer/scoring contract; Run06 defects; 9a-a/c', 'judgment save, projection or calculation'
    if any(w in text for w in ('commission', 'plan_', 'planning', 'page_bind', 'probe_case')):
        return 'M4/M5 immutable plan/owner authority; 9a-a bindings; c business copy', 'plan/checkpoint/import'
    if any(w in text for w in ('review', 'rubric', 'release', 'acceptance')):
        return 'M8 scoped review; S2 independent review; formal release deferred to 9a-e', 'review eligibility/results; release refusal'
    if any(w in text for w in ('export', 'layout', 'render', 'deliver', 'snapshot', 'assembler', 'table_', 'draft_')):
        return 'M7/M8 and accepted 9a-b paired draft export; existing content checks', 'assembly/export/delivery'
    if any(w in text for w in ('content_', 'hierarchical', 'text_work', 'position_')):
        return 'M2/M4/M6-M8 native content/task boundaries preserved in 9a', 'native content/action contract'
    if any(w in text for w in ('workspace', 'knowledge', 'learning', 'deepseek', 'legacy_', 'webapp')):
        return 'O4/O5 retained routes; preserve existing contract pending owner decision', 'retained-route input/action validation'
    return 'AGENTS sections 3/5; accepted baseline runtime/storage contract (M0-M10)', 'existing runtime/storage action'

def build(inputs):
    raw = [json.loads(p.read_text()) for p in inputs]
    assert all(d['exit_code'] == 0 and not d['incomplete'] and not d['instrumentation_errors'] for d in raw)
    entries = {}
    for d in raw:
        for entry in d['catalog']:
            key = (entry['role'], entry['tool'], entry['operation_profile'],
                   entry['source'], json.dumps(entry['schema'], sort_keys=True))
            if key not in entries:
                entries[key] = {**entry, 'origins':set()}
            entries[key]['origins'].add(entry['origin'])
    events = [e for d in raw for e in d['observations']]
    attributed = [e for e in events if e['case'] and e['actor'] and e['native_call_id']]
    rejected = [e for e in attributed if e['rejected']]
    unique_rejections = {(e['case'], e['actor'], e['native_call_id']) for e in rejected}
    by_tool = defaultdict(set)
    by_site = defaultdict(set)
    by_reason = defaultdict(set)
    for e in rejected:
        identity = e['case'], e['actor'], e['native_call_id']
        by_tool[e['role'], e['tool']].add(identity)
        for site in e['raise_sites']:
            by_site[site['file'],site['line']].add(identity)
        for code in e['codes']:
            by_reason[e['role'],e['tool'],code].add(identity)
    observed_tools = {(e['role'],e['tool']) for e in attributed}
    field_rows = []
    for index, e in enumerate(sorted(entries.values(), key=lambda e:(e['role'],e['tool'],e['operation_profile'],e['source'] or '',json.dumps(e['schema'],sort_keys=True)))):
        req, consumer = requirement(e['source'] or '')
        scope = 'native' if e['operation_profile'] == NATIVE else 'historical caller-ID profile'
        for path, required, schema in fields(e['schema'], e['schema']):
            constraints = {k:v for k,v in schema.items() if k not in ('$defs','properties','items','title','description','default')}
            field_rows.append(dict(variant=index+1, role=e['role'],tool=e['tool'],profile=scope,field=path,
                required_in_parent=required,requirement=req,
                reader=f"{e['source']}:{e['line']} {e['tool']} -> {consumer}",
                schema=json.dumps(constraints,ensure_ascii=False,sort_keys=True),
                tool_rejections=len(by_tool[e['role'],e['tool']]) if (e['role'],e['tool']) in observed_tools else 'unmeasured'))
    assert field_rows
    write('agent-fields.tsv', field_rows, list(field_rows[0]))
    check_rows = []
    for source in sorted((ROOT/'src/report_agent').rglob('*.py')):
        text = source.read_text()
        tree = ast.parse(text)
        path = str(source.relative_to(ROOT))
        def walk(node, function='<module>'):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                function = node.name
            kind = None
            if isinstance(node, (ast.Raise, ast.Assert)):
                kind = type(node).__name__.lower()
            elif isinstance(node, ast.Call):
                name = ast.unparse(node.func).split('.')[-1]
                if name in ('Field','field_validator','model_validator','gap'):
                    kind = name
            if kind:
                expression = ast.get_source_segment(text,node) or ''
                req, consumer = requirement(path, expression[:200])
                check_rows.append(dict(site=f'{path}:{node.lineno}',kind=kind,
                    requirement=req,reader=f'{function} -> {consumer}',
                    expression=' '.join(expression.split())[:600],
                    observed_rejections=len(by_site[path,node.lineno]),
                    evaluated='unmeasured; zero observed is not evaluation coverage'))
            for child in ast.iter_child_nodes(node):
                walk(child,function)
        walk(tree)
    write('checks.tsv',check_rows,list(check_rows[0]))
    reason_rows = [dict(role=r,tool=t,reason=c,unique_rejected_calls=len(ids)) for (r,t,c),ids in sorted(by_reason.items())]
    write('refusals.tsv',reason_rows,['role','tool','reason','unique_rejected_calls'])
    old_sql = ROOT/'docs/verification/stage1-9a-inventory/s2-checks-initial.tsv'
    with old_sql.open() as f:
        sql = list(csv.DictReader(f,delimiter='\t'))
    for row in sql:
        row['refusal_count'] = sum(len(v) for (r,t,c),v in by_reason.items() if c == row['code'])
        row['status'] = 'Observed offline SDK refusals only; total rule evaluations unmeasured'
    write('s2-checks.tsv',sql,list(sql[0]))
    summary = dict(scope='Current five-role factory schemas plus explicit historical variants; repository Python guard census and all 12 S2 families. No claim that every check was exercised.',
        source_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        samples=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in inputs],
        schema_variants=len(entries),fields_including_nested=len(field_rows),
        native_variants=sum(e['operation_profile']==NATIVE for e in entries.values()),
        python_check_sites=len(check_rows),sql_families=len({r['code'] for r in sql}),sql_clauses=len(sql),
        sdk_tool_invocations=len(events),attributed_invocations=len(attributed),unique_rejected_calls=len(unique_rejections),
        unattributed_invocations=len(events)-len(attributed),unfinished=0,instrumentation_errors=0,
        by_role={r:dict(invocations=sum(e['role']==r for e in attributed),
                        rejected_calls=(len({(e['case'],e['actor'],e['native_call_id']) for e in rejected if e['role']==r})
                                        if any(e['role']==r for e in attributed) else None),
                        measurement='observed offline sample' if any(e['role']==r for e in attributed) else 'unmeasured')
                 for r in sorted({e['role'] for e in entries.values()})},
        field_specific_rejection_rates='unmeasured; tool totals are not field counts',
        evaluation_coverage='unmeasured; zero observed is not proof a check ran',
        paid_model_calls=0,production_checks_added=0,
        b2_guards=json.loads((OUT/'planned-guards.json').read_text())['tests'])
    (OUT/'inventory.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('observations',nargs='+',type=Path)
    build(parser.parse_args().observations)
