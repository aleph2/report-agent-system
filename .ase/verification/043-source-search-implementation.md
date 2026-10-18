# Task043 source-search view implementation

2026-09-29. Worker `/root/review_fork` implemented only
`src/report_agent/source_search.py`, `src/report_agent/deep_runtime.py`,
`src/report_agent/review.py` and `tests/test_source_search_view.py`, plus this record.
Main owns safe preparation, scripts, actual execution, freezing and integration.
The accepted design and pre-implementation alignment are recorded in
043-source-observation-native.md. No model/network/credential calls, original data
changes, paid experiment or private checkpoint/reasoning inspection occurred in
this implementation work. All test workspaces, PDF sources and model responses
were synthetic and temporary.

## Result and API

The new `source_search.py` keeps search matching separate from observation
presentation. Unconfigured projects retain the exact existing full-table result.
`search_sources(query, offset=0, limit=10, source_id=None, table_detail=None)` accepts
`references` or `full`; None uses the bound project default, otherwise full.
Explicit full always calls the existing `with_source_tables` path, including its
existing optional compact-table behavior. No second geometry implementation exists.
`read_source_page`, `inspect_source_page`, Catalog search, source permissions,
matching text, ordering and pagination remain unchanged.

Trusted preparation uses:

```python
from report_agent.source_search import configure_source_search, bind_source_search

identity = configure_source_search(workspace, default_table_detail="references")
# {"version": "source-search-view-v1", "default_table_detail": "references"}
assert bind_source_search(workspace) == identity
```

Configuration is stored at `source_search_view`, its immutable binding at
`source_search_binding`. Configure requires a clean-import receipt explicitly
excluding copied outcomes/reviews/feedback/issues/graph/checkpoints/new OCR, one
newly selected draft, no review results/targets, prior model/attempt events,
runtime/checkpoint state or legacy context experiment. An existing checkpoint file,
including an empty one, is deliberately refused at this preparation boundary.
Both configuration and binding plus the bound-event record are written together
in a transaction under the existing run lock. Repeating the same trusted request
is idempotent; changing/removing configuration is rejected.

The binding records the initial draft ID and digest of `clean_import`. Main must
finish any safe-import audit update to that receipt before configuration, then
record the returned identity in separate preparation/freeze records. Binding does
not require a particular `candidate-import.json` schema. These functions are not
agent tools; the agent can choose an observation view, not change its project
binding, role or source authority.

## Truthful deferred access and native identity

References retain the complete Catalog result and add one reference per explicitly
located source/physical page, preserving first occurrence order. They reuse
`physical_page_number`, do not infer pages from block ordinals, and preserve
unlocatable entries separately. Each reference contains source ID, source-version
metadata SHA, physical page, inspect tool/arguments, `status=not_expanded`,
`extraction_status=not_extracted` and `original_bytes_verified=False`. It explicitly
says source bytes have not been rechecked or table presence established by this
view. Missing metadata SHA remains None, not a fabricated hash.

No PDF is opened or table extraction performed on the references path. The original
hash/membership/path/page checks still execute on full or inspect access. The
response says omission does not establish missing tables/information, and exposes
both direct inspection and `table_detail='full'`. No semantic summary, new OCR,
known-error target, fixed inspection order or cross-call audit deduplication is added.

`native_review` validates the binding directly at construction and when preparing
the attempt; `run_report` also validates before model construction. Configured
native targets include `source_search_view`; review projection requires that exact
identity. Thus a satisfied result without this identity cannot be reused as this
candidate's result. With no configuration, no new target field is added and old
full-mode projection remains compatible. Neither production role text nor original
criteria nor the GraderResponse contract changed; no legacy calibration/context
flag is needed or enabled.

## Offline evidence

Installed WSL Ubuntu-24.04 / `dysun` environment, no dependency installation:

```text
/home/dysun/.venvs/report-agent-system/bin/python -m pytest tests/test_source_search_view.py -q
14 passed in 12.16s

/home/dysun/.venvs/report-agent-system/bin/python -m pytest tests/test_source_search_view.py tests/test_source_tables.py tests/test_document_tools.py tests/test_compact_tables.py tests/test_evidence_tools016.py tests/test_review_context.py tests/test_acceptance_runtime.py -q
160 passed in 73.63s
```

The focused cases verify exact old default/full equality; all original matched
text/paging retained; deferred access does not run PDF extraction; cross-page
locators and unlocatable entries; page-only deduplication without deleting matches;
unchanged read/inspect results; stale original hash rejected through full/inspect;
cross-project source rejection; fresh-only/idempotent/immutable configuration;
direct native target identity; old unconfigured target compatibility and stale
identity exclusion. A real native graph with an offline scripted model chooses
default references then explicit full and consumes the original table rows; its
tool schema contains the view choice but no configuration tool. This proves
interface mechanics, not model autonomy or semantic quality. All network entry
points used by the synthetic native model test are denied.

`git diff --check` on the two modified tracked runtime files passed. Git's existing
Windows LF/CRLF notice is not a changed source-data hash or a test failure.

## Review and limits

Independent `alignment_review` was asked to review the implementation and focused
tests after the initial14-test pass and received the final160-test evidence. Its
completed focused review found no new necessary correction or blocker: truthful
deferred/unverified-original states, complete matches/paging, explicit full access,
unchanged read/inspect, fresh configuration and target/recovery binding agree with
the confirmed scope. It independently noted that native synthetic tests establish
callability, not quality improvement. Main records the integration disposition.

The user's subsequent priority is a separate model-switch test using042B after
the user updates interface configuration. Accordingly043 implementation, tests
and records are retained without running the candidate or expanding its scope.
This closes the already-requested implementation review only; no new model call
or additional work was started.

No new confirmed production defect was discovered by these checks. The existing
P2-043-A01 baseline SQLite-read containment is owned and corrected by Main's safe
preparation path, outside these files. Main must freeze/review the integrated
candidate before actual use. Deferred evidence can require an extra agent-chosen
call and can be overlooked; smaller responses do not establish improved judgment.
One native grader probe has no author loop and cannot completeG1 or engineering
acceptance. No further tests/calls are implied by this implementation record.
