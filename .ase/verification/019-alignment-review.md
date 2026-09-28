# Task019 independent alignment review

2026-09-28. Independent development alignment-reviewer `alignment_review` reviewed
the proposed design and the concrete harness/fixtures read-only. Main transcribes
its returned findings here because that role does not write files.

Disposition: no blocking alignment finding and no newly confirmed P0–P3 deviation.
This is development review, not a runtime report approval gate.

The reviewer independently checked that both corrected candidates differ only by
`40 块沉降板` -> `6 块沉降板`, short candidates are exact substrings of the matching
full versions, and the common source matches the independently verified table.
Commission, source, system prompt and rubric are shared. The commission consistently
excludes unrelated report/export judgments. Four offline tests were reported by Main;
the independent reviewer did not rerun them or claim model-quality evidence.

The runner reads only the input JSON and rejects label fields. References remain
outside the fixture directory. Each case creates a fresh model/agent, a claimed
output directory and one complete HumanMessage; it has no evidence tools, prior
history or author/revision loop. It saves only the public structured result and
existing redacted LocalAudit events, not the complete agent result. Errors preserve
receipts and stop; attempted directories cannot be silently replayed. Production
implementation and prompts are unchanged.

Main accepted two design findings before execution: verify all quoted aggregate
quantities, and score explicit target evidence separately from the top-level verdict.
No target statement is inconclusive; rejection on a non-target issue is not detection.
The source reviewer verified all four numbers; the packet/reference file records
the target scoring and excludes equivalent counting-unit wording.

The reviewer also clarified that four initial case invocations do not guarantee four
provider requests: inherited SDK transport retries and native structured-output repair
may add calls. Main must report observed model calls/usage, and classify transport or
schema failures as inconclusive rather than content errors. Local callback counts do
not independently establish the absence of SDK-internal transport retries.

Limits retained: localization and clean table transcription reduce production task
difficulty; four cases do not establish production equivalence, error rates, long-context
causation, a repaired historical P2, or an accepted end-to-end correction loop.
