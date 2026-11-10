# Retire archived ASE experiments — current-tree cleanup

Source: 0 added / 1,638 removed across 12 obsolete experiment scripts; application src unchanged. Five old test modules removed (22 collected cases). No application check/guard is removed or weakened. The census loses exactly 13 sites belonging to the removed correction launcher; its scanner and guard remain unchanged.

All 210 ASE files were archived outside the public repository and verified byte for byte. A verified private Git bundle preserves all existing branches/tags and their reachable history. The original run databases, G5/source originals, financial records, holds and historical .analysis records are untouched.

Independent read-only dependency checking found no current application/Stage 1 consumer. Two extra diagnostic wrappers and their two tests extend the original list. Their oracle_file fields are metadata, not file reads; their retirement is an explicit obsolete-experiment cleanup, not a technical requirement of removing .ase. Shared model/stance helpers stay.

Historical .analysis/task053/run_retry.py remains evidence. It depends on the retired flat probe and ASE task file and is not a valid current launcher; consult the privately archived historical code instead.

.gitignore excludes .ase to prevent accidentally adding the private archive again. M8's frozen review tag remains 4d808dd; the owner accepted it, main has advanced to it and the M8 branch is retired. This is a separate cleanup branch.

Verification: all 6,159 remaining tests collect, exactly 22 obsolete cases fewer; 76 focused guards passed. Passing checks leave no case DBs. [Evidence](../verification/ase-retirement-20261109.json). No full regression or paid run was started. Deleting current files does not remove public history or email addresses. No history rewrite or visibility change is performed by this cleanup.
