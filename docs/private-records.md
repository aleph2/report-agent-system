# Private case records

The owner requires case-derived content to stay outside the public repository.
Original historical records, direct instruction packs, source scope and contact policy:
`.private/`.

`current-tree-before-privacy.tar` preserves the original tree;
`repository-before-sanitization.bundle` preserves the original histories.
`classified-removal-scope.json` lists the archived public paths.
`o6-private-scope.json` holds the real extraction scope; public tests use synthetic scope.
`round-summary-policy-20261026.json` retains the authorized routing privately.
The rewritten public candidate is not the original tested/accepted historical snapshot.
Use original private tags, on case copies, for historical recovery.

The operator links or mounts `.private/` to private storage locally; Git ignores it.
Historical checkouts retain original private history and are read-only archives.
Use a fresh clone of public `main` for development; do not push from an old checkout.
