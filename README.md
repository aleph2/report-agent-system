# Report Agent System

## Opening October release cases

To read a case that stores source files in the October release layout, use
the original private `regression-20261028-ocr-fake01` tag on a copy of the case.
It retains the original release manifest and validation record; the public tag
with the same name is a sanitized derivative. See [private records](docs/private-records.md).

## Current model request timeout (2026-10-24)

The native async model-call deadline is 600 seconds, including SDK work and parsing.
Constructed chat and vision clients use HTTP connect/read/write/pool timeouts of
15/600/60/60 seconds. Existing recovery and retry policies are unchanged; separate
attempts and a whole report run retain their own resource limits. Sync compatibility
clients have the HTTP phase timeout, not the async overall deadline. Newly built
processes/clients take this policy; saved historical requests and unknown outcomes
are preserved and must not be replayed to apply it. Dated settings below describe
their historical runs rather than the current timeout.

## Current runtime boundary (2026-10-27)

Fresh implicit native `init` uses the complete V4 contract bundle: separate task
descriptions, program-owned operation identity, concise prompts, reader expression,
stateful context with complete review materials, executable review work units and
task-local submission selectors. Explicit historical profiles stay explicit; reading
or reinitializing an existing case does not silently upgrade its contracts. Model and
effort settings remain separately configured; this does not select a new model.

The four report roles share the DeepAgents runtime and ownership/trace/recovery
mechanisms. Their task histories, permissions, tools and applicable business contracts
differ. Summary activity belongs to the actor whose history is summarized even when
it uses the coordinator model service. Default per-run model clients are cached and
closed by their creating host; an injected factory retains client ownership.

Each fresh execution owns its writable inputs, state, checkpoints and outputs. Managed
fixtures and independent durable source/financial stores may be reused; another run's
temporary directory must not be a live dependency. Only rounds03–06 were retained in
`.runs` after authorized cleanup. Older paths below are historical descriptions, not
current dependencies, available recovery backups or instructions to restore retired runs.

Current review evidence is in `.analysis/round06-reviewer-rootcause-20261027` and
`.analysis/unified-r06-implementation-20261027`. No new report execution is implied.

## Private historical recovery records

Old handoffs, cleanup commands and their original verification records are retained
in the private archive described in [private records](docs/private-records.md).
They are historical evidence, not current execution or restart entry points.
Read old cases on copies with their original private tagged code. Never overwrite
an online database or replay an unknown paid request to inspect its history.

Independent greenfield prototype, not a modification or wrapper of the previous
highway-report application. The current increment implements outcome-task coordination,
shared results, a versioned source library, producer corrections, draft/review,
deterministic DOCX export and a local desktop workbench.
It is not yet accepted as a production report product or engineering deliverable.

## Architecture

Current execution boundary (2026-10-14): agents choose goals, evidence, strategy
and actions; independent bounded tools produce substantive text/comparisons.
Writer commits exact owned tool output, Reviewer uses bounded comparisons, and
Learner retains strategy formulation. See [current tool and observation contracts](docs/independent-text-tools.md).
Older non-hierarchical/ADK/native-rubric execution is inactive; saved history and
exports remain readable. Historical descriptions below do not authorize replay.

- [Current system architecture](ARCHITECTURE.md): versioned structured content,
  a content tree with cross-node relations, local and upper-level review, export
  fidelity and rendered-page checks. Handoff creation is separate from choosing
  its assignee or next action. The opt-in `hierarchical-review-v1` backend now has
  immutable content snapshots, persistent review feedback, native revision/recheck,
  DOCX mappings and actual page rendering. See [implementation and verification limits](docs/hierarchical-review-implementation.md).
  Real-model quality acceptance and the new content UI are still pending.
- The 2026-09-30 [quality design update](.ase/054-evidence-centered-quality-design.md)
  makes evidence-based automatic review feedback the core of the delivery loop,
  including bidirectional coverage, semantic provenance, versioned document anchors,
  correction regression and honest stopping. Its [discussion coverage](.ase/054-discussion-coverage.md)
  records all adopted topics and research limits. This is a target design; the
  implementation gaps are explicit and no runtime change is implied by this entry.
- New project report runs use the versioned hierarchical contract. The coordinator saves
  versioned standards before production; authors explicitly adopt the same version,
  and the delegated reviewer chooses its evidence-gathering strategy and tools.
  Every criterion has a located assessment: satisfied, not satisfied or undetermined.
  Uncertainty alone does not force an author revision or count as a pass. Existing
  runs retain their historical policy. See [responsibilities and limits](.ase/030-acceptance-design.md).
- DeepAgents 0.7.19 owns the model/tool loop, delegation, context management and
  LangGraph checkpoint recovery. Application code does not schedule semantic stages.
- Code tools expose source reading, literal search, task state, issues and committed results.
- Independent text tools make bounded model requests and return to the agent.
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
- The coordinator decides goals and delegates substantive report production to the
  Writer's independent text tools. Roles are available profiles, not mandatory stages.
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

### Restore and stage the current report system

Use a clean checkout of the saved commit in WSL/Linux with Python 3.12:

```bash
python3.12 -m venv /path/to/report-venv
/path/to/report-venv/bin/python -m pip install -c requirements.lock '.[test]'
. /path/to/report-venv/bin/activate
```

`config/current.json` is the single maintained configuration for the report host:
the existing role models and report interfaces, 600 seconds per attempt, at most
three attempts, SDK/connect retries disabled, and a separate 200,000,000-token
round limit including used and unresolved reservations. `requirements.lock` pins
the installed runtime dependency versions used for offline restoration checks.
No new agent prompts or two-file prompt loader changes are part of this release.

Supply the private original documents independently and place provider credentials
in this checkout's `.env`. Neither credentials nor real documents, old checkpoints,
old financial databases or former `.analysis` directories are needed from Git.
The file must contain the existing `HIGHWAY_MODEL_DEEPSEEK_NAME/BASE_URL/API_KEY`
and `HIGHWAY_MODEL_NAME/BASE_URL/API_KEY` bundles; names must match current.json.
It may retain the existing role generation settings; the host verifies effective
settings before sending. Missing credentials are an error, not a fallback to legacy.

For this report, the input directory contains the same eleven original documents,
including `报告编写范围说明.md` and exactly one format-reference PDF under `成果报告/`.
Input hashes and PDF limits are measured from these originals during staging;
they are not borrowed from an older run. Use new independent runtime and ledger
paths, outside the checkout and input directory. Existing paths are not overwritten.

```bash
python scripts/stage_report.py --revision COMMIT_ID --inputs /path/to/originals \
  --run /path/to/new-run --ledger /path/to/new-finance/token-budget.db \
  --authority 'reference to the actual user authorization for this run'
python scripts/prepare_report.py --run /path/to/new-run
```

These two commands deny Python network connections and do not invoke models.
Stage uses `git archive` of the explicit commit, including its original prompts;
uncommitted or untracked prompt changes in the working directory cannot enter it.
The run's source and configuration are immutable execution snapshots, not another
maintained configuration. `deployment.json` records paths and commit identity only.

Before any paid launch, independent review must create `neo-approval.json` in the
new run with `approved: true`, the exact `host_sha256` and `prepared_sha256`.
Neither staging nor preparation fabricates that approval. Check without starting:

```bash
python scripts/launch_report.py --run /path/to/new-run --check
```

Only a separately authorized launch omits `--check`. This preservation work did
not launch the report. A prior launch intent, start, checkpoint or terminal record
blocks repeat launch; these scripts do not resume historical checkpoints or replay
unknown requests. A pre-existing canonical ledger is checked for preservation;
its absence does not prevent a fresh independently budgeted case.

Offline restoration verification (synthetic inputs, SDK mocks, no paid calls):

```bash
PYTHONPATH=src python -B -m pytest -q -p no:cacheprovider \
  tests/test_authorized_three_attempt_recovery.py \
  tests/test_large_search_public_return.py tests/test_restart600_host.py \
  tests/test_report_release_restore.py
```

This verifies startup mechanics and the two repairs. It does not establish actual
provider availability, report quality or safe resumption of an interrupted old run.

Provider credentials live only in this repository's root `.env` (Git-ignored),
moved from the retired legacy project's configuration location on 2026-10-31.
Hosts using `load_mixed_services` read this file explicitly; tools accepting
`--env-file` must receive this path. The CLI still consumes process environment
variables; it does not automatically load `.env`.
Historical frozen run directories retain their original hosts and configuration
paths as execution evidence. They are not restart entry points after this move;
do not rewrite their approval hashes or replay their pending requests.

Run release regressions from a detached worktree at the tested commit. Pytest removes passing temporary cases and retains the latest failed run. For parallel runs, set `PYTEST_DEBUG_TEMPROOT` to a stable, existing project directory per shard and let pytest create its numbered subdirectory. Create test databases under `tmp_path` or `tmp_path_factory`. Put results and coverage outside scratch. Passing `--basetemp` disables automatic rotation across runs.

Use a separate virtual environment; install with `python -m pip install -e '.[test]'`.
The historical ADK test fixtures additionally require `.[historical-tests]`; they
are retained as prior evidence, not the new report execution architecture.
Activate the project virtual environment selected for your machine before running these commands.

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
report-agent content-delivery --project .runs/example --output report.docx
# Historical saved drafts remain exportable; diagnostics are explicit:
report-agent export --project HISTORICAL_CASE --draft-id SAVED_DRAFT_ID --execution-record
# Observe chosen work before its text tool executes; agent inference still costs:
report-agent report-run --project ISOLATED_DECISION_CASE --decision-only
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

Recovery has separate boundaries: opt-in bounded physical model-request recovery,
supported direct-child checkpoint recovery, and root `report-run` reentry. A pending
native delegation reservation can block root reentry; direct-child recovery tests do
not prove transparent whole-report resume. Preserve unknown outcomes and their holds;
do not replay them to obtain a fresh result. An already reviewed current delivery may
return without a model call. Human interrupts require an explicit issue decision before
resuming. The earlier `run` command is a historical materials
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


### Complete bound Reviewer materials (fresh projects)

For a new native V4 case, select `context_policy: stateful-tools-v2` and
`context_projection: review-materials-v1` in its manifest. The existing immutable
projection binding rejects switching an executed case. Other roles retain their
current views. Reviewer receives the exact saved Snapshot closure, complete
standards/original requirements and scope links, with one payload per object version.
Original data and ranged recovery tools remain available; ordinary history may be
compacted. Artifact files/images still need the existing inspection tools. Supplied
data creates no read/check/review receipt and never implies acceptance.

This simple mode sends the complete bound business packet on each Reviewer decision;
it does not guarantee arbitrarily large material fits. Existing whole-request capacity
admission applies, with no silent trimming. Use a fresh, separately authorized validation
to assess real model behavior, latency and token cost.

Optional `REPORT_REVIEWER_REASONING_EFFORT=high` selects Reviewer alone for a fresh
compatible DeepSeek service. It uses the existing immutable generation binding;
unset preserves the previous behavior and other roles retain their own settings.
It does not change an old case, authorize a retry, or establish equivalence with max.

### Sanitized public history

Public tags in this candidate are sanitized derivatives, not the original accepted
or tested commit hashes. Historical case recovery uses the original private bundle
and its original tags, on a copy of the case. See [private records](docs/private-records.md)
and [the candidate review](docs/reviews/privacy-candidate-20261109.md).
