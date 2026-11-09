# M4 plan core verification

Commit **1569c674864c9d072d525f16539f13e6f956cdeb** passed the full offline regression. Of 6,109 collected cases, **6,100 passed** and **9 conditional integrations skipped**. The skip IDs match M3. The suite ran for 42 minutes 36 seconds, with the timing-sensitive module first and seven parallel groups afterward. All groups returned zero. Every collected case had an outcome. Network access was guarded, model credentials were removed and there were zero paid model calls. [Results, skips and file digests](regression.json)

## Plan approval and compatibility

The Coordinator proposes a versioned commission plan. The owner checkpoint records the exact proposal, requirements version and choices. The plan pins its skeleton and text profiles. Drafts, skeletons and profiles use immutable content versions. Fresh imports copy the selected evidence and preserve the original case. Existing historical plans keep their read path.

An independent alignment review reproduced an export that could use a withdrawn approval via cached preflight, and a regenerated confirmation checklist that could still present it. The candidate rechecks the selected approval in both paths. A focused recheck passed 47 tests. Dispatcher and task execution modules retain the M3 hashes. The shared content store changed to support plan inputs and enforce their read restrictions. All three S2 contract files retain their M3 hashes.

## Regression findings

The first integration run found 15 failures. One showed a plan identity collision between independent fresh cases. Three positive-path tests supplied an obsolete hand-built approval. Eleven historical export checks encountered the new approval check on snapshots that predated native plan authority. The final candidate isolates fresh case identities, exercises current approval through the Coordinator and owner checkpoint, and preserves the existing checks for historical snapshots. Withdrawn native approvals still block export.

Package statement coverage from the suite was **90.66%**. All changed modules with M0 baselines met their floors when the same-revision operator checks were included. These checks exercised the read-only Fake03 identification command and repeated import of a synthetic historical case, including its text profile. The table shows where operator coverage contributed to meeting a floor. [Per-module coverage](coverage.json)

| Module | M0 floor | Full suite | With operator checks |
| --- | ---: | ---: | ---: |
| src/report_agent/fake_verification.py | 83.21% | 81.99% | 86.76% |
| src/report_agent/probe_case.py | 88.64% | 87.07% | 89.12% |

Basic Pyright reported **676** diagnostics, with **0 added** against M3 by module, rule and message. Of 6,086 M3 test IDs, 6,074 are retained. Each of the 12 retired IDs names its replacement test. The M4 collection includes 35 new IDs. [Test mapping](test-migration.json)

## Fake03 checkpoint and owner review

The offline replay restored 16 Writer judgments and 16 Reviewer views. A/X32 retained its provisional value of 27 and its question. The current A/X51 remained unscored and kept its interpretation question. Each slope's calculator result stayed unscored and lists the missing inputs. This checkpoint exercises saved judgments, calculation and review with scripted inputs. [Replay record](fake03-checkpoint.json)

The review tag points to the tested executable revision. Verification files are in the accompanying documentation-only commit on the existing M4 branch. Moving the default branch requires owner acceptance of M4 and separate confirmation of the exact old and new commits.
