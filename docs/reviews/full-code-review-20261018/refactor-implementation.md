# Agent/tool boundary refactor — first implementation increment

Neo leads design and independent review; Codex Main implements. This increment addresses the decision-result boundary, assigned review identity and comparison permissions, and deterministic document rendering. It does not close the entire code-review inventory or establish customer acceptance.

## Platform responsibilities and application responsibilities

The implementation retains the installed DeepAgents/LangChain agent loop, native tools, `ToolMessage`, `AgentMiddleware`, and filesystem offloading. There is no second agent scheduler, semantic workflow inside a generic tool, or additional summarization model.

The application owns immutable business versions, actor permissions, exact original tool returns, and explicitly declared review scope. The agent chooses actions from its goal and the returned observations. Independent text tools perform substantive text work; their actual qualifications and unfinished work must reach the deciding agent.

Neo's installed-version/source investigation and design decisions are in [refactor-design.json](refactor-design.json). Relevant official platform references: [middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom), [tools and artifacts](https://docs.langchain.com/oss/python/langchain/tools), and [unit testing](https://docs.langchain.com/oss/python/langchain/test/unit-testing). Platform support does not by itself verify this application's effective inputs; the tests inspect the actual graph and adapter boundary.

## Implemented changes

| Area | Previous mechanism | Current responsibility and evidence |
|---|---|---|
| Decision observations, NFR-01 | Several recursive projections shortened fields and could hide late qualifications. Program-side artifacts did not establish model visibility. | One public-result representation at the existing middleware boundary. Explicit reads are complete as returned before native offloading. Producer body adoption uses exact receipt/index; qualifications, generation notes, reviewer findings and incomplete checks remain visible. Final model-facing messages are checked after middleware and OpenAI message serialization. |
| Large read results, RF-A01 | Control restoration could put whole offloaded bodies back into the context. An initial test incorrectly expected that behavior. | Only after native offloading, declared source/body data paths become explicit deferred references. Other fields, including nested table extraction errors and limitations, remain unchanged. Exact actor-owned originals remain recoverable with hashes. A read receipt proves the tool returned data; it does not prove the model read deferred data. |
| Review comparison, NFR-02 | The assignment admitted an exact historical read, but saving its resulting review rejected the same dependency. | An explicitly assigned historical ContentNode version can be a dependency after the current reviewer actually reads it. Targets and criteria must still belong to the selected snapshot. No snapshot extension, arbitrary version, foreign receipt, or retroactive read authorization. |
| Review addressing, NFR-03 | Assignment and checker addressed a scope differently. | Shared target/criterion/scope/kind identity; new task scope labels must be unique. Ambiguous assignment is rejected before checker dispatch. Historical task hashes are not rewritten. |
| Directory, NFR-07 | Each nested report node could insert a full document TOC. | Only the root report emits the document directory. Original content nodes are unchanged. Actual DOCX XML is checked. |
| Paragraph formatting, NFR-08 | Exact-line formatting took a separate text path and could lose Markdown images or inline semantics. | Parse and render Markdown once, then apply typography to the resulting paragraphs. Image, bold, link, list, table and code behavior are exercised. Explicit heading boundaries preserve inline parser state. |

The paragraph selector has one intentional, limited semantic adjustment: ordinary line selectors style their existing rendered paragraph. Conflicting styles selecting the same rendered paragraph are rejected explicitly. An explicit `heading_level` still creates the requested heading boundary. This is not a claim that every historical layout behavior is identical.

## What the fake LLM verification exercises

- Native agent graph → actual registered tool → real middleware → next model input, including platform offloading and adapter serialization.
- Independent fake text/checker calls → real business persistence, task reconciliation, source receipts and unchanged adoption.
- Owned observation recovery, tampered hashes/identity rejection, and legacy observation recovery without creating new business receipts.
- Native fake Writer → independent text tool → committed content → a common snapshot → actual Word and Excel files. Both normal and reference-delivery modes are exercised.
- Two exact historical public tool returns with provenance and SHA verification; these are not a replay of an entire historical checkpoint.
- Synthetic adversarial cases for incomplete review, duplicate scope, unauthorized historical comparison, nested report directories and Markdown formatting.

All verification in this increment uses temporary workspaces and fake models. Network calls are denied in the final combined run. The original reports, OCR results, live project databases, provider reservations and email-stop state are not test targets.

The reusable boundary suite is `tests/test_boundary_refactor.py`, using the existing `Driver`/`BaseChatModel` fake rather than a parallel test agent implementation. In the project Python environment:

```sh
python -m pytest -q tests/test_boundary_refactor.py tests/test_text_work.py
```

The first file blocks network access and inspects actual boundary inputs. The second includes the existing native Writer-to-Word/Excel path. Historical fixtures are data with verified provenance; they are not executable instructions or permission to resume an old run.

## Investigation and test corrections retained

The original seven-failure run remains in `refactor-before.xml`. The broader integration run remains recorded as **243 passed / 3 failed**, not retroactively relabeled green. Neo and Main traced those three failures to tests using previously removed Reviewer organizer APIs; the tests now exercise the legal bounded-review path without restoring those permissions.

The later 29-file regression also exposed two older artifact-review fixtures calling the removed `submit_artifact_review` organizer tool. The actual native ToolMessage reports that the tool is invalid and no ReviewRecord is saved; see `artifact-fixture-diagnostic.json`. Their replacement retains the real export read and actor-bound publication assertions through the current independent bounded checker. Internal save/coverage tests are retained as internal tests, not claimed as active agent permissions.

Neo found RF-A01 during implementation review and rejected the initial large-context test's full-body reinsertion expectation. The corrected object/selection counterexamples failed before the repair and then passed. The first counterexample fixture also omitted a required containment edge; it was corrected without changing the store guard. The synthetic PDF fixture initially placed its file outside the permitted `sources/` directory; it was corrected without relaxing original-file access checks. These fixture failures are not counted as newly discovered product defects.

The first adjacent regression ran while Main was still changing `decision_data.py`. Its 155 passes are retained as historical evidence, not claimed to certify the later source hash. Final verification records the stable source and test hashes separately.

## Limits and remaining work

This increment removes the generic recursive clipping in `decision_data.py`; it does not claim every navigation path has been migrated. Large `read_task_assignment` and other legacy navigation paths retain their existing bounded presentation. Old checkpoints without the new delivery binding retain their explicit compatibility behavior.

No invented context-capacity limit was introduced. Large control results still rely on platform/model capacity; this has not been validated with paid calls. Analysis and vision observations are not guessed to be disposable source bodies.

The existing `decision_data_delivered` event is recorded before filesystem offloading. It describes the prepared representation, not final provider consumption or model reading. The final-input claims here rely on the subsequent fake-model/adapter input assertions, not that event alone.

NFR-04/05/06/09/10/11/12 remain separate findings: Office transaction boundaries, zero-dispatch outcome handling, feedback target retention, header typography, summary outcome handling, effective prompt identity and ledger classification. Their scope and order remain Neo's decision.

Fake models establish deterministic data and control behavior. They do not establish that a real agent will choose the right strategy, that a model will produce correct engineering judgments, or that the first-contract report meets all customer feedback. Those claims require distinct evidence.

## Final verification and review

Latest evidence passes **535 distinct test cases across 29 files**, with zero provider/network calls. This consists of the stable-source full run (**533 passed, 2 old-interface fixture failures**) and the corrected artifact-review file (**21/21 passed**). The application source did not change between those runs. It is not represented as one all-green run, and repeated cases are not added twice. Compilation of all nine changed application modules passed.

The reconciled machine-readable result is [refactor-final-reconciled.json](refactor-final-reconciled.json). The original combined result remains [refactor-final-verification.json](refactor-final-verification.json), with XML/text retaining its failures. Neo's final scoped verdict is appended to [refactor-design.json](refactor-design.json). The original full-review `neo-review.json` and `coverage.json` remain historical records.

Neo's independent verdict is **scoped implementation review passed, fake-only**. His next priority is offline diagnosis of the shared zero-dispatch lifecycle and budget binding through the normal entry point, then structural contracts. The remaining seven findings and four unverified diagnostics have not been closed by these results. This verdict does not start a paid validation or historical run.
