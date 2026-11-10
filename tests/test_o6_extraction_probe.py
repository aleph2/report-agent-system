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
    quote = 'Synthetic slope A, chainage K8+100-K8+180, measured 23 m'
    for key, numbers in {'design': (3, 5), 'survey': (2,)}.items():
        pages = [f'Outside scope {p}' for p in range(1, max(numbers) + 1)]
        for p in numbers:
            pages[p-1] = f'Selected {key} {p}'
        if key == 'design':
            pages[2] = quote
        raw = pdf_bytes(pages)
        file = key + '.pdf'
        (library / file).write_bytes(raw)
        docs[key] = (file, sha256(raw).hexdigest(), numbers)
    scope = dict(subject='SYNTHETIC-SLOPE-A', documents=docs, goal='Extract synthetic A only.',
                 citation=dict(source_id='design', locator='page 3', quote=quote))
    case = tmp_path / 'o6'
    inputs = probe.prepare(library, case, scope)
    assert inputs['documents']['survey']['original_pages'] == [2]

    driver = Driver(coordinator=[])
    with pytest.raises(ValueError, match='O6_UNEXPECTED_ACTION_SCOPE'):
        await probe.extract(case, driver('coordinator'), scope)
    assert not driver.calls
    with pytest.raises(ValueError, match='O6_INPUT_SCOPE_CHANGED'):
        await probe.extract(case, driver('coordinator'), {**scope, 'subject': 'SYNTHETIC-OTHER'})
    assert not driver.calls
