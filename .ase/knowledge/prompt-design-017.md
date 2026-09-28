# Effective native reviewer design, 2026-09-28

User requested reference to OpenAI official prompt design documentation. Main used
the OpenAI Docs and agent-prompt-design skills and fetched these official pages:

- https://developers.openai.com/api/docs/guides/prompt-engineering
- https://developers.openai.com/api/docs/guides/prompting
- https://developers.openai.com/api/docs/guides/evaluation-best-practices

Applied general guidance: separate role/instructions from changing task evidence,
make the intended output and trust boundary clear, store prompts as versioned
application code, and measure behavior on representative cases. These are design
inputs, not evidence that a GPT prompting recipe improves GLM5.3. No model migration,
OpenAI API dependency, chain-of-thought request or answer-bearing few-shot examples.

The report-reviewer.md role describes outcome, evidence capability and judgment.
The existing report-review.md rubric remains the acceptance criteria. Per-attempt
saved artifact identities remain dynamic observations. The effective system prompt
appends the installed DeepAgents GRADER_SYSTEM_PROMPT unchanged, retaining the
GraderResponse schema semantics, conservative criterion confirmation and untrusted
transcript handling. Prompt identity is recorded on each evaluation target.

Framework source inspected: DeepAgents 0.7.19 rubric.py in the existing WSL venv.
The system_prompt parameter replaces the default; no automatic append. Native
tools and grader_middleware permit evidence gathering; on_evaluation is observability,
not flow control. Reuse the existing native needs_revision loop and terminal adapter.
Official supporting source: https://www.langchain.com/blog/introducing-rubrics-for-deepagents
The reference.langchain.com page returned unsupported text/markdown through web
fetch; installed implementation is the precise version evidence.

Task016 is a known representative failure case, not a held-out evaluation. Preserve
the same report, sources/OCR, model and rubric where possible. Prompt and available
delegation change together; no single-run causal or general reliability claim.
Offline positive/negative cases establish wiring and native controls only. Independent
content review must assess both justified findings and unwarranted rejection after
the true run; its conclusions never enter the running application's input.
