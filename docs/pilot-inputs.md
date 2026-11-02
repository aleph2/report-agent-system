# Pilot input folder

Select the directory containing the customer's authorized generation inputs.
It must contain exactly one file named `报告编写范围说明.md`, at any depth. Put the
commission, report purpose, scope, content/style requirements, deliverables and
source-conflict rules in that file. The host does not choose a report genre or
require Word and Excel deliverables.

Supported inputs are `.pdf`, `.md` and `.docx`; Word `~$` lock files are ignored.
There is no exact file-count requirement. Each staged input is copied into the
new run and pinned by SHA-256. Symlink escapes and unsupported types are rejected;
files are not silently dropped or converted. Excel input remains unsupported:
export or convert it to a supported format before selecting the input folder.

Optional reference PDFs belong in `成果报告/` directly under the selected input
root. Zero, one or several are supported. They are labelled
`structure_and_format_only` and the commission tells agents to use them for
structure, style and layout, not as a factual or assessment basis. This is prompt
and metadata guidance; source provenance still needs review in the delivered
report. No reference instruction is added when none is supplied.

For M1 authorized on 2026-11-02, the selected root is the customer's
`前置资料和参考规范指南` directory. Its sibling `成果报告` is **not** included:
Codex may compare it with the generated result afterwards, but generation agents
do not receive that sibling directory or report.

M1 uses one independent persistent 200,000,000-token account for both model smoke
checks, full report attempts and reruns. The initial full report run has a
100,000,000-token ceiling. Used tokens and reserved/unknown upper bounds count;
unknown outcomes are not reset or blindly resent. Explicit ledger reuse requires
the same M1 authorization receipt and a pinned unchanged account baseline. A new
run is single-use; continuing an interrupted run is not implemented by relaunching
it or resetting its run budget.
