"""Inventory first-party Python state access in src/ and scripts/ without importing the app."""
import argparse
import ast
from collections import defaultdict
import csv
from pathlib import Path
import re
import json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/reviews'
STATE = re.compile(r'\b(?:from|into|join|update|table(?: if not exists)?)\s+["\x60\[]?state\b', re.I)
KEY = re.compile(r'[a-z][a-z0-9_]*(?::.*)?\Z')
CALLS = {
    'commission_plan': {'_state': 'read', '_set': 'write'},
    'legacy_state': {'_get': 'read', '_set': 'write'},
    'review_steps': {'_get': 'read', '_put': 'write'},
    'model_recovery': {'_get': 'read', '_put': 'write'},
    'bounded_operations': {'reserve_once': 'write', 'record_outcome': 'write', 'record_not_dispatched': 'write'},
    'live_messages': {'_once': 'write'},
}


def walk_scope(node):
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield child
            yield from walk_scope(child)


def spelling(expr):
    return ast.unparse(expr).replace('\t', ' ').replace('\n', ' ')


class Module:
    def __init__(self, path):
        self.path = path
        self.tree = ast.parse(path.read_text('utf-8'))
        self.functions = {f.name: f for f in ast.walk(self.tree) if isinstance(f, ast.FunctionDef)}
        self.aliases = {}
        for n in ast.walk(self.tree):
            if isinstance(n, ast.ImportFrom):
                for alias in n.names:
                    self.aliases[alias.asname or alias.name] = ((n.module or '').split('.')[-1], alias.name)
        self.bindings = {}
        for scope in (n for n in ast.walk(self.tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))):
            bindings = defaultdict(list)
            for n in walk_scope(scope):
                if isinstance(n, ast.Assign):
                    for target in n.targets:
                        if isinstance(target, ast.Name):
                            bindings[target.id].append(n.value)
                if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and isinstance(n.iter, (ast.Tuple, ast.List)):
                    bindings[n.target.id].extend(n.iter.elts)
            self.bindings[scope] = bindings

    def target(self, expr):
        if isinstance(expr, ast.Name):
            return self.aliases.get(expr.id, (self.path.stem, expr.id))
        if isinstance(expr, ast.Attribute):
            parent = spelling(expr.value)
            return self.aliases.get(parent, ('', parent))[-1], expr.attr
        return '', ''

    def keys(self, expr, scope, modules, visited=frozenset()):
        if expr in visited or len(visited) > 14:
            return set()
        visited = visited | {expr}
        resolve = lambda child: self.keys(child, scope, modules, visited)
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return {expr.value}
        if isinstance(expr, ast.JoinedStr) and isinstance(expr.values[0], ast.Constant):
            return {expr.values[0].value.split(':')[0] + ':*'} if ':' in expr.values[0].value else set()
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            return {s.split(':')[0] + ':*' for s in resolve(expr.left) if ':' in s}
        if isinstance(expr, ast.IfExp):
            return resolve(expr.body) | resolve(expr.orelse)
        if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
            return set().union(*(resolve(e) for e in expr.elts))
        if isinstance(expr, ast.Name):
            values = self.bindings.get(scope, {}).get(expr.id) or self.bindings[self.tree].get(expr.id, [])
            if values:
                return set().union(*(resolve(e) for e in values))
        target, name = self.target(expr.func if isinstance(expr, ast.Call) else expr)
        mod = modules.get(target)
        if mod:
            if isinstance(expr, ast.Call) and name in mod.functions:
                f = mod.functions[name]
                return set().union(*(mod.keys(r.value, f, modules, visited) for r in walk_scope(f)
                                     if isinstance(r, ast.Return) and r.value))
            if isinstance(expr, (ast.Name, ast.Attribute)):
                return set().union(*(mod.keys(v, mod.tree, modules, visited) for v in mod.bindings[mod.tree].get(name, [])))
        return set()

    def rows(self, modules):
        for scope in ast.walk(self.tree):
            if not isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for call in walk_scope(scope):
                if isinstance(call, ast.Attribute) and call.attr == 'manifest':
                    obj = spelling(call.value)
                    if obj == 'store' or obj.endswith('.store'):
                        yield self.row(scope, call, 'property', 'read', obj + '.manifest', {'manifest'})
                if not isinstance(call, ast.Call):
                    continue
                args = list(call.args)
                if not args:
                    args = [kw.value for kw in call.keywords if kw.arg in ('key', 'sql')]
                if not args:
                    continue
                target, name = self.target(call.func)
                receiver = spelling(call.func.value) if isinstance(call.func, ast.Attribute) else ''
                op = kind = expr = None
                if isinstance(call.func, ast.Name) and receiver == '':
                    for alias in self.bindings.get(scope, {}).get(call.func.id, []):
                        if isinstance(alias, ast.Attribute) and alias.attr in ('get', 'set'):
                            name, receiver = alias.attr, spelling(alias.value)
                if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
                    for alias in self.bindings.get(scope, {}).get(receiver, []):
                        if isinstance(alias, ast.Attribute) and alias.attr == 'store':
                            receiver = spelling(alias)
                if name in ('execute', 'executemany', 'executescript'):
                    fragments = [n.value for n in ast.walk(args[0]) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                    if isinstance(args[0], ast.Name):
                        fragments.extend(self.keys(args[0], scope, modules))
                    for sql in fragments:
                        if STATE.search(sql):
                            yield self.sql_row(scope, call, sql, modules)
                    continue
                if name in ('get', 'set') and (receiver.split('.')[-1] in ('store', 'storage') or
                        receiver == 'self' and self.path.stem == 'store' or re.search(r'\bStore\(.*\)$', receiver)):
                    kind, op, expr = 'store', {'get':'read', 'set':'write'}[name], args[0]
                elif name in CALLS.get(target, {}) and len(call.args) >= 2:
                    kind, op, expr = 'helper', CALLS[target][name], call.args[1]
                elif target == 'legacy_state' and name in modules['legacy_state'].functions:
                    f = modules[target].functions[name]
                    if name.startswith(('get_', 'set_')):
                        key = next((n.args[1] for n in walk_scope(f) if isinstance(n, ast.Call)
                                    and len(n.args) >= 2 and isinstance(n.func, ast.Name) and n.func.id in ('_get','_set')), None)
                        if key:
                            yield self.row(scope, call, 'accessor', 'read' if name.startswith('get_') else 'write',
                                name, modules[target].keys(key, f, modules))
                    elif name.startswith(('read_', 'iter_', 'insert_')):
                        yield self.row(scope, call, 'accessor', 'write' if name.startswith('insert_') else 'read', name, set())
                if expr:
                    yield self.row(scope, call, kind, op, spelling(expr), self.keys(expr, scope, modules))

    def row(self, scope, call, kind, op, expr, keys):
        families = {k.partition(':')[0] + (':*' if ':' in k else '') for k in keys if KEY.fullmatch(k) or k.endswith('_%') or k == '?'}
        return (str(self.path.relative_to(ROOT)), call.lineno, getattr(scope, 'name', '<module>'),
                kind, op, expr, ','.join(sorted(families)) or '?')

    def sql_row(self, scope, call, sql, modules):
        verb = sql.strip().lower().split()[0]
        op = {'select':'read', 'delete':'delete', 'create':'schema'}.get(verb, 'write')
        keys = set()
        expr = None
        params = call.args[1] if len(call.args) > 1 else None
        if isinstance(call.func, ast.Attribute) and call.func.attr == 'executemany' and params:
            batches = [params]
            if isinstance(params, ast.Name):
                batches = self.bindings.get(scope, {}).get(params.id, []) or self.bindings[self.tree].get(params.id, [])
            if any(isinstance(batch, (ast.List, ast.Tuple)) for batch in batches):
                # Each parameter row has its own key; JSON/value operands can also be strings.
                if verb in ('insert', 'replace'):
                    insert = re.search(r"\bstate\s*(?:\(([^)]*)\))?\s*values\s*\(([^)]*)\)", sql, re.I)
                    columns = (insert[1] or 'key,value').lower().replace(' ', '').split(',') if insert else []
                    values = insert[2].split(',') if insert else []
                    if 'key' not in columns or len(columns) != len(values):
                        return self.row(scope, call, 'sql', op, spelling(params), {'?'})
                    key_column = columns.index('key')
                    token = values[key_column].strip()
                    if token != '?':
                        fixed = re.fullmatch(r"'((?:''|[^'])*)'", token)
                        return self.row(scope, call, 'sql', op, token, {fixed[1] if fixed else '?'})
                    index = sum(value.count('?') for value in values[:key_column])
                else:
                    bound_key = re.search(r"\bkey\s*=\s*(\?)", sql, re.I)
                    if not bound_key:
                        return self.row(scope, call, 'sql', op, spelling(params), {'?'})
                    index = sql[:bound_key.start(1)].count('?')
                operands = []
                for batch in batches:
                    if not isinstance(batch, (ast.List, ast.Tuple)):
                        keys.add('?')
                        continue
                    for row in batch.elts:
                        if not isinstance(row, (ast.List, ast.Tuple)) or len(row.elts) <= index:
                            keys.add('?')
                            continue
                        key = row.elts[index]
                        operands.append(spelling(key))
                        keys.update(self.keys(key, scope, modules) or {'?'})
                return self.row(scope, call, 'sql', op, 'batch keys: ' + ', '.join(operands), keys)
        if verb in ('insert', 'replace'):
            match = re.search(r"values\s*\(\s*'([^']+)'", sql, re.I)
            if params and isinstance(params,(ast.Tuple, ast.List)) and not match:
                expr = params.elts[0]
        else:
            matches = re.findall(r"\bkey\s*(?:=|like|glob)\s*'([^']+)'", sql, re.I)
            match = None
            keys.update(k.rstrip('%*') if not k.endswith('_%') else k for k in matches)
            if params and not matches:
                if isinstance(params, (ast.Tuple, ast.List)):
                    expr = params.elts[-1] if verb == 'update' or 'substr(' in sql.lower() else params.elts[0]
                else:
                    expr = params
            fixed = re.search(r'\bkey\s+in\s*\(([^)]+)\)', sql, re.I)
            if fixed:
                keys.update(re.findall("'([^']+)'", fixed[1]))
        if match:
            keys.add(match[1].rstrip('%*'))
        if params and isinstance(params, ast.ListComp):
            for generator in params.generators:
                if isinstance(generator.iter, (ast.Tuple, ast.List)):
                    keys.update(self.keys(generator.iter, scope, modules))
        if expr:
            keys.update(self.keys(expr, scope, modules))
        operand = spelling(expr) if expr else ' '.join(sql.split())[:180]
        return self.row(scope, call, 'sql', op, operand, keys)


def census():
    paths = sorted(p for folder in ('src', 'scripts') for p in (ROOT / folder).rglob('*.py') if p != ROOT/'scripts/state_census.py')
    parsed = [Module(p) for p in paths]
    modules = {m.path.stem:m for m in parsed}
    with (DATA/'m0-state-bindings.tsv').open(encoding='utf-8') as source:
        bindings = {(r['file'], r['scope'], r['operand']):r['families']
                    for r in csv.DictReader(source, delimiter='\t')}
    rows = []
    for module in parsed:
        for row in module.rows(modules):
            path, _, scope, _, _, operand, _ = row
            resolved = bindings.get((path, scope, operand))
            rows.append((*row[:-1], resolved or row[-1]))
    return sorted(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace-dir', type=Path, action='append',
                        help='merge per-process offline SQLite observations; use once per fresh run directory')
    parser.add_argument('--observed', type=Path, help='output TSV for the merged runtime observations')
    parser.add_argument('--sites', type=Path, default=DATA/'m0-state-sites.tsv')
    parser.add_argument('--root', type=Path, default=ROOT, help='source tree to scan, e.g. an archived tag')
    args = parser.parse_args()
    ROOT = args.root.resolve()
    if args.trace_dir or args.observed:
        if not (args.trace_dir and args.observed):
            parser.error('--trace-dir and --observed must be supplied together')
        observed = set()
        for directory in args.trace_dir:
            files = list(directory.glob('*.jsonl'))
            if not files:
                parser.error(f'no trace files in {directory}')
            for path in files:
                for line in path.read_text('utf-8').splitlines():
                    observed.add(tuple(json.loads(line)))
        if not observed:
            parser.error('no state operations observed')
        with args.observed.open('w', newline='', encoding='utf-8') as out:
            writer = csv.writer(out, delimiter='\t', lineterminator='\n')
            writer.writerow(('operation', 'family'))
            writer.writerows(sorted(observed))
        raise SystemExit(0)
    with args.sites.open('w', newline='', encoding='utf-8') as out:
        writer = csv.writer(out, delimiter='\t', lineterminator='\n')
        writer.writerow(('file','line','scope','access','operation','operand','families'))
        writer.writerows(census())
