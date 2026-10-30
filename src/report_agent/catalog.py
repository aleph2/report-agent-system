from __future__ import annotations

from .errors import ActionRejected

import hashlib
import json
from bisect import bisect_right
from uuid import uuid4

from .store import digest, encode


class Catalog:
    """Immutable sources and located text. No semantic merging or inferred facts."""

    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS source_versions (
                    id TEXT PRIMARY KEY, operation TEXT UNIQUE NOT NULL,
                    data TEXT NOT NULL, original BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS source_blocks (
                    source_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    locator TEXT NOT NULL, text TEXT NOT NULL,
                    PRIMARY KEY(source_id, ordinal));
            """)
            for source in store.manifest["sources"]:
                if not db.execute("SELECT 1 FROM source_blocks WHERE source_id=?", (source["id"],)).fetchone():
                    self._blocks(db, source["id"], [{"locator": "manifest text", "text": source["content"]}], idempotent=True)

    @staticmethod
    def _blocks(db, source_id, blocks, *, idempotent=False):
        ordinal = 0
        for block in blocks:
            # All characters remain retrievable; chunk boundaries are not semantic claims.
            for start in range(0, len(block["text"]), 4000):
                text = block["text"][start:start + 4000]
                locator = f'{block["locator"]}; chars {start + 1}-{start + len(text)}'
                values = (source_id, ordinal, locator, text)
                if idempotent:
                    # Only the manifest's initial lazy seed uses this path.
                    # Exact concurrent seeds are safe; a conflict rolls back
                    # this connection's entire initialization transaction.
                    db.execute('INSERT INTO source_blocks VALUES (?, ?, ?, ?) '
                               'ON CONFLICT(source_id, ordinal) DO NOTHING', values)
                    if db.execute('SELECT locator,text FROM source_blocks WHERE source_id=? AND ordinal=?',
                                  (source_id, ordinal)).fetchone() != (locator, text):
                        raise ActionRejected('INITIAL_SOURCE_BLOCK_CONFLICT')
                else:
                    db.execute('INSERT INTO source_blocks VALUES (?, ?, ?, ?)', values)
                ordinal += 1

    def sources(self):
        initial = [{**s, "document_id": s["id"], "replaces_id": "", "limitations": s.get("limitations", [])}
                   for s in self.store.manifest["sources"]]
        with self.store.connect() as db:
            added = [json.loads(r[0]) for r in db.execute("SELECT data FROM source_versions ORDER BY rowid")]
        replaced = {s["replaces_id"] for s in added}
        return [{**s, "current": s["id"] not in replaced} for s in initial + added]

    def metadata(self):
        return [{k: v for k, v in s.items() if k != "content"} for s in self.sources()]

    def import_file(self, filename, data, replaces_id=""):
        from .ingestion import parse_document

        if not filename or any(c in filename for c in ("/", "\\", "\x00")) or filename in {".", ".."}:
            raise ActionRejected("FILENAME_MUST_BE_BASENAME")
        operation = digest({"filename": filename, "sha256": hashlib.sha256(data).hexdigest(), "replaces_id": replaces_id})
        with self.store.run_lock(), self.store.connect() as db:
            old = db.execute("SELECT data FROM source_versions WHERE operation=?", (operation,)).fetchone()
            if old:
                return {"source": {k: v for k, v in json.loads(old[0]).items() if k != "content"}, "reused": True}
            previous = next((s for s in self.sources() if s["id"] == replaces_id), None) if replaces_id else None
            if replaces_id and (previous is None or not previous["current"]):
                raise ActionRejected("REPLACEMENT_REQUIRES_CURRENT_SOURCE")
            parsed = parse_document(filename, data)
            source_id = str(uuid4())
            source = {"id": source_id, "document_id": previous["document_id"] if previous else source_id,
                      "title": parsed["title"], "filename": filename, "replaces_id": replaces_id,
                      "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                      "coverage": parsed["coverage"], "limitations": parsed["limitations"],
                      "content": "\n\n".join(b["text"] for b in parsed["blocks"]),
                      "origin": "operator_upload"}
            db.execute("INSERT INTO source_versions VALUES (?, ?, ?, ?)", (source_id, operation, encode(source), data))
            self._blocks(db, source_id, parsed["blocks"])
            row = db.execute("SELECT value FROM state WHERE key='source_changes'").fetchone()
            changes = json.loads(row[0]) if row else []
            changes.append({"id": str(uuid4()), "source_id": source_id, "replaces_id": replaces_id, "assessment": None})
            db.execute("INSERT OR REPLACE INTO state VALUES ('source_changes', ?)", (encode(changes),))
            db.execute("INSERT INTO events(kind,data) VALUES ('source_imported', ?)",
                       (encode({"source_id": source_id, "replaces_id": replaces_id, "operation": operation}),))
        return {"source": {k: v for k, v in source.items() if k != "content"}, "reused": False}

    def read(self, source_id, offset=0, limit=10):
        source = next((s for s in self.metadata() if s["id"] == source_id), None)
        if source is None:
            raise ActionRejected("SOURCE_NOT_IN_PROJECT")
        self._page(offset, limit)
        with self.store.connect() as db:
            total = db.execute("SELECT count(*) FROM source_blocks WHERE source_id=?", (source_id,)).fetchone()[0]
            rows = db.execute("SELECT ordinal, locator, text FROM source_blocks WHERE source_id=? ORDER BY ordinal LIMIT ? OFFSET ?",
                              (source_id, limit, offset)).fetchall()
        return {"source": source, "blocks": [{"ordinal": i, "locator": loc, "text": txt} for i, loc, txt in rows],
                "total_blocks": total, "offset": offset, "next_offset": offset + len(rows) if offset + len(rows) < total else None,
                "coverage_note": "A page is not proof that the entire source was read."}

    @staticmethod
    def _page(offset, limit):
        if offset < 0 or not 1 <= limit <= 50:
            raise ActionRejected("PAGE_REQUIRES_NONNEGATIVE_OFFSET_AND_LIMIT_1_TO_50")

    def search(self, query, offset=0, limit=10, include_history=False, source_id=None):
        self._page(offset, limit)
        if not query.strip():
            raise ActionRejected("SEARCH_QUERY_REQUIRED")
        sources = self.sources()
        if source_id is not None:
            sources = [s for s in sources if s["id"] == source_id]
            if not sources:
                raise ActionRejected("SOURCE_NOT_IN_PROJECT")
        searched = [s for s in sources if include_history or s["current"]]
        fold = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
        needle = query.translate(fold)
        matches = []
        with self.store.connect() as db:
            for source in searched:
                content = source["content"]
                position = content.translate(fold).find(needle)
                if position < 0:
                    continue
                rows = db.execute("SELECT ordinal,locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal",
                                  (source["id"],)).fetchall()
                starts, cursor = [], 0
                for _, _, text in rows:
                    start = content.find(text, cursor)
                    if start < 0:
                        raise RuntimeError("SOURCE_INDEX_INCONSISTENT")
                    starts.append(start)
                    cursor = start + len(text)
                folded, windows = content.translate(fold), {}
                while position >= 0 and rows:
                    first = max(0, bisect_right(starts, position) - 1)
                    last = max(first, bisect_right(starts, position + len(query) - 1) - 1)
                    windows[first] = max(last, windows.get(first, first))
                    position = folded.find(needle, position + len(query))
                for first, last in windows.items():
                    matches.append({"source_id": source["id"], "ordinal": rows[first][0],
                        "ordinals": [r[0] for r in rows[first:last + 1]],
                        "locators": [r[1] for r in rows[first:last + 1]],
                        "locator": rows[first][1] if first == last else rows[first][1] + " through " + rows[last][1],
                        "text": content[starts[first]:starts[last] + len(rows[last][2])]})
        page, total = matches[offset:offset + limit], len(matches)
        return {"matches": page,
                "scope": {"source_id": source_id, "include_history": include_history,
                          "searched_source_ids": [s["id"] for s in searched]},
                "total": total, "offset": offset, "next_offset": offset + len(page) if offset + len(page) < total else None,
                "method": "literal substring, ASCII case-insensitive; no synonym inference",
                "count_unit": "distinct starting blocks, with continuation blocks when a match crosses a boundary",
                "coverage_note": "No match does not establish missing information. Try other terms or read the source."}
