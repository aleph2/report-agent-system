# Stage 1 / 9a part c — review candidate

**Source: +103 / −50, net +53 lines. Explicit raise/assert expressions: 3 added / 3 removed (includes the scope-error replacement). One new historical lookup fallback; no new legacy workflow.** This is not a code-size reduction: removing live hash dependencies while preserving completed details, accepted archives and cold-copy facts costs a small net addition. Verification-only tooling/tables are reported separately in the [details](../verification/stage1-9a-c/README.md).

## Changes and their readers

| Files | Requirement and resulting reader |
| --- | --- |
| `qualitative_review.py`, `operation_identity.py` | Host binds native operation ID and assigned frozen row. SDK Reviewer supplies only indicator/finding; exact redo, conflicts and frozen-view refusal remain. The early-return route now wraps locally; dispatcher unchanged. |
| `writer_judgments.py`, `writer_judgment_authority.py`, assertion actions/store/launch/export | Remove new claim receipt hashes/pins. Existing payload storage holds completed business details by judgment ID, in the same assertion transaction. Projection, Reviewer and calculator consume them; atomic rollback and archive round-trip preserve qualifiers and inputs. |
| `assessment_results.py`, `assessment_projection.py`, vocabulary | New calculations no longer produce or require an auxiliary projection digest. Calculator identity, input/version/scope and staleness checks remain. The optional historical field is logged in the [S2 amendment log](s2-amendments.json). |
| `probe_case.py`, `commission_requirements.py`, `plan_inputs.py` | Reproduced M5 copy failure: carry verified immutable source/page facts, not old task receipts. Exclusion validation consumes them; no Writer image-access grant is imported. |

## Evidence and bounds

Main ran **311 core**, **96 instrumented replay**, **54 copy/exclusion** and **1 catalog** focused checks, all passing; sets overlap. The six defect replays, ten controls, A/X32's 27/question, current unscored A/X51, producer binding, image ownership, exact recovery, archive restore and stale-export refusal survive. No test was retired. [Measured inventory and failures retained](../verification/stage1-9a-c/README.md).

The inventory contains all enumerated five-role schemas and nested fields, 3,054 explicit Python guard/constraint sites, all 12 S2 families, and measured native-call refusals. Zero observed is distinct from unmeasured evaluation coverage; one unattributed success remains private. Capability-family mappings index inherited requirements; they do not certify every check semantically. B2's two guards are listed **planned**.

Self-review only; no independent review claimed. No dispatcher, S2 catalog/SQL, export formatting, main, original case, ledger or hold change; no model call. Main stays at accepted b `fdf8f93`.

**Clean full run:** owner-authorized on exact `a70ab4d`: **6,179 passed / 9 unchanged skips / 0 failures**, 26m29s, all 6,188 nodes once, all nine coverage floors met (overall 90.63%). All 1,265 frozen files unchanged; passing source copy removed automatically; zero retained temporary test databases. No retry or reconciled failures. [Full result](../verification/stage1-9a-c/clean-full.json).

**Pending:** owner review/acceptance. Main remains accepted b. B2 starts from main only after c acceptance; no b2 source or new Word/Excel/PDF is claimed here.
