# Task015: Evaluator Research and Local Calibration

Research cutoff: **2026-09-28**. Author: independent implementation reviewer.
Scope: LLM-as-judge, self-correction, tool feedback and correlated errors;
recommendations for this repository, not a new report run or production change.
Only papers, conference proceedings and author/official sources support the
literature claims below. Search queries contained no project/source text.
No paid model requests, source-answer assessment or hidden-reasoning inspection
were performed. Proposed experiments below have **not** been executed.

## Decision Summary

Do not conclude either "LLMs cannot correct themselves" or "a reviewer role
makes the same model independent." Published results depend on task, feedback,
training, comparison baseline and evaluation criterion. Human preference,
factual correctness, defect detection and successful repair are different targets.

The cheapest useful next step is a small **version-pinned local evaluator test**,
not another autonomous full report: independently label a few evidence-complete
cases, pair actual defects with correct controls, measure false alarms, then test
one bounded repair on a subset. First distinguish missing evidence from failure
to use available evidence. Keep the existing native rubric implementation; do
not build another judge framework, permanent business gate or fixed agent sequence.

Nothing cited here establishes GLM-5.3's current detection or correction rates.
Task014 remains a development case, not a held-out benchmark. Its successful
execution is evidence of the trunk working, not a calibrated reviewer.

## Evidence: Support and Counterexamples

The following are selective, decision-relevant findings, not an exhaustive survey.
Numbers describe each paper's setup, not expected project performance. Older
results must not be generalized to every later reasoning model. Recent preprints
are explicitly distinguished from confirmed conference publications.

### Judging Is Useful, But the Target Matters

**Zheng et al., NeurIPS 2023, MT-Bench/Chatbot Arena.** Strong judges achieved
over 80% agreement with human preferences in the studied settings. The same work
documents position, verbosity, self-enhancement and reasoning limitations.
Supporting case: scalable preference assessment can work. Limitation: agreement
on conversational preference is not sensitivity to consequential report defects.
[Paper](https://arxiv.org/abs/2306.05685v4).

**Tan et al., ICLR 2025, JudgeBench.** Difficult response pairs labeled by
objective correctness expose much poorer judging than preference benchmarks;
several strong contemporary models perform near chance. This does not imply
all judges fail, but rejects using a preference leaderboard as sufficient
validation of a technical reviewer.
[Paper](https://arxiv.org/abs/2410.12784).

**Norman et al., 2026-06-17 preprint, Reliability without Validity.** Across
21 judges and three benchmarks, rankings vary and high repeatability can coexist
with position bias. The authors report little verbosity bias under their specific
rubric, a useful counterexample to treating that bias as universal. Agreement
and chance-corrected agreement differ; that difference is not itself a measured
percentage-point error in engineering accuracy. Use class-specific errors and
ground truth, not repeatability alone.
[Paper](https://arxiv.org/abs/2606.19544v1).

### Self-correction Can Work, But Finding the Defect Is Separate

**Madaan et al., 2023, Self-Refine.** The same model generates, critiques and
refines, without additional training; seven tasks show improvements over one-shot
generation, with an approximately 20-point average improvement reported by the
authors. This is positive evidence for same-model refinement, not proof of
reliable factual checking on arbitrary tasks or a compute-matched advantage.
[Paper](https://arxiv.org/abs/2303.17651v2).

**Huang et al., ICLR 2024, Cannot Self-Correct Reasoning Yet.** Under intrinsic
reasoning correction without external feedback, tested models often fail to
improve and can change correct answers into incorrect ones. This limits a
particular inference-time method, not the possibility of tool-supported or
trained correction. It motivates retaining correct controls, not testing only
known-bad examples.
[Conference paper](https://proceedings.iclr.cc/paper_files/paper/2024/file/8b4add8b0aa8749d80a34ca5d941c355-Paper-Conference.pdf).

**Tyen et al., Findings of ACL 2024.** Error localization and correction are
tested separately. Providing the true error location improves correction across
five reasoning tasks, although models struggle to find the mistakes themselves.
The supplied location is privileged feedback: success with it measures repair
capacity, not autonomous detection.
[Paper](https://arxiv.org/abs/2311.08516v3).

**Liu et al., December 2024 revision, Intrinsic Self-Correction Ability.** A
counterexample to blanket pessimism: neutral prompts and zero temperature yield
improvements in their experiments. Their limitations describe restricted models/
datasets and missing error bars. Treat this as a prompt/sampling hypothesis to
test locally, not a theorem that a neutral instruction or temperature zero will
make GLM reliable or deterministic at its serving endpoint.
[Paper, sections 5-6](https://arxiv.org/html/2406.15673v2).

**Kumar et al., 2024, SCoRe.** Multi-turn reinforcement learning improves
self-correction on MATH/HumanEval with Gemini models; simple offline supervised
correction training is not sufficient in their comparisons. This is evidence
that the capability can be trained, not an off-the-shelf prompting recipe or
evidence that GLM-5.3 has undergone equivalent training.
[Paper](https://arxiv.org/abs/2409.12917v2).

### External Feedback Helps Under Verifiable Conditions

**Gou et al., ICLR 2024, CRITIC.** Tools supply retrieval or execution feedback.
For ChatGPT mathematical program synthesis, Table 2 reports GSM8K 72.5 to 78.2
and TabMWP 75.0 to 89.0 versus program-of-thought. It is not uniformly positive:
text-davinci-003 on SVAMP falls from 84.0 to 80.7. Tool removal usually weakens
correction, but some no-tool conditions improve too. Crucially, starred CRITIC
results use an oracle that selects only incorrect answers; they are not autonomous
detect-and-repair results. An executable result verifies that execution, not
the applicability of an engineering rule or correctness of supplied inputs.
[Paper, sections 4.1-4.2 and Table 2](https://arxiv.org/html/2305.11738v4).

**Zhou et al., ICML 2025, JETTS.** Ten judges and eight generators are evaluated
on reranking, search and critique-based refinement. The refinement comparisons
use equal-sized candidate sets; the tested critique-capable judges do not beat
both greedy generation and reranking on the aggregate task categories. This
contrasts with assuming that an articulate critique necessarily helps repair.
The tested models/settings, not all future critics, bound this negative result.
[Paper, sections 3.4 and 4.4](https://arxiv.org/html/2504.15253v2).

### Same-family Bias and Correlated Errors Are Not Identical

**Wataoka et al., 2024, Self-Preference Bias.** GPT-4 tends to score lower-
perplexity, more familiar outputs more favorably than humans do, including texts
not generated by itself. The mechanism is not simply reading an author label.
Removing names is sensible blinding, but does not eliminate stylistic familiarity.
[Paper](https://arxiv.org/abs/2410.21819).

**Kim et al., ICML 2025, Correlated Errors.** A study of over 350 models finds
substantial shared errors, including among different providers. Its judge case
study evaluates models against a judge's answers; that is not the same protocol
as an interactive rubric agent. The result still supports measuring joint errors
rather than assuming independent votes. A different vendor is not an independent
ground-truth oracle.
[Paper, section 4](https://arxiv.org/html/2506.07962v1).

**Pombal et al., 2026-08-03 v3 preprint, Rubric-Based Self-Preference.** On
programmatically checkable IFEval/LiveCodeBench criteria, judges can be over 50%
more likely to falsely mark their own failed outputs satisfied, relative to
other outputs; this is a relative increase, not 50 percentage points. Ensembles
mitigate but do not remove the bias. More reasoning effort does not reliably
remove it in their ablation. Tested families listed in section 2.4 do not include
GLM. A structured rubric therefore does not by itself establish independence.
[Paper, sections 2-3 and appendix G](https://arxiv.org/html/2604.06996v3).

**Verga et al., 2024, PoLL.** In six datasets and three evaluation settings,
a diverse panel of smaller judges outperforms a single large judge at lower
reported cost. This supports testing diversity, not rejecting it categorically.
It does not prove a panel is economical or more accurate for this project's
local evidence tasks. Measure marginal defect detection before adding judges.
[Paper](https://arxiv.org/abs/2404.18796v2).

**Recent directions, not dependencies to adopt now.** CARE models shared
confounders and reports better aggregation on 12 benchmarks; its guarantees have
modeling assumptions, and a handful of local cases cannot validate them.
[CARE, revision 2026-09-08](https://arxiv.org/abs/2603.00039v2).
JEV compares a cheaper classifier with three LLM judges: accuracy differences
are often inconclusive, while correlated confident errors limit cascade gains
despite large cost reductions. This very recent preprint motivates checking
complementarity; it does not justify importing a classifier into this repo.
[Rao and Callison-Burch, 2026-09-24 preprint](https://arxiv.org/abs/2609.29769v1).

## What Task014 Does and Does Not Establish

Local evidence: [post-run trace](014-postrun-trace.md) and
[clean-input audit](014-clean-inputs.md). These are project observations,
not public literature claims.

- The uninterrupted run made a saved draft and native iteration-0 satisfied
  verdict. There was no native needs-revision-to-repair cycle in this run.
  Task014 alone cannot estimate reviewer recall, false-positive rate or repair yield.
- The worker corrected a rejected source UUID after a catalog observation.
  That is a genuine tool-feedback recovery, not evidence that it can independently
  detect an erroneous engineering assumption.
- The grader read all 21,419 draft characters, sampled 190/902 export blocks,
  and made six source searches. It made no calculation call. Its initial native
  transcript retained four of nine prior calculator observations.
- The all-six-recompute claim has a traceability gap. No new calculator call
  alone is not proof that the arithmetic was wrong, nor that valid earlier
  evidence could not be reused. A local test must distinguish correct evidence
  reuse from unsupported completeness claims.
- Same GLM family, writer statements, retrieval coverage and context truncation
  are competing hypotheses, not established causes of that claim. Changing the
  model, prompt and evidence package together would not identify the cause.
- Cost baseline: 3,859,402 GLM tokens, including 767,727 for the grader, plus
  8,843 vision tokens. Replaying the entire report is unnecessary to test whether
  a reviewer can catch one localized defect or repair one paragraph.

## Smallest Useful Local Experiment

### A. Offline First: Freeze Cases and Independent Labels

Prepare a small diagnostic set, not a new parsing platform. Start with **six
paired cases** (one defective variant and one independently checked correct
control per evidence unit), plus **two insufficient-evidence cases**: 14 items.
Use synthetic numbers/text or permitted local fragments shaped like Task014's
failure opportunities. Do not assume the actual Task014 draft is a correct control.
Do not insert the real report's desired answers into production prompts.

Suggested six defect/control pairs:

| Pair | Defective variant | Correct control / independent oracle |
| --- | --- | --- |
| Arithmetic | One known weighted-sum result changed | Exact Decimal calculation of fixed, explicitly given inputs |
| Input applicability | Correct sum but wrong supplied row/unit/condition | A short source fixture explicitly fixes the valid input/rule; domain ambiguity is not forced into a gold label |
| Attribution | Supported-looking citation points to a contradicting or unrelated located block | Claim and locator agree under a manually verified fixture |
| Absence/coverage | No search hit or partial read promoted to "source lacks X" | Located counterevidence; paired qualified statement does not overclaim |
| Review evidence | Claims six checks from partial or stale-version receipts | Complete matching-version evidence is available and may be reused without mandatory recalculation |
| Export boundary | Claims full visual/layout verification from text-only partial preview | Same preview with an accurately limited statement |

The two uncertain cases should require "insufficient evidence / further check",
not invented certainty or automatic rejection of a usable limited draft. An open
human issue by itself is not a planted defect. Separate unresolved source authority
from correctable report mistakes, as the current project policy requires.

Keep per-case source locator/hash, artifact/version, rubric/config hash,
observation coverage, expected defect location, allowed alternative correct
outcomes, and label rationale. Keep labels outside model-visible tool data.
Use independent arithmetic/fixture checks; contested domain labels require a
qualified human, not majority model voting. If labelers disagree, record ambiguous.
This preparation can be validated with fake models and network disabled; fake
passes prove plumbing only, never actual reviewer capability.

### B. Separate Detection from Evidence Access

After separate paid authorization, reuse native rubric and existing read tools
in a disposable evaluation workspace, not `run_report` on Task014. Do not restore
the live checkpoint, rewrite the original draft or regenerate/OCR the sources.
Each item is a fresh short conversation with a single pinned candidate; tool
behavior, permissions and grade schema remain the real ones.

First compare only two treatments, keeping model/settings/rubric/candidate fixed:

1. **Available evidence:** the local source/receipt package is accessible through
   existing read tools; the agent chooses how to inspect it.
2. **Observed evidence:** the identical relevant source/receipt package is supplied
   as observations up front, without a verdict, error hint or expected answer.

This estimates the contribution of access/selection/context, not the isolated
effect of a better instruction. Label it as an evidence-delivery intervention.
Record whether the necessary evidence was requested, returned and available when
the verdict was produced. "Tool available" is not "evidence observed".

Use three pairs as development cases and three different evidence-unit pairs,
plus the uncertain cases, as held-out diagnostic cases. Keep each pair together
in one split. Do not tune on held-out outputs. This is deliberately too small for
a population-quality claim; display counts and uncertainty, not a persuasive
percentage from three defects. Synthetic variants of the known project remain
development-derived, even when hidden from prompt tuning.

Only if a specific residual warrants it, run one small, separate comparison:
remove author completion/review claims while preserving evidence, or swap one
judge model while preserving everything else. Do not bundle those interventions.
Cross-model comparison should reuse the same cases, include correct controls,
and inspect both judges' jointly missed defects, not just disagreement.

### C. Test Repair Only After Measuring Detection

On a selected few labeled items, fork the same initial artifact for one revision
under three inputs: neutral recheck with no new evidence; actual reviewer
feedback; independently verified defect location/evidence. The last is an oracle-
assisted diagnostic, not a deployable autonomous success. Include a correct
control to reveal damage from false feedback. Keep revision opportunity and
output scope comparable; do not compare nine retries with one baseline call.

The existing native feedback route should deliver the actual criterion and
location to the worker. Score the resulting artifact against the independent
label, not against the same grader's second approval. Preserve original and
revised hashes, exact feedback and tool observations. A receipt proving the
feedback was delivered is different from a successful repair.

One revision is an experimental contrast, not a proposed permanent runtime
limit. No new agent loop, automatic terminal restart, forced tool sequence,
replacement summary engine or production rubric edit is recommended here.

## Metrics That Make the Result Interpretable

Use **defect-positive** terminology consistently:

- TP: real, located defect correctly identified; FN: defective case passed or
  defect missed. Recall = TP/(TP+FN). False-pass rate on bad cases = FN/(TP+FN).
- FP: correct case wrongly criticized as defective; TN: correct case accepted.
  False-alarm rate = FP/(FP+TN). Precision = TP/(TP+FP), with the sampled defect
  prevalence explicitly stated. Balanced synthetic prevalence is not production
  prevalence, so its precision is not a production precision estimate.
- Separate wrong-location/spurious extra findings from the planted-defect match;
  a long critique containing one valid issue is not automatically wholly correct.
- Report abstentions and coverage separately. On a defective case, abstention
  is not successful detection unless the defect is actually localized. Show both
  decided-case error and unresolved fraction; do not hide abstention in accuracy.
- Repair: bad-to-good transitions / initially bad cases; damage: good-to-bad /
  initially good cases; net improvement uses the same initial population. Also
  report repair conditional on correct detection, so reviewer and writer failures
  do not get merged into one opaque end-to-end score.
- Report evidence-supported checking claims, not tool-call counts as a quality
  proxy. Reuse of valid receipts counts; irrelevant repeated calculations do not.
- For two judges, measure joint false passes and conditional misses on judge-A
  failures. Role separation, different providers and inter-judge agreement are
  not substitutes for this measured complementarity.

List raw n/N and item-level paired outcomes. If confidence intervals are useful,
use established statistical-library intervals/paired procedures and respect
evidence-unit clustering; do not treat repeated runs or mutations as independent
projects. A tiny pilot with zero false alarms does not establish a low real-world
false-alarm rate. Agreement/kappa can supplement, but not replace, defect metrics.

## Cost and Action Boundaries

Current authorization covers research, not the proposed paid phases. Suggested
staging for later approval: first six development items x two evidence conditions
= **12 bounded judge episodes**, then inspect whether they distinguish the
hypotheses before authorizing held-out evaluation. Do not automatically execute
every alternative, panel, seed and repair treatment.

An episode may contain multiple provider calls. Before execution, count the
actual assembled request tokens locally and record a separate experimental call/
token allowance, including grading, tool turns, output and SDK retries. Use small
evidence-complete packets rather than the full 100k-token report history. Budget
exhaustion is `incomplete`, never pass. These are visible experiment controls,
not hidden cumulative quotas added to the report application. No monetary saving
is guaranteed without current authorized prices and measured actual usage.

Escalate to a full integration run only for a specific remaining integration
question after a local effect is demonstrated, not merely because a new prompt
sounds stricter. A local fix cannot establish unseen end-to-end report quality;
eventually reuse the normal trunk acceptance process rather than replacing it
with endless micro-evaluations.

## Current Disposition

The Task014 P2 review-claim evidence gap remains contained by trace disclosure
and independent assessment; these papers neither prove its cause nor upgrade
it to a global stop order. No new implementation defect is established solely
by the literature. Main can choose the next smallest authorized diagnostic.
No GLM calibration rates, repair improvements, ensemble advantage or causal
prompt effect have been measured by this research task.
