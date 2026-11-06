# Writer reservation: offline experiment

This package records the reviewed forecast experiment after
`writer-context-repair-20261105` (`1a3770d`). It does **not** replace the live
request reservation or authorize a second HP02 probe.

- `candidate.py`: forecast calculation and strict response-usage diagnostic.
- `test_candidate.py`: 22 offline tests with networking blocked and fresh synthetic ledgers.
- `verification.json`: sanitized measurements and review disposition.

## Results and limits

The proposal is `min(1048576, ceil(local_input * 1.2) + 4096) + 65536`.
Nine hash-checked request bodies, counted with the pinned official GLM tokenizer,
produce forecasts of **74,170–88,276** tokens. All are below100K.
These values are forecasts, not a verified financial upper bound.

A synthetic test using the real `TokenBudget` and `ProbeBudget` classes admits
81,632 when prior usage is1,418,368. Provider usage of85,536 then leaves
**1,503,904 settled**, exceeding the hard1.5M cap by3,904 before response checking
can stop subsequent work. This demonstrates a flaw in the proposed promotion,
not an incident in the deployed runtime. A shadow forecast miss must not mark
an authoritative full-bound ledger row as a real bound violation.

**Disposition:** offline measurement and diagnostics accepted by independent
architecture and alignment review. Promotion of this empirical forecast to
`RequestBound` is blocked until the actual endpoint's input serialization,
bounded hidden overhead and output enforcement/tolerance are established.
Reuse the existing capacity-measurement interface once that serving contract exists.
The live reservation remains1,179,648. G5 is stopped; the unknown2M hold and all
historical records are preserved. Another probe requires explicit owner approval.

The provider contract also matters for output: [Alibaba's API documentation](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions/)
includes reasoning in `max_completion_tokens` and documents a possible10-token
discrepancy. That contract has not been established for the private endpoint.
A local tokenizer or repeated normal responses does not establish that contract.

The review's roughly25 requests and250–375K slope total are predictions.
The scripted replay does not establish real Writer behavior, engineering quality,
or completion cost. No paid model calls were made for this experiment.

## Reproduce the published tests

From the repository root, using its existing Linux environment:

```sh
PYTHONPATH=src python -B -m pytest -q docs/reviews/writer-reservation-offline-20261106/test_candidate.py
```

The tests supply synthetic counts; the nine real-material measurements are the
recorded local replay. Private request bodies, source documents, ledger records,
credentials and20MB tokenizer assets are intentionally not published here.
No runtime module imports this experiment. The initial red log was a missing-module
collection failure, not a behavioral regression. The22 behavioral tests passed
before publication and are rerun from this published path.

Full application regression was not repeated for this packaging-only change;
prior context-repair evidence remains applicable to unchanged runtime code.
