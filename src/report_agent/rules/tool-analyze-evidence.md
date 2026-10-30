Optional one-shot LLM comparison of caller-selected, version-bound source text,
saved results or exact ContentNodes. Choose the question and actual material; the
question may have a false premise. For tree content use snapshot_ref and selected
refs/ranges: text characters up to 16000, or table rows up to 100. No descendants
are fetched automatically. Source offsets/limits are text blocks, not PDF pages;
whole-page mechanical table supplements remain separate. Empty source/result lists
are allowed. Returns observations and limits, not a verdict. No search, delegation,
business-artifact writes or acceptance decision.