# Public-history sanitization plan — review only

Owner direction: keep code public and prepare sanitization. No history rewrite, tool installation, visibility change or forced publication is authorized by this document. Privacy is prioritized before M9. Ordinary Stage 1 work and the separate current-tree retirement are not history rewrites.

## Verified inventory and private recovery

The read-only public-ref snapshot, taken before the M8 acceptance handoff, has 14 branches and 53 tags: 227 reachable commits and 3,159 unique blobs. It contains 210 historical ASE paths / 280 blob versions. Two known private contact addresses occur in 16 blob versions across 11 paths, including three paths outside ASE. Nine other email-like strings and 11 binary paths remain unclassified; absence of an email is not proof that a file is public-safe.

The original archive is private, outside the checkout. Its tar snapshot was verified byte-for-byte; its all-ref Git bundle explicitly preserves all 67 advertised branch/tag targets. Original run databases, source files, ledgers, held/unknown requests and authority records are never edited. Exact path/value inventories remain private and are not reproduced here.

## Proposed content treatment

- Purge `.ase/` and former names, if any, from every affected public ref.
- Purge retired correction-launcher versions containing actual project prompt material. Review other obsolete script versions before deciding their historical removal.
- Review repository `.memory/`, private decision history, and other case-derived records using the private inventory. Remove private records as whole public copies; preserve their authentic originals privately. Do not manufacture redacted financial or authority evidence.
- Remove literal private contact routing from public `AGENTS.md`; retain a reference to the existing private contact policy. Verify the authorized sender/recipient can still be resolved locally, without sending mail.
- Classify the remaining address strings, binaries and historical records. Keep deliberately synthetic/public fixtures. Do not blindly purge all analysis folders or replace every email-shaped string.

## Execution and approval gates

1. Approve the exact purge/redaction scope after classification, including the private contact-policy location. Refresh the backup/ref inventory immediately before execution and freeze writers for the update window.
2. Authorize installing a pinned maintained `git-filter-repo` version supporting sensitive-data removal (at least 2.47). It is not installed. Do not build a custom history rewriter.
3. After approval, prepare the candidate only in a separate private disposable copy. Apply the approved path removals and safe redactions across all affected public branches/tags. Keep old/new ref maps private. No public ref changes at this stage.
4. Check approved-content absence across reachable objects, retained application/fixture equality, remaining test collection and focused guards. Preserve the single clean full-regression authorization for after M10/before 9a; request another full run only if an actual semantic change requires it. No paid model test is needed.
5. Present the concrete candidate and exact old/new ref map for final owner approval. Only then may Main update the approved public refs, checking their old IDs first. Stop if a ref moved or protection rejects the update. Do not disable protections or use an unrestricted mirror force-push.
6. Verify the resulting remote refs/content. Prepare, but do not send without communication authority, any required GitHub Support or collaborator instructions. Old clones must not push the original history back.

## Review hashes, historical cases and rollback

Commit/tag IDs and signatures can change. Do not silently claim rewritten tags are the exact snapshots previously tested or accepted. Establish an explicitly sanitized public baseline; original October/M8 hashes, case-recovery code and evidence stay authoritative in the private archive. Do not rewrite historical case records to adopt new Git IDs.

A rejected private candidate is discarded without affecting the originals or remote. After a publication problem, stop and recover privately from the bundle; do not publicly roll back by re-exposing sensitive originals. Cached GitHub views, PR references, forks and other clones need separate handling; a rewrite cannot erase copies held by others. These limitations and the maintained-tool procedure are covered by [GitHub's official guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

Pending before execution: approved content classification/path list, private contact-policy verification, tool-install authority, private candidate checks and final approval of the exact ref update. No installation, sanitization or visibility change has occurred.

## Preparation status, owner authority of 9 November

The owner authorized the isolated pinned tool installation and private candidate preparation.
The repository was temporarily made private under the owner-delegated visibility decision.
Current files and historical objects are included in classification. Original records
remain in the verified private archives. No rewritten ref has been published.
See `privacy-candidate-20261109.md` and the private exact ref map before approving publication.
