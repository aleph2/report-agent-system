# Retire archived ASE experiments — current-tree cleanup

Production application source: unchanged. Old experiment scripts: 12 removed; old test modules: five removed (22 collected cases). No application check/guard is removed or weakened. The census loses exactly 13 sites belonging to the removed correction launcher; its scanner and guard remain unchanged.

All 210 ASE files were archived outside the public repository and verified byte for byte. A verified private Git bundle preserves all existing branches/tags and their reachable history. The original run databases, G5/source originals, financial records, holds and historical .analysis records are untouched.

Independent read-only dependency checking found no current application/Stage 1 consumer. Two extra diagnostic wrappers and their two tests extend the original list. Their oracle_file fields are metadata, not file reads; their retirement is an explicit obsolete-experiment cleanup, not a technical requirement of removing .ase. Shared model/stance helpers stay.

Historical .analysis/task053/run_retry.py remains evidence. It depends on the retired flat probe and ASE task file and is not a valid current launcher; consult the privately archived historical code instead.

.gitignore excludes .ase to prevent accidentally adding the private archive again. M8's frozen review tag and branch remain unchanged, and main remains accepted M7. This is a separate cleanup branch.

Verification pending: remaining collection and focused census/access/interface guards. No full regression or paid run has been started. Deleting current files does not remove public history or email addresses. No history rewrite or visibility change is performed by this cleanup.
