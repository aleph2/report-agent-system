# S1 assertion store proof

On 2026-11-07 the offline test runner passed **31 tests in 42.03 seconds**. The run comprised 30 S1 cases and the existing native Writer/Reviewer replay. O1 selected SQLite and Pydantic directly. This evidence addresses behavior on that stack. It provides no comparison with an RDF store. The S1 adapter is isolated in [tests/assertions/sqlite_probe.py](../../tests/assertions/sqlite_probe.py). The production action layer belongs to S3, after owner review of S2.

## Reproduce

Use the repository's native environment and offline guard.

```sh
python -B tests/support/run_offline_tests.py -q tests/assertions tests/test_run06_claim_replay.py --tb=short
```

Measured environment: Python 3.12.14, SQLite 3.53.4, Pydantic 2.13.5. Each commission gets its own temporary database. The connection test reads back journal mode `wal`, busy timeout 5,000 ms, `synchronous=2` (FULL) and enabled foreign keys. Each action uses one `BEGIN IMMEDIATE` transaction for lookup, producer check, judgment, audit and operation result. The read-only view opens a separate connection. The tests use synthetic data, local processes, and a scripted model for the existing native replay.

## Historical outcomes

The oracle is the [recorded replay](fake03-claim-validation-offline.md) at `53ee2d0`. The proof reads the frozen business inputs and existing claim annotations. It invokes native Pydantic step validation and claim checks within the S1 transaction. A separate read-only SQLite connection verifies what persisted. The existing native replay exercises the actual Writer tools and the assigned Reviewer's frozen view on the current policy. For the four refused original submissions, that native replay submits a separate, explicitly scripted gap afterwards.

| Original row | Proposed action and observed result |
|---|---|
| A/X32 | Committed the provisional assumption and its value 27. The Reviewer can see the original question and `QUESTION_EFFECT_CONFLICT`. |
| A/X42 | Refused. The cited facts do not establish facility presence or distances. No original judgment was visible to the Reviewer. |
| A/X51, historical | Committed the supported moderate grade at 37. The Reviewer sees the refused adjustment, the proposed 49 and its original rationale. |
| A/X52 | Refused. The cited facts do not establish coverage of A's design drawings. |
| B/X32 | Refused. No applicable observation establishes event frequency at B. |
| B/X51 | Refused. A's survey coverage cannot establish B's investigation counts. |

All four refusals persisted the original operation result and the `save_gap` recovery hint. None acquired the producer binding or wrote a partial judgment/audit. Ten controls retained their original kind, grade, value, rationale, question, missing field, basis kind and plausible grades in the read-only view: A/X21, A/X22, A/X23, A/X41, B/X21, B/X22, B/X23, B/X41, B/X42 and B/X52. Normal semantic-review flags on gaps remain visible.

**Current A/X51 is a separate case.** The owner deferred the guideline interpretation to engineering. The proof refuses the scored proposal and then saves an unscored gap in a fresh operation. Both conditional grades, low and moderate, remain in the review record. The native replay separately confirms the effective unscored gap under the real save path. This case does not replace the historical 49-to-37 replay.

## Atomicity, ownership and recovery

| Experiment | Observation |
|---|---|
| Kill the Python child after the judgment insert and before the audit insert | Child exited with the injected code 73. Reopening the database found zero judgments, audits, results or producer bindings. A subsequent save committed one of each. |
| Start two submissions of the same operation at a barrier, with independent connections | Both received the same committed judgment ID and recorded result. Exactly one judgment and one audit persisted. |
| Give two Writers separate valid packets for the same plan and slope | After one claimed the slope, the other received `PRODUCER_CONFLICT`. A different test denied a Writer whose packet omitted the slope with `PACKET_SCOPE`. |
| Kill the child after commit and before return | The persisted result survived process exit. After the saved judgment was superseded and the assignment became ineligible, an exact repeat returned the original result while read access remained valid. A separate revocation test denied receipt retrieval after read access was revoked. The other action on the same task had no result and had to pass the current eligibility check before saving. |
| Reuse the same operation ID with a different actor, task, attempt, plan, frozen snapshot or payload | Each variant received `OPERATION_CONFLICT`. Record counts stayed at one successful operation. |

The S1 tests add test-local code only. This slice deleted or rewrote zero existing tests. Full-suite, migration, coverage and tag-wide measurements are recorded with M0. S1 demonstrates the feasibility of the transaction contract. S3 must repeat these cases against the production actions and queries before claiming production equivalence.
