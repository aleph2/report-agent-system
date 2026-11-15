"""Project-scoped Neo4j facts, immutable revisions, relations and write receipts.

The application binds project_id, producer and writable from trusted task context;
these constructor settings must never be exposed as agent-controlled arguments.
Catalog source IDs/locators are validated by the caller. No SQL facts are created.
"""

from __future__ import annotations

import json
import os

from .errors import ActionForbidden, ActionRejected


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value, field, *, empty=False):
    if not isinstance(value, str) or "\x00" in value or (not empty and not value.strip()):
        raise ActionRejected(f"INVALID_{field.upper()}")
    return value


def _page(limit, offset):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ActionRejected("LIMIT_MUST_BE_1_TO_100")
    if type(offset) is not int or offset < 0:
        raise ActionRejected("OFFSET_MUST_BE_NONNEGATIVE")


def _fact(node):
    data = dict(node)
    data.pop("embedding", None)
    data["provenance"] = json.loads(data.pop("provenance_json", "[]"))
    data["current"] = data.get("status") == "active"
    data.setdefault("replaced_by", "")
    return data


class Knowledge:
    """No connection or embedding load until an operation needs it.

    """

    def __init__(self, project_id: str, uri: str | None = None, embedding=None,
                 *, producer: str = "knowledge", writable: bool = True):
        self.project_id = _text(project_id, "project_id")
        self.producer = _text(producer, "producer")
        self.writable = writable
        self.uri = uri or os.environ.get("REPORT_GRAPH_URI", "bolt://127.0.0.1:17687")
        self._driver = None
        self._schema_ready = False

    @property
    def driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                self.uri, auth=None, connection_timeout=5, max_transaction_retry_time=5,
            )
        return self._driver

    def close(self):
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _schema(self, vector=False):
        with self.driver.session(database="neo4j") as session:
            if not self._schema_ready:
                for query in (
                    "CREATE CONSTRAINT ra_project IF NOT EXISTS FOR (p:RAProject) REQUIRE p.id IS UNIQUE",
                    "CREATE CONSTRAINT ra_fact IF NOT EXISTS FOR (n:RAFact) REQUIRE (n.project_id,n.id) IS UNIQUE",
                    "CREATE CONSTRAINT ra_receipt IF NOT EXISTS FOR (r:RAReceipt) REQUIRE (r.project_id,r.operation_id) IS UNIQUE",
                ):
                    session.run(query).consume()
                self._schema_ready = True

    def _rows(self, cypher, **params):
        with self.driver.session(database="neo4j") as session:
            return session.execute_read(lambda tx: tx.run(cypher, {"project": self.project_id, **params}).data())

    def _authorize(self, owner):
        if not self.writable or owner != self.producer:
            raise ActionForbidden("KNOWLEDGE_PRODUCER_PERMISSION_DENIED")

    def _provenance(self, values):
        if not isinstance(values, (list, tuple)):
            raise ActionRejected("SOURCE_IDS_MUST_BE_A_LIST")
        refs = []
        for item in values:
            if isinstance(item, str):
                item = {"source_id": item, "locator": ""}
            if not isinstance(item, dict) or set(item) - {"source_id", "id", "locator", "project_id"}:
                raise ActionRejected("INVALID_SOURCE_REFERENCE")
            if item.get("project_id", self.project_id) != self.project_id:
                raise ActionForbidden("SOURCE_REFERENCE_PROJECT_MISMATCH")
            if "source_id" in item and "id" in item and item["source_id"] != item["id"]:
                raise ActionRejected("AMBIGUOUS_SOURCE_REFERENCE")
            refs.append({"source_id": _text(item.get("source_id", item.get("id")), "source_id"),
                         "locator": _text(item.get("locator", ""), "locator", empty=True)})
        return refs

    def describe(self):
        return {
            "project_id": self.project_id, "producer": self.producer, "writable": self.writable,
            "authority": "Neo4j owns facts and relations; catalog sources and report artifacts remain external.",
            "source_references": "Strings or {source_id, locator}; caller validates catalog existence and project access.",
        }

    def receipt(self, operation_id):
        _text(operation_id, "operation_id")
        self._schema()
        rows = self._rows("MATCH (r:RAReceipt {project_id:$project,operation_id:$operation}) RETURN r.result AS result",
                          operation=operation_id)
        return json.loads(rows[0]["result"]) if rows else None


    def _get(self, tx, id, owner=None, active=False):
        row = tx.run("MATCH (n:RAFact {project_id:$project,id:$id}) RETURN n",
                     project=self.project_id, id=id).single()
        if not row:
            raise ActionRejected("KNOWLEDGE_NOT_FOUND_IN_PROJECT")
        fact = _fact(row["n"])
        if owner is not None and fact["owner"] != owner:
            raise ActionForbidden("KNOWLEDGE_OWNED_BY_ANOTHER_PRODUCER")
        if active and fact["status"] != "active":
            raise ActionRejected("KNOWLEDGE_REQUIRES_ACTIVE_VERSION")
        return fact


    def read(self, id):
        _text(id, "id")
        self._schema()
        with self.driver.session(database="neo4j") as session:
            return session.execute_read(lambda tx: self._get(tx, id))

    def read_many(self, ids: list[str]) -> list[dict]:
        """Read exact versions in one query; preserve input order and duplicates.

        Any missing or foreign-project ID rejects the whole batch. Empty input
        returns [] without connecting. No schema initialization or writes occur.
        """
        if not isinstance(ids, (list, tuple)):
            raise ActionRejected("KNOWLEDGE_IDS_MUST_BE_A_LIST")
        requested = [_text(id, "id") for id in ids]
        if not requested:
            return []
        rows = self._rows(
            "UNWIND $ids AS id OPTIONAL MATCH (n:RAFact {project_id:$project,id:id}) RETURN id,n",
            ids=list(dict.fromkeys(requested)))
        nodes = {row["id"]: row["n"] for row in rows}
        missing = [id for id in dict.fromkeys(requested) if nodes.get(id) is None]
        if missing:
            raise ActionRejected("KNOWLEDGE_NOT_FOUND_IN_PROJECT: " + _json(missing))
        return [_fact(nodes[id]) for id in requested]


    def traverse(self, id, depth=1, limit=20, offset=0):
        _text(id, "id")
        _page(limit, offset)
        if type(depth) is not int or not 1 <= depth <= 5:
            raise ActionRejected("DEPTH_MUST_BE_1_TO_5")
        self.read(id)
        rows = self._rows(
            f"MATCH path=(a:RAFact {{project_id:$project,id:$id}})-[:RA_RELATES*1..{depth}]-(b:RAFact) "
            "WHERE all(n IN nodes(path) WHERE n.project_id=$project AND n.status='active') "
            "AND all(r IN relationships(path) WHERE r.project_id=$project) "
            "WITH path,b ORDER BY length(path),b.id,[r IN relationships(path) | r.id] "
            "SKIP $offset LIMIT $take RETURN nodes(path) AS nodes,[r IN relationships(path) | properties(r)] AS relations",
            id=id, offset=offset, take=limit + 1)
        paths = [{"nodes": [_fact(n) for n in row["nodes"]], "relations": row["relations"]} for row in rows[:limit]]
        return {"paths": paths, "project_id": self.project_id, "depth": depth, "limit": limit, "offset": offset,
                "next_offset": offset + limit if len(rows) > limit else None, "has_more": len(rows) > limit,
                "coverage_note": "Undirected explicit relation paths through active versions, paged within requested depth. "
                    "Deeper paths and historical versions are excluded; no completeness claim. Pages are not snapshots."}
