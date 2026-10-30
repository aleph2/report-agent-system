Commit owned decisions, structure and relations, or adopt exact text-tool payloads.
Substantive ContentNode/Evidence needs text_work_id; payload may be omitted for
adoption. Only a single-line report/chapter heading with claim_kind=structure and
empty qualifiers is a direct structure decision. Do not rewrite table cells,
captions or substantive qualifiers here. Co cannot author ContentNodes.

Criterion needs saved Requirement refs in requirement_refs, plus purpose, scope,
expected_outcome, evidence_expectation and allowed_limits. Source IDs, SourceArtifact
refs and operator instruction IDs are not Requirement refs. Current input_refs are
in read_decision_state; content_status supplies more. Relation needs subject_ref,
predicate, object_ref and provenance_kind; contains also needs position. Same-batch
new refs use {client_key:key}. Ownership, CAS and batch binding remain unchanged.
If operation_id is absent from your exposed schema, the runtime supplies it; do not
invent one. If your interface exposes it, reuse it only with identical arguments;
a corrected known failure needs a new ID. In either interface use actual diagnostics
for representation errors and saved receipts before replaying unknown write effects.