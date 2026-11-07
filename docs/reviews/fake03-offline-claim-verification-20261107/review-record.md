# Fake03 qualitative Writer · offline review record

Candidate `7f92c74eb3fa14b1e870bc01faccf5e2af4835f9` · previous Run 06 code `459110c3ca7d73acafbf4ba1fd8d32a33c1e70b0`

## Verdict

The old revision reproduced all 16 historical business-input digests on a fresh case. The candidate refused four unsupported grades, corrected one value and flagged one question. The other ten rows retained their kind, grade, value, rationale, question and missing-data field. Each replay starts from synthetic inputs and uses the real tool schema, validator and persistence path.

The full regression collected **5,819 tests**, with **5,810 passed**, **9 skipped** and **0 failed**. Every collected test was accounted for once. Source and fixture hashes stayed fixed during the run. The gate completed at 2026-11-07T13:14:38.005631+00:00. See [gate](full-regression.json) and [reproduction instructions](reproduction.md).

An initial candidate exposed a general-runtime tool-wrapping regression during the full suite. The final candidate preserves the existing structured tool schema and still enforces scope on invocation. The full-suite result above applies to the corrected commit.

## Six historical defects

| Row | What the historical save claimed | Result on the candidate |
| --- | --- | --- |
| A/X32 | A rockfall about 2 km away supported a provisional occasional grade at 27. The follow-up question proposed raising the grade for seasonal overlap. | Preserved the assumption and 27. Flagged the grade-change question for semantic review. |
| A/X42 | An offsite rockfall and A’s material type established that nearby facilities were all beyond the method’s distance thresholds. | Refused the low grade at 12. A facility survey with adequate coverage or measured distances is needed. |
| A/X51 | One section and three boreholes justified moderate. The absence of records about other investigation types justified moving up to 49. | Retained moderate under the agreed A convention. Rejected the adjustment, saved 37 and retained the proposed 49 and its reason in the audit. Other investigation types remain unknown. |
| A/X52 | A's support design and a reference to a B drawing established a relatively complete A drawing set. | Refused the assumed high grade at 62. A-specific drawing coverage is needed. |
| B/X32 | A rockfall outside A occurred once in the rainfall observation period and established frequency for B. | Refused moderate at 37. The event has no confirmed period or link to B. |
| B/X51 | A page covering A established zero sections and investigation points on B. | Refused very high at 87.5. Coverage of a different slope cannot supply B's counts. |

Four explicitly scripted follow-ups saved gaps so the resulting rows could also be inspected. The replay annotated the original propositions with the new fields. For A/X32 the annotation supplied the original question’s grade-changing intent. Its example Reviewer finding was scripted. These checks establish how the system handles a declared claim and preserves the record for independent review. They do not measure whether a model chooses the right handles, declares its intended effect correctly, or independently detects a misleading statement.

The ten controls include A/X21 at 37, A/X41 at 62, and eight gaps. The view includes both an observation’s source text and the proposition for which the Writer selected it. Cross-object material can be contextual even when invalid as decisive evidence. A Reviewer may add a finding against a pinned row digest. A finding does not overwrite the Writer’s row.

## Differently worded controls

Fake04 has four synthetic source PDFs and 16 observations. Twelve matched examples cover event periods, genuine zero counts, season versus frequency, the subject and extent of facility surveys, investigation counts and report coverage, drawings, groundwater and within-band adjustments. The capture includes the selected fact IDs, source quotations, resulting values and actual diagnostic. It exercises the production claim validator with independently phrased inputs. [Paired examples](fake04-paired-examples.json) · [Fixture](fake04/README.md)

## Files for review

- [Human-readable view of the 16 saved rows](reviewer-rows.md).
- [All historical inputs and annotations, native refusals, effective rows and complete Reviewer views](replay-and-reviewer-views.json). Select a label such as `A/X51` under `rows` and under `reviewer_views`. The frozen contribution includes its source, plan and method provenance, row digest and effective value. The example finding is under `scripted_finding`.
- [Historical reproduction](historical-reproduction.json) and [original Writer inputs](original-writer-inputs.json).
- [Reviewable patch](fix.patch) against the original revision. From a checkout at the baseline, use `git apply --check fix.patch` and `git apply --binary fix.patch`.
- [Offline gate counts](full-regression.json), [focused tests](focused-tests.txt), [campaign ledger check](ledger-check.json) and [file hashes](SHA256SUMS).

No paid Writer or Reviewer was called. The fake-verification campaign remained at 1,991,060 settled tokens with a 1,179,648-token hold. Model comparison and live qualitative judgment remain unevaluated. This review does not grant engineering acceptance or qualify production reports.
