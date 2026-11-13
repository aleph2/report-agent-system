# Phase2 item 4 — existing planning IDs in current state

Source +37/−0; checks/guards added: none; removed: none; new legacy fallback paths: 0.

Owner-delegated requirement: show actual known object, indicator and section IDs in the existing Coordinator current-state tail. Historical replay showed this table was absent at turns 58–60. No aliases or persistent lookup store are created.

`commission_planning.planning_ids` projects only IDs and labels from the current draft, skeleton and linked reviewed method entries, with the draft revision and requirements reference. The exact published-plan reference remains separate; identical rows are represented by `same_as_draft`, while differing published rows remain visible. The note directs page-binding proposals to published IDs. No plan assembly, gap calculation or source/attribute bodies are included. An empty projection is omitted.

`task_context.exact_task_context` adds this projection only for an enabled Coordinator. Main reproduced missing behavior, then ran **21 focused cases, all passed in 15.36s**, including the existing native wire check proving the table reaches the actual current-state tail. The new behavioral case covers before-object state, draft edits, publication and subsequent draft changes without changing the published basis. Neo reviewed source and terminal evidence and approved this commit; Neo did not independently run tests.

Evidence: `.private/context-fix-phase2-20261112/implementation/slice4-red.log` and `slice4-focused.log`. Actual model error reduction and token cost remain for the final candidate replay; neither is established by these synthetic checks. No paid call or financial mutation occurred.
