# Writer page-context repair

The first guarded HP02 probe spent 384,089 tokens on one assignment read and seven page reads, without attempting to save a judgment. Its eighth sent prompt contained 101,325 input tokens. This increment addresses page-payload duplication and repeated old tool outputs before any second probe. It does not establish engineering correctness or authorize another launch.

## Scope and implementation

The page tool now offers one representation per call. Its default text view returns the exact frozen source blocks once, with native text as a fallback. Explicit native-text and table views preserve access to the other source channels. Table rows and cell order remain intact; model-facing coordinate arrays and duplicate full-page text are omitted. Availability/coverage and unverified drawing limitations remain explicit. Source records, raw extraction, access checks and actual image-delivery receipts are unchanged.

Text-only Writer sessions use LangChain 1.4.2 ContextEditingMiddleware and ClearToolUsesEdit. A small policy adapter protects every result in the latest unconsumed tool batch and preserves errors. Older page/window outputs are cleared only from the next model request; their call arguments retain source handles and page/offsets. Non-reading tool results and saved indicator arguments/quotes remain. Native checkpoint history and source evidence are not deleted, and re-reading stays available. Editing happens before the existing prompt-provenance boundary so the audited offer and final request describe the edited context. Image-capable sessions retain their existing delivery behavior.

The dedicated Writer instruction asks for each supported indicator to be saved as soon as its evidence is adequate. The Writer chooses indicator order, further reading, grades and any defensible assumptions; there is no programmed page-to-indicator sequence. A refusal or stop preserves prior valid rows. Static prompt clarity and scripted persistence tests do not prove a real Writer will follow this instruction or judge correctly.

## Offline verification

The seven-page scenario replays the first probe's same source/page sequence with deterministic SDK responses, actual tools and an independently imported business snapshot. It performs no inference and saves no engineering judgments in that real-source replay. Separate synthetic fixtures verify early row/quote persistence, multi-result batches, errors, alternate page views and final SDK serialization.

Final serialized requests are measured with the official GLM-5.3 tokenizer/template pinned at `zai-org/GLM-5.3` revision `ba32f8c19c8738e2c57c71798c601d477a7bf844`. This labels the fixed offline trajectory's open-weight-template input count, including its system text and tool schemas. Synthetic assistant messages do not model future private reasoning growth. It is not proof of the private service's framing, a universal context ceiling, billed usage or engineering adequacy.

Option B remains unproven. The existing scoped request reservation stays 1,179,648; global financial authorization, the 20M rescue cap, the 1.5M probe cap and historical holds are unchanged. The pre-request settled-usage threshold therefore remains 320,352. Lower page-context counts alone do not guarantee completion of a second probe.

Current evidence is retained in the owner-authorized `writer-context-repair-20261105` monitoring directory: focused tests, final-wire replay, pinned tokenizer hashes, source/ledger preservation, independent alignment review and full regression/node reconciliation. The accepted baseline's two legacy DeepAgents checkpoint/profile failures remain deferred and are not represented as fixed.

G5 and the first HP02 probe stay stopped. Remaining slopes, Word/Excel export, paid model calls, vision routing and a second probe are outside this implementation authority.

Final offline verification: all nine fixed-trajectory requests are below 30,000 pinned-template input tokens; maximum 15,536 and total 117,492. Full regression accounts for all 5,637 collected nodes: 5,626 passed, two accepted legacy failures, nine skipped tests and two collection skips. No unexpected failures, paid report-model calls, ledger changes or second probe.
