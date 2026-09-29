"""Task046: restored GLM with the unchanged approved report-claims paragraph."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from dotenv import dotenv_values

from run_simple_model_switch import ROOT, GraderResponse, OpenAI, error_data, httpx, now, read, sha, write

DEST = ROOT / '.runs/task046/glm-report-claims/attempt-01'
BASE = ROOT / '.runs/task042/relation-verdict-controls'
PROMPT = ROOT / '.analysis/task045/frozen-request.json'
PARAMS = ROOT / '.analysis/task042/actual-parameters.json'


def prepare(env_file):
    if sha(PROMPT.read_bytes()) != '3b5d647981279f8b9e7b4a7ec40ec40184bc6f7c495b835577facba031ad9d54':
        raise ValueError('UNCHANGED_APPROVED_PROMPT_REQUIRED')
    old = read(PARAMS)
    payload = {k: v for k, v in old.items() if k not in ('model_name', 'extra_body')}
    payload.update(old['extra_body'])
    payload['messages'] = read(PROMPT)['messages']
    if payload['model'] != 'glm-5.3':
        raise ValueError('USER_SELECTED_GLM_REQUIRED')
    if payload['tools'] != read(PROMPT)['tools']:
        raise ValueError('TOOL_SCHEMA_CHANGED')
    if GraderResponse.model_json_schema() != read(BASE / 'batch.json')['response_schema']:
        raise ValueError('RESPONSE_SCHEMA_CHANGED')
    frozen = ROOT / '.analysis/task042/frozen/model-inputs.json'
    if sha(frozen.read_bytes()) != '813e37605266edbfe9871a1960a7d3e90ca1cb97a538c8844317e1d5aa575816':
        raise ValueError('FROZEN_CASES_MISMATCH')
    case = next(c for c in read(frozen)['cases'] if c['id'] == '051e6c85b549')
    ids = [c['id'] for c in json.loads(case['rubric'])['criteria']]
    config = dotenv_values(env_file)
    url, key = config.get('HIGHWAY_MODEL_BASE_URL'), config.get('HIGHWAY_MODEL_API_KEY')
    if url != 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1' or not key:
        raise ValueError('RESTORED_ALIYUN_CONFIGURATION_REQUIRED')
    return payload, ids, url, key


def run(args):
    payload, ids, url, key = prepare(args.env_file)
    protected = [PROMPT, PARAMS, Path(__file__), Path(__file__).with_name('run_simple_model_switch.py'),
                 ROOT / '.ase/verification/042-fixture-oracle.md']
    hashes = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in protected}
    if args.check_only:
        print(json.dumps({'status': 'preflight_passed', 'model': payload['model'], 'url': url,
                          'message_sha256': {m['role']: sha(m['content']) for m in payload['messages']},
                          'same_messages_as045': payload['messages'] == read(PROMPT)['messages'],
                          'criteria': len(ids)}))
        return
    DEST.mkdir(parents=True, exist_ok=False)
    write(DEST / 'request.json', payload)
    receipt = dict(status='attempted', started=now(), model=payload['model'], base_url=url,
                   frozen_files=hashes, request_sha256=sha((DEST / 'request.json').read_bytes()),
                   model_selection='explicit user glm-5.3 overrides env model name; URL/key from env',
                   message_sha256={m['role']: sha(m['content']) for m in payload['messages']},
                   model_requests=0, model_responses=0, usage=None, max_retries=0,
                   timeout_seconds=dict(connect=15, read=1800, write=60, pool=60),
                   differences_from042=['approved system paragraph', 'direct SDK instead of agent wrapper',
                                        'transport retries 2 to 0', 'restored current credential'])
    write(DEST / 'receipt.json', receipt)
    print(json.dumps({'status': 'starting', 'model': payload['model'], 'base_url': url}), flush=True)
    try:
        request = dict(payload)
        thinking = request.pop('thinking')
        with OpenAI(base_url=url, api_key=key, max_retries=0,
                    timeout=httpx.Timeout(**receipt['timeout_seconds'])) as client:
            receipt['model_requests'] = 1
            write(DEST / 'receipt.json', receipt)
            response = client.chat.completions.create(**request, extra_body={'thinking': thinking})
        # Public fields only; neither read nor serialize private reasoning.
        public = dict(id=response.id, model=response.model, created=response.created,
                      usage=response.usage.model_dump(mode='json') if response.usage else None,
                      choices=[dict(index=c.index, finish_reason=c.finish_reason,
                                    message=dict(role=c.message.role, content=c.message.content,
                                                 tool_calls=[t.model_dump(mode='json') for t in c.message.tool_calls or []]))
                               for c in response.choices])
        write(DEST / 'response.json', public)
        receipt.update(model_responses=1, returned_model=response.model, usage=public['usage'])
        if len(response.choices) != 1 or response.choices[0].finish_reason != 'tool_calls':
            raise ValueError('EXPECTED_ONE_TOOL_RESPONSE')
        calls = response.choices[0].message.tool_calls or []
        if len(calls) != 1 or calls[0].function.name != 'GraderResponse':
            raise ValueError('EXPECTED_GRADER_RESPONSE')
        result = GraderResponse.model_validate_json(calls[0].function.arguments).model_dump(mode='json')
        if [row['name'] for row in result['criteria']] != ids:
            raise ValueError('CRITERION_COVERAGE_MISMATCH')
        write(DEST / 'output.json', result)
        receipt.update(status='completed', result=result['result'], exact_criterion_coverage=True)
    except Exception as exc:
        receipt.update(status='error', error=error_data(exc))
    receipt.update(ended=now(), postflight_matches=all(sha((ROOT / p).read_bytes()) == h for p, h in hashes.items()))
    write(DEST / 'receipt.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    run(parser.parse_args())
