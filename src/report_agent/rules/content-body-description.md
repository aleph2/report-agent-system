Complete kind-specific content: report/chapter/block/cell/claim needs nonblank text;
table needs named columns and rectangular rows; figure needs source_id, caption
and page (a positive integer, 1-based physical PDF page; 1 for a raster image). Auxiliary fields
cannot replace these rendered fields. A table footnote must be text: nonblank text
is exported verbatim, absent/null/blank adds none, and non-text is rejected at export.