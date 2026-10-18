# Layout repair v1 — 2026-10-01

Implemented by Main, without the suspended ASE workflow. Email communication remains paused.

## Changes

- Optional native `layout` delegation with an immutable grant to one coordinator-owned snapshot. The role can produce exports and observations, but cannot edit report content, criteria, reviews or select delivery.
- Coordinator instructions retain responsibility for format findings: send evidence/requirements to layout, route content changes to writer, select the new export and request reviewer recheck. No mandatory extra runtime stage.
- Export controls: A4 margins/fonts, heading levels, table captions/widths/repeated headers/row splitting, landscape tables or figures, page breaks and page numbering. Structural qualifiers remain in mappings; substantive and unknown qualifiers remain visible.
- Layout service defaults to writer service; explicit complete REPORT_LAYOUT_* configuration is supported. Existing saved role-service identities reject a silent change; use a fresh project for a new live trial.
- `scripts/reflow_content_snapshot.py` performs an offline export on a private database copy. Its sample-specific table choices are verification inputs, not evidence of autonomous model choices.

## Evidence

- Combined content/layout/runtime/single-reviewer/regression selection: 50 tests passed. Final focused layout suite: 4 passed after heading/TOC-depth changes. Final TOC spacing adjustment was rendered directly.
- Exact source: `.runs/task060/mixed-single-reviewer-v1`, snapshot `0b22e04b-11b2-4403-b17e-e303e93a4e61` v1. All 243 frozen object digests unchanged in the verification copy.
- Latest sample: `.analysis/layout-repair/preview-v4/layout-preview.docx`; SHA256 `eaf1eb143abe17454cd0808f012dd83db7f651fac0d5b857e03a26efad0f8982`. Corresponding PDF/pages are in `preview-v4/render`, 36 pages.
- Visual coverage: v3 all-page contact-sheet inspection; v4 changed directory inspected at full page. This is an engineering preview, not exhaustive final-document visual acceptance. Table proportions and captions are improved; the formerly empty TOC now contains the actual headings and fits one page.

## Limits and remaining work

- No live model run or independent runtime reviewer acceptance was performed. Protocol tests do not prove the model will autonomously use the controls well. Original trial/delivery and scoring conclusions were not repaired or promoted.
- Directory has cached heading text, but page-numbered navigation still requires field update in an office application; automatic field refresh has not been verified.
- Sparse pages before landscape tables, duplicated cover-like source content, and content-specific layout refinements remain. These prevent claiming final publication quality, but do not block a clearly labelled preview or testing the new role.
- No new report figures are created by this change. The script's real sample contains no figures; source-image behavior is not established by that sample.
- Existing unrelated workspace changes were preserved. No deployment or paid model calls.

## Future direction confirmed in discussion

Human interaction and accumulated experience are a subsequent substantial workstream, not implemented here:

1. Present the question, original evidence, alternatives and impact together; make decisions easy and resume affected work without requiring full reruns.
2. Capture the decision and its reason during normal interaction. Distinguish user preference, project agreement and professional experience; record applicability, provenance, confirmation and versions.
3. Retrieve relevant experience for later work with visible reasons; support correction, exceptions and expiry. A one-off choice must not silently become a universal rule.
4. For indicator selection, retain which candidates were considered, selection/exclusion reasons and the human-confirmed context. This discussion does not establish that the current five-indicator choice is correct or universally reusable.

The user compared this direction to “hermess”; no claim about that product's actual implementation was verified or adopted.

## Development approach — subsequent user decision

The user considers ASE unsuitable as the governing process for this agent project. Continue without ASE workflow/gates. Agent capability work should focus on real observations, feedback quality, action selection, improvement, termination and accumulated experience. Protocol tests establish tool and permission behavior only; they do not establish autonomous professional competence. Deterministic permissions/data-integrity checks remain useful without making fixed test cases the primary criterion for agent quality. Distinguish system execution failure, invalid tool arguments, inadequate evidence, poor judgment and lack of improvement when interpreting traces.
