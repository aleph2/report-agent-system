"""Exact cold-seed idempotency, without changing OCR/import conflict semantics."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from report_agent.catalog import Catalog
from report_agent.errors import ActionRejected
from test_task_supervision import ws, offline


def rows(ws):
    with ws.store.connect() as db:
        return db.execute('SELECT source_id,ordinal,locator,text FROM source_blocks ORDER BY source_id,ordinal').fetchall()


def test_forced_two_thread_manifest_seed_preserves_three_exact_blocks(ws,monkeypatch):
    text = '甲乙丙丁'*2200+'原文末尾'
    ws.store.set('manifest',{**ws.store.manifest,'sources':[{'id':'s','title':'Original','content':text,'coverage':'complete'}]})
    original = Catalog._blocks
    barrier = Barrier(2)
    calls = []
    def simultaneous(db,source_id,blocks,**kwargs):
        calls.append((source_id,kwargs))
        barrier.wait(timeout=10)
        return original(db,source_id,blocks,**kwargs)
    monkeypatch.setattr(Catalog,'_blocks',staticmethod(simultaneous))
    with ThreadPoolExecutor(max_workers=2) as pool:
        catalogs = list(pool.map(lambda _: Catalog(ws.store),range(2)))
    assert len(catalogs)==2 and calls == [('s',{'idempotent':True})]*2
    values = rows(ws)
    assert [r[1] for r in values] == [0,1,2]
    assert ''.join(r[3] for r in values) == text
    assert values[-1][2] == f'manifest text; chars 8001-{len(text)}'


def test_existing_ocr_rows_are_not_reseeded_or_replaced(ws):
    Catalog(ws.store)
    with ws.store.connect() as db:
        db.execute('DELETE FROM source_blocks WHERE source_id=?',('s',))
        db.execute('INSERT INTO source_blocks VALUES (?,?,?,?)',('s',0,'physical page 139','既有OCR限定原文'))
    before = rows(ws)
    Catalog(ws.store)
    assert rows(ws)==before


def test_regular_block_import_still_rejects_duplicate_key(ws):
    Catalog(ws.store)
    before=rows(ws)
    with pytest.raises(sqlite3.IntegrityError):
        with ws.store.connect() as db:
            Catalog._blocks(db,'s',[{'locator':'manifest text','text':'different text'}])
    assert rows(ws)==before


@pytest.mark.parametrize('earlier_source',[False,True])
def test_later_chunk_conflict_rolls_back_all_new_writes_but_preserves_original(ws,earlier_source):
    Catalog(ws.store)
    with ws.store.connect() as db:
        db.execute('INSERT INTO source_blocks VALUES (?,?,?,?)',('conflict',1,'original location','original text'))
    before=rows(ws)
    with pytest.raises(ActionRejected,match='INITIAL_SOURCE_BLOCK_CONFLICT'):
        with ws.store.connect() as db:
            if earlier_source:
                Catalog._blocks(db,'earlier',[{'locator':'manifest text','text':'other new source'}],idempotent=True)
            Catalog._blocks(db,'conflict',[{'locator':'manifest text','text':'x'*8001}],idempotent=True)
    assert rows(ws)==before


def test_repeated_exact_seed_is_accepted_without_overwriting(ws):
    Catalog(ws.store)
    before=rows(ws)
    with ws.store.connect() as db:
        Catalog._blocks(db,'s',[{'locator':'manifest text','text':ws.store.manifest['sources'][0]['content']}],idempotent=True)
    assert rows(ws)==before
