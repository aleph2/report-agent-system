"""Opt-in offline census of attempted SQLite state operations, including rollback."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

TABLE = re.compile(r'\b(?:from|into|update|join)\s+(?:main\.)?["\x60\[]?state\b', re.I)
INSERT = re.compile(r"\binto\s+state\s*(?:\(\s*key\s*,\s*value\s*\))?\s*values\s*\(\s*'((?:''|[^'])*)'", re.I)
END_KEY = re.compile(r"\b(?:where|and)\s+key\s*=\s*'((?:''|[^'])*)'\s*;?\s*$", re.I)
READ_KEY = re.compile(r"\bkey\s*(?:=|like\b|glob\b)\s*'((?:''|[^'])*)'", re.I)


def family(key):
    prefix, sep, _ = key.partition(':')
    if re.fullmatch('[a-z][a-z0-9_]{0,90}', prefix):
        return prefix + (':*' if sep else '')
    return '<opaque:' + hashlib.sha256(prefix.encode()).hexdigest()[:12] + '>'


def observations(sql):
    head = sql.lstrip()[:1024]
    if not TABLE.search(head):
        return
    verb = head.split(None, 1)[0].lower()
    if verb in ('insert', 'replace'):
        match = INSERT.search(head)
        yield 'write', family(match[1]) if match else '<unresolved>'
    elif verb in ('update', 'delete'):
        match = END_KEY.search(sql[-1024:])
        yield ('write' if verb == 'update' else 'delete'), family(match[1]) if match else '<unresolved>'
    elif verb == 'select':
        keys = READ_KEY.findall(head)
        for group in re.findall(r"\bkey\s+IN\s*\(([^)]+)\)", head, re.I):
            keys.extend(re.findall("'((?:''|[^'])*)'", group))
        if not keys:
            yield 'read', '<scan>'
        for key in keys:
            yield 'read', key if key == 'operator_%' else family(key)
    else:
        yield 'other', '<unresolved>'


def install(directory):
    # Fail at startup if the evidence path is unusable. SQLite suppresses callback errors.
    seen = set()
    path = Path(directory)
    (path / f'{os.getpid()}.jsonl').touch()

    def trace(sql):
        for row in observations(sql):
            if row in seen:
                continue
            with (path / f'{os.getpid()}.jsonl').open('a', encoding='utf-8') as out:
                out.write(json.dumps(row) + '\n')
            seen.add(row)

    original = sqlite3.connect

    def connect(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(trace)
        return db

    sqlite3.connect = sqlite3.dbapi2.connect = connect
