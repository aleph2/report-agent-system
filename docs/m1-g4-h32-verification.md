# G4 H3.2 — Planning input contracts

## Behavior

Planning accepts document chainage such as `K1+020+12.5` and decimal metres. Conversion uses exact decimal arithmetic; the saved boundary retains the submitted notation, and the owner brief shows it alongside normalized metres. Existing canonical saved plans remain readable.

The boundary tool now selects its customer basis by a current scope requirement anchor ID. The system verifies the requirement source pins and supplies the saved quote and locator. The agent cannot supply a competing free-form customer-basis citation through this tool.

Planning citations may omit their locator when they include an exact quotation. At save ingress, a quotation occurring exactly once in the same source is resolved to a canonical existing locator. An incorrect supplied locator can be corrected on the same basis. The operation receipt records original and resolved locators, source reference and resolution reason. A valid explicit locator still disambiguates repeated text. Missing or ambiguous quotations return the affected field and available matching locations. Counting includes cross-block occurrences; a unique same-page span may use the existing page prefix. A quote spanning unrelated locations without a representable canonical locator is explicitly refused, rather than assigned an invented address.

Downstream authority checks remain strict: they validate saved citations without rewriting approved plans. Global SourceCitation, source authorization, requirement completeness, owner approval, transaction receipts and the five-rejection pause remain in force.

Planning tools publish and validate a shared Pydantic input model through the existing native MessageTool mechanism. Native schema errors retain nested field paths. State-dependent errors expose applicable fields and choices where meaningful; permissions still require the original authority.

A second failure from the resumed pinned run was incorporated: a valid boundary source cannot pass the existing factual-source guard when the plan has no actual extracted section using that source. Diagnostics now identify the boundary source and related section kind/source fields. The guard is unchanged; a dummy section is not a remedy.

## Verification record

Implementation: h32_patch. Independent code/contract review: Neo. Native-schema parity and integration verification: Main. Interface mapping: h32_interface_audit.

Baseline: decc14408e74e93d09583cc6d001cce068ebefd4 in the native Linux development checkout. The stopped candidate-03 remains on its separately pinned source; this patch is not installed in that case.

- Initial targeted reproduction: six failing cases before implementation.
- Additional factual-source diagnostic reproduction: four failures and one existing positive case before the diagnostic change.
- Effective-schema coverage: all ten planning step tools, the two current zero-argument planning actions, and actual ToolNode nested-argument error feedback.
- Synthetic sources reproduce the recorded boundary failure shapes; no customer source files or model reasoning are committed.
- Pre-integration targeted verification: 60 passed in 24.78 seconds.
- Fresh guarded full04: 4,961 passed, 11 failed, 9 skipped; all 4,981 collected nodes completed exactly once. Ten failures exposed lost outer diagnostic reasons; one transport test reached its 0.25-second deadline before any HTTP dispatch was observed.
- Final message-only correction: all 948 tests in 39 affected whole modules passed in the audited replacement batch (231.98 seconds). All 11 original failed nodes are covered. Only the diagnostic summary and its assertion changed after full04.
- Reconciliation: 4,972 passed and 9 skipped across the two explicitly identified batches, with the unchanged 4,981-node fresh collection, matching phase/JSONL/JUnit outcomes and source/evidence pins. This is not a single all-green full-suite invocation.
- The 9 opt-in integration nodes (graph and local embedding coverage) were skipped; 2 additional modules were skipped at collection because optional GEPA/DSPy packages are absent. They are separate categories.

The first full-suite attempt was interrupted for diagnosis after 96 passes, one failure and two skips. The failure was a missing managed historical fixture in the native checkout, not an established product regression. Fifty existing managed fixture files were copied with matching SHA256 hashes; the failing file then passed on its own. The original failed run and import receipt are retained in local H3.2 evidence.

The next serial attempt was deliberately interrupted after 155 passes and two skips to use the reviewed five-shard runner. It is not full-suite evidence.

The first sharded batch (full03) exposed a test-isolation defect introduced by the new H3.2 tests: registering an H2 test module as a global pytest plugin applied its autouse HTTP patch to unrelated SDK tests. The batch was interrupted and is not reused as final coverage. It also exposed a legacy source-error-code compatibility regression and a valid H3 scripted caller still using the replaced free-form boundary basis. Corrections preserve existing rejection semantics and assertions; the fresh full04 batch above was then executed. The test-only archive fixture was isolated from the real restart budget, while the static shipped-configuration assertion was updated to the already-approved 200M/278,464,822 baseline. Production configuration, account limits, ledgers and test deadlines were not changed by H3.2.

## Limits

Offline tests verify deterministic contracts and scripted runtime behavior; they do not establish model autonomy or engineering acceptance. H3.2 does not approve the current report plan, change budgets, release historical holds, restart the report, or re-enable email.

The diagnostic continuation of the paid report ended as incomplete at 2026-11-04 04:10:03 UTC. The Coordinator recorded non-pausing questions and then ended; no resumable interrupt remained. The owner later approved evidenced second-volume design and survey substitution for sections 2.1–2.5, with missing information and uncertainty disclosed. That decision was recorded without starting a host or approving the plan. Duplicate candidate records still contain unresolved inclusion/height conflicts. H3.2 does not settle these engineering decisions.

A separate observed output-eviction defect can hide the tail of a large planning draft. An older intact observation of the same requirement version offers a compact recovery route. Runtime output preservation/pagination remains a later cleanup item, not a claimed H3.2 repair.

## Evidence and residual verification limits

Local audit root: `/home/dysun/report-agent-m1/g4-restart-20261103/h32/`. `full04/outcome-audit.json`, `full04/skip-reasons.json`, and `full04/final-message/reconciliation.json` retain the separate batch evidence. Neo independently reviewed source and verification records; the test runner produced the results.

The unchanged transport module also passed on its own (22 tests, 3.91 seconds). Its concurrent deadline-before-send failure remains recorded; the underlying latency cause is not proven. No timeout was increased and no existing oracle was weakened. The final full-module replacement includes transport coverage. No live-provider validation or engineering sign-off is claimed.
