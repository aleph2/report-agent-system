"""Fresh operator case and tool-limited Coordinator with no provider transport."""
from hashlib import sha256
import json

from langchain_core.messages import AIMessage, ToolMessage
import pytest

from report_agent import extraction_probe as probe
from test_deep_runtime import Driver, call
from test_ingestion import pdf_bytes


async def test_scoped_extraction_refuses_other_pages_and_never_restarts(tmp_path, monkeypatch):
    library = tmp_path / 'originals'
    library.mkdir()
    docs = {}
    for key, (_, _, numbers) in probe.DOCUMENTS.items():
        pages = [f'Outside scope {p}' for p in range(1, max(numbers) + 1)]
        for p in numbers:
            pages[p-1] = f'Selected {key} {p}'
        if key == 'design':
            pages[95] = 'Left K9023+670-K9023+760 measured 18 m'
        raw = pdf_bytes(pages)
        file = key + '.pdf'
        (library / file).write_bytes(raw)
        docs[key] = (file, sha256(raw).hexdigest(), numbers)
    monkeypatch.setattr(probe, 'DOCUMENTS', docs)
    case = tmp_path / 'o6'
    inputs = probe.prepare(library, case)
    assert inputs['documents']['survey']['original_pages'] == [43]

    def step(messages):
        text = messages[-1].content
        assert 'Outside scope' not in text
        assert 'Selected survey 43' in text
        return AIMessage(content='', tool_calls=[call('assert_source', dict(subject=probe.SUBJECT, predicate='height',
            state='value', coverage='object', value=18, unit='m', source_id='design', page=95,
            quote='Left K9023+670-K9023+760 measured 18 m'), 'unauthorized-page')])

    def correct(messages):
        refused = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
        assert refused.status == 'error'
        return AIMessage(content='', tool_calls=[call('assert_source', dict(subject=probe.SUBJECT, predicate='height',
            state='value', coverage='object', value=18, unit='m', source_id='design', page=96,
            quote='Left K9023+670-K9023+760 measured 18 m'), 'authorized-page')])

    driver = Driver(coordinator=[step, correct, AIMessage('Owner comparison pending.')])
    result = await probe.extract(case, driver('coordinator'))
    assert result['stop'] == 'coordinator_final' and result['model_invocations'] == 3
    assert len(result['assertions']) == 1 and result['assertions'][0]['claim']['citation']['page'] == 96
    assert [r['status'] for r in result['tool_attempts']] == ['error', 'success']
    assert {t['name'] for t in driver.bindings['coordinator'][0]} == set(probe.ACTIONS)
    assert json.loads((case/'o6-results.json').read_text())['owner_comparison'] == 'pending'
    with pytest.raises(FileExistsError):
        await probe.extract(case, driver('coordinator'))
    assert len(driver.calls) == 3
