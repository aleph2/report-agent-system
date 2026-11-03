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

Optional template PDFs belong in `成果报告/` directly under the selected input
root. Alternatively, pass `--template /path/to/report.pdf` to `stage_report.py`;
repeat the flag for several PDFs. The staging step copies them under
`inputs/成果报告/` and includes them in the same hash manifest and PDF profiles.
Original files remain unchanged. Duplicate destination names, symbolic links,
non-PDF templates and resource-limit violations are refused. Zero templates remains
valid for commissions that do not require one.

Templates are labelled `template`. Their permitted use follows the customer's
scope and the confirmed section plan. For this M1 sample, fixed sections use the
template's wording with declared replacements; project facts and scores come from
the applicable design/survey materials, never the template's example results.

The original M1 run used `前置资料和参考规范指南` and excluded its sibling
`成果报告`. That historical choice is superseded by the approved fix plan. For
the rerun, retain the original input root and explicitly pass the sibling template
PDF with `--template`; do not move the customer's originals or silently include
unrelated files from the parent directory. A staged receipt must prove the template
was included before the real checkpoint. No rerun is authorized by this document.

The scope file already limits this sample to the supplied first-contract-section
materials. The revised plan may replace the outline's named whole-project inputs
with actual supplied sources, citing the exact section4 customer quotation and
displaying the substitution and its limitations in the ordinary checkpoint brief.
This does not require the customer to restate the same scope. Source conflicts and
unknown parameters remain visible; five drawing candidates are not proof of an
exhaustive engineering inventory.

For Linux/WSL execution, use Linux-native storage for the writable run/case and
financial databases; copy completed deliverables to Windows. The previous M1 run
and ledger were under `/mnt/c` (9p/DrvFS). WAL mode alone does not validate filesystem
locking. Do not move, reset or duplicate an active financial account: before G4,
preserve the original ledger and every reservation, establish a verified authoritative
Linux-native account location and update its path-bound authorization/preflight
records. The G4 preparation adds a shared mount check at stage, prepare, launch
and direct host run, before database/provider effects. It resolves symlinks and
checks the containing mount of new paths and each database path. Only verified
local Linux filesystem types are admitted; 9p, DrvFS, network, volatile and unknown
types are refused. This is a startup check, not protection against privileged
mount changes during execution or a power-loss test.

The original M1 ledger is preserved as historical evidence. G4 preparation relocates
the same account using SQLite backup in its owning WSL runtime, checks all schema
and rows and integrity, preserves the original hash, and records the new path-bound
authority. No usage, reservation or unknown outcome is reset. Use the recorded new
authority and ledger together; do not dispatch against the historical account.

New host cases carry `assessment_presentation: table-spec-v1`: any selected
assessment method requires both reviewed table specifications at proposal,
confirmation and calculation. Non-assessment commissions need no assessment
tables. Older records remain readable; the legacy table fallback cannot generate
new assessments under this contract. The customer cannot supply a Word template;
the explicitly staged PDF remains the template and its layout limits stay visible.

M1 uses one independent persistent 200,000,000-token account for both model smoke
checks, full report attempts and reruns. The initial full report run has a
100,000,000-token ceiling. Used tokens and reserved/unknown upper bounds count;
unknown outcomes are not reset or blindly resent. Explicit ledger reuse requires
the same M1 authorization receipt and a pinned unchanged account baseline. A new
run is single-use; continuing an interrupted run is not implemented by relaunching
it or resetting its run budget.
