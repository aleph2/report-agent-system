# Task010: Agent-maintained working state

User approved a minimal implementation and a separate test of the calculation-to-next-
action transition. Main implements/tests; Anscombe independently reviews alignment.
Stage: scoped risk validation on the existing native DeepAgents trunk, not acceptance
of the complete report. Task009 remains untouched and stopped.

Hypothesis: explicit responsibility for adopted inputs/rules/results and remaining
work improves use of existing todos/scratch files. This is not a proven historical
root cause. Task009 preserved tool results and coarse todos but requested calculate
82 times and saved no draft. Its third identical call raised a custom RuntimeError.
The known guard defect remains P2 (contained in isolated trial; blocks claiming the
repetition recovery is fixed). Main owns disposition in a separate guard change.

Only production change: concise coordinator prompt guidance. No tool, schema, agent
roster, guard, checkpoint, scheduling, provider or permissions changes. Native tools
remain optional choices; do not force a tool sequence or per-call double bookkeeping.

User authorization covers this isolated GLM5.3/high test. Use only synthetic inputs,
the existing authorized service, serial calls and fresh .runs/task010 directories.
No real source upload, OCR, graph writes, old task recovery, GUI restart or email.

Compare old and new coordinator prompt on two matched scenarios: successful totals
already observed, and an explicit human input correction invalidating one total.
Seed genuine arithmetic outputs as clearly recorded synthetic historical fixtures,
not new agent calls. Seed only a coarse in-progress todo, no prepared result ledger.
Do not tell the agent the test criteria or which tool to call next.

Observe through the production build_agent and tools. Stop the local experiment at
the first saved draft or agent end; 20 outer tool rounds are a test-only observation
bound, not a product quota. Preserve errors and incomplete attempts, never auto-retry.
Check adopted values, useful persisted state and actual draft progress; do not grade
only a fixed call count. Confirm scratch/todos survive reopening native checkpoints.
Old/new synthetic success does not prove causal improvement or long-context recovery.
