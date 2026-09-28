# Task016 Evidence Tools and Unassisted Trial

## Preflight

2026-09-28. Main implemented the scoped change; independent reviewer Anscombe
accepted the boundaries (016-alignment.md). No runtime prompts or rubric changed.

- Focused native integration tests: 4 passed in 5.82s.
- Full suite: 593 passed, 9 skipped, 2 warnings in 112.35s. Skips are not passes;
  this is offline protocol/regression evidence, not report content acceptance.
- Clean importer completed into `.runs/task016/autonomous-report`, using only
  Task006 sources and frozen OCR: 10 original files including scope; 1617 blocks.
- Goal SHA256: a0637c7c3e3b2d377cda50d7e29ee424f14753884996c2d12b0ffff258f5cd87.
- Source-index SHA256: 6c094821f9b06a323fb44f9d0b0da82df0fade051a5a660403af349a1d305a00.
- Code hashes are in the isolated import-receipt.json. Additional frozen files:
  - src/report_agent/rules/report-review.md: cff789a67297516f4b92c46bb7cb03ece799ab17a850514340bc50130f527106
  - scripts/prepare_clean_trial009.py: 0c702746ecaf46a29dade836b20065f5ed19c587dab359ea78562049bc428d56
  - scripts/run_deepagents_trial.py: 1af8517fb7af3a70cd3cc60240818f0fad1a92fbd3e3a8331ae7505a9d89d84f
- Installed DeepAgents 0.7.19, LangGraph 1.2.12, LangChain 1.4.2,
  langchain-openai 1.6.6, OpenAI SDK 2.54.0.
- Effective adapter: GLM5.3, high, thinking enabled/clear_thinking false,
  nonstreaming, parallel_tool_calls false, max_tokens 65536, SDK retry 2.
  Existing vision tool selects deepseek-v4.1-flash. Secrets remain in process
  memory via the existing launcher, not in this evidence record.

No prior report, manual reference report, review findings, answer-bearing hints,
graph/checkpoints or visual observations imported. Both tool capabilities change
together, so a single run cannot establish separate causal effects.

## Execution

Rawls independently verified clean inputs at 09:23:11 UTC with no startup blocker;
see 016-clean-inputs.md. Main starts the authorized invocation around 09:25 UTC.
One authorized invocation only;
no automatic whole-run resume, manual hints, source decisions or draft repairs.
Post-run findings will be recorded separately and not sent to this running agent.

## Mail

Gmail profile/search transport failed around 09:21 UTC. No email sent and no
successful-query watermark advanced. Failure notified in chat and recorded in
task015-mail state; result delivery will be attempted after test completion.
Profile and full overlapping search recovered at 09:24:20 UTC; correct account,
no new matching messages or bounce candidates and no next page.

## Completed Runtime Evidence

Native run started 09:25:07 UTC, finished 09:58:33 UTC: 33m26s. Launcher exited
0 after export. One start, no resume/human decision, no runtime code/rule/source
changes. Post-run hash checks match every code/original/OCR receipt entry and
the frozen rubric. Native result is reviewed_draft, iteration 0 satisfied,
five criteria passed; no needs_revision and no report revision. This is the
system's verdict, not independent content or engineering acceptance.

- 128 GLM responses: coordinator 39, knowledge 65, rubric_grader 24.
- Usage: 6,752,638 prompt + 113,835 completion = 6,866,473 tokens;
  all responses have usage. No visual calls or visual token use.
- 122 business-boundary tool calls: includes 18 searches, 45 original-page
  text inspections, 3 delegated tasks, 6 calculations, 9 knowledge puts,
  3 links, 13 export reads. Page inspection is not visual interpretation.
- All 18 searches supplied source_id and all first recorded tool observations
  show matching actual scope and no returned matches from other sources.
- Four rejected tool calls were returned as errors and did not terminate the
  run: one invalid result reference, one source-page range, two preview ranges.
- Saved 3 purpose results and 1 draft (26,256 characters), ID
  cf1be9a3-756b-44a6-983c-0d85520906cc. Draft hash
  7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d.
- New graph namespace 298a3a3b-12e4-4fd8-bc99-37dedac422fc; writes/links observed,
  but no knowledge_search/read/traverse calls. Cannot claim graph retrieval gain.
- Source-scoped retrieval exercised successfully. Grader vision was available
  and offline-tested, but unused here, so its real-run quality effect is unknown.
- Compared with Task014 (18m24s, 56 GLM responses, 3,859,402 GLM tokens plus
  two visual calls), this run is slower and uses more calls/tokens. Tool fixes
  do not establish efficiency improvement, nor isolate a cause of quality change.

Read-only aggregation: `.analysis/task016-postrun/audit.py` and trace-summary.json.
It reads ordinary tool observations, metadata and persisted rubric records, not
private reasoning/checkpoints. Raw stored report_status/delivery in the compact
legacy audit remain unreviewed_draft; native rubric projection is reviewed_draft.
Report the native record and exact target, not the raw legacy field alone.

## Independent Content Review and Main Disposition

Chandrasekhar independently inspected this exact draft and ordinary evidence
trace; see 016-postrun-content.md. Main accepts the evidenced P2 findings:

- Monitoring column attribution still wrong in section 5.2.3: 40 settlement
  plates stated, whereas original design table assigns 40 to inclinometer tubes
  and 6 to settlement plates. The old 96-tube statement disappeared but the
  class of column-binding error persists.
- Geological candidates now reach the report and grader, a real retrieval gain,
  but screening is incomplete and one candidate is both excluded and pending.
- The old 55-point mismatch disappeared, but slope-angle qualification and
  some mapping-completeness band descriptions still do not justify scores.
  Independent arithmetic using exact fractional weights matches all six totals;
  58.0 is not an arithmetic error. Rounded-display precision is only P3.
- Claimed fieldwork/process and statements that investigation remains pending
  are inconsistent; unconfirmed source differences cannot become verified causes.

These findings block claims of verified full-scope engineering use/sign-off,
not the completed diagnostic test or explicitly limited draft circulation.
Containment: retain the unchanged experiment artifact with this issue list and
native/independent verdicts separate. Main owns follow-up disposition; no source
decisions, report repair, retry or second paid experiment is performed here.

Conclusion: source-filter defect is fixed and exercised, but evaluator acceptance
remains too broad relative to the contradictory evidence actually observed.
Tool capability alone did not resolve review misses. Next proposed validation is
focused grader calibration using independently labelled pass/fail examples and
existing native feedback, testing consequential contradictions rather than adding
hard-coded engineering decisions or compulsory micro-stages. Not executed here;
engineering values and source conflicts remain for human resolution.

## Export Review and Closeout

Gauss independently rendered the unchanged original DOCX with the documents
renderer and inspected 37/37 pages; see 016-export-review.md. There are 11 tables
and no embedded images. No confirmed P0/P1 clipping, missing table rows or
unreadable content. P2 publishing gaps: empty automatic TOC (p3), duplicate
front matter/production instructions (p5-6), and promised rather than assembled
independent attachments (p35). P3 placeholders and literal Markdown remain.

Main accepts these as limits on claims of formal publication/attachment
completeness, not a demand to duplicate historical attachments or invent absent
personnel. Body tables are present. Source-imaging absence alone is not an
engineering failure criterion. The experimental draft can be circulated only
with the content and publishing limitations above.

Original exported DOCX SHA256 (unchanged before/after QA):
f1f2fe2083fc02e4c1078ae32a4c81e9d10191f1108c080e0d4a013bbdffe3dd.
This fresh export is distinct from the earlier native-grader preview byte hash;
do not imply that a fresh file was itself the exact native-reviewed snapshot.

No post-run findings were injected, no report repairs made, and no second paid
experiment or deployment started. Scoped implementation, regression testing,
independent review, clean unassisted execution and post-run assessment complete.
Quality limitations remain open; email closeout is tracked in task015-mail state.

Results sent by verified Gmail account dysun.sunny@gmail.com to only
dongyong.sun@derobotee.com at 10:09:02 UTC, no attachments/CC. Message ID
1a0e77d41dfabe66, existing thread 1a0e6b3516608eda, connector returned SENT.
Initial local schema rejection (to array rather than string) did not dispatch;
corrected request returned the single successful send receipt. Five-minute mail
discussion monitoring remains active; no further paid trial is started here.
