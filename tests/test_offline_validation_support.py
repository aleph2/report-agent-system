"""Managed offline runner/child guard preserve real localhost and phase reporting."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_managed_runner_preserves_phase_plugin_and_subprocess_network_guard(tmp_path):
    root=Path(__file__).resolve().parents[1]
    runner=root/'tests/support/run_offline_tests.py'
    sample=tmp_path/'test_offline_sample.py'
    sample.write_text('''import socket, subprocess, sys
import pytest
def test_loopback_and_external_guard():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen(1)
        with socket.create_connection(listener.getsockname()) as connection:
            accepted,_=listener.accept();accepted.close()
    with pytest.raises(RuntimeError,match='OFFLINE_TEST_EXTERNAL_DNS_FORBIDDEN'):
        socket.getaddrinfo('external-fixture.invalid',443)
    code="import socket; socket.getaddrinfo('external-fixture.invalid',443)"
    child=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert child.returncode!=0 and 'OFFLINE_TEST_EXTERNAL_DNS_FORBIDDEN' in child.stderr
@pytest.mark.skip(reason='synthetic setup skip accounting')
def test_explicit_skip(): pass
''',encoding='utf-8')
    phase=tmp_path/'phases.json'
    environment={**os.environ,'REPORT_OFFLINE_PHASE_REPORT':str(phase),'PYTHONDONTWRITEBYTECODE':'1'}
    result=subprocess.run([sys.executable,'-B',str(runner),'-q',str(sample),'--rootdir',str(tmp_path),
        '-p','no:cacheprovider'],cwd=root,env=environment,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    data=json.loads(phase.read_text(encoding='utf-8'))
    assert data['exit_code']==0 and len(data['collected_nodes'])==2
    assert data['collection_reports']==[]
    assert [(r['when'],r['outcome']) for r in data['results']]==[
        ('setup','passed'),('call','passed'),('teardown','passed'),('setup','skipped'),('teardown','passed')]
    assert len(Path(str(phase)+'.jsonl').read_text().splitlines())==5
