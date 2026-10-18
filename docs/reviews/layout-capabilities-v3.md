# Layout capability update — 2026-10-01

User-authorized scope: enable actionable specialist capability requests, make current capabilities visible to coordinator/layout, improve presentation without rewriting frozen report facts, and continue the real reviewer-feedback experiment. ASE remains suspended. Email remains paused.

## Runtime changes

`read_layout_capabilities` exposes the current schema, implementation digest and native directory-refresh availability. `request_layout_capability` saves a scoped HandlingRecord with attempted approaches, evidence, requested operation, task identity and capability digest. The coordinator can read it through feedback; development supplies implementation and evidence, then the coordinator can resume that task. This is a durable handoff, not an automatic code-writing/deployment agent or an always-on development worker.

Presentation controls now support exact unique lines inside text blocks/claims as headings or independently styled paragraphs. No replacement text is accepted. Existing global spacing, page breaks, table splitting and width choices remain model decisions. Substantive qualifiers remain visible. Optional `refresh_toc` uses the packaged native LibreOffice/UNO finalizer, checks normalized paragraph/table/media preservation, and rebuilds OOXML mapping positions using preserved bookmarks after finalization. New export identities require review.

## Native Ubuntu support

Validated locally under Ubuntu 24.04 (WSL Linux userspace), LibreOffice 24.2.7.2, `/usr/bin/python3` with `python3-uno`. Both finalization and PDF rendering used native Linux executables, with no Windows bridge. This is not a production-server deployment.

Server prerequisites:

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends libreoffice-writer python3-uno fonts-noto-cjk
```

Application uses its own Python environment. The UNO worker uses the distribution Python; pip-installed application environments do not need to import UNO. Each operation starts a headless isolated LibreOffice profile/private pipe with macros and external updates disabled, bounds execution time and cleans up owned processes. Missing dependencies are reported through capabilities and tool feedback. Pin distribution/packages/fonts in deployment images when stable pagination matters. Word/Windows pagination may differ from Linux fonts and LibreOffice.

## Evidence and limits

- Initial regression selection: 24 passed. Extended layout suite including native Linux directory-refresh integration: 7 passed.
- Real-report offline probe: `.analysis/layout-capabilities-v3/result.json`, export `c318740e-5bd8-487b-b48a-b9eda7f88a4d` v1. 572 non-TOC paragraphs and 11 tables preserved under whitespace-normalized comparison. TOC refreshed and reopened with retained cache, including 4.3.1 at page 19; native PDF render completed, 34 pages.
- This probe supplied its own two new controls to verify tool operation. It is not model-autonomy evidence. The real-model continuation must establish whether reviewer feedback leads to useful new actions; success is not inferred from protocol checks.
- Capability requests do not automatically launch development. No runtime role may mark an implementation successful merely by filing a request; published code and verification evidence must exist.
