# Production entry for synthetic and real cases

Source lines added/removed: +96/−91 (unchanged helper relocation). Checks/guards added/removed: 0/0. New legacy fallback paths: 0.

The approved first slice moves `refusal_rows` into its production consumer, `writer_indicator_steps.py`, and moves fake-only `run_mini_assessment` to `fake_verification.py`. Their executable logic is unchanged. Probe callers and five existing test modules use the new locations. No new test functions.

Main ran the existing helper/probe/mini-assessment checks: **59 passed in 149.87 seconds**, offline. Neo independently reviewed the diff, executable AST equivalence and the log, without rerunning tests. Private evidence: `.private/production-entry-20261113/C-helper-moves-focused.log`.

The previously qualified e466 candidate remains separate: 6,287 passed and nine unchanged skips. It is not tagged for the superseded harness path. Production launch-authority and canonical Writer integration are approved next slices, not implemented or verified by this record yet. No paid launch, case mutation, grant change or hold release.
