Page frozen-snapshot node identities, sizes and relations without loading bodies.
The actor-bound snapshot_structure receipt covers this returned page only: offset,
returned_refs, next_offset, total_nodes and manifest version. It satisfies no body/source
read dependency. Manifest order is index order; contains relations define document order.
Choose needed body/source reads independently. A partial index proves neither absence
across unread scope nor correctness. You may save partial findings with remaining work.
