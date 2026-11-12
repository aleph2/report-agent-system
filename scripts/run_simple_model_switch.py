"""One isolated SDK call using unchanged Task042 B messages and tool schema."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from dotenv import dotenv_values
import httpx
from openai import OpenAI

from report_agent.acceptance_review import GraderResponse
from report_agent.deep_models import error_data

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.runs/task042/relation-verdict-controls'
EXPECTED = {
    'system': '340e74c063010a8957579a17ab2e9b20cd960e4858eb382e6f5521a86d70b2a4',
    'user': '68504cfd4871eda5210dfdd19e26e8a880df22066721028a682067e68dc07c39',
}


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def now():
    return datetime.now(timezone.utc).isoformat()


def prepare(env_path):
    inputs = read(BASE / '051e6c85b549/input.json')
    if set(inputs) != set(EXPECTED) or any(sha(inputs[k]) != h for k, h in EXPECTED.items()):
        raise ValueError('FROZEN_MESSAGES_MISMATCH')
    if GraderResponse.model_json_schema() != read(BASE / 'batch.json')['response_schema']:
        raise ValueError('FROZEN_RESPONSE_SCHEMA_MISMATCH')
    frozen = ROOT / '.analysis/task042/frozen/model-inputs.json'
    if sha(frozen.read_bytes()) != '813e37605266edbfe9871a1960a7d3e90ca1cb97a538c8844317e1d5aa575816':
        raise ValueError('FROZEN_CASES_MISMATCH')
    case = next(c for c in read(frozen)['cases'] if c['id'] == '051e6c85b549')
    ids = [c['id'] for c in json.loads(case['rubric'])['criteria']]
    previous = read(ROOT / '.analysis/task042/actual-parameters.json')
    config = dotenv_values(env_path)
    model, url, key = (config.get('HIGHWAY_MODEL_' + k) for k in ('NAME', 'BASE_URL', 'API_KEY'))
    if model != 'deepseek-v4.1-flash-1017' or url.rstrip('/') != 'https://api.deepseek.com' or not key:
        raise ValueError('USER_SELECTED_DEEPSEEK_CONFIGURATION_REQUIRED')
    payload = dict(model=model, messages=[{'role': k, 'content': inputs[k]} for k in ('system', 'user')],
                   tools=previous['tools'], tool_choice='auto', parallel_tool_calls=False,
                   reasoning_effort='high', max_tokens=65536, stream=False,
                   thinking={'type': 'enabled'})
    return payload, ids, url, key


def run(args):
    payload, ids, url, key = prepare(args.env_file)
    if args.check_only:
        print(json.dumps({'preflight': 'passed', 'model': payload['model'], 'base_url': url,
                          'message_sha256': EXPECTED, 'criteria': len(ids),
                          'tools': len(payload['tools']), 'api_key_present': bool(key)}))
        return
    root = ROOT / '.runs/task044/simple-model-switch/attempt-01'
    root.mkdir(parents=True, exist_ok=False)
    write(root / 'request.json', payload)
    receipt = dict(status='attempted', started=now(), model=payload['model'], base_url=url,
                   runner_sha256=sha(Path(__file__).read_bytes()),
                   message_sha256=EXPECTED, request_sha256=sha((root / 'request.json').read_bytes()),
                   model_requests=0, model_responses=0, usage=None, max_retries=0,
                   timeout_seconds=dict(connect=15, read=1800, write=60, pool=60),
                   differences=['model and endpoint and key', 'tool_choice required to auto',
                                'max_completion_tokens to max_tokens', 'omit GLM clear_thinking',
                                'direct SDK without agent loop', 'transport retries 2 to 0'])
    write(root / 'receipt.json', receipt)
    print(json.dumps({'status': 'starting', 'model': payload['model'], 'base_url': url}), flush=True)
    try:
        request = dict(payload)
        thinking = request.pop('thinking')
        with OpenAI(base_url=url, api_key=key, max_retries=0,
                    timeout=httpx.Timeout(**receipt['timeout_seconds'])) as client:
            receipt['model_requests'] = 1
            write(root / 'receipt.json', receipt)
            response = client.chat.completions.create(**request, extra_body={'thinking': thinking})
        # Export only public fields; do not serialize or inspect private reasoning.
        public = dict(id=response.id, model=response.model, created=response.created,
                      usage=response.usage.model_dump(mode='json') if response.usage else None,
                      choices=[dict(index=c.index, finish_reason=c.finish_reason,
                                    message=dict(role=c.message.role, content=c.message.content,
                                                 tool_calls=[t.model_dump(mode='json') for t in c.message.tool_calls or []]))
                               for c in response.choices])
        write(root / 'response.json', public)
        receipt.update(model_responses=1, returned_model=response.model, usage=public['usage'])
        if len(response.choices) != 1 or response.choices[0].finish_reason != 'tool_calls':
            raise ValueError('EXPECTED_ONE_TOOL_RESPONSE')
        calls = response.choices[0].message.tool_calls or []
        if len(calls) != 1 or calls[0].function.name != 'GraderResponse':
            raise ValueError('EXPECTED_GRADER_RESPONSE')
        result = GraderResponse.model_validate_json(calls[0].function.arguments).model_dump(mode='json')
        if [row['name'] for row in result['criteria']] != ids:
            raise ValueError('CRITERION_COVERAGE_MISMATCH')
        write(root / 'output.json', result)
        receipt.update(status='completed', result=result['result'], exact_criterion_coverage=True)
    except Exception as exc:
        receipt.update(status='error', error=error_data(exc))
    receipt['ended'] = now()
    write(root / 'receipt.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    run(parser.parse_args())
