# Report Agent System — working rules for coding agents

Current rules only. Dated decision histories, superseded grants and incident
details live in `docs/decisions-history.md`; they are evidence, not instructions.
Current design references: `tasks/plan.md` (Stage 1 plan) and the architecture
document it links. If a rule here conflicts with a task the owner gives, ask.

## 1. Authority and money

- No installs, uploads, paid model runs, full regressions, report restarts or
  replay of unknown requests without explicit owner authorization for that action.
- Each paid run needs the owner's authorization naming its scope and spending cap;
  one launch per authorization. [CONFIRM: does the 50,000,000-token standing
  per-round authorization of 2026-10-26 still apply, or is it replaced by this?]
- Never release the historical 2M hold. Never reset usage, invent a grant, or
  release or replay an unknown outcome; reconcile it first.
- Preserve every ledger row, hold, unknown outcome and authorization receipt.
- Credentials, signing keys and provider keys stay local, never in git.
- Public code-review publication is authorized by the owner (2026-11-09).
  This does not authorize deployments or new paid model runs.

## 2. Roles and the shared checkout

- Neo leads technical decisions, design choices and validation order, and checks
  code, traces and actual results. Main implements and supplies the evidence.
  Neo decides whether a reported issue is real and needs fixing; review findings
  are inputs, not automatic stop orders. Neo cannot expand owner permissions.
- Main is the only Git operator (index, commit, tag, push, branch moves).
- One writing chat per source file at a time; read
  `.analysis/session-skills-coordination-20261025/ownership.md` before writing and
  record any transfer. Never reset, stash, restore or reformat others' uncommitted work.
- Neo leads file cleanup: scope, retention and order. Keep originals, run state,
  paid responses, traces and ledgers; delete only disposable caches and test data.
  Equal hashes alone never justify deleting a case source path.

## 3. Data that must be preserved

- Historical run databases, G5 originals and source originals are never modified.
  Read old cases on a copy; October-format cases open with tag
  `regression-20261028-ocr-fake01`.
- Each run owns its own input snapshot, state and outputs, and never depends on
  another run's writable directory. Reuse a verified snapshot by explicit import
  with its provenance.
- Live WSL SQLite files (cases, ledgers) are read only from WSL Python with
  `mode=ro`, closed promptly. Windows tools never open them, even read-only:
  copy through SQLite backup in WSL first. (Reproduced SQLITE_IOERR_DELETE.)

## 4. Complexity defaults

When a task does not say otherwise, apply these defaults. An exception needs a
named requirement or reproduced bug and the code that reads the result.

1. Migrating a receipt, digest or check: drop it unless code reads it for a named
   requirement. Example: M7's body, text and records digests.
2. One operation writes one store. Save content first, then the record that
   references it. Example: M4's first candidate joined two databases.
3. Before proposing an S2 amendment, ask whether the record belongs in the
   assertion store. Only claims that someone reviews, challenges or supersedes
   belong there. Example: M7's assembly receipts are case records.
4. Revising an assertion: supersede or retract the old one; never add a parallel
   record. Records nothing depends on may simply be overwritten.
   Example: M6's two active answers.
5. No compatibility code for versions that were never accepted.
   Example: the held-M4 guard.
6. After each change, delete the code it made unnecessary.
7. Before implementing, give the owner a change list: what will be added and
   removed, which files, and for each addition the requirement and the code that
   reads it. Keep it short; it is scope clarity, not a new approval stage.
8. Verification records start with source lines added/removed, checks and guards
   added/removed, and legacy fallback paths; keep the record to one page and
   link details.

## 5. Design rules

- Greenfield system: do not copy, import, wrap or modify the legacy application,
  its services, configuration or data. Verified source/OCR inputs and third-party
  libraries may be reused.
- Before adding a capability, check what DeepAgents/LangChain or a maintained
  integration already provides; build only the remaining gap, in the platform's
  extension point (tool, middleware, backend, model adapter, skill).
- Agents choose actions from goals and real observations. Do not hide a fixed
  workflow inside a tool, prompt or skill.
- Every operation is atomic, repeatable and right-sized. Failed work is redone,
  not resumed; an outside effect that may have happened (a paid call) is held and
  reconciled.
- Code comes from an owner requirement, a plan item or a reproduced bug, never
  from a possible future use.
- Root causes point to design. Repeated similar bugs mean investigating the
  shared mechanism, not another local patch.
- Classify confirmed bugs P0–P3 and name the exact action each one blocks.
  Zero bugs is not the goal; P2/P3 do not stop work by default.

## 6. Diagnosis and claims

- Investigate failures from code, traces and actual outputs; separate confirmed
  causes from hypotheses. Do not substitute prompt patches, passing test counts or
  another paid run for diagnosis.
- Claims stay within what was actually verified. Say which agent or person ran
  what, and say so plainly when evidence or independent review is missing.
- Keep private data out of web searches.

## 7. Round-completion email

After each report-generation test round reaches a terminal state and Neo has
reviewed it, send one concise summary from private-contact@example.invalid to
private-contact@example.invalid: flow and artifacts, token use, first failures and
corrections, open issues, next steps; label failed rounds honestly. Never resend
a sent message; reconcile Sent before retrying an unknown send.
Policy: `.analysis/task059-mail/round-summary-policy-20261026.json`.
