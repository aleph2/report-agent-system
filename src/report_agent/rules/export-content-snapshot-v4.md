Export an authorized exact snapshot or saved deliverable to Word with presentation-only options.
Provide exactly one of snapshot_ref or deliverable. For a saved declaration use
deliverable={"kind":"deliverable","operation_id":<result.deliverable.operation_id>};
this selector is not the whole returned declaration. The program resolves its exact members and
creates or reuses the bound snapshot. You do not need to copy member_refs and freeze them
again. Use the same handle or exact snapshot for companion XLSX and review delegation;
applicable standards are bound independently by the review task, not by cloning the snapshot.
Existing snapshots keep their ownership. First resolving saved_work may create a new snapshot
owned by this caller under the existing rules. Layout tasks may export only the snapshot
explicitly granted at delegation.
Node options identify exact refs: heading_level promotes the existing first text line;
column_weights set table proportions, landscape isolates a table/figure on wide pages.
Directory refresh is layout.refresh_toc, inside layout; top-level refresh_toc or
refresh_toc_default is unsupported. To change only refresh, read the prior ExportArtifact
object's export_config.layout and retain its nodes/styles/headings before changing this
field. read_content_export returns parsed content, not the saved layout configuration.
To reuse saved layout exactly, pass layout_from_export_ref naming an exact Word
ExportArtifact instead of layout. The server validates its saved configuration against
this target snapshot; it never remaps node versions or chooses latest.
This cannot replace text, numbers, conditions, evidence or criteria. A new export needs
applicable artifact review for its changed presentation; old artifact review does not
cover it. Unchanged content evidence may still be reused under its exact scope/version.
