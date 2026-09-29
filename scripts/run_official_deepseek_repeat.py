"""Task048: unchanged Task045 request on user-restored official DeepSeek service."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_simple_model_switch import (
    ROOT, GraderResponse, OpenAI, error_data, httpx, now, prepare, read, sha, write,
)

BASE = ROOT / '.runs/task044/simple-model-switch/attempt-01/request.json'
DELTA = ROOT / '.ase/experiments/045-report-claims-addendum.txt'
FREEZE = ROOT / '.analysis/task045/frozen-request.json'
DESTINATION = ROOT / '.runs/task048/official-deepseek-repeat/attempt-01'


def candidate(env_file):
    payload, ids, url, key = prepare(env_file)
    if sha(BASE.read_bytes()) != '8e03b094ea14106e1088bafbe87f7cffd534a6d9b7782b11987d10c59933ea33':
        raise ValueError('BASELINE_REQUEST_MISMATCH')
    if payload != read(BASE):
        raise ValueError('BASELINE_PARAMETERS_MISMATCH')
    delta = DELTA.read_text(encoding='utf-8').strip()
    if not delta:
        raise ValueError('EMPTY_PROMPT_DELTA')
    payload['messages'][0]['content'] += '\n\n' + delta + '\n'
    return payload, ids, url, key


def run(args):
    payload, ids, url, key = candidate(args.env_file)
    if args.freeze:
        FREEZE.parent.mkdir(parents=True, exist_ok=False)
        write(FREEZE, payload)
        print(json.dumps({'status': 'frozen', 'model': payload['model'],
                          'request_sha256': sha(FREEZE.read_bytes()),
                          'system_sha256': sha(payload['messages'][0]['content']),
                          'user_sha256': sha(payload['messages'][1]['content']),
                          'only_difference': 'append approved paragraph to system'}))
        return
    if payload != read(FREEZE):
        raise ValueError('FROZEN_REQUEST_MISMATCH')
    protected = [BASE, DELTA, FREEZE, Path(__file__),
                 Path(__file__).with_name('run_simple_model_switch.py'),
                 ROOT / '.ase/verification/042-fixture-oracle.md']
    hashes = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in protected}
    DESTINATION.mkdir(parents=True, exist_ok=False)
    write(DESTINATION / 'request.json', payload)
    previous = read(BASE.with_name('receipt.json'))
    receipt = dict(status='attempted', started=now(), model=payload['model'], base_url=url,
                   frozen_files=hashes,
                   message_sha256={m['role']: sha(m['content']) for m in payload['messages']},
                   request_sha256=sha((DESTINATION / 'request.json').read_bytes()),
                   model_requests=0, model_responses=0, usage=None,
                   max_retries=previous['max_retries'], timeout_seconds=previous['timeout_seconds'],
                   differences_from045=['none in request/settings; new independent observation with restored credential'])
    write(DESTINATION / 'receipt.json', receipt)
    print(json.dumps({'status': 'starting', 'model': payload['model'], 'base_url': url}), flush=True)
    try:
        request = dict(payload)
        thinking = request.pop('thinking')
        with OpenAI(base_url=url, api_key=key, max_retries=receipt['max_retries'],
                    timeout=httpx.Timeout(**receipt['timeout_seconds'])) as client:
            receipt['model_requests'] = 1
            write(DESTINATION / 'receipt.json', receipt)
            response = client.chat.completions.create(**request, extra_body={'thinking': thinking})
        # Export public fields only; do not read or serialize private reasoning.
        public = dict(id=response.id, model=response.model, created=response.created,
                      usage=response.usage.model_dump(mode='json') if response.usage else None,
                      choices=[dict(index=c.index, finish_reason=c.finish_reason,
                                    message=dict(role=c.message.role, content=c.message.content,
                                                 tool_calls=[t.model_dump(mode='json') for t in c.message.tool_calls or []]))
                               for c in response.choices])
        write(DESTINATION / 'response.json', public)
        receipt.update(model_responses=1, returned_model=response.model, usage=public['usage'])
        if len(response.choices) != 1 or response.choices[0].finish_reason != 'tool_calls':
            raise ValueError('EXPECTED_ONE_TOOL_RESPONSE')
        calls = response.choices[0].message.tool_calls or []
        if len(calls) != 1 or calls[0].function.name != 'GraderResponse':
            raise ValueError('EXPECTED_GRADER_RESPONSE')
        result = GraderResponse.model_validate_json(calls[0].function.arguments).model_dump(mode='json')
        if [row['name'] for row in result['criteria']] != ids:
            raise ValueError('CRITERION_COVERAGE_MISMATCH')
        write(DESTINATION / 'output.json', result)
        receipt.update(status='completed', result=result['result'], exact_criterion_coverage=True)
    except Exception as exc:
        receipt.update(status='error', error=error_data(exc))
    receipt['postflight_matches'] = all(sha((ROOT / p).read_bytes()) == h for p, h in hashes.items())
    receipt['ended'] = now()
    write(DESTINATION / 'receipt.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--freeze', action='store_true')
    run(parser.parse_args())
