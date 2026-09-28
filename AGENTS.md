# Independent Report Agent System

Read `.ase/principles.md` and the active task before changing code.
For architecture work, also read `.ase/roles/architect.md` and its linked knowledge.
The user-selected framework is DeepAgents; Google design patterns are references.
The current ADK prototype is not evidence that this framework choice was implemented.
The confirmed v0.4 revision governs implementation: dynamic goal-level coordination,
bounded text tools, no mandatory expert roster; preserve ownership and final review.
This is a greenfield application. Do not copy, import or wrap the legacy application,
modify its services/configuration/data, or use its writable storage. Documents and
verified source/OCR inputs may be reused with provenance; third-party libraries are allowed.

Agents choose actions from goals and real observations. LLM text analysis is a bounded
tool capability, not automatically a separate agent. Do not prescribe the full semantic
tool sequence or move a fixed multi-expert pipeline into a tool, prompt or Skill.
Bind permissions to the current task on the server; the model cannot change roles.

Develop the smallest decisive prototype, then the real end-to-end report path.
Use focused tests for deterministic behavior; simulated models do not prove autonomy
or content quality. Keep current model/call authorization explicit in task records.
Classify confirmed defects P0-P3 and name the specific blocked action; do not require
zero defects before learning from a contained experiment.

For changes to agent/tool boundaries, ownership, recovery or principle-compliance
claims, obtain independent alignment review within the existing review step.
Use `.ase/roles/alignment-reviewer.md`; record actual reviewer identity and disposition.
Missing review or runtime evidence must be disclosed, never represented as passed.
Do not create a runtime compliance agent or a new approval loop.
