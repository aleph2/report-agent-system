Read frozen source text blocks. offset and next_offset are zero-based block
positions, not characters or physical PDF pages; inspect_source_page uses 1-based
physical pages. Selected text is preserved. Follow supplied recovery paths or use
read_tool_observation with your own observation_ref for deferred original returns.
Recovery does not expand access. next_offset=None completes block pagination only,
not reading of deferred content.

source_table_views contains separate unverified whole-page mechanical table
supplements when available. They can be incomplete and do not replace original text,
perform OCR or verify column meaning. table_detail='references' preserves selected
text and defers table extraction to exact inspect_source_page locators; unexpanded
is not absent. Omitted/full keeps full supplements independently of search defaults.
Changing views does not authorize retrying unknown paid work.