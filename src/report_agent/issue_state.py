"""Immutable case issue content and the wait projection consumed by runtime guards."""
from functools import partial
import json
from typing import Any

from . import legacy_state as legacy
from .store import Store, digest, encode


_READERS = {
    'IssueWaits': legacy.get_report_issues,
    'IssueRecord': legacy.get_g6_issue_record,
    'IssueBinding': legacy.get_g6_issue_binding,
    'IssueRoute': legacy.get_g6_issue_route,
}


def _head(db, kind, identity):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='content_heads'").fetchone():
        return None
    row = db.execute('SELECT v.data FROM content_heads h JOIN content_versions v USING(type,id,version) '
                     'WHERE h.type=? AND h.id=?', (kind, identity)).fetchone()
    return json.loads(row[0]) if row else None


def _get(kind, storage, identity, default=None) -> Any:
    if isinstance(storage, Store):
        with storage.connect() as db:
            return _get(kind, db, identity, default)
    record = _head(storage, kind, identity)
    if record:
        return record['payload']
    return (_READERS[kind](storage, default) if kind == 'IssueWaits'
            else _READERS[kind](storage, identity, default))


def _save(kind, storage, identity, value, *, actor=None):
    from .content_store import Actor, ContentStore
    if isinstance(storage, Store):
        with storage.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return _save(kind, db, identity, value, actor=actor)
    ContentStore.ensure_schema(storage)
    previous = _head(storage, kind, identity)
    if previous and previous['payload'] == value:
        return previous['ref']
    ref = previous['ref'] if previous else None
    return ContentStore._insert(storage, actor or Actor('host', 'host', 'issue-projection'), kind, value,
        id=identity, version=ref['version'] + 1 if ref else 1, previous_ref=ref)


def get_wait_projection(storage, default=None) -> Any:
    return _get('IssueWaits', storage, 'human-waits', default)


def get_report_issues(storage, default=None) -> Any:
    from .issue_authority import answers
    rows = get_wait_projection(storage, default)
    signed = answers(storage)
    return [{**row, **signed.get(row.get('id'), {})} for row in rows] if rows is not None else rows


def set_report_issues(storage, value):
    return _save('IssueWaits', storage, 'human-waits', value)


get_g6_issue_record = partial(_get, 'IssueRecord')
set_g6_issue_record = partial(_save, 'IssueRecord')
get_g6_issue_binding = partial(_get, 'IssueBinding')
set_g6_issue_binding = partial(_save, 'IssueBinding')
get_g6_issue_route = partial(_get, 'IssueRoute')
set_g6_issue_route = partial(_save, 'IssueRoute')


def _iter(kind, db):
    historical = (legacy.iter_g6_issue_record_ordered if kind == 'IssueRecord'
                  else legacy.iter_g6_issue_route_ordered)
    rows = dict(historical(db))
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='content_heads'").fetchone():
        for identity, raw in db.execute('SELECT h.id,v.data FROM content_heads h '
                'JOIN content_versions v USING(type,id,version) WHERE h.type=?', (kind,)):
            key = (legacy.issue_record_key(identity) if kind == 'IssueRecord'
                   else legacy.issue_route_key(identity))
            rows[key] = encode(json.loads(raw)['payload'])
    return sorted(rows.items())


iter_g6_issue_record = partial(_iter, 'IssueRecord')
iter_g6_issue_record_ordered = iter_g6_issue_record
iter_g6_issue_route_ordered = partial(_iter, 'IssueRoute')


def issue_view(store):
    """Host-only report issues; report uncertainty does not create runtime human waits."""
    from .assertions.launch import Commission
    with store.connect() as db:
        waits = get_report_issues(db, [])
        material = [json.loads(raw) for _, raw in iter_g6_issue_record(db)]
        rows = [{'id': row['id'], 'kind': 'human_wait', 'record': row, 'report_locations': []}
                for row in waits]
        for proposal in material:
            issue = proposal['issue']
            plan = proposal.get('commission_plan_ref')
            route = get_g6_issue_route(db, digest([plan, issue['id']])) if plan else None
            location = (route or proposal.get('binding') or
                        ({'node_ref': proposal['node_ref']} if proposal.get('node_ref') else None))
            rows.append({'id': issue['id'], 'kind': issue.get('kind', 'material_issue'),
                         'record': proposal, 'report_locations': [location] if location else []})
    for entry in Commission.issue_records(store.root):
        row = entry['record']
        entry.update(id=row['id'], kind=row['claim']['kind'])
        entry['report_locations'] = ([{'object_id': row['subject']}]
                                     if row['claim']['kind'] == 'judgment' else [])
        rows.append(entry)
    by_id = {entry['id']: entry for entry in rows}
    subjects = {}
    for entry in rows:
        for location in entry['report_locations']:
            if location.get('object_id'):
                found = subjects.setdefault(location['object_id'], [])
                if location not in found:
                    found.append(location)
    for entry in rows:
        claim = entry['record'].get('claim', {})
        if claim.get('kind') == 'finding':
            target = by_id.get(claim['target'])
            if target:
                entry['report_locations'] = target['report_locations']
        if not entry['report_locations'] and claim.get('kind') in {'question', 'conflict', 'finding'}:
            entry['report_locations'] = subjects.get(entry['record']['subject'], [])
    return rows
