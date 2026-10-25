# Report Agent System

A Python/DeepAgents application for goal-driven report authoring, independent review,
and presentation. Agent decisions use real task observations; the server owns version
binding, permissions, immutable business evidence, operation identities and persistence.

## Install

Use Python 3.12 or later in an isolated virtual environment:

```bash
python -m pip install -e '.[test]'
report-agent --help
```

Provider credentials and customer manifests are configured locally. Never commit keys,
source/customer files, runtime databases, private traces or learning libraries. Native
Word rendering/directory refresh needs LibreOffice Writer, UNO Python and suitable fonts.
Historical ADK tests additionally require the `historical-tests` optional dependencies;
optional graph/model-learning integrations have their own environment requirements.

## Layout

- `src/report_agent`: native runtime, tools, prompts, storage, export and application UI.
- `tests`: original and added regression tests, retained without weakening their oracles.
- `scripts`: application/development utilities; historical reference scripts can require
  private local archives and do not run automatically as part of installation.
- `pyproject.toml`: pinned runtime and optional dependency definitions; package base0.1.0.

See `ARCHITECTURE.md` and `RELEASE_VALIDATION.md` for responsibility and evidence boundaries.
The Git tag identifies this source snapshot; it does not confer engineering approval.

## Regression scope

The published package, test and script bytes are checked against the locally tested source.
This repository intentionally excludes operational history and private model archives.
Some unchanged historical tests require a separate, local private fixture bundle. Restore
those authorized local fixtures before attempting the complete historical suite; missing
fixtures are not a product pass. No tests or pinned oracle hashes have been removed or
changed to hide this limitation. A fresh clone has not been independently run through the
entire same historical suite. The exact local outcome is recorded in `RELEASE_VALIDATION.md`.

The report-validation scenario uses fictional source data. Some other historical fixtures
encode generic layout constraints derived from prior standards; the complete fixture corpus
must not be described as entirely fictional. No raw customer standard is bundled here.
