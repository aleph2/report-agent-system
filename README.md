# Report Agent System

Independent greenfield prototype, not a modification or wrapper of the previous
highway-report application. The current increment implements outcome-task coordination,
shared results, a versioned source library, producer corrections, draft/review,
deterministic DOCX export and a local desktop workbench.
It is not yet accepted as a production report product or engineering deliverable.

## Architecture

- [Current system architecture](ARCHITECTURE.md): versioned structured content,
  a content tree with cross-node relations, local and upper-level review, export
  fidelity and rendered-page checks. Handoff creation is separate from choosing
  its assignee or next action. These are design changes; new capabilities remain
  to be implemented. Existing prototype behavior and history are described below.
- The 2026-09-30 [quality design update](.ase/054-evidence-centered-quality-design.md)
  makes evidence-based automatic review feedback the core of the delivery loop,
  including bidirectional coverage, semantic provenance, versioned document anchors,
  correction regression and honest stopping. Its [discussion coverage](.ase/054-discussion-coverage.md)
  records all adopted topics and research limits. This is a target design; the
  implementation gaps are explicit and no runtime change is implied by this entry.
- New project report runs use requirement-derived acceptance. The coordinator saves
  versioned standards before production; authors explicitly adopt the same version,
  and the native acceptance agent chooses its evidence-gathering strategy and tools.
  Every criterion has a located assessment: satisfied, not satisfied or undetermined.
  Uncertainty alone does not force an author revision or count as a pass. Existing
  runs retain their historical policy. See [responsibilities and limits](.ase/030-acceptance-design.md).
- DeepAgents 0.7.19 owns the model/tool loop, delegation, context management and
  LangGraph checkpoint recovery. Application code does not schedule semantic stages.
- Code tools expose source reading, literal search, task state, issues and committed results.
- The optional text-analysis tool makes one bounded model request and returns to the agent.
  It cannot write artifacts, delegate agents or fetch extra data.
- The optional `analyze_source_image` tool uses `deepseek-v4.1-flash` on the same
  configured account for a stated visual/OCR question. GLM5.3 remains the agent model.
  It reads hash-verified project PDF pages or single PNG/JPEG/WebP images, optionally
  cropped. Located observations are cached separately; existing OCR and shared facts
  are not overwritten. This is not a mandatory OCR stage or whole-document coverage.
  The bounded call uses the OpenAI SDK directly, avoiding inherited model callbacks
  containing base64; local audit records provenance, response metadata and usage.
- Immutable source snapshots, artifacts, receipts and observations live in the new project's
  own SQLite store. File locking serializes project runs; a thin tool middleware
  serializes business actions. Native AsyncSqliteSaver persists conversation and
  pending execution in `checkpoints.db`; business commits retain separate receipts.
  Shared indexed facts/relations live in a separate Neo4j with local multilingual
  embeddings. Original sources and derived summaries remain distinguishable.
- Source intake stores original bytes and located extracted text in one transaction.
  TXT/MD use UTF-8; DOCX body/table text and PDF page text are explicitly partial.
  No OCR is triggered. Upload limits reject the document, not truncate it. Current
  parser resource checks are not a hard memory/CPU sandbox for hostile documents.
  Backend/CLI intake also accepts PNG/JPEG/WebP as image-only partial sources;
  the current desktop upload picker still lists text, Word and PDF extensions.
  OCR is an optional agent tool call after intake, not part of the upload transaction.
- Literal source search and paginated reading return positions, unread continuations
  and limitations. Synonyms/evidence meaning remain expert judgments. Shared results
  can be searched and read on demand; the coordinator starts with metadata.
- A revision is a new task bound to the original result's producer. It commits a new
  immutable version and a receipt; old versions remain available. Known consumers
  become outdated, not automatically rerun. New source relevance is assessed by the
  coordinator, including possible effects beyond previously recorded consumers.
- The coordinator can compose directly or delegate to knowledge, writer and reviewer
  capabilities. These are available permission profiles, not mandatory stages.
  The default general-purpose subagent is disabled. Scratch files use StateBackend,
  with no host filesystem or shell access. Downstream roles cannot change knowledge.
- No purpose/plan/materials submission chain is required. Source use and report
  structure are agent judgments. Reviews name an observed exact draft version.
  Reading a result does not automatically make it an adopted dependency.
- Source issues and operator decisions are recorded separately from immutable results.
  Only explicit operator action closes a human issue. Recording a decision alone does
  not close it. Context changes invalidate an older review; UI and export use the same
  latest review of the selected draft. System failures are not missing-source judgments.

## Run (WSL/Linux, Python 3.12)

Use a separate virtual environment; install with `python -m pip install -e '.[test]'`.
The historical ADK test fixtures additionally require `.[historical-tests]`; they
are retained as prior evidence, not the new report execution architecture.
The development environment is `/home/dysun/.venvs/report-agent-system`.

```bash
report-agent init --project .runs/example --manifest examples/materials-new.json
report-agent status --project .runs/example
python -m pytest -q
```

For the report path, add a source-ID keyed `document_uses` object to a manifest when
the operator already supplied that basis. Without it, the coordinator may request
purpose work. Initialize in a separate directory, then use:

```bash
report-agent report-run --project .runs/example
report-agent report-status --project .runs/example
report-agent serve --project .runs/example --port 18140
report-agent export --project .runs/example --draft-id SAVED_DRAFT_ID
report-agent import --project .runs/example --file /absolute/path/notes.docx
# Explicitly replace a current source version while preserving its history:
report-agent import --project .runs/example --file /absolute/path/notes.docx --replaces-id SOURCE_ID
```

The web server binds only `127.0.0.1`; this is not a multi-user authenticated service.
Opening/polling/downloading never launches models. Start/continue is an explicit action.
The desktop UI shows actual agent/tool activity, failures, human interruptions and
saved outcomes. It does not turn log counts into a progress percentage or guess ETA.
Do not expose this prototype server to other machines.

Reproducible **offline protocol fixture**, without provider requests:

```bash
python scripts/run_offline_report.py --project .runs/offline002
report-agent serve --project .runs/offline002 --port 18140
```

This uses the actual ADK dispatch with a deterministic scripted model from the test
fixtures. The chosen actions and report text are scripted, not autonomous quality
evidence. The GUI labels the fixture and disables provider execution for this store.
`--attention` creates a separate error/human-input test scenario in a new directory.

The source-library/revision fixture uses a fresh project directory:

```bash
python scripts/run_offline_library.py --project .runs/library-example
report-agent serve --project .runs/library-example --port 18140
```

It checks file intake, source reading, producer correction, selective draft revision,
exact-version review and export. A further unrelated source addition is assessed
without regenerating the report. These decisions are scripted, not model-quality proof.

For an authorized live invocation provide `REPORT_MODEL=glm-5.3`, `REPORT_BASE_URL`
and `REPORT_API_KEY` in the process environment, then run
`report-agent report-run --project .runs/example`. Do not commit secrets. The application
does not read the legacy application's config or code. All example documents are synthetic.

`report-run` resumes pending native checkpoints after failure, or returns an already
reviewed current delivery without a model call. Human interrupts require an explicit
issue decision before resuming. The earlier `run` command is a historical materials
prototype, not the current report path. `events` prints local protocol evidence, which may contain input text;
do not publish it as ordinary user progress. `.runs/` is ignored by Git.

Task006 uses the native runtime. `scripts/run_deepagents_trial.py` is a development
launcher that may explicitly read only the three authorized GLM service settings
from an existing container into memory. `--serve` starts only the workbench; it
never starts a report. The regular application still uses process environment.
Actual sources and frozen OCR are imported read-only by `scripts/import_verified_sources.py`;
legacy report/plan outputs are not imported.

Reports explicitly adopt immutable `fact_ids`. Delivery, export and report-status
check their current graph status. Graph failure makes validity unknown, not a missing
source. Producer reassessment of changed graph versions is not implemented yet;
changed references remain marked for attention without automatic rewrite. A local
model review and successful DOCX export are not engineering acceptance.

Explicit operator feedback reopens the task and keeps existing materials immutable:

```bash
report-agent feedback --project .runs/example --feedback "Add the supported timing limits."
report-agent run --project .runs/example
```

Feedback is operator input, not a model tool. It cannot be added while a worker holds
the project lock. Old results remain available; only the current selection is cleared.
For `run`, exit 0 means a draft was selected without execution errors, 1 means execution
failed/interrupted, and 2 means attention is needed or a committed result has a trailing
execution error. None of these codes constitutes a semantic review. A completed result
can be read again without loading provider credentials or making a model request.

## Evidence and limitations

Historical ADK evidence is retained in `.ase/verification/001-prototype.md`,
`.ase/verification/002-report-trunk.md` and `.ase/verification/003-shared-library.md`.
The scripted fixtures establish protocol, ownership and persistence behavior, not
autonomous report quality; Tasks002/003 made no provider calls. The earlier ADK path
used disabled SDK retries (`num_retries=0`), a shared wrapper with up to three attempts
for selected transient HTTP failures before response emission, a 180-second request
timeout, a 1800-second task timeout and a three-occurrence identical-action guard.
Those settings describe the historical path only.

Task006 uses native DeepAgents 0.7.19 with SDK `max_retries=2`. HTTP timeouts are
connect 15 seconds, read 1800 seconds, write 60 seconds and pool 60 seconds;
there is no task deadline or cumulative call/token quota. Native LangGraph
checkpoints persist conversation and pending execution for recovery, while business
receipts protect committed writes. This does not promise exact replay of hidden
model reasoning. A separate Neo4j stores shared facts and relations with local
multilingual semantic vectors and full-text retrieval. Literal source-library
search remains a distinct capability. Graph mechanics and real local vector checks
are recorded in `.ase/verification/006-knowledge-evidence.md`.

Task006's `synthetic-reuse-fixed` live run produced a model-reviewed synthetic draft
and DOCX export using 13 GLM5.3 requests/responses and 85,617 reported tokens.
Its two-page DOCX was rendered with the existing Windows LibreOffice installation
and visually checked. This rendering evidence covers that synthetic export only;
the earlier LibreOffice-unavailable observation was a PATH discovery issue.
It does not verify a real-material report's layout, completeness or engineering quality.

Nine original documents and 1,530 pages of existing extracted text (977 native-text
pages and 553 OCR pages) have been independently imported for the real-material
trunk, without rerunning OCR or changing legacy
services or data. These intake counts do not establish that all evidence was read,
retrieved or correctly used. Real-material trunk verification remains required.
Consult `.ase/verification/006-deepagents-integration.md` for run-specific evidence
and review disposition; this README is not a live record of the actual run's state.

The prototype is not a multi-user authenticated service. Large-scale retrieval
performance, OCR/image extraction beyond the reused inputs, richer document
formatting and production Word layout require further validation. DOCX export
currently uses basic paragraphs and headings. A committed correction does not prove
semantic accuracy, and unresolved source issues must remain explicit. Model review,
synthetic success and a rendered export do not constitute engineering acceptance.
