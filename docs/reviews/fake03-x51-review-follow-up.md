# Fake03 claim-verification review follow-up

Reviewed revision `7f92c74`, tag `fake03-offline-claim-verification-20261107`.

## X51 decision before the 16-row Writer and Reviewer pilot

The confirmed register establishes one section and three boreholes on A. Pit and geophysical investigation counts are unreported. The method pack cites pages 22–23. Its moderate band counts drilling, pits and geophysics. Its low band names drilling and pits. The owner or engineers must specify which investigation types qualify for low and which grade applies when both descriptions fit. The owner deferred this interpretation to engineering review for Fake03. A/X51 is an unscored gap. Low and moderate are recorded as conditional possibilities. Neither is an assigned grade.

Two offline calls to the tagged validator demonstrate the issue. With the A counts, it accepts moderate and refuses low. With one section, two boreholes, one pit and an explicit zero geophysical count, it accepts either proposed grade. The existing replay demonstrates that an unsupported value adjustment falls back from 49 to the midpoint of the selected grade. It does not establish A's grade.

The [pilot scope decision](../../tests/fake_data/mini_commission/engineering-review.json) binds A/X51 as an engineering deferral. The Writer can save a gap and the Reviewer can inspect both possibilities in its frozen view. The [row-specific answer key](../verification/fake03-qualitative-x51-answer-key.json) has SHA-256 `269f3972f6a309593fbdcb92ec85858fa18aa3ed5f0d5a1bc546619652565b4f`. Before engineering adopts a general X51 interpretation, test three boreholes with pits explicitly zero, a complete mixed inventory, and multiple sections with only aggregate counts. The previous tag and replay preserve the original midpoint result.

## Design items

| Item | When it matters | Verification |
| --- | --- | --- |
| Coordinator produces the typed register and the owner confirms it | Live Coordinator handover | Trace a confirmed fact from the source page to the register and Writer. Include an unknown fact and a scoped negative finding. |
| Put indicator fact requirements, band rules and overlap conventions in versioned method data | Method maintenance | Test the configured rule boundaries against the pinned definitions and identify the method revision on each result. |
| Make the midpoint policy an explicit scope decision | Real report | Verify a default midpoint, an authorized departure and an unsupported departure under the selected policy. |
| Record X51 counts by section | Real slopes with more than one section | Distinguish two inventories with the same object total and different per-section counts. |
| Check short outside-register quotations against their source and location | Citation handling | Accept an independently sourced short phrase and require the fact ID for a quotation from the registered location. |

The next proposed paid experiment covers the 16 qualitative rows and the first live Reviewer pass on frozen Writer rows. Retain both the Writer's original judgments and the Reviewer's independent findings so the two can be assessed separately.
