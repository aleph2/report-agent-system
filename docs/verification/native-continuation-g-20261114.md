# Tag g: authority-admitted native child continuation

Product source **+40/-60** in two modules; existing tests **+61/-46**;
test-support rehearsal driver **+174/-0**. No net increase in test cases;
existing cases are updated/replaced in place for the new admission contract.
Added: derived admission for exact pinned-root children and single-use identity
checks. Removed: unused local-SQLite permit, diagnostic hash/error-string/node
allowlist and its unused imports. No new compatibility/fallback path, executor,
store, dependency, retry, model/cap change, hold release or generic guard waiver.

Base: `3556838e6e52a1498e8658adc907eaa98a186255` (f).
Frozen implementation: `307e85e3b82671cf85580c69f9d3afe75e7983a4`.
The only production files changed are `run_authority.py` and
`supervision_plugins.py`. Admission is computed after final preflight inside the
existing run lock; authority JSON cannot supply it. The duplicate guard still
requires the reserved actor/task/call/request digest, native report thread,
original namespace/head, exact parent map/root and role. Consumption occurs once
after the awaited head read. Outside an admitted continuation, refusal remains.
Existing budget, preserved-hold, source/provenance and task-assignment gates remain.

| Check | Evidence and limit |
| --- | --- |
| Focused existing cases | 30 passed / 0 failed in one combined run (46.60s); strengthened authority-context and frozen-fixture-path reruns each 1 passed, overlapping those 30. Initial race RED1 and setup 29P/1F remain retained. |
| Authority context | Actual authorized-run case rejects forged JSON admission, observes derived context only for continuation, and verifies reset after exit. |
| Current root rehearsal | Actual case/profile/absolute path on isolated whole-grant copy; exact original prose child reaches first model request for sections 2/4. Actual offered section-prose contract and recorded exact disposition feedback are asserted present. Single-use original namespace/head is asserted. |
| Assessment rehearsal | Separate fresh actual-case copy; two explicitly scripted native decisions use public resume_task_scope and assess_assigned_object, through real guards. Existing business task reaches inner X21; exact X11/X12 receipt rows are unchanged. Old assessment namespace is retained. This proves route availability, not what a model will choose. |
| No-call/live integrity | Fail-loud stub before provider send; external network disabled in a separate user/mount/network namespace. Whole copied grant directory is privately bound at the original absolute path. Both profiles stay review-interfaces-v4/native-tool-runtime-v1. All 2,061 original file hashes match before/after; Neo independently rehashed them. Zero paid calls. The sentinel intentionally ends only the copied graph. |
| Native invariants | Existing tests cover changed call/task/digest/state, missing/wrong child, wrong root/role, head drift, outside admission and two concurrent consumers. Error type/node no longer decide admission. |
| Full regression | **6,299 passed / 0 failed / 9 unchanged skips**, 6,308 unique, 31m7.4s. All 1,387 frozen-file hashes and nine coverage floors pass; temporary copies/databases cleaned. [Complete result](native-continuation-g-full-20261114.json). |
| Review | Neo independently approved core, both rehearsals and terminal full: raw shard recount, nine exact skips, coverage floors and fixture/source integrity. Final tag/SHA requires Claude's written review before any paid preflight/run. |

Private raw requests, case identities, authorities and proofs stay local under
`.private/continuation-guard-g-20261114/`; full evidence under
`.private/continuation-guard-g-full-20261114/full/`. Earlier rehearsal setup
failures are retained (Path constructor; scripted response missing adapter message
ID). Neither required another product change. Original f full remains failed and
is not relabeled. Source search fallback was used because no Graphify index or
executable was available; no live Langfuse evaluation was claimed.

The [complete source-only guard candidate list](native-continuation-g-sweep-20261114.md)
and [public rehearsal outputs](native-continuation-g-rehearsal-20261114.json)
are retained alongside this record. Only the reproduced native duplicate-admission blocker is repaired here.
Other sequence/mixed candidates remain backlog until reproduced, per scope.

Qualification complete. Next: immutable g tag/push and TAG READY
package, then explicit Claude tag+SHA approval. Paid work is stopped. H is a
separate authorized change and is not built on g before that review.
