# Fake03 qualitative Writer claim checks

## Reproduction

Commit `459110c` accepted all 16 Run 06 qualitative saves. The frozen business inputs are in `tests/fixtures/fake03_run06_saved_inputs.json`. On a fresh mini-commission the earlier code reproduces their input digests. Six rows contained errors despite having genuine source quotations. The save path could bind quoted text to a source without establishing which proposition it supported.

## Change and acceptance criteria

The qualitative Writer saves register identifiers against three distinct claims: the grade, an assumption and any move away from the midpoint. The system resolves the quotations and checks the observation's subject, scope, state and purpose. Direct event frequency requires the event's own count and period. An investigation count requires a record that actually counts that item on the subject. An unsupported grade is refused with a route to a gap. A failed value adjustment preserves the supported grade and its midpoint. Questions and engineering interpretations remain reviewable.

The Reviewer reads the exact frozen Writer row under its assigned slope and records any finding separately. Its view includes the provenance of the plan, register and sources, the effective input and the claim checks. A stored finding cannot change a Writer row.

| Historical row | Offline check |
| --- | --- |
| A/X32 | Preserve the provisional grade and 27. Keep the original question visible and flag its proposed grade change. |
| A/X42 | An offsite rockfall and a material description cannot establish facility distances. Refuse the grade. |
| A/X51 | Preserve moderate from the confirmed survey observations. Refuse the unsupported 49 and retain the midpoint 37. |
| A/X52 | A reference to B's drawing cannot establish the completeness of A's drawing package. Refuse the grade. |
| B/X32 | A rainfall period cannot establish the observation period or frequency of rockfalls at B. Refuse the grade. |
| B/X51 | A page covering A cannot supply zero investigation counts for B. Refuse the grade. |

## Offline checks

Run the following from the repository's native Python environment. The replay scripts the historical propositions and annotates them with the new fields. After a refusal, a scripted gap exercises the real save path. Its example Reviewer finding is also scripted.

```sh
python -B tests/support/run_offline_tests.py -q tests/test_run06_claim_replay.py tests/test_writer_typed_claims.py tests/test_fake_attestation_register.py tests/test_fake04_claim_controls.py tests/test_qualitative_review_view.py
```

Set `FAKE03_OFFLINE_REPLAY_RECORD` to an output path to retain all 16 before/after records, the tool refusals, the frozen Reviewer views and the sample finding. The ten controls must preserve their business outcomes. Fake04's synthetic PDFs use new wording and exercise positive and negative evidence for the same rules. The full offline regression is required on the same revision.

These checks verify what the system enforces or exposes to review. A Writer still chooses the claim and its links, and semantic agreement between the free text and those links requires independent review. A live model comparison is a separate experiment.
