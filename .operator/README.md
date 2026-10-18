# Direct operator requirements

`instructions.json` contains confirmed direct requirements. The host loads it before normal report runs, using explicit report category and identity. This is separate from learned Experience candidates; no candidate is promoted here.

New CLI projects use `--report-category construction_safety_risk_assessment` and a stable `--report-id`. An optional `--instruction-pack` selects another host-owned pack. Unknown and other categories do not receive these category requirements. Agents and source quotations cannot choose applicability. Missing previously bound packs and version conflicts fail before models.

Edits require a larger pack version; changed instructions require their complete payload history and corresponding active version. Registry history and withdrawal receipts remain in each project. Import is restart-idempotent, and sync intents protect interrupted imports. Tool capabilities and source/ownership permissions do not expand.

Raw III/IV preference (“总体来说，评估结果控制在三级及以下。但是不能打四级。如果实在需要大四级，要说明原因”) is retained in the current validation scope as unresolved client intent. It is not an instruction to change source facts or force scores. Soil30m/rock20m quoted heights require actual guideline checking. The specific high-slope physical91 table clarification is bound only to this report. Other professionals must interpret their own applicable guides.

Loading is not semantic application or engineering acceptance. Verify effective inputs, chosen actions, real files and independent runtime review.
