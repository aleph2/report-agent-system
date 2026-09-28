# Task018 verification: responsibility and autonomous review strategy

2026-09-28. Main performed prompt design, implementation, focused tests and
integration. Independent development alignment review by alignment_review,
reused from Task017 under .ase/roles/alignment-reviewer.md. No report-runtime
reviewer was added and no provider model was called.

## User decision and implementation

The user said the prompt was too specific about how to review and asked to make
the grader responsible for results while choosing its own strategy. The role now
owns reliability of assessment and usefulness of feedback, including both justified
acceptance and detection of material defects. Neither passing nor finding more
defects is its goal. Strategy, evidence acquisition, coverage and stopping judgment
remain with the grader under the unchanged native grading contract.

- report-reviewer.md: 3233 -> 1187 characters; purpose, responsibility, autonomous
  strategy, evidence-grounded verdict and truthful scope, read-only/human boundaries.
  Removed named-tool recommendations and method-specific review instructions.
- report-review.md: 2989 -> 1579 characters. Preserved scope, evidence, correctness,
  human authority and saved/exported deliverable outcomes. Removed commands to read
  the full report, invoke tools, follow particular checks or justify a chosen method.
  Applicability beyond arithmetic, actual report consistency, honest limitations,
  source-vs-system failures and compatible limited drafts remain quality standards.
- review.py: the appended application observation identifies the exact target and
  available project context; it no longer instructs the grader to use project_status
  or read the export with tools. Artifact hashes and binding logic are unchanged.
- test_reviewer_prompt017.py: removed only the assertion requiring a tool name in
  system prose. The actual bound-tool capability and denied-tool assertions remain.

No changes to model/parameters, tool implementation, review-only permissions,
native response schema, default GRADER_SYSTEM_PROMPT, history preparation, revision
or terminal feedback control. No source/report/checkpoint/legacy data modifications.
Existing Task016/017 prompts, traces and assessment outcomes remain historical.

## Checks

Executed in existing Ubuntu-24.04 WSL environment:

```text
python -m pytest -q tests/test_reviewer_prompt017.py tests/test_native_rubric013.py tests/test_review_feedback.py
24 passed, 1 warning in 44.48s
```

The warning is the existing RubricMiddleware beta API warning. These offline tests
block HTTP and check the effective SystemMessage, unchanged native contract,
single review entry, real bound tools/permissions, prompt-version acceptance,
native needs_revision -> revision -> satisfied mechanics, target-bound export
reads and terminal/error/recovery behavior. Scripted decisions verify mechanics,
not model judgment. `git diff --check` passed.

Exported current assembled text to ignored `.analysis/task018/` without constructing
a provider request or reading credentials:

- SystemMessage: 2323 characters; digest
  `07d7d853ae3e317e640b5adb8524a16d3ab9e2e8296145cef1e38ad2086c7a29`.
- Rubric: 1579 characters; digest
  `3566067762dd0d15d12a2910fc43edcdccd7158a4c6b7ad6c9faaa93adb84806`.

These are current assembly identities, not claims about an already executed real
GLM request. The existing hash comparison prevents mismatched earlier acceptance
from serving as acceptance under the newly active prompt/rubric.

## Independent review and Main disposition

alignment_review reviewed the proposed design before implementation, then the
four-file implementation diff and retained tests. It found no blocking finding or
new P0-P3 principle deviation. Coverage autonomy does not waive the native requirement
to affirmatively support every passed criterion. Tool schema pagination and modality
descriptions are interface semantics, not a prescribed semantic workflow. Five
outcome categories, source/system failure distinction, actual inputs/applicability,
honest performed-work claims, limited-draft boundaries and upstream ownership remain.

Main accepts the focused findings. No extra runtime gate or fixed review plan is
needed. The real-world effect of shorter instructions remains unverified.
P2-017-R01 is still open: this change does not establish that the grader detects the
previous material contradictions or triggers useful autonomous correction. It
continues to block quality-promotion claims and engineering reliance, while not
blocking this bounded prompt integration. Containment and disposition remain in
017-postrun-content.md; Main owns subsequent evidence-based validation.

## Design references reused

Applied agent-prompt-design and the OpenAI official documentation already fetched
in this discussion:

- https://developers.openai.com/api/docs/guides/reasoning-best-practices
- https://developers.openai.com/api/docs/guides/evaluation-best-practices

Clear outcomes, concise instructions and empirical assessment are design guidance.
OpenAI model guidance is not evidence that this change improves GLM-5.3. No new
model comparison, paid calibration set or end-to-end trial was run in this task.
