# Revised M4 plan core verification

Tested commit `b23238aed97662642d43d4737b13ec2a22a82c07` on `codex/stage1-m4-plan-core-20261108`. The held M4 candidate and its [original verification record](../stage1-m4/README.md) remain available.

## How plan approval works

The first candidate wrote immutable plan content and a corresponding proof through a single transaction spanning two WAL databases. This was a P1 issue for M4 acceptance because later migrations would copy the pattern. SQLite documents that a host crash can leave such a transaction committed in only one file. [SQLite transaction guarantees](https://sqlite.org/lang_attach.html)

The Coordinator now saves immutable plan content in the case database. A separate assertion transaction publishes a convention referencing its exact type, ID and version. At the owner checkpoint the immutable choices are saved first. The authenticated owner act identifies those choices and targets the exact proposal. The assertion store selects the published proposal and governs approval and withdrawal. Frozen skeletons and text profiles are referenced by version.

This removes the cross-database publication transaction, reverse proof link, split-commit repair and M4-specific hashes for plan content, owner choices, frozen inputs and the grant’s plan binding. The shared content-store checksums and operation IDs retain their existing purposes. Export and checklist generation still check whether the pinned approval is effective.

## Crash, redo and withdrawal

- An interruption after content save leaves an unused version. An exact redo reuses it. A changed request under the same key is refused.
- A late submission of an older version leaves the newer proposal current. A crash after saving the owner's choices leaves the checkpoint pending. After a lost act result, repeating the reply closes the original issue once and preserves a newer pending checkpoint.
- An independent alignment reviewer reproduced two stale-approval paths. A case with a held-format native proposal and earlier legacy pins now refuses to use those pins as current authority. A natively published older artifact also requires live approval on export, even if its envelope predates input pins. Historical immutable content remains readable.
- The Fake03 comparison test reproduced a preparation-seal failure when an empty assertion WAL and shared-memory sidecar disappeared. These transient files no longer alter the seal. A nonempty assertion WAL still changes it.

## Offline results

Of **6,117** collected cases, **6,108 passed** and **9 conditional integrations skipped**. The skip IDs match M3. No cases failed, went missing or ran twice. The timing-sensitive module ran first, then seven groups in parallel. Wall time was 31 minutes 46 seconds. The runner guarded network access and cleared model credentials. There were zero paid calls. [Regression and file digests](regression.json)

An initial 6,117-case run exposed five unlisted reads in the state census and a historical assembly fixture that kept its content outside its simulated database. The final inventory records the reads. The fixture now exercises the shared read path and still checks that its preflight writes nothing. The owner-reply redo test also covers off-plan reductions and changed answers after resolution. No production source changed between these two runs.

The Fake03 replay restored 16 Writer judgments and 16 Reviewer views. A/X32 kept 27 and its question. Current A/X51 stayed unscored pending interpretation. Both slopes retained unscored calculator results with their missing inputs. [Fake03 results](fake03-checkpoint.json)

Suite statement coverage was **90.67%**. Every changed module with an M0 baseline met its floor after including the same-revision read-only fixture identification and two historical import exercises. Each import preserved exact pins across two fresh directories. One case also carried a text profile. [Coverage by module](coverage.json)

| Module | M0 floor | Suite only | Including operator checks |
| --- | ---: | ---: | ---: |
| src/report_agent/fake_verification.py | 83.21% | 82.31% | 87.00% |
| src/report_agent/probe_case.py | 88.64% | 87.16% | 89.19% |

Pyright reported 676 diagnostics with zero added against M3 by module, rule and message. The five dispatcher/runtime files and all three S2 contract files retain their M3 hashes. The implementation uses existing convention and owner act shapes.

The nine IDs retired or reparameterized since the held tag are each mapped to replacement checks, including the four split-WAL cases. Seventeen IDs were added to that collection. [Held M4 to revised M4 test mapping](redo-test-mapping.json) · [M3 to revised M4 mapping](test-migration.json)

Main integrated the change and ran the offline gate. The authority and plan contributors implemented and tested their separate persistence paths. The independent alignment reviewer reproduced and rechecked both historical edge cases. This candidate is ready for owner review. Default-branch promotion requires separate owner confirmation.
