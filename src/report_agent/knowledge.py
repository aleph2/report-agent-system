"""Project-scoped Neo4j facts, immutable revisions, relations and write receipts.

The application binds project_id, producer and writable from trusted task context;
these constructor settings must never be exposed as agent-controlled arguments.
Catalog source IDs/locators are validated by the caller. No SQL facts are created.
Requires Neo4j 2026.02+ (filtered vector SEARCH) and the official Python driver.
"""

from __future__ import annotations

import json
import math
import os
import re

from .embeddings import LocalEmbedding
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

    embedding=None uses lazy LocalEmbedding; False explicitly disables vectors.
    An injected provider implements model_id, dimensions, embed_documents/query.
    """

    def __init__(self, project_id: str, uri: str | None = None, embedding=None,
                 *, producer: str = "knowledge", writable: bool = True):
        self.project_id = _text(project_id, "project_id")
        self.producer = _text(producer, "producer")
        self.writable = writable
        self.uri = uri or os.environ.get("REPORT_GRAPH_URI", "bolt://127.0.0.1:17687")
        self.embedding = LocalEmbedding() if embedding is None else embedding
        self._driver = None
        self._schema_ready = False
        self._vector_ready = False
        self._vector_index = "ra_fact_vector_v1"

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
                    "CREATE FULLTEXT INDEX ra_fact_text IF NOT EXISTS FOR (n:RAFact) ON EACH [n.title,n.body] OPTIONS {indexConfig: {`fulltext.analyzer`: 'cjk'}}",
                ):
                    session.run(query).consume()
                session.run("CALL db.awaitIndex('ra_fact_text', 30)").consume()
                self._schema_ready = True
            if vector and not self._vector_ready:
                session.run(
                    f"CYPHER 25 CREATE VECTOR INDEX {self._vector_index} IF NOT EXISTS "
                    "FOR (n:RAFact) ON n.embedding WITH [n.project_id,n.status,n.embedding_model] "
                    "OPTIONS {indexConfig: {`vector.similarity_function`: 'cosine'}}",
                ).consume()
                session.run("CALL db.awaitIndex($name, 30)", name=self._vector_index).consume()
                self._vector_ready = True

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
            "embedding": self.embedding.describe() if hasattr(self.embedding, "describe") else
                {"model_id": self.embedding.model_id, "dimensions": self.embedding.dimensions} if self.embedding else None,
            "source_references": "Strings or {source_id, locator}; caller validates catalog existence and project access.",
            "search_modes": ["text", "vector", "hybrid"], "max_limit": 100, "max_traversal_depth": 5,
            "coverage_note": "Search returns candidates, not source completeness. No hit does not prove absent evidence. "
                "Vector ANN is approximate. Vector/hybrid pages cover a fixed pool of up to 200 candidates per mode; "
                "refine the query to discover beyond that pool. Hybrid uses reciprocal-rank fusion. "
                "Offset pages are not snapshots. Facts without a matching model vector are excluded from vector search.",
            "history": "read(id) and read_many(ids) include superseded/retracted content; search and traversal return active versions only.",
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

    def _vector(self, text, query=False):
        if not self.embedding:
            raise ActionRejected("EMBEDDING_DISABLED_USE_TEXT_MODE")
        raw = self.embedding.embed_query(text) if query else self.embedding.embed_documents([text])[0]
        vector = [float(v) for v in raw]
        if len(vector) != self.embedding.dimensions or not all(math.isfinite(v) for v in vector) or not any(vector):
            raise ActionRejected("INVALID_EMBEDDING_VECTOR")
        return vector


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


    def _text_hits(self, query, take):
        # Treat user text as literal words, never as executable Lucene query syntax.
        terms = re.findall(r"\w+", query, flags=re.UNICODE)
        if not terms:
            return []
        lucene = " OR ".join('"' + t + '"' for t in terms)
        return self._rows(
            "CALL db.index.fulltext.queryNodes('ra_fact_text',$query) YIELD node,score "
            "WHERE node.project_id=$project AND node.status='active' "
            "RETURN node AS n,score ORDER BY score DESC,node.id LIMIT $take", query=lucene, take=take)

    def _vector_hits(self, query, take):
        vector = self._vector(query, query=True)
        self._schema(vector=True)
        return self._rows(
            f"CYPHER 25 MATCH (n:RAFact) SEARCH n IN (VECTOR INDEX {self._vector_index} FOR $vector "
            "WHERE n.project_id=$project AND n.status='active' AND n.embedding_model=$model LIMIT $take) SCORE AS score "
            "RETURN n,score ORDER BY score DESC,n.id",
            vector=vector, model=self.embedding.model_id, take=take)

    def search(self, query, mode="hybrid", limit=10, offset=0):
        _text(query, "query")
        _page(limit, offset)
        if mode not in {"text", "vector", "hybrid"}:
            raise ActionRejected("INVALID_SEARCH_MODE")
        self._schema()
        # Keep the fusion window fixed across pages so ranks do not shift with offset.
        take = 200 if mode in {"vector", "hybrid"} else offset + limit + 1
        groups = []
        if mode in {"text", "hybrid"}:
            groups.append(("text", self._text_hits(query, take)))
        if mode in {"vector", "hybrid"}:
            groups.append(("vector", self._vector_hits(query, take)))
        hits = {}
        for kind, rows in groups:
            for rank, row in enumerate(rows, 1):
                fact = _fact(row["n"])
                hit = hits.setdefault(fact["id"], {**fact, "score": 0.0, "scores": {}})
                hit["scores"][kind] = row["score"]
                hit["score"] += 1 / (60 + rank) if mode == "hybrid" else row["score"]
        ordered = sorted(hits.values(), key=lambda x: (-x["score"], x["id"]))
        matches = ordered[offset:offset + limit]
        more = len(ordered) > offset + limit
        coverage = self._rows(
            "MATCH (n:RAFact {project_id:$project,status:'active'}) "
            "RETURN count(n) AS active_facts, sum(CASE WHEN n.embedding IS NOT NULL AND "
            "n.embedding_model=$model THEN 1 ELSE 0 END) AS matching_model_vectors",
            model=self.embedding.model_id if self.embedding else "")[0]
        return {"matches": matches, "project_id": self.project_id, "mode": mode, "limit": limit,
                "offset": offset, "next_offset": offset + limit if more else None,
                "has_more": more, "total": None, "candidate_limit_per_mode": take,
                "candidate_counts": {kind: len(rows) for kind, rows in groups},
                "coverage": coverage,
                "coverage_note": self.describe()["coverage_note"],
                "embedding_coverage": getattr(self.embedding, "coverage_note", "Provider-defined") if mode != "text" else None}

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
