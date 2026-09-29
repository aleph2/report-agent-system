"""Task050: isolated strict protocol and reasoning-capacity comparison."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

from run_official_deepseek_repeat import candidate, FREEZE
from run_simple_model_switch import (
    ROOT, GraderResponse, OpenAI, error_data, httpx, now, read, sha, write,
)

DEST = ROOT / '.runs/task050/deepseek-strict'


def strict_schema(schema, ids):
    """Adapt only wire constraints; original local validation remains authoritative."""
    value = deepcopy(schema)

    def visit(node):
        if isinstance(node, list):
            return [visit(item) for item in node]
        if not isinstance(node, dict):
            return node
        node = {k: visit(v) for k, v in node.items()
                if k not in {'discriminator', 'minLength', 'title'}}
        if 'oneOf' in node:
            node['anyOf'] = node.pop('oneOf')
        if 'const' in node:
            node['enum'] = [node.pop('const')]
        if node.get('type') == 'object':
            node['additionalProperties'] = False
            node['required'] = list(node.get('properties', {}))
            props = node.get('properties', {})
            if 'name' in props and 'passed' in props and 'status' in props:
                props['name'] = {
                    'type': 'string', 'enum': list(ids),
                    'description': 'Exact criterion ID supplied in the rubric. Copy the ID unchanged; do not replace it with a descriptive name.',
                }
        return node

    return visit(value)


def prepare_strict(env_file, effort):
    payload, ids, url, key = candidate(env_file)
    if payload != read(FREEZE):
        raise ValueError('FROZEN_REQUEST_MISMATCH')
    payload = deepcopy(payload)
    for tool in payload['tools']:
        fn = tool['function']
        fn['parameters'] = strict_schema(fn['parameters'], ids)
        fn['strict'] = True
    payload['reasoning_effort'] = effort
    payload['max_tokens'] = 131072 if effort == 'max' else 65536
    return payload, ids, url.rstrip('/') + '/beta', key


def run(args):
    payload, ids, url, key = prepare_strict(args.env_file, args.effort)
    root = DEST / args.effort
    if args.check_only:
        print({'preflight': 'passed', 'model': payload['model'], 'base_url': url,
               'effort': args.effort, 'max_tokens': payload['max_tokens'],
               'criteria': len(ids), 'messages_unchanged': payload['messages'] == read(FREEZE)['messages']})
        return
    if args.effort == 'max' and read(DEST / 'high/receipt.json')['status'] != 'completed':
        raise ValueError('HIGH_PROTOCOL_NOT_VALIDATED')
    root.mkdir(parents=True, exist_ok=False)
    protected = [FREEZE, Path(__file__), ROOT / '.ase/verification/042-fixture-oracle.md',
                 ROOT / 'src/report_agent/acceptance_review.py',
                 ROOT / 'scripts/run_simple_model_switch.py',
                 ROOT / 'scripts/run_official_deepseek_repeat.py']
    hashes = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in protected}
    write(root / 'request.json', payload)
    receipt = dict(status='attempted', started=now(), base_url=url, model=payload['model'],
                   effort=args.effort, max_tokens=payload['max_tokens'],
                   frozen_files=hashes, model_requests=0, model_responses=0, usage=None,
                   max_retries=0, timeout_seconds=dict(connect=15, read=1800, write=60, pool=60),
                   request_sha256=sha((root / 'request.json').read_bytes()),
                   message_sha256={m['role']: sha(m['content']) for m in payload['messages']},
                   differences_from048=['beta endpoint', 'strict schema and exact ID description/enum'] +
                   (['reasoning high to max', 'max_tokens 65536 to 131072'] if args.effort == 'max' else []))
    write(root / 'receipt.json', receipt)
    print({'status': 'starting', 'effort': args.effort, 'base_url': url}, flush=True)
    try:
        request = dict(payload)
        thinking = request.pop('thinking')
        with OpenAI(base_url=url, api_key=key, max_retries=0,
                    timeout=httpx.Timeout(**receipt['timeout_seconds'])) as client:
            receipt['model_requests'] = 1
            write(root / 'receipt.json', receipt)
            response = client.chat.completions.create(**request, extra_body={'thinking': thinking})
        public = dict(id=response.id, model=response.model, created=response.created,
                      system_fingerprint=getattr(response, 'system_fingerprint', None),
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
        (root / 'public-arguments.txt').write_text(calls[0].function.arguments, encoding='utf-8')
        result = GraderResponse.model_validate_json(calls[0].function.arguments).model_dump(mode='json')
        if [row['name'] for row in result['criteria']] != ids:
            raise ValueError('CRITERION_COVERAGE_MISMATCH')
        write(root / 'output.json', result)
        receipt.update(status='completed', result=result['result'], exact_criterion_coverage=True)
    except Exception as exc:
        receipt.update(status='error', error=error_data(exc))
    receipt['postflight_matches'] = all(sha((ROOT / p).read_bytes()) == h for p, h in hashes.items())
    receipt['ended'] = now()
    write(root / 'receipt.json', receipt)
    print({k: receipt[k] for k in ('status', 'effort', 'model_requests', 'model_responses', 'usage', 'postflight_matches')}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--effort', choices=['high', 'max'], required=True)
    parser.add_argument('--check-only', action='store_true')
    run(parser.parse_args())
