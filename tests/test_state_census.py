"""State census instruments the real SQLite boundary without retaining payloads."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_child_sqlite_writes_are_redacted_and_rolled_back_attempts_are_seen(tmp_path):
    env = dict(os.environ, REPORT_STATE_CENSUS_DIR=str(tmp_path))
    subprocess.run([sys.executable, '-c', """
import sqlite3
db = sqlite3.connect(':memory:')
db.execute('create table state(key text primary key, value text)')
db.execute('insert into state values (?,?)', ('g6_section_prose:private id', 'SECRET'))
db.execute('update state set value=? where key=?', ("where key='spoof'", 'rubric_reviews'))
db.execute("select value from state where key in (?,?)", ('rubric_targets','rubric_status'))
db.execute('delete from state where key=?', ('rubric_status',))
db.rollback()
"""], env=env, check=True)
    raw = ''.join(p.read_text() for p in tmp_path.glob('*.jsonl'))
    assert {tuple(json.loads(line)) for line in raw.splitlines()} >= {
        ('write', 'g6_section_prose:*'), ('write', 'rubric_reviews'), ('delete', 'rubric_status'),
        ('read', 'rubric_targets'), ('read', 'rubric_status')}
    assert 'SECRET' not in raw and 'private' not in raw and 'spoof' not in raw


def _scanner():
    import runpy
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/state_census.py'))


def test_static_census_follows_store_alias_and_grouped_sql(tmp_path):
    scanner = _scanner()
    source = tmp_path / 'alias.py'
    source.write_text("""
def save(workspace, db, suffix):
    backend = workspace.store
    backend.set(key='g6_section_prose:' + suffix, value={})
    lookup = workspace.store.get
    lookup('rubric_status')
    sql = "SELECT value FROM state WHERE key IN ('rubric_reviews', 'rubric_targets')"
    db.execute(sql)
""", encoding='utf-8')
    module = scanner['Module'](source)
    module.row.__globals__['ROOT'] = tmp_path
    facts = {(row[4], row[6]) for row in module.rows({})}
    assert facts == {('write', 'g6_section_prose:*'), ('read', 'rubric_status'),
                     ('read', 'rubric_reviews,rubric_targets')}


def test_state_surface_has_a_reviewed_classification_and_no_new_access_sites():
    import csv
    from collections import Counter
    scanner = _scanner()
    data = scanner['DATA']
    for directory in ('src', 'scripts'):
        for path in (scanner['ROOT'] / directory).rglob('*'):
            if path.suffix in {'.sql', '.js', '.sh'}:
                assert not scanner['STATE'].search(path.read_text(encoding='utf-8')), path
    rows = scanner['census']()
    with (data / 'm0-state-sites.tsv').open(encoding='utf-8') as source:
        recorded = list(csv.reader(source, delimiter='\t'))[1:]
    # Line moves alone do not introduce a dependency. Added call sites, new
    # literal families or changed dynamic operands require a reviewed inventory.
    signature = lambda row: (row[0], *row[2:])
    assert Counter(map(signature, rows)) == Counter(map(signature, recorded))
    with (data / 'm0-state-families.tsv').open(encoding='utf-8') as source:
        catalog = {r['family']:r for r in csv.DictReader(source, delimiter='\t')}
    meta = {'@accessor', '@all', '@helper', '@scan', '@schema'}
    for *_, families in rows:
        assert set(families.split(',')) <= catalog.keys() | meta
    assert all(r['classification'] in {'assertion','mixed','runtime','legacy'}
               and r['disposition'] and r['rationale'] for r in catalog.values())
