# Task008: Current-account vision capability

User authorized deepseek-v4-flash on the currently configured account for optional
visual understanding and OCR. GLM5.3 remains the decision model. Reuse existing OCR;
do not resume Task007, run bulk OCR, change legacy code/config/data or change provider.

Main first validates the decisive assumption: the current provider accepts actual
image input for the requested model. Current account is Alibaba Cloud Model Studio;
its model list exposes deepseek-v4-flash-0731, not the unsuffixed requested name.
The provider docs describe this as text-only, unlike DeepSeek's own current endpoint.

Run a bounded synthetic image probe (no engineering source data), record request
intent and result, disable retries, and distinguish rejected/unknown responses from
successful visual recognition. Do not implement a nonfunctional tool merely to
claim completion. If supported, add a thin project-bound optional tool, retaining
provenance and existing ownership; no new agent, fixed OCR stage or runtime loop.

Independent alignment reviewer: Anscombe (01a0e33c-c20e-7493-b090-1912cc5cf60f).
Evidence: scripts/probe_vision008.py and .runs/task008/vision-probe.json.
This is capability validation, not report acceptance or engineering sign-off.

Official references checked 2026-09-28:
- https://api-docs.deepseek.com/guides/vision/
- https://www.alibabacloud.com/help/en/model-studio/deepseek-api
- https://docs.modelstudio.console.alibabacloud.com/en/model-studio/deepseek-v4-flash

## Updated authorization and decisive evidence

User subsequently specified deepseek-v4.1-flash. Same-account synthetic probe passed:
random image-only nonce, left red square and right blue circle recognized, provider
reported 212 image tokens. Exact v4 alias returned 403; listed 0731 returned text
explicitly saying it could not see the image. No fallback was silently substituted.
Proceed with v4.1 optional tool. Source SHA/page/crop and response metadata retained;
successful same-question observations cached separately from original/OCR/graph data.
GLM agent roles and ownership remain unchanged. No current report resumed or deployed.
