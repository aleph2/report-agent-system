Export an authorized exact snapshot or saved deliverable to XLSX and save an ExportArtifact.
Provide exactly one of snapshot_ref or deliverable. Existing snapshots keep their ownership. First resolving saved_work may create a new snapshot
owned by this caller under the existing rules.
Each sheet has name, table_ref selecting a table ContentNode, and optional note_refs
selecting text-note ContentNodes. Selected text notes,
including corrections and qualifiers, are copied verbatim after that table.
The sheet and table references define workbook contents and organization.
Optional report_export_ref links an exact companion Word version, not its correctness.
A linked Word and XLSX must use the same snapshot; a cross-snapshot link is rejected.
For a snapshot with declared workbook_refs, sheets must select all and
only those workbook-only table/note nodes, leaving report prose separate.
An export record establishes file creation, not independent review or acceptance.
