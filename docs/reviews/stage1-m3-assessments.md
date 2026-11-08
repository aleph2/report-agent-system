# M3 assessment migration

The owner accepted the M2 tag at `bac73ea`. The lifecycle gate for M3 is the offline Fake03 replay through the Writer and calculator. The frozen input set includes ten control rows, the six historical problem rows and the subsequent A/X51 owner deferral.

## Pilot commissioning decision

The engineering lead owns technical review of the 11 pilot criteria alongside M3/M4. The owner confirms the resulting project conventions before the real report starts. These are role assignments. Each interpretation still requires an actual review against its guideline table, band or exception, and applicable source material. Record the reviewer’s name, evidence, criterion version, proposed interpretation, and any unresolved question. The owner’s confirmation must identify the reviewed version. Engineering sign-off remains a separate named-human decision.

| Criterion | Printed indicator | Engineering review |
| --- | --- | --- |
| X11 | 边坡高度 | Pending |
| X12 | 坡形坡率 | Pending |
| X21 | 地层岩性 | Pending |
| X22 | 坡体结构 | Pending |
| X23 | 地下水 | Pending |
| X31 | 施工季节 | Pending |
| X32 | 自然灾害的影响 | Pending |
| X41 | 工程措施类型 | Pending |
| X42 | 周边环境 | Pending |
| X51 | 地质资料 | Pending |
| X52 | 设计文件 | Pending |

X11 requires both total-height and bench-height evidence for the larger-of rule. X51’s drilling and pit wording remains open where it affects the grade. A missing or disputed reading must retain its question and alternatives. The Fake03 dispositions belong to the synthetic case. The engineering lead reviews the real pilot material independently.

## Implementation and review

- Bind the calculator result to its exact Writer judgments, plan, object, weight strategy, rank order and method version. Preserve complete arithmetic, level and sensitivity. Store incomplete status, justified ranges, robustness and the outstanding indicator IDs. An unresolved result has no adopted score.
- Check the scoped assignment and the one-producer binding independently. Keep task receipts in runtime storage. A lost reply must recover the same result. Preserve historical reads and pinned selections.
- Exercise the normal Writer-to-calculator entry point offline. Verify how an incomplete or unreviewed selection appears to downstream consumers. Keep the existing dispatcher and engineering authorities intact.
- Map each removed test node individually to its covering test and explain any deliberately retired behavior. Compare per-file coverage to M0 and run the full offline regression before the review tag.


## Recalculating a reviewed assessment

The trusted case operator can select a new calculator result after the reviews of the saved inputs are complete. Run `python -m report_agent.assessment_refresh /path/to/existing/case SLOPE_OBJECT_ID` in the report environment. The command uses the current approved plan and the recorded Writer assignment. Its JSON result identifies the previous and current assessment and its status. Repeating it on a current scored assessment returns the same reference. A Word or Excel snapshot pinned to the earlier assessment continues to refer to that version.

## Independent review findings

| Severity | Observation and affected action | Disposition |
| --- | --- | --- |
| P1 | A fresh bulk submission could become the selected score before any Writer judgments existed. That would let an unverified number reach the assembled report. | Fresh raw input in the system-assembled route is a draft. The selector, chapter and export checks use the authenticated calculator result. Historical G3 reads retain their original scope. |
| P1 | Review could confirm a draft’s inputs without giving the operator a supported way to obtain its score. | The explicit refresh command derives a successor from the reviewed inputs and preserves the draft. |
| P2 | Changing the projection’s runtime marker could bypass the review check for a result whose immutable content identified it as native. | The reader verifies its identity against immutable content. Missing or inconsistent status cannot qualify a score. |
| P2 | A fact retraction between the calculator commit and the rendering projection could make recovery fail. | An authorized exact retry uses the frozen operation receipt. Current eligibility still applies to new calculations and revoked assignments cannot recover the result. |

The historical paid assessment-completion command advertises only the bulk scoring tool. Under system assembly this can produce drafts but cannot meet its own five-selected-results stop condition (P2). The launcher refuses this route before creating work or reserving tokens. Archived results remain available for inspection.

The [individual test migration record](../verification/stage1-m3/m2-retired-tests.tsv) lists the 55 M2 removals or renamed test cases, their specific covering tests and the behavior deliberately retired.
