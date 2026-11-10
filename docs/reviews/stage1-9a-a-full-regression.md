# Part a — full regression and test migration corrections

Follow-up: the separately authorized [clean replacement passed and part a is accepted](stage1-9a-a-acceptance.md). The failed-run facts below are preserved.

Follow-up production source **+5 / -5 / net 0** (neutral identifier rename only); checks/guards **+0 / -0**; legacy fallbacks **+0**. Part-a production total remains +503 / -129 / net +374. [Results](../verification/stage1-9a-a-full/results.json).

**Gate not passed.** The owner accepted a in substance and authorized one full offline run on 5c34d34, conditional main advancement on a clean result. That run finished in 31m14s: **6,124 passed / 35 failed / 9 skipped**, with no missing, duplicate or unexpected cases or collection errors. Coverage 90.50%; all 13 existing floors met. This is a failed run, not a reconciled green result.

The 35 failures have four reproduced causes: ten old Writer tool-set expectations; eleven old Coordinator extraction/schema expectations; thirteen retired file-policy/role fixtures; and the unchanged domain-neutrality guard rejecting an indicator local name. The correction at **3cca78e** changes the tests to the approved roles and supplied-file boundary and renames only that local/parameter. It adds no approval, fallback, domain rule, dispatcher change or guard exemption. A changed source display title remains a distinct immutable version; it no longer invokes retired file reapproval. Wrong content, citations, file membership, page bindings and source version eligibility retain their checks.

**177 focused cases pass** across the affected modules, including the replacement for each of the 35 failures. Native Writer coverage now checks two exact quotations, conflict storage, exact replay, wrong-quote refusal, foreign-observation refusal and absence of receipts after refusals. [Exact failure-to-pass mapping](../verification/stage1-9a-a-full/failed-node-replacements.json). One-file Pyright: zero errors. The inverse local-name substitution is byte-identical to the tested candidate source. No new mutation experiment or independent rerun is claimed.

Current collection is **6,169**, including the new Writer regression. The original failed-run logs and its 233 failed-case database files remain private under pytest's failed/count-1 retention policy; successful test cases are automatically removed. The frozen failed-run source copy is retained with its unchanged-input manifest. No original case, paid response, ledger or hold was modified.

Both part-d references are now explicit in the consolidated list: the binding's plan reference in rule text and the checkpoint marker in question text. Local/private import boundaries are noted for the affected c/d work.

**Next required action:** authorize one replacement clean offline full run on this correction. Main remains cac8ca6; part b has not started. Do not advance main or claim part-a final acceptance from the focused pass. No paid launch is authorized here.
