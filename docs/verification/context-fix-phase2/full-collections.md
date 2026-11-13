# Phase2 item 3 — complete small planning collections

Source +42/−12; checks/guards added: full-read selector validity and complete serialized response fit; removed: none of the existing paging/version guards; new legacy fallback paths: 0.

Owner-delegated requirement: `read_planning_draft(full=True, collection=...)` returns the entire named planning collection when it fits the existing observation allowance. This covers requirements, objects, sections, questions, reconciliations and the reader's other ordinary collections. Subject-specific assertion readers retain their own interface.

The candidate keeps the same requirements reference, draft revision and collection digest. It measures the complete returned envelope, including escaped JSON text and diagnostics, against the actual Coordinator FilesystemMiddleware instance's selected eviction limit and installed SDK character factor. The native builder creates that middleware once before its tools and passes a build-scoped predicate through existing factories; no new size constant or configuration source was added. Default behavior and existing continuations are unchanged.

An oversized or unconfigured full read explicitly returns `full_read.complete=false` plus the ordinary paged result. A successful full read has neither a next page nor next character offset. Missing/stale continuation pins and incompatible selectors remain refused.

Main reproduced five missing-behavior RED cases, then ran **140 focused cases, all passed in 108.14s**, under the offline network guard. The existing native wire check now proves the actual factory delivers a complete requirements read. Existing H3 and carryover readers also pass. Neo checked installed SDK eviction/serialization and instance replacement, reviewed source and terminal logs, and approved this commit. Neo did not independently run tests.

Evidence: `.private/context-fix-phase2-20261112/implementation/slice3-red.log` and `slice3-focused.log`. Exact live-provider savings and full-candidate regression remain unverified. No paid call or financial mutation occurred.
