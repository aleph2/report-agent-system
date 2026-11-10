# Unscored assembly: historical source trace

This is a source comparison on sanitized history, not a historical execution claim.

| Revision | Code | Confirmed behavior |
| --- | --- | --- |
| Pre-M3 ca1360d | writer_assessment.py:387–400 | score requires all method indicators saved, no interrupted indicators, no gap rows, and all native saved rows; otherwise no canonical assessment is published. |
| Pre-M3 ca1360d | system_assembler.py:180–209 | assembly requires the assessment receipt, generated ranking/evaluation/level/evidence records, and validate_outcome; missing assessments prevent ready status. |
| M3 5b0336c | assessment_projection.py; system_assembler.py:191–194 | adds native calculator projection and explicit score_blocker check, reporting assessment_score_unavailable for unscored results. |
| Current M10 candidate | tests/test_run06_claim_replay.py | executed native replay: 16 rows saved, both slopes unscored, exact assembly refusal asserted; three planning issues also missing. |

M3 therefore added the unscored representation and an explicit refusal, but available source does not show a formerly successful incomplete-draft export. Do not describe this as a verified old success regressing to a new failure.

The existing provisional-text renderer in risk_scoring.py names pending review, but that text alone does not prove current assembler admission: score_blocker accepts scored/historical-scored statuses and refuses pending_review. Required 9a work must test admission, rendering and release separately, including unscored drafts, rather than relying on the renderer string.

The missing Fake03 issue records cover: design versus survey discrepancy; initial date versus revision; adopted design ratio versus retained survey ratio. These must remain visible in the required issue registry and be materialized/routed in the eventual draft; no export checks were weakened here.
