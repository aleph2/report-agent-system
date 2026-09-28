# Task008: Optional vision/OCR capability verification

Date: 2026-09-28. Latest explicit authorization: use deepseek-v4.1-flash on the
current account for visual capability. GLM5.3 still controls report agents.

## Outcome and boundary

Implemented a single optional analyze_source_image tool available to the existing
four role profiles. It accepts a project source ID, purpose/question, physical PDF
page or single-image page 1, and optional normalized region. It uses actual image
input rather than OCR text disguised as an image test. No added runtime agent,
mandatory OCR stage, semantic pipeline, graph mutation or report auto-resume.

Rawls implemented project-bound PDF/image rendering and image intake. Main added
the bounded model tool, configuration, registration, tests and synthetic live trials.
Anscombe independently reviewed architecture boundaries and implementation.

Existing source originals, frozen OCR and Task007 results/checkpoints remain intact.
The visual response cache is derived analysis, not a source replacement or accepted
fact. Adoption into knowledge remains an explicit producer action. No arbitrary
path/URL or credentials/model parameter is exposed to agents. No legacy code/config
or writable storage changes. The existing credential loader reads the already
authorized service settings without exposing the key; this is not a legacy business
implementation dependency.

## Decisive provider evidence

- Current endpoint model listing exposed deepseek-v4-flash-0731.
- Requested unsuffixed deepseek-v4-flash: HTTP403 AccessDenied.Unpurchased.
- Listed deepseek-v4-flash-0731: HTTP success, but explicitly could not see the image;
  nonce recognition failed. Transport success alone was not accepted as vision proof.
- User then selected deepseek-v4.1-flash. Same endpoint returned the image-only random
  nonce and correct left red square/right blue circle; 212 image tokens reported.
- Evidence retained separately in .runs/task008/vision-probe.json and
  .runs/task008/v41/vision-probe.json. No blind retries or unapproved model fallback.

Official DeepSeek docs describe image inputs, while Alibaba's older v4/0731 model
docs list text-only input. Exact endpoint/model live evidence decides this integration;
do not generalize the probe to every deployment of similarly named models.

## Verification

- First focused suite: 74 passed before review corrections.
- Registered tool real trial, first implementation: two logical visual requests
  (fresh image-only PDF OCR and a cropped raster observation), plus cache reuse.
  Nonce and both numeric values found; visual description correct; source snapshots
  unchanged and no published result created. .runs/task008/registered-tool/result.json.
- After replacing the LangChain visual request with direct SDK invocation and
  strengthening protocol-error handling: 79 focused tests passed.
- Full suite final: **536 passed, 9 skipped**, 56.67s; one existing experimental
  historical ADK warning. The skipped tests are not counted as successful evidence.
- Final direct-SDK registered-tool trial: **passed**, two logical requests plus one
  same-request cache hit. Image-only PDF nonce BCBC5E33, table A=28.9 m/B=38.0 m,
  cropped left red square/right blue circle recognized. Provider reported 562 and
  282 image tokens; both responses name deepseek-v4.1-flash. Source snapshots unchanged,
  no published results, no report resume. Evidence:
  .runs/task008/registered-tool-sdk/result.json.

Synthetic observations do not prove Chinese engineering-drawing accuracy, autonomous
choice of this tool, whole-document OCR coverage, report quality or engineering sign-off.
The PDF rendition is up to 144DPI/4096px; cropping a PDF rendition does not add detail.
Backend/CLI image intake works; existing desktop upload picker still lists TXT/MD/
DOCX/PDF only. Report preview is still structural/textual; this increment does not
add rendered report-page vision. No running server deployment/restart occurred.

## Review findings and Main disposition

1. Potential P1: inherited LangChain callbacks/tracing could capture image payloads.
   No exposure observed; synthetic inputs contained no engineering data. Blocked real
   engineering-image calls on that path. Main replaced it with plain OpenAI Async SDK
   calls and local provenance-only request audit; no model callback path remains.
2. P2: refusal, unexpected tools and a different returned model could enter the cache.
   Main added protocol-only non-success handling and tests; no semantic keyword gate.
3. P2: expected visual configuration/response failures could abort the agent run.
   Main returns sanitized failure observations and tests missing config; cancellation
   is not swallowed. SDK alone retries transient requests, not entire agent tasks.
4. Potential P1, same audit boundary: OpenAI SDK DEBUG options can include images.
   Main added a coroutine-scoped SDK logger filter and an actual AsyncOpenAI/local
   MockTransport regression checking request image presence but no image/question/key
   in DEBUG logs. Outside-call logging remains intact. Anscombe accepted this narrow
   closure after source inspection; did not independently run tests or paid calls.
5. P3 test reliability: initial full suite had 534 passed/9 skipped/one failed existing
   export test because its literal date count also matched today's audit timestamp.
   Main narrowed the assertion to the two exact compilation-date paragraphs, retaining
   cover/title expectations. Export implementation unchanged. Final suite passed.

Main accepts independent review: no hidden micro-workflow, source permission expansion
or unresolved image-audit blocker found in this scope. No claim that testing proves
semantic correctness of all visual responses. This increment is implemented and
verified in new processes; the existing GUI server has not been restarted/deployed.

Failures/incomplete responses are not saved as successful observations. Source
validation errors make no paid call. A normally completed response is still model
interpretation, not independently proven recognition or correct engineering facts.
