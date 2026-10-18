# System Design, User Requirements, and Agent Design

Prepared on 17 October 2026 for the independent report-agent-system project. Author: Codex. Requirements and interpretation boundaries: input from Neo. Runtime and prompt-path inspection: input from body_alignment_review.

This document answers three questions: how the system is currently designed to operate, what the user requires, and what each agent is responsible for and actually receives. It preserves the distinction between intended design and implementation. Design documents, passing tests, model statements, and a terminated task are not treated as final delivery acceptance.

**Current assessment: the system has capabilities for reading sources, building versioned content, independent text processing, Word/Excel export, and review. However, the full report for Contract Section 1 has not completed acceptance against the customer's requirements. Recent investigations into layout and material handoffs found substantive gaps. Implementation and paid execution remain paused while analysis, discussion, and documentation continue.**

Preparing this dossier did not change application code, run reports, launch learning, publish strategies, or modify business data. The cumulative authorization of 170,000,000 tokens is a historical ceiling, not an instruction to resume execution; the current balance must come from the execution ledger. Email communication is stopped. The Bailian platform audit is deferred.

This is an English edition of the existing dossier, not a new status assessment. Quotations translated from Chinese are explicitly identified as translations; the linked Chinese records retain the original wording. Prompt and code excerpts in the appendices remain unchanged.

## Reading guide and evidence boundaries

- [Agent and tool prompt details](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/reviews/system-design-and-requirements-20261017/en/agent-prompts.md): original role instructions, internal tool prompts, dynamic assembly code, tool registration, and framework contributions.
- [Source and extraction manifest](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/reviews/system-design-and-requirements-20261017/prompt-sources.json): source locations, file hashes, extracted-text hashes, and applicability.
- [Customer feedback and original statements](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/customer-feedback-collected-20261016.md): original message references and formatting-standard excerpts, in Chinese.
- [Original Report Formatting Standard](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/format-standard-original-text.txt): including cover and title-page exceptions, in Chinese.
- [Neo's user-decision history](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/neo/current-user-decisions-20261015.md): a chronological record. Earlier budget or runtime entries do not override later decisions.
- [Chinese edition](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/reviews/system-design-and-requirements-20261017/README.md).

Four evidence categories are used:

| Category | Meaning |
|---|---|
| User-confirmed | An explicit user requirement or clarification; not proof of implementation. |
| Present in code | A mechanism exists in the captured working tree; not a guarantee for every path or business outcome. |
| Observed | Supported by a particular execution trace, model input, or artifact; limited to that case and version. |
| Discussed / unverified | A proposed design, external suggestion, or unproven effect; documenting it does not activate it. |

The source basis is the current working tree at capture, with base commit b5525a3474b2f284f7a638f226be35a57d6e5d13 and pre-existing uncommitted changes. The appendix hashes identify the captured content. Older ARCHITECTURE, ADK, native-rubric, and experiment documents mix intended design with historical implementations and cannot be read as a current runtime specification. This dossier is not a fresh full-repository audit or an exhaustive list of all historical bugs.

## 1. Final objective and requirement scope

### 1.1 Product objective

Generate professional, traceable **construction safety risk assessment reports** that meet the commissioned scope and applicable standards. This report category includes bridges, tunnels, roads, slopes, and culverts. Lessons from this slope report must not be hardcoded as universal facts for every report, nor should category-wide requirements be confined to this single report.

Each report must use its own:

1. **Report Scope Statement**: contract sections, assessment objects, and required coverage.
2. **Extraction Outline**: information to extract and organize from the materials.
3. **Report Formatting Standard**: fonts, sizes, pages, paragraphs, tables, figures, and contents.
4. **Applicable guidelines and standards**: assessment objects, indicator definitions, classification methods, empirical values, scoring, and table formats.
5. **Actual project evidence**: geological investigations, design documents and individual slope drawings, site inspections, expert reviews, and their uncertainties.

These English document names are reading aids for the corresponding Chinese source titles, not newly issued standards.

### 1.2 Objective of the complete validation

The user explicitly clarified the objective. English translation:

> Continue with the previous plan, but do not stop after validating a fix. I am giving you a budget of 50 million tokens. Keep iterating now that customer feedback has arrived. Codex and Neo should continue to the final step: your first option, the full-scope report for Contract Section 1, according to the Report Scope Statement.

The endpoint is therefore **the full Contract Section 1 report and a separate issue-list Excel workbook, covering source use, content generation, layout, actual artifacts, and the normal review chain**. Existing OCR results are the principal starting input for this iteration; the request does not require repeating OCR merely for validation. A local repair, one slope test, an openable file, or a matched Word/Excel pair is an intermediate result.

### 1.3 First-draft quality

The user requires the unreviewed first draft to be reasonably close to the final report. Writer must not leave known writing, table-format, or layout requirements for Reviewer to implement for the first time.

The user's “something like idempotency” raises two distinct requirements:

- **Operations:** repeated calls, recovery, and retries must not silently duplicate writes, consume budget twice, or alter object identity.
- **Content:** internal candidates may involve trial and error, but portions claimed as complete should satisfy known requirements and evidence. Incomplete portions may be clearly identified; omissions, conflicts, and errors must not be presented as complete and correct conclusions.

This does not require code to prove all engineering meaning, or prohibit every internal draft because one chapter is missing. It requires quality to be maintained during construction, rather than relying entirely on final-review rework.

## 2. User feedback and requirements

The following requirements include important clarifications. Their identifiers are navigation aids for this document, not newly created runtime checks. The linked feedback compilation preserves the original report-feedback sources. Later design discussion comes from direct user messages in this conversation; no unavailable message IDs are invented.

### 2.1 Content, scope, and scoring

| ID | User requirement or clarification | Boundary to preserve |
|---|---|---|
| R01 | Cover the full Contract Section 1 scope in the Report Scope Statement. | Do not silently reduce it to completing Excel, pairing exports, or processing already-written chapters. The coverage inventory is independent of the current report tree. |
| R02 | Extract and write according to the Extraction Outline. | Reading the outline does not prove every chapter or text tool received and applied it. |
| R03 | Apply category-level feedback to construction safety risk assessments across bridges, tunnels, roads, slopes, and culverts. | Keep category preferences, project-specific facts, and guideline-specific rules distinct. |
| R04 | Check geological and individual slope-design documents against the guideline wording; select the actual type or classification band first, then its score. | Do not infer the type backward from a desired score or risk level. Missing evidence does not justify guessing. |
| R05 | Determine weathering grade from the actual geological description, such as strongly or completely weathered material. | Match stratum descriptions and weathering to the guideline bands individually; do not score from a generic material label alone. |
| R06 | Where calculation of the same indicator conflicts within the guideline, use its empirical values. The later clarification refers to the table on page 91 of the slope guideline, not a formula. | Coordinator or an appropriate agent should interpret the applicable guideline and derive the method; do not hardcode the page number or one weight sequence for every project. |
| R07 | The user expressed a preference for overall risk at Level III or below, with reasons required if Level IV is necessary. | Preserve the complete statement and its exception below. It does not authorize forced score reduction, suppression of adverse evidence, or fabricated low risk. |
| R08 | Include slopes with important structures such as anti-slide piles, even below the usual height thresholds; do not filter only by 30 m for soil or 20 m for rock. | These heights are the user's examples. Applicability still requires checking the guideline and project materials. |
| R09 | Establish why slope K1320+380–760 was omitted. | This is an assessment-object coverage issue, not merely a request to add a sentence. Check the object's scope and evidence. |
| R10 | Follow the guideline's structure and content for indicator weights and scores, including the cited S3-2-11-4-2 table and the page 11 example. | The page 11 table-format requirement and the page 91 empirical-value method are distinct. |
| R11 | Preserve complete relevant original geological/hydrological paragraphs and tables or figures for the corresponding site; screenshots are allowed. | Do not select only a short sentence that supports an indicator while omitting qualifications, captions, headers, or adverse conditions. This also does not mean inserting the entire source book. |
| R12 | Table size and pagination may change, but the content must remain unchanged. | Layout flexibility does not permit changes to indicators, notes, calculation relationships, column meanings, or values. |
| R13 | Use actual site-inspection, expert-review, and design evidence. | Real project-team activities are distinct from whether the AI visited the site. Do not invent activities, signatures, or engineering approval. |
| R14 | Make citations understandable to the customer. | Internal IDs such as source-XXX must not replace identifiable source names, locations, and attribution. Internal traceability must remain. |
| R15 | Do not routinely insert statements about the system not attending the site, or reading/OCR/model-processing details, into the report body. | Preserve real engineering evidence gaps, technical conflicts, and uncertainty. A professional voice does not justify removing them. |
| R16 | Excel is separate from Word and exists to present report-related issues to the customer. | Normal source summaries, principal technical standards, or routine recordbook entries must not be presented as issues. Genuine missing or conflicting information requiring customer action may be listed. |

The full risk-level statement is retained in the Chinese source. Faithful English translation:

> In addition, generally speaking, keep the assessment result at Level III or below. It should not be Level IV. If Level IV is genuinely necessary, explain why.

This statement contains both a preference and an exception. The system should report the result supported by the evidence and guideline. If that result invokes the exception, explain the basis and clarify with the customer when needed, rather than silently changing the score.

### 2.2 Formatting

This table summarizes the standard already supplied to the project. It is not a newly invented developer template. Chinese font-size names are retained in transliteration to identify the standard precisely.

| Element | Supplied requirement |
|---|---|
| Paper and margins | A4, 210 × 297 mm; top, bottom, and left margins 25 mm; right margin 15 mm; gutter 0, on the left. |
| Fonts | Bold Songti headings; Songti body; Times New Roman for Latin letters and numbers. |
| Heading sizes | Levels 1–4 use Xiao'er, Xiaosan, Sihao, and Xiaosi respectively; numbering follows Chapter 1, 1.1, 1.1.1, and (1). |
| Regular sizes | Body: Xiaosi; tables: Wuhao; headers and footers: Xiaowu. |
| Line spacing | 1.5 lines for headings, body, tables, and contents. Preserve the cover/title-page exceptions, including single and 2.5-line spacing. |
| Paragraph spacing | Level 1: 10 pt before and after; level 2: 0.2 lines before and after; level 3 and body: 0 before and after. Body first-line indent: two characters. Follow the standard for heading hanging indents and other details. |
| Alignment | Cover, tables, and level 1 headings centered; level 2 left-aligned; level 3 and body justified. |
| Contents | An automatic Word table of contents with at least three levels. Title: bold Songti Sanhao; entries: Xiaosi, with level 1 bold. Do not repeat the global contents inside subreports. |
| Tables | Caption above, centered, bold Songti Wuhao. Table text Wuhao, with Times New Roman for Latin letters/numbers. Line spacing 1.5. Double outer border, 0.5 pt. Follow the specified numbering. |
| Figures | Caption below. Follow the standard's caption, numbering, and note sizes and numbering rules. |
| Headers and footers | Project name on the left and report name on the right, Songti Xiaowu. Centered Arabic page numbers starting at 1, Times New Roman Xiaowu. |
| Cover and title page | Project title, report title, organization, date, responsible person, and qualifications have distinct font, size, and spacing requirements. A single body-text configuration must not override them. |
| Details | Consistent full-width Chinese punctuation, spacing between numbers and units, year formatting, and list numbering. |

The user's observations of the intermediate report were specific: margins and fonts/sizes were not implemented; another table of contents appeared on pages 15 and 25; line spacing was not 1.5. Those page numbers describe the user's observation and must not be silently replaced with our rendered PDF page numbers.

Layout uses tool parameters for supported capabilities. Where a capability such as table line spacing or a double border is missing, a developer must add it. Responsibility for layout does not give Layout permission to edit application source code. Acceptance requires Reviewer to inspect the actual Word document and rendered output. Correct configuration, a correct XML field, or a successful export alone cannot replace visual inspection.

### 2.3 Working practices, authorization, and engineering

| ID | Confirmed requirement | Current interpretation |
|---|---|---|
| W01 | Neo represents the user's working preferences in decisions; Codex implements. | Neo first judges whether an issue is established, worth resolving, and in what order. Inspect source code, traces, actual inputs, and artifacts—not just Main's conclusions. |
| W02 | Investigate root causes proactively. | Do not merely rerun or patch a prompt. Distinguish typos, interface defects, shared design causes, and architectural causes; inspect related paths. |
| W03 | Repeated similar bugs call for improvement to their common design. | Multiple patches, additional guards, or larger test counts do not establish architectural convergence. |
| W04 | Apply relevant principles from Code Complete. | Manage complexity, hide implementation details, define clear interfaces, diagnose with evidence, and refactor safely. Access to the full book has not been verified; do not invent quotations. |
| W05 | Prefer DeepAgents and compatible components. | Inspect installed capabilities first, then maintained integrations, then the remaining domain-specific gap. Do not build a second agent control loop. |
| W06 | Separate agent decisions from LLM text-processing tools. | Agents still need to understand goals and relationships between chapters and evidence, and may read originals as needed. Independent tools perform bounded extraction, comparison, and generation. |
| W07 | Validate against the final delivery objective. | Unit tests, valid schemas, rejection of bad calls, or preservation of an old version do not prove correct model invocation or customer compliance. |
| W08 | Progress step by step through problems to complete validation. | Pausing affected execution to investigate and repair a root cause can be correct. Improve repair completeness rather than simply minimizing pauses. |
| W09 | Account honestly for paid usage and unproductive calls. | Preserve original requests/responses, actual usage, unknown outcomes, and retries. Do not add cached tokens again when they are already included. |
| W10 | List all known bugs with their corresponding solutions. | Historical inventories must be inspectable item by item; counts or a few categories are insufficient. Already-fixed issues still merit design-level review. |
| W11 | Preserve the user's statements for Neo's learning. | Retain provenance and superseded decisions. An archive is not proof of future compliance. |
| W12 | Match project complexity to actual needs; clean unnecessary files and SQLite data. | Neo leads authorized cleanup. Preserve OCR, authoritative originals, required recovery data, paid-call evidence, and historical references. Identical hashes alone do not authorize deleting arbitrary paths. |
| W13 | Task-authorized visual reading is allowed. | The user corrected earlier assistant-added bans on personnel/signature pages. Permission to read does not imply unrestricted disclosure of personal information. |
| W14 | Stop email; defer the Bailian audit. | Old ACTIVE heartbeats and login requests are historical and must not automatically reactivate these activities. |

## 3. System design: confirmed principles and actual structure

### 3.1 Three responsibility boundaries

| Component | Responsibility | What it must not substitute for |
|---|---|---|
| Agent decision loop | Understand the commission, select sources and tools, choose strategy, delegate appropriate tasks, adopt or reject candidates, explain gaps, and select the next action. | Program code must not silently choose engineering conclusions for it; tool success alone is insufficient evidence of correctness. |
| Independent LLM tool | Perform bounded extraction, comparison, generation, review, or image analysis using the supplied goal and materials; return results and limitations. | No hidden retrieval, delegation, business writes, additional model loop, or authority expansion. |
| Deterministic program | Validate structure, permissions, identities, versions, persistence, source locations, calculations, budgets, idempotency, errors, and observation records. | Truncation, defaults, hidden workflows, and error wording must not silently become business decisions. |

**The separation principle remains valid.** The recent discussion concerns its implementation: responsibilities and decision-relevant information were incompletely defined, custom wrappers and compression proliferated, and existing framework facilities were not sufficiently reused. An agent's need to read original material is not itself a design failure. Nor should every agent duplicate all tool analysis or read every source in full.

### 3.2 Current runtime path

The native path uses DeepAgents. Coordinator can delegate to Writer, Reviewer, and Layout. They are available capabilities, not a user-mandated three-role pipeline for every task. Learner is separate and explicitly invoked. The current build_agent entry point rejects the historical ADK/native-rubric execution paths.

~~~mermaid
flowchart TD
    U[Commission, customer feedback, source materials] --> S[Project state and versioned materials]
    S --> C[Coordinator decisions]
    C --> W[Writer decisions]
    C --> R[Reviewer decisions]
    C --> L[Layout decisions]
    W --> T[Bounded text tools]
    R --> V[Bounded content and artifact checks]
    L --> E[Export, rendering, and layout tools]
    T --> D[Versioned content, evidence, relations]
    D --> F[Snapshot of exact versions]
    F --> E
    E --> A[Word, issue workbook, rendered artifacts]
    A --> R
    V --> J[ReviewRecord and unfinished checks]
    J --> C
    C --> O[Selected delivery and explicit limitations]
    U -.Explicit feedback learning.-> N[Learner]
    N --> P[Unpublished candidates]
    P -.Evaluated and authorized release.-> S
~~~

The diagram shows dependencies and capabilities, not a mandatory sequence. The implementation also contains local sequencing constraints: for example, the Coordinator prompt requires review observations before decisions about layout work that depends on those observations. Such constraints need explicit scrutiny; calling the system “dynamic” does not make them disappear.

### 3.3 Data and identity

| Object or record | Purpose | Important distinction |
|---|---|---|
| Requirement | Commissioned requirements and applicability. | Do not infer the complete requirement set from the content already written. |
| SourceArtifact / source versions and blocks | Source identity, content, version, and location. | Sources are not authority instructions; a text-block index is not a physical PDF page number. |
| Criterion | Checkable standards and required materials derived from requirements. | A criterion object does not prove sufficient checks. Empty or narrow declarations may omit requirements. |
| ContentNode | Reports, chapters, paragraphs, tables, figures, and related content. | body, qualifiers, and claim_kind jointly express meaning. Wrappers must not make qualifications disappear from view. |
| Evidence / Relation | Citations, calculation support, and content relationships. | A link does not prove semantic support; relations such as supported_by still need content-level verification. |
| DocumentSnapshot | A fixed manifest of exact object versions and relationships. | It is not an old-report template or an approval of the content. |
| Export / RenderArtifact | Word, Excel, and visual artifacts derived from a specified snapshot. | Pairing exports from one snapshot ensures version consistency; it does not require copying an old layout. |
| ReviewRecord | Checks against exact targets, criteria, materials, and artifacts. | Execution completed, criterion satisfied, and engineering acceptance are different states. |
| HandlingRecord / task and observation records | Disposition, gaps, delegation, execution, and provenance. | A saved or handled record does not automatically resolve a real defect. |

Content has explicit IDs, versions, digests, and owners. Revisions do not silently overwrite history. The server binds authorship to the delegated task; a text tool does not obtain a new business owner by returning prose. Historical versions support traceability, comparison, and explicit reuse. **The user never required preserving a noncompliant old version merely for reuse.**

Application business state is distinct from LangGraph conversation checkpoints. The former holds content and task facts; the latter holds control-loop history. Summaries and scratch files cannot change authoritative goals, versions, permissions, or completion states.

### 3.4 Source retrieval and material handoffs

The current source catalog stores text blocks and performs literal keyword matching. Hybrid RAG over source materials has not been deployed on this main path. Optional Neo4j/vector knowledge capabilities do not establish that all source documents already have semantic indexing.

- Originals are stored in blocks; reads support pagination and recovery by explicit source and location.
- Literal matching can miss synonyms, aliases, relationships across paragraphs, and table/figure meaning.
- Text-block pages and physical PDF pages are different location units; visual tools access the corresponding original page.
- An agent can hold an observation reference and pass authorized full material to an independent text tool without copying the whole body into task prose.
- Recoverability does not prove that material was read. A few matching excerpts do not prove complete coverage.

**Discussed direction:** combine keywords, exact identifiers/scope filters, and semantic retrieval; return to the original location and expand complete relevant paragraphs and tables. A few engineering aliases may help, but a large synonym dictionary is not a prerequisite. An index finds candidates; it does not prove truth, applicability, or full coverage. This direction is not yet deployed.

### 3.5 I/O between agents and tools

The code already uses Pydantic business models, typed inputs, independent text-result validation, receipts, and archived raw responses. It is not devoid of contracts. The weakness is that structures, projections, error messages, and completion meanings across layers do not consistently preserve what agents need for decisions.

A handoff should make clear:

1. The objective and applicable requirements, beyond the output schema.
2. Which materials, versions, and extents the tool actually received, and which it did not.
3. The result, conflicts, qualifications, gaps, and conclusions that cannot be drawn.
4. The correspondence between results, materials, objects, and raw responses, and how the agent can inspect and adopt them.

This is a responsibility analysis, not a newly released fixed field contract. Valid structure, existing IDs, and a normally completed tool call do not prove correct meaning. Conversely, an agent working around a program defect and continuing does not prove that the defect has disappeared.

### 3.6 Layout, export, and review

Layout reads scope, formatting standards, and selected versions, then operates tools through parameters. The current design separates Word content from workbook-only nodes, so the issue table need not be inserted into Word. Word and Excel can bind to the same snapshot.

Reviewer checks the delegated targets. Content-semantic review and artifact review require different materials. Execution completion, verdicts, coverage bookkeeping, and delivery selection must remain distinct. Missing materials should remain unexecuted or undetermined, rather than being converted into “completed and passed.”

Final acceptance cannot rely only on data or Word XML. Font appearance, pagination, tables, contents, headings, and page layout need actual rendered observations. Reviewer's independence does not permit weakening standards or rewriting Writer's content without authority.

### 3.7 Feedback, experience, and instruction lifecycles

| Channel | Existing role | What it does not establish |
|---|---|---|
| User-statement archive / Neo records | Requirement history and development decision evidence. | Saving Markdown automatically supplies it to every runtime agent. |
| operator_feedback / application task context | Supply current project feedback to decision roles. | Every tool received all requirements, or the artifact implements them. |
| Scoped instructions | Versioned instructions filtered by system, report_category, project, report, assignment, and role; explicit override and conflict handling. | General understanding of arbitrary natural-language contradictions, or permission to override evidence or authorization. |
| Learner | Form experience candidates and dispositions from feedback and evidence; distinguish facts, preferences, and methods. | One execution proves useful learning, or candidates publish automatically. |
| Released experience context | Supply active scoped preferences/strategies and discoverable additional experience. | Presence in a prompt proves adoption, improvement, or cross-project generalization. |
| Optional GEPA experiment | Evaluate/optimize saved guidance candidates when an experiment runner is explicitly connected. | A mandatory report stage, the same mechanism as native Learner, permission to change facts, or automatic global release. |

The user's request to avoid excessively narrow experience means learning how to identify the applicable guideline and method—not turning one site's facts into rules for every report. Knowledge facts and behavioral strategies need distinct scopes and release evidence. External suggestions to learn checks or tighten rules automatically are references, not permission to shrink the user's scope or change authorization.

### 3.8 Models, summarization, budgets, and recovery

The mixed-service configuration maps Coordinator, Reviewer, and text/vision tools to the specified DeepSeek configuration bundle. Writer uses glm-5.3; Layout defaults to Writer's configuration. Explicit role configurations can take precedence. A bundle's name does not prove a direct official-service connection; saved role-model identities identify each run. No secrets or environment files are exported here.

Separating decisions from text tools reduces some repeated context, but decision history still grows. Agents retain objectives, tool observations, tasks, errors, and decision traces, so conversation summarization may still be triggered.

The stateful path reinjects application context for every decision call and wraps LangChain summarization with the project's WorkingSummary. The summarizer uses the Coordinator service. Its prompt targets about 1,200 tokens; the 16,384-token output cap is not the trigger threshold. The installed framework calculates trigger and retention settings from the model profile, as documented in the prompt appendix. These are project-runtime settings, not the Codex application's own compaction settings.

Budget and recovery are deterministic execution responsibilities: reserve before calls, record actual usage, preserve unknown outcomes, never treat unknown usage as zero or automatically replay it, and identify exact recovery points, versions, and owners. Existing binding repairs, call counts, and ledgers do not prove complete cost attribution. Historical terminal runs do not resume because of a new heartbeat or this dossier.

### 3.9 Engineering components and storage

| Layer | Current components and entry points | Status boundary |
|---|---|---|
| Local service and workbench | Python package, report-agent CLI, FastAPI webapp, and static frontend; project status, source, execution, issue-handling, delivery, and learning APIs. | Existing operational interfaces, not full product acceptance. Reading status does not imply launching a model. |
| Agent execution | DeepAgents control loop/delegation and LangGraph checkpoints; project middleware binds business identities, context, and execution limits. | The framework owns generic runtime mechanics; the application still owns project permissions and business versions. |
| Project business storage | Each project's SQLite state.db and file directory; traceable sources, content versions, events, analysis receipts, and exports. | Separate writable storage from the legacy highway system; do not directly modify legacy services or data. |
| Conversation recovery | checkpoints.db preserves conversation and control-flow history. | Not a business snapshot; a retained checkpoint is not automatic replay authorization. |
| Experience library | Feedback, candidates, versions, and releases by customer/project and applicable category. | Facts and preferences/strategies have different lifecycles; no automatic global promotion. |
| Export and rendering | python-docx, openpyxl, PDF/image tools; actual files, structure, and rendered observations recorded separately. | Successful export does not establish content, visual, or engineering correctness. |
| Knowledge capabilities | Optional Neo4j/vector-related modules. | Installed dependencies do not prove source semantic retrieval is connected to this main path. |
| Development evidence | .analysis, .runs, .memory, and docs hold investigations, experiments, handoffs, and designs. | Historical records should not become multiple contradictory sources of current task state. |

Verified installed versions include DeepAgents 0.7.19, LangChain 1.4.2, langchain-core 1.6.5, LangGraph 1.2.12, Pydantic 2.13.5, and langchain-openai 1.6.6. See pyproject.toml for declared dependencies. Versions are environment facts, not proof that the framework has supplied the application's business design.

Historical cleanup archived duplicate request events in selected terminal cases. Full-history call/cost audits must read the corresponding complete archives, not just compacted online databases. Sharing immutable material, reducing mirrors, and consolidating materialization remain convergence goals, not universally implemented guarantees. This dossier did not perform further file or database cleanup.

## 4. Agent design details

### 4.1 Report runtime roles

| Role | Inputs and decisions | Main capabilities | Boundaries and outputs |
|---|---|---|---|
| Coordinator | Full current objective, commissioned scope, requirements, sources, task observations, budget, and feedback; strategy, delegation, coverage, continuation, and requests for human information. | Inspect sources/state; form criteria/relations; delegate; coordinate versions, snapshots, and delivery. | Must not impersonate Writer's authorship or Reviewer's verdict, or narrow the user's goal for convenience. Produces saved decision objects, tasks, and delivery state. |
| Writer | Its assignment, applicable requirements, actual evidence, structure, and revision targets; chapter logic, material sufficiency, and candidate adoption. | Read/analyze sources; call process_report_content; save owned nodes and evidence through receipts. | Independent text tools perform substantive writing, while Writer remains responsible for understanding and adoption. Preserve qualifications and adverse facts; do not alter other owners. |
| Reviewer | Exact targets, snapshot, criteria, required checks/materials, and independent evidence; check selection and further material gathering. | perform_assigned_review, perform_assigned_artifact_review, and controlled reading/calculation/vision. | The actual system prompt is ORGANIZER_PROMPT; checker TOOL_PROMPT is separate. Save real verdicts and gaps; do not rewrite report content without authority or independently claim engineering acceptance. |
| Layout | Assigned snapshot, formatting standard, relevant renderings, and review feedback; presentation parameters and proportionate verification. | Layout configuration, Word/Excel export-related work, rendering observations, and capability-gap requests. | Do not change engineering facts, scores, sources, or criteria. Own checks do not replace independent acceptance. No source-code editing. |
| Learner / experience_optimizer | Explicit version-bound feedback, evidence, existing experience, and evaluations; what to learn and how to formulate candidates. | Read feedback/evidence/candidates; optionally analyze materials; propose_experience; record feedback disposition; optimize experiments only with an explicit runner. | Not mandatory for each report. Candidates default to inactive. No automatic release, original-report edits, factual changes, authorization changes, or model changes. |

### 4.2 Components with prompts that are not autonomous agents

| Component | Purpose |
|---|---|
| process_report_content and related text work | Generate bounded candidates from selected materials, objectives, and target schemas. |
| Evidence analysis | Extract/analyze explicitly supplied material and return sources and limitations. |
| Bounded review checker | Perform assigned checks and preserve materials, findings, and unfinished items. |
| Artifact review checker | Perform bounded checks of actual exported/rendered artifacts. |
| Vision | Interpret a specified image/page; success does not establish full-document coverage. |
| WorkingSummary | Compact working history for continuation without changing authoritative application state. |

These tools may invoke an LLM, but they do not have independent long-term objectives, arbitrary delegation, business-write authority, and open-ended loops. A system prompt alone does not make a component an agent.

### 4.3 Development collaboration

Neo represents the user's expressed working preferences and final delivery objective. Neo judges issue validity, priorities, design tradeoffs, and root causes, inspecting source code, actual traces, and results. Codex Main investigates, implements, verifies, and supplies delivery evidence. Other reviewers provide focused evidence for Neo's decisions.

Neo cannot expand the user's budget, release authority, or engineering sign-off permissions. Neo is not a mandatory report-runtime approval agent. This document does not claim that Neo is the user or perfectly reproduces all the user's thinking.

### 4.4 How prompts are assembled

One role prompt does not represent a complete model input. There are seven layers:

1. **Role base:** common plus the role file; Reviewer is replaced with ORGANIZER_PROMPT on the current path; Learner has a separate rule file.
2. **Framework/middleware interfaces:** additional system instructions and tool schemas. The installed filesystem/delegation defaults do not duplicate complete usage prose in the system message; they primarily use tool descriptions. Coordinator's explicit todo middleware adds a system prompt. See the [framework appendix](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/reviews/system-design-and-requirements-20261017/en/framework-prompts.md).
3. **Current server-bound application context:** goal, scope, owner, assignment, current versions, feedback, budget, and remaining checks.
4. **Effective external instructions and experience:** filtered by role and scope. Candidates and historical instructions must not activate automatically.
5. **Current user/delegation messages and history:** including tool observations and necessary summaries.
6. **Internal tool prompts and material packets:** independent tools do not automatically inherit Writer's full reading history; selected references must supply the materials.
7. **The actual request after model adaptation:** final roles/messages/tool schemas are the evidence for that call. A source string, configuration name, or prompt_hash alone is not the full input.

The appendix preserves static originals and dynamic assembly code; it does not claim that every checkpoint receives the same effective prompt. In particular, some Reviewer identity metadata still hashes the content-reviewer text while build_agent actually uses ORGANIZER_PROMPT. That hash cannot establish the effective input.

## 5. Key observed gaps

These are design-relevant facts and limitations, not a replacement for the complete historical bug inventory. Historical defect counts must not be treated as the current unresolved count.

| Topic | Evidence and established mechanism | Interpretation |
|---|---|---|
| Goal reduction and old-version reuse | The 16 October investigation found Coordinator instructions narrowing work to Excel/pairing exports and copying the old R6 layout. The user did not request an R6 copy. | Version consistency cannot substitute for the current goal. A snapshot itself does not require old-layout reuse. |
| Formatting not implemented | The standard appeared in later effective inputs, yet Writer supplied 25 mm margins on every side, 1.3 body spacing, 1.15 table spacing, and a two-level contents setting. Export followed those parameters. | “The standard was never read” is not a sufficient explanation. New/old Word equivalence is not compliance with the standard. |
| Repeated contents | Nested report nodes caused the exporter to create multiple contents tables; multiple occurrences were observed in Word. | A specific interaction between code and content structure, which should not be left for the customer to discover. |
| Material selection influenced by program signals | Selected evidence over 64,000 characters was rejected with TEXT_WORK_SELECT_SMALLER_LOCATED_EVIDENCE; the suggested action could influence the agent to narrow selection. | A rejection of the whole request, not a two-source limit and not silent truncation of an accepted packet. |
| Insufficient decision-facing results | Some historical returns showed only 240-character source fragments and did not adequately expose bodies/limitations; Writer could adopt from receipts alone. | Raw material being saved does not mean the agent received sufficient decision information. Recoverable does not mean recovered. |
| Confusion between tool input and decision projection | In the traced chains 1133→1136→1137 and 1203→1206→1207, selected materials reached the independent tool unchanged. | Do not claim that the original PDF was cut, or that selected tool input was silently removed in those two chains. Locate clipping at its actual layer. |
| Overstated end-to-end progress | Component tests, schema rejection, successful saves, export equivalence, and local reviews were taken as broader progress. | They do not establish normal content/layout acceptance or full Contract Section 1 coverage. The investigated case had zero ReviewRecord objects. |
| Feedback persistence confused with effectiveness | Original feedback, candidates, injection, adoption, and artifact outcomes are separate stages. | Saved “learning input” is not implemented feedback; one successful case does not establish generalization. |
| Agent workarounds conceal program defects | Agents change strategy after rejection/clipping and may eventually obtain apparent success. | Preserve the first deviation and its impact chain. Continued execution does not prove a sound underlying design. |

Detailed evidence: [layout and generation-quality RCA](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/neo-trace-review.md), [origin of R6 reuse](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/r6-layout-origin-root-cause-20261016.md), [material transformation comparison](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/table-material-program-transformation-proof-20261016.md), [guideline-table execution RCA](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/guide-table-execution-root-cause-20261016.md), and [verbatim omitted text](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/omitted-tool-return-verbatim-20261016.txt). These original investigation records are in Chinese.

## 6. Discussed changes that are not complete

| Direction | Discussion or recommendation | Remaining work |
|---|---|---|
| Clarify agent/tool/program boundaries | Agents retain semantic judgment; tools perform bounded substantive work; code handles deterministic responsibilities. | Inspect actual paths for compliance and determine which duplicated layers should be removed. |
| Consistent I/O responsibility | Make inputs, results, limitations, material coverage, error meaning, and original recovery explicit. | No completed migration to a new common protocol or full-chain validation. Complete fields alone do not prove sufficient meaning. |
| Framework-first implementation | Reuse LangChain tool schemas, structured model output, ToolMessage artifacts, and middleware. | Selecting a component does not solve domain contracts automatically. Verify strict/provider behavior for the actual version. |
| Hybrid source retrieval | Combine literal and semantic retrieval with exact locations and recovery of complete context. | Hybrid RAG is not deployed on the main source path; recall and coverage remain unverified. |
| Quality during construction | Apply known requirements in the first draft; use independent review for remaining defects. | Do not substitute additional end-stage approvals for correct construction. Actual first-draft quality still needs proof. |
| Preserve failure signals during validation | Link raw program outputs, model-visible inputs, agent strategy changes, and artifacts. | Agent adaptation is not a system pass. Detect whether omissions or errors were concealed. |

The technical documents supplied from the backup directory are reference material, not automatic changes to this system or proof that the main project implements them. Historical scan counts and statements that budget controls were disconnected require checking against the correct object, date, and version. A blanket inference from missing supported_by links to every report lacking evidence also requires attention to the metric definition and sampled semantic evidence.

Framework boundaries matter: DeepAgents response_format principally constrains an agent's final structured_response, not every tool result. LangChain args_schema constrains tool arguments; with_structured_output constrains model returns. ToolMessage.artifact can retain raw material that is not model-visible, but must not hide decision-critical information. Middleware provides a common integration point; it does not define correct domain meaning for us. Official references appear below.

## 7. Recent discussion retained

The following are English translations of direct statements in the current conversation. We cannot claim that they are all already present in the older 659-/81-entry archives. The Chinese edition preserves the wording of this later discussion without rewriting those archives.

> Our structural constraints on returned results are not strong.

> We have built a lot ourselves. Do DeepAgents or third-party open-source frameworks support this?

> So the separation itself is supported, and tools exist. The program has interfered too much with things the platform should handle.

> After thinking about it, I still see this as your implementation problem. The design principle itself was not wrong, but you did not fully use the platform's existing tools and did not think the implementation through. Working this way will lead to endless problems.

> These problems seem spread throughout the system. Program and agent responsibilities are tangled, as are tool and agent responsibilities. The system has become complex and insufficiently simple. I have initiated several code and design reviews, but the problems remain, with many hidden traps.

> We spent more than 100 million tokens on real-data validation to expose problems. But this system has a characteristic: after agents handle errors introduced by the program, the errors become difficult to detect. They end up buried more deeply.

These concerns call for examining actual responsibilities and combined behavior while retaining original failure evidence. They must not be reduced to “change frameworks,” “add more guards,” or “another run will solve it.”

## 8. Source and record navigation

| Topic | Entry points |
|---|---|
| Development constraints | [AGENTS.md](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/AGENTS.md); [architecture document, including historical and intended design](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/ARCHITECTURE.md) |
| Runtime and role construction | [deep_runtime.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_runtime.py); [role/tool bindings](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/hierarchical_tools.py) |
| Model services | [model_config.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/model_config.py); [deep_models.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_models.py) |
| Dynamic context and summaries | [task_context.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/task_context.py); [working_summary.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/working_summary.py) |
| Text tools and adoption | [text_work.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/text_work.py); [independent text-tool documentation](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/independent-text-tools.md) |
| Decision projections | [decision_data.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/decision_data.py) |
| Review | [bounded_review.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/bounded_review.py); [artifact_review.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/artifact_review.py) |
| Source reading and retrieval | [catalog.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/catalog.py); [source_search.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/source_search.py) |
| Learning | [learning_runtime.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/learning_runtime.py); [feedback-learning documentation](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/feedback-learning.md) |
| Instruction versions and applicability | [prompt_instructions.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/prompt_instructions.py); [documentation](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/prompt-instructions.md) |
| Original user statements | [initial archive](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/neo/user-statements-20261014.md); [post-Neo supplement](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/neo/user-statements-since-creation-20261015.md); [current decision entry point](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/neo/current-user-decisions-20261015.md) |
| Historical bugs and design review | [itemized bug inventory](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/full-chain-acceptance-20261014/complete-bug-inventory-20261015.html); [actual design review](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/full-chain-acceptance-20261014/actual-design-review-20261015.html) |

Framework references describe capabilities, not proof that this project has completed the corresponding work:

- [DeepAgents structured final output](https://docs.langchain.com/oss/python/deepagents/customization#structured-output)
- [LangChain tool schemas](https://docs.langchain.com/oss/python/langchain/tools#advanced-schema-definition)
- [Structured model output](https://docs.langchain.com/oss/python/langchain/models#structured-output)
- [ToolMessage and artifacts](https://docs.langchain.com/oss/python/langchain/messages#tool-message)
- [Custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom)
- [Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/)

The deliverable is this traceable summary and its prompt appendices. It does not independently authorize refactoring, resuming paid execution, rewriting reports, or releasing experience.
