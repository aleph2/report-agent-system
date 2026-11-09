# Historical M7 C5 investigation — superseded

The owner resolved this investigation on 2026-11-09 by keeping S2/C5 unchanged and storing operational generation data in immutable case records. There is **no pending C5 acknowledgment**. The artifact_ref proposal was withdrawn, not granted an exception. See the [current M7 design](../../reviews/stage1-m7-report-provenance.md).

The material below records the abandoned approach at commit `0c5781a`. Its executable reproduction applies only to that historical code pin, on a copy; it is not a current test or acceptance gate. Earlier logs and commits are preserved.

---

# M7 aggregate lineage: C5 acknowledgment gate

The owner acknowledged the optional `Derived.artifact_ref` with two conditions: an actual stale-export consumer and explicit assembler attribution. The typed field is implemented at `99b3d51`; existing serialized numeric records and schema versions are unchanged. M7 is not complete, and main remains `48fabae`.

## Reproduction

The [small executable reproduction](test_aggregate_gate.py) uses the production `AssertionHost`, authenticated grants and existing actions. It saves two source observations under subjects A and B, then asks the assembler service to record their inclusion in a report artifact. Every input and the exact artifact reference are in its host-issued packet. No model call, real project source or production case is involved.

Run from the repository root:

```sh
/home/dysun/.venvs/report-agent-system-native/bin/python -B tests/support/run_offline_tests.py -q -c pyproject.toml docs/verification/stage1-m7-c5/test_aggregate_gate.py
```

Current expected diagnostic result: **one failure and one passing negative control**.

[Recorded results](results.json)

- The desired nonnumeric artifact lineage fails with `C5: Cross-subject support needs a current confirmed transfer with matching scope`.
- The ordinary derivation without `artifact_ref` still correctly refuses the same transfer.

The reproduction isolates the action contract; the complete case-record/export integration is not claimed to exist yet. The direct cause is `support_refs` and the cross-subject Ground clause in `checks.sql`: both classify all derivation inputs as evidentiary transfer. This is correct for applying another slope's evidence, but does not distinguish a report's inclusion of both slopes. Independent reviewer `/root/m6_review` checked this finding and the minimal change described below.

## Impact and proposed disposition

P2, confined to the unpromoted M7 integration. It blocks publishing aggregate artifact provenance and proving the required stale-export behavior. Main and the original G5 records are unaffected. Omitting the upstream IDs would lose staleness; changing their subjects or manufacturing confirmed transfer conventions would change their meaning. Those alternatives are not used.

The requested additional S2 amendment is limited to input-lineage edges for `kind=derived`, the existing calculator capability/action, a valid typed `artifact_ref`, and no numeric `value` or `assessment`. Numeric derivations, every judgment and recommendation, conflicts, and grounds for classification, assumption, adjustment or context retain their C5 checks. C4 packet membership and C10 strength rules remain enforced. The assembler remains the producer; the calculator label is only its permission role.

No SQL check or action catalog has been changed. The check amendment will be logged separately in `s2-amendments.json` after owner acknowledgment, followed by positive aggregate, negative numeric/judgment/non-input-ground, and stale-export tests.

## Completed preparation and remaining work

The new reference is covered by existing C4: its exact canonical case-version reference must be in the host packet, and packet-restricted reads redact an unoffered artifact pointer. A test first reproduced acceptance of an unissued pointer, then passed with the packet check. This P2 new-field binding defect was contained on the M7 branch and fixed before promotion; no new authority is added.

The surrounding assertion/S2/M6/separation regression passed 209 tests. Independent preparation review by `/root/m6_review` found no blocking permission issue and independently passed the two provenance tests in 0.21 seconds. It corrected a P3 evidence label: the C5 control is an ordinary unscored derivation, not a numeric result. The public test name and wording now reflect that; actual numeric and judgment controls remain required after the additional check amendment. No completed M7 or stale-export claim follows from these preparation tests.

The planned-section migration patch and its missing-generation RED test are preserved as work in progress. Incomplete bridge imports have been parked until the action contract is settled; no partial exporter integration has been shipped. Remaining work is the immutable-case/provenance integration for the active families, the assembler identity and actual stale-export consumer, behavior-preserving regression checks, then the final full-suite run and M7 review tag. The M4/M5 JSON references stay on the 9a list. Engineering review still needs a named lead.
