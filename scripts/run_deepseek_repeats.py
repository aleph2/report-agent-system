"""Task051: fixed independent-context repeats of Task050 request bytes."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from run_deepseek_strict_probe import prepare_strict
from run_simple_model_switch import (
    ROOT, GraderResponse, OpenAI, error_data, httpx, now, read, sha, write,
)

DEST = ROOT / '.runs/task051/deepseek-repeats'
BASE = ROOT / '.runs/task050/deepseek-strict'
EXPECTED = {
    'high': '63bfb57026825423795495b11fd6baf25fb8ef27690836cb6e5b196c1a57093f',
    'max': 'd3854f920039a23b04400fccdee15e44f8854c627362e873548e55e3c67a5e8d',
}
TIMEOUT = dict(connect=15, read=1800, write=60, pool=60)


def schedule():
    return [dict(id=f'{effort}-{repeat:02d}', effort=effort)
            for repeat in range(1, 4) for effort in ('high', 'max')]


def settings(env_file):
    configs = {effort: prepare_strict(env_file, effort) for effort in EXPECTED}
    for effort, (payload, ids, url, key) in configs.items():
        frozen = BASE / effort / 'request.json'
        if sha(frozen.read_bytes()) != EXPECTED[effort] or payload != read(frozen):
            raise ValueError('TASK050_REQUEST_MISMATCH')
    if configs['high'][1:] != configs['max'][1:]:
        raise ValueError('CONFIG_CHANGED_DURING_PREFLIGHT')
    return configs


def prepare(env_file):
    configs = settings(env_file)
    DEST.mkdir(parents=True, exist_ok=False)
    files = [Path(__file__), ROOT / 'scripts/run_deepseek_strict_probe.py',
             ROOT / 'scripts/run_official_deepseek_repeat.py',
             ROOT / 'scripts/run_simple_model_switch.py',
             ROOT / 'src/report_agent/acceptance_review.py',
             ROOT / '.ase/verification/042-fixture-oracle.md',
             ROOT / '.ase/tasks/051-deepseek-repeats.md']
    for item in schedule():
        path = DEST / item['id']
        path.mkdir()
        (path / 'request.json').write_bytes((BASE / item['effort'] / 'request.json').read_bytes())
    manifest = dict(status='prepared', prepared=now(), concurrency=3,
                    order=schedule(), request_sha256=EXPECTED,
                    frozen_files={str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in files},
                    base_url=configs['high'][2], timeout_seconds=TIMEOUT, max_retries=0)
    write(DEST / 'manifest.json', manifest)
    print({'status': 'prepared', 'requests': 6, 'concurrency': 3}, flush=True)


def validate_result(public, ids):
    choices = public['choices']
    if len(choices) != 1 or choices[0]['finish_reason'] != 'tool_calls':
        raise ValueError('EXPECTED_ONE_TOOL_RESPONSE')
    calls = choices[0]['message']['tool_calls']
    if len(calls) != 1 or calls[0]['function']['name'] != 'GraderResponse':
        raise ValueError('EXPECTED_GRADER_RESPONSE')
    result = GraderResponse.model_validate_json(calls[0]['function']['arguments']).model_dump(mode='json')
    if [row['name'] for row in result['criteria']] != ids:
        raise ValueError('CRITERION_COVERAGE_MISMATCH')
    return result


def attempt(item, config, manifest):
    _, ids, url, key = config
    path = DEST / item['id']
    payload = read(path / 'request.json')
    receipt = dict(status='attempted', started=now(), trial=item['id'], effort=item['effort'],
                   base_url=url, model=payload['model'], model_requests=0, model_responses=0,
                   usage=None, max_retries=0, timeout_seconds=TIMEOUT,
                   request_sha256=sha((path / 'request.json').read_bytes()),
                   phase='api', frozen_files=manifest['frozen_files'])
    write(path / 'receipt.json', receipt)
    print({'trial': item['id'], 'status': 'starting'}, flush=True)
    try:
        request = dict(payload)
        thinking = request.pop('thinking')
        with OpenAI(base_url=url, api_key=key, max_retries=0,
                    timeout=httpx.Timeout(**TIMEOUT)) as client:
            receipt['model_requests'] = 1
            write(path / 'receipt.json', receipt)
            response = client.chat.completions.create(**request, extra_body={'thinking': thinking})
        # Only export public final answers, tool calls and usage, never reasoning text.
        public = dict(id=response.id, model=response.model, created=response.created,
                      system_fingerprint=getattr(response, 'system_fingerprint', None),
                      usage=response.usage.model_dump(mode='json') if response.usage else None,
                      choices=[dict(index=c.index, finish_reason=c.finish_reason,
                                    message=dict(role=c.message.role, content=c.message.content,
                                                 tool_calls=[t.model_dump(mode='json') for t in c.message.tool_calls or []]))
                               for c in response.choices])
        write(path / 'response.json', public)
        receipt.update(phase='validation', model_responses=1, returned_model=response.model, usage=public['usage'])
        result = validate_result(public, ids)
        write(path / 'output.json', result)
        receipt.update(status='completed', result=result['result'], exact_criterion_coverage=True)
    except Exception as exc:
        receipt.update(status='error', error=error_data(exc))
    receipt['postflight_matches'] = all(sha((ROOT / p).read_bytes()) == h
                                        for p, h in manifest['frozen_files'].items())
    receipt['ended'] = now()
    write(path / 'receipt.json', receipt)
    print({k: receipt.get(k) for k in ('trial', 'status', 'phase', 'result', 'usage')}, flush=True)
    return receipt


def run(env_file):
    configs = settings(env_file)
    manifest = read(DEST / 'manifest.json')
    if manifest['status'] != 'prepared' or manifest['order'] != schedule():
        raise ValueError('BATCH_ALREADY_STARTED_OR_CHANGED')
    for name, digest in manifest['frozen_files'].items():
        if sha((ROOT / name).read_bytes()) != digest:
            raise ValueError('FROZEN_FILE_CHANGED')
    for item in schedule():
        path = DEST / item['id']
        if (path / 'receipt.json').exists() or sha((path / 'request.json').read_bytes()) != EXPECTED[item['effort']]:
            raise ValueError('TRIAL_ALREADY_STARTED_OR_CHANGED')
    manifest.update(status='running', started=now())
    write(DEST / 'manifest.json', manifest)
    pending = list(schedule())
    receipts = []
    halted = False
    with ThreadPoolExecutor(max_workers=3) as executor:
        active = {}
        while pending or active:
            while pending and len(active) < 3 and not halted:
                item = pending.pop(0)
                active[executor.submit(attempt, item, configs[item['effort']], manifest)] = item
            if not active:
                break
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                active.pop(future)
                receipt = future.result()
                receipts.append(receipt)
                if (receipt['status'] == 'error' and receipt['phase'] == 'api') or not receipt['postflight_matches']:
                    halted = True
    manifest.update(status='halted' if halted else 'completed', ended=now(),
                    unstarted=pending, results=[{k: r.get(k) for k in
                        ('trial', 'status', 'phase', 'result', 'model_requests', 'model_responses', 'usage')}
                        for r in receipts])
    write(DEST / 'manifest.json', manifest)
    print({'status': manifest['status'], 'finished': len(receipts), 'unstarted': len(pending)}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    (prepare if args.prepare else run)(args.env_file)
