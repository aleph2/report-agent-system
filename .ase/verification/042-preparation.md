# Task042 preparation and offline verification

2026-09-29. `/root/review_fork` implemented the two diagnostic scripts and their
focused offline tests. Main owns actual paid execution and integration; the
assigned specialist owns the independent oracle and semantic assessment.
This worker made no model calls, read no service credentials, inspected no private
reasoning or checkpoint messages, and changed no production code, original report,
criteria, sources or previous run. No email was sent.

## Frozen preparation

`scripts/prepare_relation_verdict_diagnostic.py` produced
`.analysis/task042/frozen/model-inputs.json` and `input-receipt.json` using one
randomly generated assignment seed `12458623401771080409`. The seed controls only
the experimental assignment, not model sampling. A rebuild with this recorded
seed reproduces the same assignment and content. Existing preparation directories
are refused, even when identical; no overwrite or re-randomization occurs.

| Artifact | SHA256 |
| --- | --- |
| model-inputs.json | `813e37605266edbfe9871a1960a7d3e90ca1cb97a538c8844317e1d5aa575816` |
| input-receipt.json | `d58a5aca5353eaa36b9b04682ebcd036dcb9a5231080cb8b5dbc71bab67454d8` |
| prepare_relation_verdict_diagnostic.py | `7d52a97bef5939fb73d4bd838c575e988643395334dc3d71d04d5a8fea403df5` |
| run_relation_verdict_diagnostic.py | `897270bbd683bdfaf58d70670e9c83aaefa3291362ae1a130602328825905aaa` |
| test_relation_verdict_diagnostic.py | `6e58589bcc0e1a00c740e3310ff58850e02bf057a12bb0b4d53001ddf20a46a7` |

The runtime scripts were frozen after generation and were not subsequently edited.
The receipt records original source-file hashes, public state/results/audit hashes,
all report-agent Python/rule files and imported script dependencies, field/message
hashes, field origins and limitations. Package versions are specifically stored
in the final receipt's `runtime_versions` field, populated by
`importlib.metadata.version` during preparation (prepare script lines175–176).
This field was rechecked directly in the frozen receipt during documentation
closeout. The runner's actual preflight passed with59 file hashes matching.
The recorded versions are DeepAgents0.7.19, LangChain1.4.2,
langchain-openai1.6.6, LangGraph1.2.12 and OpenAI2.54.0.

The replacement draft is the full unchanged 18,934-character Task040 body
`49a0fd72-0228-4d09-86d5-a5193a5a0018`, SHA256
`0acf099ed36fd270774f18e42dfc55ea38abb111f1da42590b0f2beead2681f4`.
The original goal and six complete criteria come from acceptance
`95f221a2-b318-4158-b1f8-235aa71c6273`, body SHA256
`e4a789d64947060be81a313a01a27fc6e7c84c3110058b15b86773e47465e013`.
Definitions and acceptance identity match the actual first grader request seq353.
The report's own revision statements remain in the unchanged body.

Source evidence preserves all 15 successful grader source-tool observation records
at sequences 416, 420, 424, 428, 432, 436, 440, 444, 448, 456, 460, 464, 496, 500,
504. Each record's observation is JSON-equal to the corresponding public callback
tool content in its `received_in_request`; that original string's SHA256 also
matches. Tool arguments, page/source identities, structures, strings, repetition
and record order remain. Main explicitly accepted ordinary JSON serialization of
these complete records with no deduplication, summary or truncation. No report,
calculation, context or export tool observations are mixed in. Hashing additional
original files for provenance does not provide their unobserved content to the
model. Image references remain strings, with no newly attached images.

## Exact input difference and execution boundary

Both anonymous cases have identical commission/source/rubric/candidate strings:
507 / 233,636 / 2,272 / 18,934 characters respectively. Case IDs and receipt fields
are not serialized into model messages. A uses the existing037 neutral-message
format. B uses that exact same message followed only by the specialist's neutral
relationship request and three neutral object locations. The suffix is484
characters; full A/B user messages are278,167/278,651 characters, not token counts.

Frozen order is A=`cf0e383fe2c1`, then B=`051e6c85b549`. Target order in B is
X21, proposed site① slope height, R31. Locations are §4.3/Table4-1/X21,
§4.3(1)/Table4-1/X11, and §4.2(1)/Tables4-1–4-6/X31. No expected labels or
correct/incorrect descriptions accompany them. The oracle is neither opened nor
serialized by the preparation or runner. The sole actual message constructor is
`prepare_relation_verdict_diagnostic.model_message`; `input.json` saves exactly
the HumanMessage passed to the model, including B's suffix.

Both arms use `reviewer_prompt(requirement_acceptance=True)`, production
`GraderResponse`, and the existing037 `real_factory`, configured GLM-5.3/high,
unchanged adapter parameters, no retrieval tools and no author/revision loop.
The production role body is3,489 characters, SHA256
`340e74c063010a8957579a17ab2e9b20cd960e4858eb382e6f5521a86d70b2a4`.
Task040's actual initial system includes this same role body plus1,372 characters
of native TodoList middleware guidance; the fresh inline wrapper does not append
that unavailable-tool guidance. This is an explicit non-replay condition, not an
A/B difference. Actual settings and credential-free invocation parameters are
recorded alongside public I/O and available usage. No full agent result is dumped.

The runner refuses existing output for a fresh batch. Any cell error stops the
batch, retains public output/errors/usage, and never retries that cell. A recorded
diagnosis can authorize only the still-unattempted second cell after the first
cell has a saved error receipt; runtime/input/schema/order must still match.
The original failed cell remains unchanged, and the pre-continuation batch is
saved separately. Ambiguous partial writes without an error receipt and a failed
second cell cannot be replayed through this continuation path. Inherited adapter
transport behavior is unchanged; there is no added semantic retry or JSON repair.

## Offline evidence and Main's CLI

Executed using the installed WSL Ubuntu-24.04 `dysun` environment, without installing
dependencies:

```text
/home/dysun/.venvs/report-agent-system/bin/python -m pytest tests/test_relation_verdict_diagnostic.py tests/test_stance_diagnostic.py tests/test_broad_criteria_diagnostic.py -q
24 passed in 8.89s
```

The15 new tests plus9 reused tests cover source callback identity and rejection of
changed/non-grader/failed observations; retention of repeated source material;
complete original criteria equality; oracle-field rejection; exact B-only suffix
and deterministic frozen assignment; refusal to overwrite; exact actual model
message/public audit; malformed criterion coverage with retained usage/output;
failed first-cell preservation; changed-runtime continuation rejection; diagnosed
unattempted suffix only; and ambiguous batch exceptions without automatic replay.
These are execution/isolation tests, not evidence of model semantic quality.

Main's authorized execution command from repository root (not executed by this
worker):

```text
/home/dysun/.venvs/report-agent-system/bin/python scripts/run_relation_verdict_diagnostic.py --inputs .analysis/task042/frozen/model-inputs.json --output .runs/task042/relation-verdict-controls --authorization-note "<Main's authorization record>"
```

Only after an explicit Main diagnosis, the same command can add `--resume
--diagnosis-note "<Main's diagnosis>"` for an eligible unattempted suffix.

No new confirmed production defect is claimed here. The controls do not reproduce
the040 native tool trajectory, demonstrate autonomous evidence discovery, estimate
stable reliability, establish a training cause, repair the business report or
closeG1. Independent actual-input review and semantic evaluation are separate
evidence owned by Main/the specialist. A not mentioning a relation is merely
unobserved; it is not proof of incorrect internal recognition.
