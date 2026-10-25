"""Task052: transport audit, flat output candidate, equal-capacity comparison."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.metadata
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError as ModelError

from run_deepseek_strict_probe import prepare_strict
from run_simple_model_switch import ROOT, GraderResponse, OpenAI, error_data, httpx, now, read, sha, write

DEST = ROOT / '.runs/task052/flat-equal-capacity'
BASE = ROOT / '.runs/task050/deepseek-strict'
TIMEOUT = dict(connect=15, read=1800, write=60, pool=60)
URL = 'https://api.deepseek.com/beta/chat/completions'
PLAN = [
    dict(id='a-union-high', stage='a', shape='union', effort='high'),
    dict(id='a-flat-high', stage='a', shape='flat', effort='high'),
    dict(id='b-flat-high', stage='b', shape='flat', effort='high'),
    dict(id='b-flat-max', stage='b', shape='flat', effort='max'),
]


def flat_schema(schema):
    result = deepcopy(schema)
    branches = result['properties']['criteria']['items']['anyOf']
    yes, no = branches
    shared = set(yes['properties'])
    if set(no['properties']) != shared | {'gap'}:
        raise ValueError('UNEXPECTED_BRANCH_FIELDS')
    if any(yes['properties'][k] != no['properties'][k] for k in shared - {'passed'}):
        raise ValueError('UNEXPECTED_BRANCH_SEMANTICS')
    item = deepcopy(no)
    item['properties']['passed'] = {'type': 'boolean'}
    item['properties']['gap']['description'] = (
        'What is missing or incorrect, specific enough to address. '
        'Use the empty string when passed is true; otherwise describe the gap.')
    result['properties']['criteria']['items'] = item
    Draft202012Validator.check_schema(result)
    return result


def payload_for(item):
    value = read(BASE / item['effort'] / 'request.json')
    value['max_tokens'] = 131072
    if item['shape'] == 'flat':
        fn = value['tools'][0]['function']
        fn['parameters'] = flat_schema(fn['parameters'])
    return value


def request_observer(expected, target):
    def observe(request):
        body = request.read()
        actual = json.loads(body)
        correct_url = (request.method == 'POST' and request.url.scheme == 'https'
                       and request.url.host == 'api.deepseek.com'
                       and request.url.path == '/beta/chat/completions'
                       and not request.url.query and not request.url.userinfo)
        record = dict(observed=now(), url=URL if correct_url else '<unexpected target>',
                      correct_url=correct_url, body_sha256=sha(body),
                      json_equals_frozen=(actual == expected),
                      strict_flags=[t['function'].get('strict') for t in actual.get('tools', [])])
        write(target, record)  # Never log request objects, headers, query or credentials.
        if not correct_url or actual != expected:
            raise ValueError('OUTGOING_REQUEST_MISMATCH')
    return observe


def validate_public(public, payload, ids, shape):
    choices = public['choices']
    if len(choices) != 1 or choices[0]['finish_reason'] != 'tool_calls':
        raise ValueError('EXPECTED_ONE_TOOL_RESPONSE')
    calls = choices[0]['message']['tool_calls']
    if len(calls) != 1 or calls[0]['function']['name'] != 'GraderResponse':
        raise ValueError('EXPECTED_GRADER_RESPONSE')
    raw = json.loads(calls[0]['function']['arguments'])
    Draft202012Validator(payload['tools'][0]['function']['parameters']).validate(raw)
    projected = deepcopy(raw)
    projection = []
    if shape == 'flat':
        for i, row in enumerate(projected['criteria']):
            if row['passed']:
                if row['gap'] != '':
                    raise ValueError('PASS_WITH_NONEMPTY_GAP')
                del row['gap']
                projection.append(f'criteria/{i}/gap: removed empty pass-only wire field')
    canonical = GraderResponse.model_validate(projected).model_dump(mode='json')
    if canonical != projected:
        raise ValueError('UNDECLARED_CANONICAL_NORMALIZATION')
    if [row['name'] for row in canonical['criteria']] != ids:
        raise ValueError('CRITERION_COVERAGE_MISMATCH')
    return raw, canonical, projection


def diagnostics(exc):
    if isinstance(exc, json.JSONDecodeError):
        return dict(kind='json_syntax', position=exc.pos, line=exc.lineno, column=exc.colno)
    if isinstance(exc, SchemaError):
        return dict(kind='wire_schema', path=list(exc.absolute_path), validator=exc.validator)
    if isinstance(exc, ModelError):
        return dict(kind='local_contract', errors=[dict(type=e['type'], loc=e['loc'])
                    for e in exc.errors(include_input=False, include_url=False)])
    return dict(kind=type(exc).__name__)


def config(env_file):
    ids = url = key = None
    for effort in ('high', 'max'):
        payload, these_ids, this_url, this_key = prepare_strict(env_file, effort)
        if payload != read(BASE / effort / 'request.json'):
            raise ValueError('TASK050_BASELINE_CHANGED')
        if ids is not None and (ids, url, key) != (these_ids, this_url, this_key):
            raise ValueError('CONFIG_CHANGED_DURING_PREFLIGHT')
        ids, url, key = these_ids, this_url, this_key
    return ids, url, key


def prepare(env_file):
    config(env_file)
    DEST.mkdir(parents=True, exist_ok=False)
    protected = [Path(__file__), ROOT / '.ase/tasks/052-flat-equal-capacity.md',
                 ROOT / '.ase/verification/042-fixture-oracle.md',
                 ROOT / 'src/report_agent/acceptance_review.py']
    protected += [ROOT / 'scripts' / name for name in
                  ('run_deepseek_strict_probe.py', 'run_simple_model_switch.py', 'run_official_deepseek_repeat.py')]
    protected += [BASE / effort / 'request.json' for effort in ('high', 'max')]
    hashes = {}
    for item in PLAN:
        folder = DEST / item['id']
        folder.mkdir()
        write(folder / 'request.json', payload_for(item))
        hashes[item['id']] = sha((folder / 'request.json').read_bytes())
    write(DEST / 'manifest.json', dict(prepared=now(), plan=PLAN, request_sha256=hashes,
          frozen_files={str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in protected},
          stages={'a': 'prepared', 'b': 'conditional'}, concurrency=2, max_retries=0,
          versions={p: importlib.metadata.version(p) for p in ('openai', 'httpx', 'jsonschema')}))
    print({'status': 'prepared', 'maximum_requests': 4, 'stage_b': 'requires flat A protocol success'})


def attempt(item, cfg, manifest):
    ids, url, key = cfg
    folder = DEST / item['id']
    payload = read(folder / 'request.json')
    receipt = dict(status='attempted', started=now(), trial=item['id'], shape=item['shape'],
                   effort=item['effort'], model=payload['model'], base_url=url,
                   model_requests=0, model_responses=0, usage=None, phase='api',
                   request_sha256=sha((folder / 'request.json').read_bytes()),
                   max_retries=0, timeout_seconds=TIMEOUT)
    write(folder / 'receipt.json', receipt)
    print({'trial': item['id'], 'status': 'starting'}, flush=True)
    try:
        request = dict(payload)
        thinking = request.pop('thinking')
        with httpx.Client(event_hooks={'request': [request_observer(payload, folder / 'outgoing.json')]}) as transport:
            with OpenAI(base_url=url, api_key=key, max_retries=0, http_client=transport,
                        timeout=httpx.Timeout(**TIMEOUT)) as client:
                receipt['model_requests'] = 1
                write(folder / 'receipt.json', receipt)
                response = client.chat.completions.create(**request, extra_body={'thinking': thinking})
        public = dict(id=response.id, model=response.model, created=response.created,
                      system_fingerprint=getattr(response, 'system_fingerprint', None),
                      usage=response.usage.model_dump(mode='json') if response.usage else None,
                      choices=[dict(index=c.index, finish_reason=c.finish_reason,
                                    message=dict(role=c.message.role, content=c.message.content,
                                                 tool_calls=[t.model_dump(mode='json') for t in c.message.tool_calls or []]))
                               for c in response.choices])
        write(folder / 'response.json', public)
        receipt.update(phase='validation', model_responses=1, returned_model=response.model, usage=public['usage'])
        raw, canonical, projection = validate_public(public, payload, ids, item['shape'])
        write(folder / 'wire-output.json', raw)
        write(folder / 'output.json', canonical)
        receipt.update(status='completed', result=canonical['result'], exact_criterion_coverage=True,
                       canonical_projection=projection)
    except Exception as exc:
        receipt.update(status='error', error=error_data(exc), diagnostic=diagnostics(exc))
    receipt['ended'] = now()
    receipt['postflight_matches'] = all(sha((ROOT / p).read_bytes()) == h
                                        for p, h in manifest['frozen_files'].items())
    write(folder / 'receipt.json', receipt)
    print({k: receipt.get(k) for k in ('trial', 'status', 'result', 'diagnostic', 'usage')}, flush=True)
    return receipt


def run(env_file, stage):
    cfg = config(env_file)
    manifest = read(DEST / 'manifest.json')
    if manifest['plan'] != PLAN or manifest['stages'][stage] not in ('prepared', 'conditional'):
        raise ValueError('PLAN_CHANGED_OR_STAGE_ALREADY_STARTED')
    for path, digest in manifest['frozen_files'].items():
        if sha((ROOT / path).read_bytes()) != digest:
            raise ValueError('FROZEN_FILE_CHANGED')
    if stage == 'b':
        a = [read(DEST / item['id'] / 'receipt.json') for item in PLAN if item['stage'] == 'a']
        if (manifest['stages']['a'] != 'completed'
                or any(r['phase'] == 'api' or not r['postflight_matches'] for r in a)
                or read(DEST / 'a-flat-high/receipt.json')['status'] != 'completed'):
            raise ValueError('STAGE_B_PROTOCOL_GATE_NOT_MET')
    items = [item for item in PLAN if item['stage'] == stage]
    for item in items:
        path = DEST / item['id']
        if (path / 'receipt.json').exists() or sha((path / 'request.json').read_bytes()) != manifest['request_sha256'][item['id']]:
            raise ValueError('TRIAL_ALREADY_STARTED_OR_CHANGED')
    manifest['stages'][stage] = 'running'
    write(DEST / 'manifest.json', manifest)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt, item, cfg, manifest) for item in items]
        outcomes = [f.result() for f in futures]
    manifest['stages'][stage] = 'completed'
    manifest[stage + '_results'] = [{k: r.get(k) for k in ('trial', 'status', 'phase', 'result')} for r in outcomes]
    write(DEST / 'manifest.json', manifest)
    print({'stage': stage, 'status': 'completed'}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare', action='store_true')
    action.add_argument('--stage', choices=['a', 'b'])
    args = parser.parse_args()
    prepare(args.env_file) if args.prepare else run(args.env_file, args.stage)
