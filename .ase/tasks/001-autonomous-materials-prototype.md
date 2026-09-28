# Task001: One autonomous materials agent

Date: 2026-09-27. Stage: critical-risk prototype; G1 and G2 not yet accepted.

The user asked to continue implementation without stopping at plans, and required a
greenfield system. Build a runnable CLI prototype using a mature agent loop (ADK
candidate), code tools and an optional bounded LLM text-analysis tool. No fixed
purpose/planning/extraction/writing/review pipeline and no legacy application import.

Scope: synthetic source input, isolated local persistence, artifacts/receipts, visible
errors, resume from committed work, offline protocol tests. No UI/report production,
production deployment, OCR, engineering-data transmission or legacy data mutation.
SQLite is a contained prototype store, not a claim that the final database/Graph choice
has been implemented. See the verification record for the actual GLM provider results.

Main implements and tests. Independent alignment reviewer checks actual boundaries.
Compare existing-result reuse with a scenario needing further reading/analysis.
Allow any valid trace; never require every tool or a second model call for its own sake.
Tests include ownership refusal, cross-project isolation, source provenance, duplicate
submit receipt, committed-result reuse after process interruption and visible failures.

The user explicitly authorized the two synthetic GLM5.3 scenarios during this task.
Read only the existing GLM provider settings into this process, without printing keys,
modifying legacy configuration or sending engineering text. No OCR. Register each
scenario before the call, preserve outcomes, do not blindly restart an attempted case.
Scripted tests remain protocol evidence only. Provider settings reuse is not application
code reuse; the new application must not depend on the legacy service at runtime.

Execution correction: the approved second case was feedback-driven supplementary
analysis, not a fresh empty-artifact case. Main mistakenly ran the latter in live001;
it is an extra, off-plan synthetic trial, NOT proof of the approved feedback case.
The deviation was disclosed to the user; evidence is retained and not relabeled.
live002 executes the originally approved feedback case once. Do not run more paid
variants under this approval. See `.ase/verification/001-prototype.md` for dispositions.
