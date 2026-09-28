# Task006: graph knowledge evidence

Updated: 2026-09-27 22:56 +08:00.
Implementer/tester: Rawls (the assigned knowledge worker in this chat).
Scope: knowledge infrastructure and synthetic fixtures only. No engineering source
text, OCR text, credentials or real-material extracts are included here.

## Outcome and lifecycle

The graph component is ready for Main's real-material trunk integration. Neo4j
CRUD, immutable content revisions, provenance, producer/project isolation,
transactional receipts, traversal and real local semantic retrieval were exercised.
This is component evidence within Task006's end-to-end-trunk stage, not acceptance
of the full report workflow, real-material coverage, or engineering sign-off.
Main owns integration and the disposition of this evidence. The reported successful
synthetic report/review/export run belongs to Main's separate runtime evidence.

This increment adds read_many(ids) for explicit adopted-fact version checks without
opening a connection/session per fact. Prior graph behavior remains covered.

## Verified environment

- Dedicated container: report-agent-knowledge006, image neo4j:2026.08.1.
- Bolt: bolt://127.0.0.1:17687. HTTP: 127.0.0.1:17474. Local prototype, auth disabled.
- Data volume: report-agent-knowledge006-data. No legacy Neo4j used or modified.
- Python: 3.12.14 in /home/dysun/.venvs/report-agent-system.
- neo4j==6.3.1, fastembed==0.8.1, onnxruntime==1.30.0.
- Local model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2,
  Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q, 384 dimensions.
- Model revision: faf4aa4225822f3bc6376869cb1164e8e3feedd0.
- ONNX SHA256: 634d0f66c29dc934c8fa72b8a4fe91dd4d420a22f1d82a241058d4316e659a99.
  Download completed and hash verified; the loader also verifies this hash.
- Cache: /home/dysun/.cache/report-agent-system/embeddings. Real vector runs used
  HF_HUB_OFFLINE=1 and CPU inference. No engineering text was sent to an embedding
  provider. No paid model calls were made by this worker.
- Latest SHOW INDEXES: ra_fact, ra_project, ra_receipt, ra_fact_text and
  ra_fact_vector_v1 all ONLINE with populationPercent=100.0.

## API contract

Knowledge(project_id, uri=None, embedding=None, *, producer='knowledge', writable=True)
uses REPORT_GRAPH_URI or the dedicated Bolt default. Identity and write permissions
must be bound by trusted server task context, never by model-provided arguments.
embedding=None uses the lazy local model; embedding=False explicitly disables it.

| Method | Contract |
| --- | --- |
| describe() | Capabilities, identity, embedding metadata and retrieval limitations; no connection needed. |
| put(title, body, source_ids, owner='knowledge', replaces_id='', operation_id='') | New immutable content version, provenance and transaction receipt. Identical operation replay reuses its result; changed payload with the same operation ID rejects. |
| read(id) | Exact version including historical/retracted records. |
| read_many(ids) | List of exact-version dictionaries in input order, preserving duplicates. One UNWIND query in a managed read transaction; no schema initialization or writes. Empty input returns [] without connecting. |
| search(query, mode='hybrid', limit=10, offset=0) | Project-scoped text/vector/hybrid candidates, matches, pagination and explicit coverage. |
| link(source_id, target_id, relation, owner='knowledge') | Same-project endpoints and source producer ownership; transactional deduplication. |
| traverse(id, depth=1, limit=20, offset=0) | Paged explicit relation paths through active, same-project facts. |
| retract(id, owner='knowledge', reason='') | Producer-authorized status change; historical content and receipt retained. |
| receipt(operation_id) | Project-scoped committed operation result for recovery. |
| close() | Release the driver; context-manager use is supported. |

read/read_many expose id, root_id, revision, owner, status, current, replaces_id,
replaced_by, source_ids and provenance. status is active/superseded/retracted;
current is true only for active. Missing replaced_by is normalized to an empty string.
Source references accept strings or {source_id, locator}; source existence and
authorization in the external catalog remain the caller's responsibility.

read_many rejects invalid IDs before connecting. If any requested ID is missing or
belongs to another project, it raises ActionRejected with
KNOWLEDGE_NOT_FOUND_IN_PROJECT and the unmatched input IDs. It returns no partial
batch and does not reveal whether an unmatched ID exists in another project.
Read-only consumers can inspect versions produced by other owners in their project.

For adoption, Main can persist fact ID + revision and re-read status using read_many.
Receipts describe the original write outcome; they are not fresh lifecycle reads.
These reads do not atomically couple Neo4j state to a later SQLite artifact commit.

## Executed checks

Latest complete run after read_many: 30 passed, 0 skipped, 2.95 seconds.

```bash
cd /mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system
env PYTHONPATH=src REPORT_GRAPH_URI=bolt://127.0.0.1:17687 \
  REPORT_GRAPH_TEST_URI=bolt://127.0.0.1:17687 REPORT_TEST_EMBEDDINGS=1 \
  HF_HUB_OFFLINE=1 /home/dysun/.venvs/report-agent-system/bin/python \
  -m pytest tests/test_knowledge.py -q
```

Coverage includes:

- Same-operation deduplication, conflicting-payload rejection, receipt recovery
  with unavailable embeddings, concurrent duplicate writes and transaction rollback.
- Revision history, source locators, current/replaced markers and retraction.
- Cross-project reads, replacement, retraction, link and traversal rejection;
  producer ownership checks and read-only write rejection.
- Native Chinese full-text retrieval, relation traversal and explicit paging.
- Actual 384-dimensional local model output written into Neo4j and searched through
  its vector index; Chinese semantic retrieval and hybrid ranking on synthetic facts.
- A closer foreign-project vector does not displace the authorized result;
  retracted facts are excluded from vector retrieval.
- read_many preserves order, duplicates, provenance and active/superseded/retracted
  states; a read-only reader opens exactly one session, leaves schema uninitialized,
  and rejects mixed valid/missing or valid/foreign batches.
- Empty/invalid batch inputs require no graph connection.

No-service run after read_many: 21 passed, 9 service-dependent tests explicitly
skipped, 0.24 seconds. Prior to this increment the full graph/local-model baseline
was 22 passed, 0 skipped. The original pip check reported no broken requirements;
this increment installed no dependencies.

The real-model smoke script also completed with ok=true, full-text hit, vector top
match, relation traversal and duplicate receipt assertions. Retained synthetic
evidence project: knowledge-check-e7f86ce5-99c9-4b8a-8ca5-555bad92113f.
Fact ID and vector top ID were both b8ecd29c-a29b-49ae-83ec-d64c21cb3823;
relation ID was db07ffad-8ccc-4e26-8909-473e1897d5bb.

```bash
env PYTHONPATH=src REPORT_GRAPH_URI=bolt://127.0.0.1:17687 HF_HUB_OFFLINE=1 \
  /home/dysun/.venvs/report-agent-system/bin/python scripts/check_knowledge.py
```

## Limits and review disposition

- Facts/relations are authoritative only in Neo4j. SQL source-library records and
  report artifacts retain their distinct roles; this worker added no SQL facts.
- The embedding covers at most the first 512 model tokens of title plus body.
  Full fact text remains readable. Long-text semantic coverage is not established.
- Vector ANN is approximate. Vector/hybrid queries use up to 200 candidates per
  mode; result pages cover that pool. Refine queries to discover beyond it.
  Search pages are not snapshots, and no hit is not evidence of absent material.
- Facts without a matching model vector are excluded from vector search; coverage
  counts expose that distinction. There is no automatic backfill of text-only facts.
- Traversal depth is 1-5 and page limit is 1-100. Old-version relations are retained
  historically and are not automatically transferred to replacement facts.
- The test fixtures establish mechanics and a small synthetic semantic-retrieval
  check, not retrieval sufficiency over the nine imported real documents.
- No current confirmed blocker for the isolated graph integration test. The initial
  full-text driver parameter collision was a P2 implementation defect affecting
  text/hybrid lookup, contained to synthetic validation, fixed before handoff and
  covered by the passing regressions. It is not an outstanding stop condition.
- Implementation and self-review were performed by this worker. An independent
  alignment review is not claimed here; Main owns that existing review step and
  overall trunk acceptance. The read_many extension preserves established ownership
  boundaries and adds no agent workflow or runtime approval stage.
