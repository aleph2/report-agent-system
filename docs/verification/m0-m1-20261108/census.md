# M0 census at the integrated M1 gate

The final offline suite on `b96e8fcb148ec08131b3d8ea3cea5b388d62f617` collected 6,044 nodes across eight shards and accounted for every node. 6,035 passed and 9 skipped. The gate recorded zero unexpected/duplicate/missing nodes, failed collection reports or failed test phases. The superseded `f906772` run was stopped early. The subsequent `d3dc3d0` run exposed failing launcher/planning test expectations and the incomplete static batch-write inventory. Neither older run contributes observations to these totals.

The full runtime observer reached **156 entries in the first-party static catalog**. The matrix retains **4 source-reachable entries without a hit** (`last_message`, `live_attempt_registered`, `live_trial_intent`, `reference_alignment_parent`) and the two historical M1 families. Neither M1 key appeared in the integrated application or its full-suite trace. Both had positive baseline write evidence. The new report-prose references and rubric records are classified individually in the catalog; their full-suite read/write evidence appears in the matrix.

| Operation | Unique family/marker pairs | In catalog | Test-only key | Predicate, sentinel or observer marker |
| --- | ---: | ---: | ---: | ---: |
| delete | 15 | 14 | 0 | 1 |
| read | 168 | 149 | 15 | 4 |
| write | 170 | 152 | 17 | 1 |

[All observed pairs](census-runtime.tsv) are the deduplicated contents of 13 nonempty Python-process trace files (50 files including startup-only traces). They record attempts, including rollback, validation and test setup. The preclassified SQL wildcard `operator_%` is counted in the catalog column when reached; it is a predicate rather than a stored key spelling. The [per-family matrix](census.tsv) joins them to the candidate static site ledger, family classification, retention or intended slice and the six-module tagged baseline. Each runtime-only row and each extra operation direction has a source citation there. There are 9 test-induced extra operation directions for otherwise catalogued families. Read/write labels in static records describe named accessors and forwarding layers as well as SQL; a read-only caller can therefore appear alongside an unused setter in the static data.

## Discrepancies and limits

* Test-only rows cover deliberately fabricated keys (transaction counters, reservations, historical inputs) and negative lookups checking that a field is absent. Opaque labels for synthetic keys containing hyphens match the SHA-256 of the prefix before the first colon. Representative runnable sources include `post-prepare-drift` (`tests/test_pilot_m1_preparation.py:441`) and `callback-effect` (`tests/test_m1_g1_reliability.py:124`). The source outside tests contains no application family for these keys.
* `read/<scan>` covers grouped, whole-table, value-filtered and key-range SELECTs whose exact set of returned keys the observer does not enumerate. The wildcard-only test predicates and their hashed labels are identified in the matrix. The opaque SHA-256 prefix `e3b0c44298fc` corresponds to a read with an empty prefix: the tagged code explicitly probes the empty string if an episode has no prior recovery key (`execution_progress.py:449,463`, recorded as `@empty`). A SELECT proves a lookup attempt, including a miss.
* `write/<unresolved>` is reproducible by `tests/test_assessment_completion_unknown_continuation.py::test_fresh_authority_is_one_shot_and_fully_pinned[recovery]` (1 passed). In the isolated fixture, line 31 seeds the sole row `model_recovery_call:old` and line 105 deliberately updates all rows with no key predicate. `delete/<unresolved>` is reproducible by the missing-link case in `tests/test_live_review_message.py:272` and the historical-unknown case in `tests/test_vision_admission.py:62` (2 passed). They delete `message_call:*` and `vision_attempt:*` via LIKE. The full observer deduplicates per process without logging statements or test IDs. These are verified origins for the forms; the stored marker does not count matching rows or identify each event.
* The census covers first-party state access in src/scripts plus Python SQLite accesses observed in the guarded tests and inheriting children. There is no real-commission or external-writer execution evidence in this record. The full-access Store forwarders, unfiltered reads, and statically reachable paths not exercised are retained in the catalog and site ledger. No completeness claim about arbitrary third-party writers is inferred.
* The final source rescan has 1,128 site signatures. The launch diagnostic edit shifted four source locations. Reconciliation on the preceding candidate identified an omitted second write in the literal batch in `source_search.configure_source_search`; the final scanner now captures both fields and preserves unresolved dynamic batch operands. Two recovery sites also explicitly record the empty-key lookup sentinel. The table includes explicit migration or retention dispositions for assertion, mixed, runtime and legacy keys.

**Disposition.** The M0 inventory/guardian closure condition is satisfied for this revision. Every observed entry is matched to a classified family, a traced test-only key, or a bounded observer form with its limitations disclosed. The unexecuted source paths stay in scope for later slices. No release, extraction-quality or real-site validation is implied.

## Reproduction and evidence

Native verification directory: `/home/dysun/report-agent-m1/verification/stage1-m1-verified-traced-20261108T140156Z-rdyrm5vk`. From the integrated checkout run `python3 scripts/state_census.py --trace-dir /home/dysun/report-agent-m1/verification/stage1-m1-verified-traced-20261108T140156Z-rdyrm5vk/state-census --observed /tmp/m0-runtime.tsv`, then compare it byte-for-byte with [the recorded TSV](census-runtime.tsv). `python3 scripts/state_census.py --sites /tmp/m0-sites.tsv` regenerates the static ledger. The identical-source gate fixture is an isolated checkout with its own private fixtures and temporaries.

| Evidence | SHA-256 |
| --- | --- |
| Eight-shard gate | `337735be9cee3b518fad0a77ae98f938ed0e858cabcbe2960da83dab3c09eb75` |
| Collected node manifest | `99155df7bd8ff84c4cf4411eb2b282d1c5071de2f0b1a2badb944a231f581525` |
| Merged runtime observations | `2c9a564f40d1c4f8908f8bba079d664372645aa1ba41f05a2f923ad48078670f` |
| Per-family reconciliation | `4aac2b31afd30af56ec6a72bceb3b1f802fbc83c866bc0c9ba8b3454706fe3bd` |
| Final static site ledger (corrected locations) | `667d9f4cf34493dac2149dd5af03b6014c8fc4c66459ba73a4877a716ecb07f9` |
