"""Aggregate saved Round 0 evidence. Run from the project root; no test execution."""
import collections
import ast
import csv
import xml.etree.ElementTree as ET
import json
from pathlib import Path

ROOT = Path.cwd()
RAW = ROOT / '.analysis/round0-coverage-20261018'
DOC = ROOT / 'docs/reviews/round0-coverage-20261018'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def outcomes(observations):
    result = {}
    for row in observations['reports']:
        node = result.setdefault(row['test'], {'outcome': 'not_completed', 'phases': []})
        node['phases'].append(row)
        if row['outcome'] == 'failed':
            node['outcome'] = 'failed' if row['phase'] == 'call' else 'error'
        elif node['outcome'] not in {'failed', 'error'}:
            if row['outcome'] == 'skipped':
                node['outcome'] = 'skipped'
            elif row['phase'] == 'call':
                node['outcome'] = 'passed'
    return result

def ratios(summary):
    return {'statements': summary['num_statements'], 'covered_statements': summary['covered_lines'],
            'line_percent': 100 * summary['covered_lines'] / summary['num_statements'] if summary['num_statements'] else None,
            'branches': summary['num_branches'], 'covered_branches': summary['covered_branches'],
            'branch_percent': 100 * summary['covered_branches'] / summary['num_branches'] if summary['num_branches'] else None}

base = read(RAW / 'baseline/observations.json')
observed = read(RAW / 'observed/observations.json')
results = outcomes(base)
other = outcomes(observed)
collected = read(RAW / 'baseline/collected.json')
unrun = sorted(set(collected) - set(results))
collection_errors = [row for row in base['errors'] if row.get('stage') == 'collection']
collection_skips = [{'name': case.attrib['name'], 'detail': case.find('skipped').text}
    for case in ET.parse(RAW / 'baseline/junit.xml').iter('testcase')
    if case.find('skipped') is not None and case.find('skipped').get('message') == 'collection skipped']
cov = read(RAW / 'baseline/coverage.json')
scope = read(DOC / 'neo-scope-review.json')
inventory = read(RAW / 'interface-inventory.json')
comparison = [{'test': node, 'baseline': results.get(node, {}).get('outcome'),
               'observed': other.get(node, {}).get('outcome')}
              for node in sorted(results.keys() | other.keys())
              if results.get(node, {}).get('outcome') != other.get(node, {}).get('outcome')]
save(RAW / 'outcome-comparison.json', comparison)
save(RAW / 'test-results.json', results)
files = {name: {**ratios(value['summary']), 'missing_lines': value['missing_lines'],
               'missing_branches': value.get('missing_branches', [])} for name, value in cov['files'].items()}
save(DOC / 'file-coverage.json', files)
with (DOC / 'file-coverage.csv').open('w', encoding='utf-8-sig', newline='') as output:
    writer = csv.writer(output)
    writer.writerow(['file', 'statements', 'covered_statements', 'line_percent', 'branches', 'covered_branches', 'branch_percent'])
    for name, row in sorted(files.items()):
        writer.writerow([name, *[row[key] for key in ['statements', 'covered_statements', 'line_percent', 'branches', 'covered_branches', 'branch_percent']]])
host = {'kind': 'Source-declared inventory; not effective runtime/API contract coverage', 'http': [], 'cli': []}
for relative in ['src/report_agent/webapp.py', 'src/report_agent/learning_api.py', 'src/report_agent/cli.py']:
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute) and deco.func.attr in {'get', 'post', 'put', 'patch', 'delete'} and deco.args and isinstance(deco.args[0], ast.Constant):
                    host['http'].append({'method': deco.func.attr.upper(), 'path': deco.args[0].value,
                        'file': relative, 'line': node.lineno, 'function': node.name, 'contract_coverage': 'not_measured'})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument' and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'command':
            host['cli'] = next(ast.literal_eval(k.value) for k in node.keywords if k.arg == 'choices')
save(DOC / 'host-interface-inventory.json', host)
all_final = set()
profiles = []
for profile in dict.fromkeys(row['profile'] for row in inventory['profiles']):
    for stage in ['compiled_native_toolnode', 'final_scripted_model_bind_tools']:
        grouped = collections.defaultdict(set)
        for row in inventory['profiles']:
            if row['profile'] == profile and row['registration_stage'] == stage:
                grouped[row['role']].update(tool['name'] for tool in row['tools'])
        for role, names in grouped.items():
            profiles.append({'profile': profile, 'role': role, 'stage': stage, 'names': sorted(names)})
            if stage == 'final_scripted_model_bind_tools':
                all_final.update((role, name) for name in names)

# Role/name union is an attempt diagnostic, NOT configuration/schema/contract coverage.
attempted = {(row['role'], row['name']) for row in observed['calls']
             if row['boundary'] == 'business_middleware'}
interface_rows = [{'role': role, 'name': name, 'middleware_attempt_seen': (role, name) in attempted,
                   'configuration_and_contract_assertion_coverage': 'not_measured'}
                  for role, name in sorted(all_final)]
save(DOC / 'interface-matrix.json', {'profiles': profiles, 'union_attempt_diagnostic': interface_rows,
     'probe_errors': inventory['errors'], 'limits': 'No percentage for full interface obligations. Attempts can reject before handler. Optimizer is not observed by BusinessBoundary.'})
paths = []
for path in scope['protocol_paths']:
    matches = {node: data['outcome'] for node, data in results.items()
               if any(node == candidate or node.startswith(candidate + '[') for candidate in path['candidate_tests'])}
    definition = {key: value for key, value in path.items() if key != 'runtime_evidence'}
    paths.append({**definition, 'runtime_evidence': {'baseline': '.analysis/round0-coverage-20261018/baseline/observations.json',
                  'comparison': '.analysis/round0-coverage-20261018/outcome-comparison.json',
                  'method': 'Exact collected nodeid and call outcome; not full state-transition coverage'},
                  'runtime_tests': matches, 'outcomes': dict(collections.Counter(matches.values())),
                  'path_assertion_coverage': 'partial_evidence_not_all_states'})
save(DOC / 'path-matrix.json', paths)
conditions = scope.get('independent_condition_audits', [])
failure_rows = []
for node, data in results.items():
    if data['outcome'] in {'failed', 'error', 'skipped'}:
        failure_rows.append({'test': node, 'outcome': data['outcome'],
                             'detail': '\n'.join(row['detail'] or '' for row in data['phases'] if row['outcome'] != 'passed')})
save(RAW / 'failures-and-skips.json', failure_rows)
lines = ['# 本轮全部失败、错误与跳过', '', '这是逐项原始结果索引，失败项数不等于独立产品缺陷数；尚未定位的原因保持未定。', '']
for row in collection_errors:
    lines += [f"## collection error: {row.get('nodeid')}", '', '```text', row['detail'], '```', '']
for row in collection_skips:
    lines += [f"## collection skipped: {row['name']}", '', '```text', row['detail'], '```', '']
if unrun:
    lines += ['## 已收集但没有执行终态', '', *['- ' + node for node in unrun], '']
for row in failure_rows:
    lines += [f"## {row['outcome']}: {row['test']}", '', '```text', row['detail'], '```', '']
(DOC / 'failures-and-skips.md').write_text('\n'.join(lines), encoding='utf-8')
metrics = {'head': read(RAW / 'baseline/environment.json')['head'],
    'collected': len(collected), 'collection_errors': collection_errors, 'collection_skips': collection_skips, 'unrun': unrun,
    'outcomes': dict(collections.Counter(row['outcome'] for row in results.values())),
    'observed_outcomes': dict(collections.Counter(row['outcome'] for row in other.values())),
    'outcome_differences': comparison, 'coverage': ratios(cov['totals']),
    'source_files': len(files), 'interface_union_role_name_count': len(all_final),
    'middleware_attempted_union_role_name_count': len(all_final & attempted),
    'unattributed_tool_entries': sum(row['role'] == 'unattributed' for row in observed['calls']),
    'protocol_families': len(paths), 'condition_groups': len(scope['critical_conditions']),
    'mcdc_total_percent': None,
    'baseline_result': read(RAW / 'baseline/result.json'),
    'observed_result': read(RAW / 'observed/result.json')}
save(DOC / 'metrics.json', metrics)
print(json.dumps(metrics, ensure_ascii=False, indent=2))
