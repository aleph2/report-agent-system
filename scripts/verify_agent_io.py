"""Run retained pytest regressions offline and archive actual fake-model traces.

This is a test runner, not a product runtime or a model quality evaluator.
Only the supplied tests run. TCP/UDP are denied; local HTTP MockTransport works.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('tests', nargs='+')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.chdir(ROOT)
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
    os.environ.update(LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')
    os.environ.pop('REPORT_GRAPH_TEST_URI', None)
    import pytest
    from langchain_core.messages import messages_to_dict
    from test_deep_runtime import Driver, ScriptedChat
    from test_bounded_review import Model

    class Record:
        nodeid = '<collection>'

        def __init__(self):
            self.results, self.denied = [], []

        def pytest_runtest_setup(self, item):
            self.nodeid = item.nodeid

        def pytest_runtest_logreport(self, report):
            self.results.append({'nodeid': report.nodeid, 'when': report.when,
                                 'outcome': report.outcome, 'duration': report.duration,
                                 'error': str(report.longrepr) if report.failed else None})

        def trace(self, value):
            with (out / 'model-trace.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps({'nodeid': self.nodeid, **value}, ensure_ascii=False, default=str) + '\n')

    record = Record()
    patches = []

    def patch(obj, name, value):
        patches.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    for name in ('connect', 'connect_ex', 'sendto'):
        original = getattr(socket.socket, name)

        def deny(sock, *a, _original=original, **kw):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                record.denied.append({'nodeid': record.nodeid, 'method': _original.__name__})
                raise OSError('AGENT_IO_TEST_NETWORK_DENIED')
            return _original(sock, *a, **kw)

        patch(socket.socket, name, deny)
    original_respond = Driver.respond

    async def respond(driver, role, messages):
        record.trace({'boundary': 'fake_model_input', 'role': role, 'messages': messages_to_dict(messages)})
        result = await original_respond(driver, role, messages)
        record.trace({'boundary': 'fake_model_output', 'role': role,
                      'messages': messages_to_dict([g.message for g in result.generations])})
        return result

    patch(Driver, 'respond', respond)
    original_bind = ScriptedChat.bind_tools

    def bind(model, tools, **kw):
        result = original_bind(model, tools, **kw)
        record.trace({'boundary': 'final_fake_model_tools', 'role': model.role,
                      'schemas': model.driver.bindings[model.role][-1]})
        return result

    patch(ScriptedChat, 'bind_tools', bind)
    original_invoke = Model.ainvoke

    async def invoke(model, messages):
        record.trace({'boundary': 'independent_text_tool_input', 'messages': messages})
        result = await original_invoke(model, messages)
        record.trace({'boundary': 'independent_text_tool_output',
                      'messages': messages_to_dict([result])})
        return result

    patch(Model, 'ainvoke', invoke)
    hashes = lambda: {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted((ROOT / 'src').rglob('*')) if p.suffix in ('.py', '.md')}
    before = hashes()
    test_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in [Path(__file__), *sorted((ROOT / 'tests').glob('*.py'))]}
    code = 2
    try:
        code = int(pytest.main(['-q', '--tb=short', f'--junitxml={out / "junit.xml"}', *args.tests], plugins=[record]))
    finally:
        for obj, name, value in reversed(patches):
            setattr(obj, name, value)
        (out / 'result.json').write_text(json.dumps({'exit_code': code, 'tests': args.tests,
            'results': record.results, 'denied_network': record.denied,
            'source_before': before, 'source_after': hashes(),
            'test_code_sha256': test_hashes,
            'limits': 'Scripted model observations and selected tests only. No model semantics, no subprocess network guarantee.'},
            ensure_ascii=False, indent=2), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
