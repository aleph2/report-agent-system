# M7: report provenance

Status: M7 in progress. The optional result-reference vocabulary is implemented and tested; aggregate provenance awaits acknowledgment of the additional C5 finding below. Baseline is accepted M6 `48fabae8606d25bd4ca20df219fc9968f2b07df4`. The first M7 action, a full offline regression of that exact revision, passed 6,150 tests with nine unchanged conditional skips. Automatic cleanup left no passing-case files outside caches. See the [baseline verification record](../verification/stage1-m7-baseline/README.md). Main stays at accepted M6 until M7 is reviewed and accepted.

## Requirement and scope

The approved Stage 1 plan, M7, replaces report receipts with provenance for section text, outcomes and snapshots. The complete M0 census also assigns the current section/object prose selections to M7.

| Family | M7 disposition | Current consumer |
| --- | --- | --- |
| `planned_section_receipt:*` | Migrate | Planned section generation and export validation |
| `assembly_receipt:*` | Migrate | System assembly and its export provenance |
| `commission_outcome:*` | Migrate | Frozen per-object conclusions |
| `g6_section_prose:*` | Migrate active current-report selection | Writer save and current assembly |
| `g6_object_prose:*` | Migrate active current-report selection | Assigned object prose and current assembly |
| `rescue_projection:*` | Keep behind accessors under O4 | Deferred rescue route |

The deferred rescue path's shared planned-section reader follows the migrated accessor. This does not migrate or retire its own rescue-projection family. O4/O5 routes, dispatcher control flow, role prompts, scoring behavior and the section 9a role split remain outside this slice.

## Why an S2 amendment is needed

Current `Derived` records identify their rule and assertion inputs, and can carry a numeric value or an assessment. They cannot identify the immutable case record containing a generated section, outcome or snapshot. `Recommendation` is a Writer's semantic recommendation, not system assembly provenance. Encoding report receipts as conventions would not meet the M7 requirement.

A direct offline shape check on `48fabae` confirms that supplying the proposed reference is refused as `extra_forbidden` at `artifact_ref`. This is a gap between the M7 requirement and the approved vocabulary, not a failing behavior test or permission to change the contract.

Relevant code at the baseline:

- `assertions/schema/kinds.py:147`: existing `Derived` shape.
- `assertions/schema/actions.json`: `derive_result` belongs to the calculator service.
- `risk_scoring.py:603,636`: planned section receipts.
- `system_assembler.py:487,497,578`: outcomes, assembly receipt and export requirement.
- `commission_plan.py:1193,1232`: selected outcomes.
- `section_writing.py:36` and `system_assembler.py:529,533`: prose selection.
- `docs/verification/m0-m1-20261108/census.tsv`: the six families above.

## Proposed dated S2 amendment

Extend the existing `Derived` claim with one optional field:

```text
artifact_ref:
    type: ContentNode | DocumentSnapshot | CommissionOutcome
    id: existing case record ID
    version: existing positive version number
```

Keep the existing `derive_result` action and calculator role. The trusted deterministic assembler records the transformation under its authenticated service identity. This does not add an agent or offer calculator authority to the Writer.

For an artifact derivation:

- The reference names an already committed immutable version in this case. The host supplies and resolves it; it is not an extra LLM argument.
- Numeric `value` and `assessment` are absent or null. Existing numeric derivations remain unchanged.
- Existing inputs/grounds identify the actual plan authority and antecedent assertions. Existing strength checks stay intact: successful assembly does not by itself establish engineering certainty.
- The assertion records provenance only. It does not approve, independently review, release or sign the report.

This moves only the typed case-version reference needed by M7 forward from the section 9a vocabulary sweep. The remaining reference cleanup stays in 9a. It is an additive amendment to `kinds.py`, logged under the existing S2 amendment process; no new schema version, action, role or SQL-check relaxation is proposed. The owner acknowledged this vocabulary addition subject to actual stale-export consumption and assembler attribution; those conditions remain M7 acceptance tests. The additional C5 integration finding below needs a separate check acknowledgment.

Independent alignment reviewer `/root/m6_review` checked the scope and this choice: extending `Derived` is smaller and semantically sound; a separate claim kind/action is unnecessary. This is design review, not implementation verification.

## Implementation plan and integration findings

### Additional C5 integration finding: acknowledgment needed

The owner acknowledged the optional reference with two conditions: an actual staleness/export consumer and the assembler's own producer identity. The field is implemented additively at `99b3d51` and its original serialized numeric shape is unchanged. The dated vocabulary amendment is logged in `s2-amendments.json`.

[Authenticated reproduction and negative control](../verification/stage1-m7-c5/README.md) found a separate, concrete obstacle in `checks.sql` C5: a report artifact for the report subject cannot list inputs belonging to slopes A and B without confirmed cross-subject transfer conventions. The desired artifact test fails with `C5: Cross-subject support needs a current confirmed transfer with matching scope`; the ordinary non-artifact derivation control passes by retaining that refusal. The test uses the real `AssertionHost`/`derive_result` path, not a mocked validator. `/root/m6_review` independently confirmed the cause and ruled out omitting inputs, changing their subjects or inventing owner-confirmed transfer conventions.

Impact: P2, confined to publishing aggregate M7 provenance; it blocks completing M7 aggregation and its staleness test. Accepted main and existing report behavior remain at `48fabae`. No SQL check has been changed. The proposed disposition is a second, dated S2 acknowledgment:

- Only a `derive_result` under the existing calculator capability, with a valid `artifact_ref` and no numeric `value` or `assessment`, may use cross-subject **input lineage** without a transfer convention.
- C5 stays unchanged for numeric derivations, judgments, recommendations, conflicts, and grounds with classification, assumption, adjustment or context purposes.
- C4 still requires the exact issued packet and existing inputs. C10 still limits result strength. The trusted assembler supplies the exact case-version result; no model-facing permission is added.
- Keep every input ID so that actual source/judgment supersession propagates to the artifact and is consumed by export. This exemption records that the report contains both slopes; it does not apply one slope's evidence to the other.

The minimal SQL change is a provenance-only predicate in C5, not a catalog/role change. It will be logged separately in `s2-amendments.json` only after the owner acknowledges it. Tests must prove the aggregate artifact succeeds, stale-input export fails, numeric and judgment transfers still refuse, and non-input grounds are not exempted. The original proposal's expectation that no SQL change was needed is superseded by this reproduced integration finding.

Main owns the M7 application changes, tests and Git operations. No other writing owner is assigned.

1. Preserve immutable report content in the case database. Record the corresponding artifact derivation separately, pointing one way to the content version.
2. Replace the active receipt and selection writers/readers with the existing case-version and assertion actions/queries. Retain read-only historical access and the O4-deferred family.
3. Each completed operation replays by its exact actor, request and bindings. A crash after case content commits leaves unused content, not an approved or exportable result; exact redo records the missing derivation. No joint transaction, backlink, new digest or repair service.
4. Preserve earlier frozen exports and all current required-issue, fixed-text, citation, internal-content and calculator-result checks.
5. Refresh the census and retired-write guard. Any removed storage test names its exact covering behavior test. Do not change behavior expectations to accommodate the migration.

## Verification

Use test-first cases for:

- The artifact reference resolves to the exact node/outcome/snapshot version; numeric results remain compatible.
- Case content alone cannot satisfy the native provenance requirement.
- Crash after content save and crash after provenance save: exact redo completes without duplicate derivations or altered content.
- Current selection follows effective assertion acts, independently of row order. Superseded selections do not replace a frozen snapshot.
- Generated fixed and derived sections, composition order, per-object outcomes and trusted assembly still reach Word and Excel through existing checks.
- Historical read fallback and the deferred rescue route remain available.
- All 25 required issues still map one-to-one between Word comments and Excel rows.
- The recorded Fake03 outcomes, packet equivalence, ranks, gaps, source qualifiers and unscored A/X51 remain intact.
- Dispatcher/protected files remain unchanged; the only S2 change is the acknowledged additive amendment.
- Full offline regression on the final M7 code pin, coverage floors, type-diagnostic comparison, independent review and automatic cleanup.

The opening full regression belongs to `48fabae`; the final M7 regression will belong to the final M7 code pin. They are separate records. No paid/model call is part of M7.

## Remaining human work

The engineering lead is still unnamed. The 11 pilot criteria and HP02 page 115 remain pending engineering review. This does not block the offline storage migration, and M7 will not supply those judgments.

## Skills and evidence limits

Main applied the using-agent-skills phase selection, Git workflow for the fixed baseline and milestone branch, and the TDD workflow's existing full-suite runner. Migration and incremental-implementation guidance were used to separate active consumers from O4-deferred work. Ponytail guided reuse of the existing result/action rather than a new agent or generic receipt framework. The artifact-reference shape and packet boundary were developed with RED/GREEN tests; 209 surrounding checks passed. Full report integration awaits the additional C5 acknowledgment. Independent preparation review by `/root/m6_review` also passed the two provenance tests; it does not establish the pending stale-export consumer.

No relevant existing Graphify graph was found in this checkout or the previously used project locations, and the native environment has neither its package nor CLI. Current source readers and call sites were inspected directly; no graph query, installation or fresh graph build is claimed. Langfuse, prompt design and paid model evaluation are outside this storage-only opening step. The independent alignment review was performed by `/root/m6_review`; it establishes the proposal's scope and semantics, not a completed implementation.
