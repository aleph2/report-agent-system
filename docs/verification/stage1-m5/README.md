# M5 commission inputs and planning checkpoints

## What the owner approves

During preparation the host records the supplied files, their declared roles, source-use instructions and imported owner material as immutable case content. Supplying a file permits the Coordinator to read it for planning. When the host supplies an explicit list, planning reads are limited to that list. Permission for report use comes from the authenticated owner response to the exact plan and source versions.

The Coordinator records its interpretation and opens the planning question in the assertion store. The plan and requirements checkpoints record the owner's actual answer there. A generic issue closure cannot stand in for that answer. Older cases keep their existing read path. New cases do not reuse historical grants.

## What changed during verification

An independent review reproduced a P1 access failure. A Coordinator given only file A could obtain excluded file B through a different tool. The correction covers page reads, searches, imports, observations and nested content reads. The tests exercise both an allowed file and a denied file through the normal tools. The review rechecked the correction.

The dispatcher’s scheduling, retries and grants use the accepted M4 logic. Three runtime and task adapters changed where they obtain or enforce source authority. The protected-file comparison identifies those edits. The three S2 contract files are byte-identical to M4. [Protected-file checks](regression.json)

## Operator checks

A new Fake03 commission imported nine fixture files and one method. The scripted owner approved A and B and excluded C. Ten source versions were pinned. Two copy checks on historical cases passed. The separate Writer replay verifies saved inputs and Reviewer views for all 16 judgments. [Fake03 checkpoint](fake03-checkpoint.json)

**Known P2 limitation.** Copying the approved miniature commission into a fresh probe fails at `objects.C.sources` with `EXCLUSION_SOURCE_NOT_DIRECTLY_RETURNED`. The copy preserves the approved plan and requirements, then asks for the original Coordinator's planning receipt for design page 1. That receipt belongs to the original run. The identical operation fails on accepted M4 (`b23238a`). This blocks launching a fresh probe from that particular copy. The fresh commission and the saved-judgment replay complete independently. [Operator results](regression.json)

## Test storage

Keep the detached worktree at the tested commit. Run pytest with `tmp_path_retention_policy = "failed"` and `tmp_path_retention_count = 1`. Give each concurrent shard a stable, project-specific pytest temporary root and let pytest allocate its numbered directory. An explicit `--basetemp` disables cross-run rotation and leaves session-scoped temporary files after a successful run. Store logs, manifests, coverage and review records outside this root.

The first diagnostic left 5,058 disposable passing-test directories. Removing those recovered 2.41 GiB in WSL. Once the full suite passed, its pytest directories released another 2.57 GiB. The logs, failure evidence, coverage, fixture manifests and fixed source snapshots are retained. These figures measure allocated Linux blocks. [Storage measurements](pytest-retention.json)

## Offline regression

The full suite ran on commit `670a7879669821f6a5968ffdd3d6305b9b9a222c` in a detached worktree. It accounted for all 6,144 cases exactly once. **6,135 passed, 9 conditional integrations skipped, and 0 failed.** The skipped cases match accepted M4. The run took 30 minutes 45 seconds and made zero paid model calls. Pyright reported the same 676 diagnostics as M4. The Writer replay and the full regression used the same 51 pinned private fixture files as M4. [Regression record](regression.json) · [Retired tests and their replacements](test-migration.json)

The only subsequent configuration change, `3ce0e3894bb8447ea207a980d8c861b997c7484a`, enables pytest's temporary-directory retention policy. Thirty-nine tests exercising M5, plan authority and copying passed with that configuration. Their pytest and tool temporary roots had zero leftover files. Deliberate mixed pass/fail runs verified that passing cases disappear, a failed case survives and the next failed run replaces the previous one. After the original full run, the shard temp directories had no stray files outside pytest and its cache. The source snapshot contained only its original files and fixture inputs. [Retention verification](pytest-retention.json)

All affected modules meet their M0 coverage floors after the successful operator checks. Three additional offline scenarios exercised Writer access to planning sources and owner resolution, immutable classifications and stale replies, and the separation of source precedence from method approval. Combined coverage was 736 of 813 statements in planning and 198 of 236 in deliverables. The failed cold-copy experiment contributed no coverage to these figures. [Coverage by module](coverage.json) · [Operator checks](regression.json)
