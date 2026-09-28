# Task009: Independent program-boundary review

User requested checking whether the program does too much. Independent reviewer:
Anscombe. Main transcribes the returned review and disposition. Static review plus
Task009 observations, not a claim of newly executed counterexample tests. No runtime
code, prompt, configuration or task state changed for this review.

## Findings

1. P2: Revision automatically adopts old inputs, mapped to latest versions.
   `workspace.py:228` and `workspace.py:332` retain dependencies even when the agent
   submits an empty input list after removing that content. An unchosen newer input
   can also become adopted. Historical links belong in the predecessor version;
   current adopted inputs should be explicit. Blocks accurate dependency claims,
   can cause irrelevant invalidation; does not block this first-draft trial.

2. P2: A replacement submission automatically closes captured corrections.
   `workspace.py:230`, `workspace.py:409` mark them resolved even if only the title
   changes and the original defect remains. `workspace.py:573` then omits those
   pending corrections. Record a proposed replacement, not semantic resolution.
   The responsible agent should state disposition; no new mandatory review stage.
   Blocks claiming the correction was actually resolved; final exact-version review
   provides partial containment, not proof the defect is fixed.

3. P2: Repetition signature is treated as proof of no progress.
   `deep_runtime.py:65` raises before the third identical call using arguments,
   result IDs and global context, without examining changed graph data, scratch
   state or returned observations. Legitimate repeated retrieval/receipt recovery
   can fail. Keep diagnostic feedback, remove this unsupported business inference
   as a hard failure. This guard did not cause Task009's varying calculations.

4. P2: Global context change becomes a mandatory changes_required verdict.
   `workspace.py:518`, `workspace.py:561`: an unrelated resolved technical issue can
   invalidate an otherwise unchanged review. Relevance belongs to agent assessment;
   uncertainty about freshness is not proof content needs modification. Blocks
   claims that every forced re-review is business-necessary; restricted export can
   continue. Keep version evidence without equating context change to content error.

## Controls to retain

- Server-bound role permissions and read-only upstream ownership; disabling the
  general-purpose delegate and restricting virtual file tools enforces authorization.
- Program-generated IDs, versions, transactional receipts and exact review targets.
  A framework checkpoint does not provide exactly-once external writes.
- Confirmed final independent review and visible delivery status. Latest applicable
  exact-draft review prevents selecting an older favorable verdict; no demonstrated
  defect supports removing that rule. Imperfect drafts remain exportable with status.
- Observation metadata proves receipt of nonempty content, not semantic completeness.
  Do not introduce a per-word/per-page compulsory reading gate.

## Attribution and consensus

Actual DeepAgents control loop, native delegation and AsyncSqliteSaver are used.
No mandatory purpose-plan-materials-calculation-report chain was found. C25 holds
at the main loop but has the local deviations above. Preserve the greenfield D08
boundaries verified for this trial.

Task009 calculation arguments are emitted by the model. The arithmetic tool does
only decimal products/sums; no program rule mandates object count, scores, number
of calculations or thresholds. These calculations therefore cannot be attributed
to a forced code pipeline. Indirect prompt effects are not causally established.

ask_human uses a native interrupt. Referring source conflicts to humans is confirmed;
pausing all work while waiting is the current implementation strategy, not a proven
universal business necessity. Revisit only when an actual independent-work use case
requires it, rather than adding another approval gate now.

## Main disposition

Accept the four P2 findings as scoped simplification candidates, not an instruction
to rewrite the architecture or disable safeguards. Current action is review, not
repair; no application changes made. None blocks the isolated Task009 observation.
For a later authorized repair: remove automatic semantic conclusions, retain
permissions/durable evidence, add focused counterexample tests, and verify actual
agent behavior. Framework reuse review is separate and still pending here.
