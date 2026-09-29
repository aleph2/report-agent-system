# Task030: requirement-derived acceptance owned by the coordinator

2026-09-29. User approved assigning acceptance-standard creation/maintenance to
the coordinator's requirement and document-purpose responsibility. Both writer
and acceptance agent share the standard before production. The acceptance agent
chooses, executes and adapts its own verification strategy and tools. This follows
the referenced discussion 01a0eae0-15f9-73d0-97d1-64b85712f28a, read on 2026-09-29.

## Outcome and authority

Implement the smallest connected requirement -> saved criteria -> saved draft ->
native acceptance -> feedback/revision path. No dedicated criteria agent, fixed
checking micro-workflow, knowledge graph migration or mandatory page scan. Criteria
describe outcomes, source requirements and allowed limits, not known-defect answers.
The coordinator owns criteria; authors own reports; the grader owns its assessment.
Neither author nor grader can overwrite criteria. They may request correction.
Criteria cannot be weakened to fit a report. Actual requirement changes/undecidable
commission choices remain with the user; ordinary clarification needs no new gate.

Current stage: critical-risk validation; G1 reliable substantive acceptance remains
open. This increment establishes mechanics, not improved model accuracy or G2/G3
promotion. All verification this turn is offline. The user's pause of paid trials
remains in force. Preserve completed Task029 and interrupted-repeat evidence.

## Implementation contract

- Immutable, source/requirement-linked criterion versions, code-assigned identities.
- Save standards before new draft production, with the same exact version visible
  to writer and grader; changing standards invalidates old acceptance applicability.
- Runtime permissions come from assigned role, not model-supplied actor fields.
- Reuse native DeepAgents0.7.19 rubric/checkpoint/author feedback loop and existing
  Workspace receipts; thin adapters for dynamic criteria and domain three-state
  results. No new scheduler or model-independent semantic truth validator.
- Every standard gets satisfied, not_satisfied or undetermined with public evidence
  and limitations. Exact criterion identity coverage is checked. Unknown is not a
  proven defect and does not force the author to invent facts. Native failed keeps
  its meaning of invalid/ungradable rubric. Usable draft != all standards satisfied.
- Grader may group investigations, choose depth and reuse valid evidence. Text,
  image and calculation tools produce observations, not final acceptance. Preserve
  operator authority over genuine source disputes and missing material.
- Historic runs/configurations/results remain legacy; do not retrofit old drafts
  into evidence of pre-production criteria or resume their paid checkpoints.

## Verification and roles

Main: implementation/integration and task record. resume_assessment: read-only
architectural advice. alignment_review: focused design/implementation review.
Offline native integration verifies shared standards, permissions, incomplete or
wrong criterion coverage, revision, uncertainty, target binding, durable recovery
and historical compatibility. No scripted model is evidence of semantic autonomy.
Measure future model-quality gain separately: misses, false positives, correct
acceptance decisions, saved corrections and regressions on independent new cases.

Prompt references checked: OpenAI reasoning best practices (clear goals/success
criteria without requesting private reasoning) and DeepAgents grading rubrics.
https://developers.openai.com/api/docs/guides/reasoning-best-practices
https://docs.langchain.com/oss/python/deepagents/rubric
These guide design; they do not establish effectiveness for this project's models.
