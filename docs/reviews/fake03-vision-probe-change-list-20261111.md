# Fake03 vision-inclusive probe — offline change list

**Revised for owner review; documentation only.** Production **+0 / −0**, tests **+0 / −0**, guards changed **0**, new fallbacks **0** this turn. Implementation size is **unmeasured**. Existing code/test patches remain untouched and uncommitted.

**Owner decision:** include Coordinator **GLM-5.3** and existing **deepseek-v4.1-flash-1017** vision backend. One combined **5.5M token cap**, one campaign ledger, stop at the owner's page-sheet checkpoint. Reuse the image tool; replace the partial text-only approach. [Failure evidence](fake03-coordinator-probe-20261111.md). Neither paid stage is authorized yet.

## Change list: additions, removals and consumers

| Requirement / consumer | Files | Planned change |
| --- | --- | --- |
| Both authorized models; HTTP/ledger admission | `fake_planning_probe.py`, `fake_verification_budget.py`, `token_budget.py`, `vision.py` | Bind both exact services and request bounds to run authority; charge vision as Coordinator support to the same cap. Set an explicit host-owned vision output limit of **8,192 tokens**, including reasoning when enabled, for both check and probe. Reserve bounded prompt + image input plus that output allowance. Replace the single-GLM/text-only assumption; preserve GLM reservation, concurrency guard, unknown outcomes, old rows/holds and campaign ceiling. No new grant/reset. |
| Authorized catalog; native request/execution boundaries | `tool_selection.py`, `deep_runtime.py`, probe caller | Add one shared tool/backend dependency declaration, resolved against actual configuration; consume it in catalog construction and static verification. Replace the text-only image blacklist. Keep the transport guard and reject guessed/stale forbidden calls before side effects. Delegation, Writer/Reviewer work and delivery remain outside planning scope. No paid selector. |
| Page facts; source readers | `document_tools.py`, `source_tables.py`, reader adapters in `deep_runtime.py` | Compute page geometry facts **on read**, using existing PDF parsers and text/table outputs. Add graphics coverage and the structural scan-like flag below; skip OCR quality unless existing OCR confidence is present. Preserve source/version/page identity, pagination and resource limits. No ingestion change, new stored record type, OCR rerun or source modification. |
| Image-tool guidance; calling agent | `deep_runtime.py::analyze_source_image` description | Use the draft below; retain existing observation, identity, usage and uncertainty fields. Coordinator discovers applicability rather than adopting engineering values. |
| Exact diagnostics and model ID; operator/profile readers | `deep_models.py`, `request_budget.py`, `fake_planning_probe.py`, `input_capacity.py`, `vision.py` | Preserve the real wire-mismatch code; report failed planning distinctly from budget stops. Integrate separately owned `-1017` normalization without overwriting its edits. Remove obsolete positive-test identifiers; preserve historical records. |

## Reader facts

- Reuse native text/count, frozen page-located text and table status/count/geometry. Distinguish extracted-text character count from PDF-glyph count; report detected tables, not a claim that no other tables exist.
- **Compute on read:** report image, vector and combined **bounding-box coverage**: union their placement/path bounds, clip to the visible page, divide by page area, and count overlapping/repeated areas once. State the coordinate basis. This is repeatable geometric coverage, not exact painted-ink or semantic drawing coverage. Reuse existing parser/geometry helpers; no new dependency without approval.
- **Structural scan-like flag:** one image covering the visible page within an explicit geometric tolerance, with no native text. Test this exact predicate; it is not proof of scanned origin, and false does not prove the document was never scanned. Mixed/vector-only pages remain distinct. Parsing failures return unknown rather than zero/false.
- **OCR quality:** carry through existing confidence only if its scale/scope is known; otherwise omit it or say unmeasured. Do not add a quality estimator.
- No ingestion writes, stored page-fact record, source/OCR changes or semantic classifier. Block offsets remain distinct from physical PDF pages; image-only pages remain discoverable. Recorded agent services omit vision, so resolve its actual service explicitly.

## Image-tool description draft

> Use for a specific page/crop when native text and mechanical tables do not resolve a relevant question, including drawings or scans. Coordinator: discover subjects, page relevance, conflicts and material types; do not adopt engineering values or scores. Returns located, unverified observations, limitations and usage. Uses the configured paid vision backend unless an exact saved result is reused; charge it to the calling role and shared run budget. Prefer adequate existing text/table results. Does not confirm facts or modify sources.

## Offline acceptance

1. Classify registered tools to determine eligibility, then inspect the **final offered catalog**, including framework injections and nested services. Fail if unauthorized/unclassified dependencies survive into that catalog or guessed-call execution. Excluded implementations may remain registered. Static verification makes **zero model calls/reservations**.
2. Replay the native drawing-tool path with mocked providers. Authorized vision works; forbidden calls cannot dispatch; ordinary report image tools remain. The actual owner wait blocks subsequent model requests. Include summary/support calls in accounting.
3. Synthetic mixed-model ledger tests: both models share the cap; exact boundaries, concurrency, original holds, unknown vision outcomes stopping all roles, and original rows preserved. No live ledger writes.
4. Reader cases: text, full-page image/no text, mixed, vector-only, overlapping graphics, rotated/cropped pages and unavailable metadata. Assert clipped union coverage never exceeds the page and repeated reads return the same facts under the pinned parser/settings. Check actual tool schemas/results, discovery purpose, unverified status, exact failure codes and model identity.
5. Reconcile partial local work; focused offline tests, independent review and one candidate/change-size record. A full regression needs separate owner authorization. Freeze answer-key scope before paid testing; do not widen it after results.

**Reservation clarification:** the existing 1,179,648 is the explicitly verified GLM bound, not a fallback caused by an unrecognized vision profile. Matching `-1017` identifies the correct service profile; it does not itself certify the token count of an image request. The implementation must bind the actual vision request allowance without altering old authorizations or relaxing the GLM guard.

## Paid decisions, separately and in order

1. **Vision check:** one fixed drawing through the actual image tool, no Coordinator model call, one provider dispatch with automatic SDK retries off. Lower the host output limit from 32,768 to **8,192**, including any reasoning output. Compute the full prompt/image-input upper bound plus output allowance; request **that exact reservation plus a small explicit margin** as the one-call cap. **About 40K is an estimate, not an applied or proved limit.** Show the bound and margin before asking authorization; do not raise the cap instead of lowering output. If the bound cannot be justified, report that fact rather than dispatching under a fictional hard ceiling.
2. **Coordinator probe:** separate approval for one fresh GLM + named vision launch, **5.5M combined**, ending at the page sheet. The consumed failed-probe authority and smoke check do not authorize it.
3. **Review:** fixed-key correctness and suitable vision-page use first; then real tokens, cache reports, refusals and time. Later continuation is a separate decision.

Read-only ledger check **2026-11-12 07:43:52 UTC**: **2,519,772 settled / 1,179,648 held / 6,300,580 available**, 328 attempts; unchanged 10M campaign. Recheck after the vision check. Preserve the separate historical 2M hold. Caps continue counting cached tokens in full.

Deferred: parallel reads, splitting page text from receipts, report-type drawing knowledge, scores/judgments, dispatcher scheduling, formal release and the real report.
