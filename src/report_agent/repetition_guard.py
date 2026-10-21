"""Stop only a proven local write replay chosen after its actual model notice.

This is an invocation-local middleware helper, not a semantic progress judge,
retry loop, call quota, or persistent authorization record.
"""
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from .content_store import ContentStore
from .content_tasks import bound_actor, current_invocation
from .errors import ActionForbidden
from .store import digest


SUPPORTED = frozenset({"commit_objects", "save_text_node"})
NOTICE = (
    "Local write-replay boundary: the last three identical successful observations "
    "are backed by the same owned durable write receipt and unchanged business state "
    "in this invocation. Choosing that exact write again without a relevant change "
    "will stop with REPEATED_ACTION_WITHOUT_STATE_PROGRESS before executing it. "
    "Choose further work from the goal and actual evidence; this does not judge "
    "semantic correctness, forbid repeated reading or calculation, or approve a report."
)


class KnownWriteRepetition:
    def __init__(self, workspace, role):
        self.workspace, self.role = workspace, role
        self.windows, self.armed = {}, {}

    def scope(self, messages):
        if self.role != "writer" or self.workspace.store.manifest.get("review_entrypoint") != "delegated-reviewer-v1":
            return None
        try:
            actor = bound_actor(self.workspace, self.role, None)
            invocation = current_invocation(self.workspace, actor)
        except ActionForbidden:
            return None
        human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        if actor is None or human is None or not human.id:
            return None
        return actor, (actor.id, invocation["delegate_operation_id"], invocation["description_sha256"], human.id)

    def fingerprint(self):
        # One consistent database view. Observation counts, activity, timestamps,
        # scratch/todos and token accounting are deliberately not business progress.
        with self.workspace.store.connect() as db:
            db.execute("BEGIN")
            if db.execute("SELECT 1 FROM content_operations WHERE json_extract(response,'$.code')="
                          "'OPERATION_OUTCOME_UNRESOLVED' LIMIT 1").fetchone():
                return None
            if db.execute("SELECT 1 FROM state WHERE key LIKE 'text_work:%' AND "
                          "json_extract(value,'$.state') IN ('reserved','running','dispatching','outcome_unresolved') LIMIT 1").fetchone():
                return None
            heads = db.execute("SELECT h.type,h.id,h.version,v.data FROM content_heads h JOIN content_versions v "
                "ON v.type=h.type AND v.id=h.id AND v.version=h.version ORDER BY h.type,h.id").fetchall()
            state = db.execute("SELECT key,value FROM state WHERE key IN "
                "('manifest','feedback','report_issues','issues','context_revision','source_changes','corrections',"
                "'content_delivery','content_execution_decision','context_policy','knowledge_enabled',"
                "'acceptance_mode','acceptance_default','active_rubric_hash','decision_observation') "
                "OR key LIKE 'operator_%' ORDER BY key").fetchall()
            sources = db.execute("SELECT data FROM source_versions ORDER BY rowid").fetchall()
        return digest({"heads": heads, "state": state, "sources": sources})

    def trusted(self, actor, call):
        if call["name"] not in SUPPORTED:
            return None
        operation = call.get("args", {}).get("operation_id")
        if not isinstance(operation, str) or not operation:
            return None
        cs = ContentStore(self.workspace.store)
        try:
            receipt = cs.receipt(actor, operation)
        except ActionForbidden:
            return None
        if receipt["state"] != "known_success":
            return None
        refs = receipt["response"].get("result", {}).get("refs")
        if not refs:
            return None
        # The receipt is real and owned. No response wording creates a receipt.
        return {"tool": call["name"], "args": call["args"], "operation_id": operation,
                "request_digest": receipt["request_digest"], "response": receipt["response"]}

    def observe(self, call, result, messages):
        scoped = self.scope(messages)
        if scoped is None:
            return
        actor, key = scoped
        ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)
                   and any(c["id"] == call["id"] for c in m.tool_calls)), None)
        proof = self.trusted(actor, call)
        if (proof is None or ai is None or not ai.id or not isinstance(result, ToolMessage)
                or result.status != "success" or result.tool_call_id != call["id"]):
            self.windows.pop(key, None)
            return
        state = self.fingerprint()
        if state is None:
            self.windows.pop(key, None)
            return
        record = {"ai_id": ai.id, "call_id": call["id"], "proof": proof, "state": state}
        self.windows[key] = [*self.windows.get(key, []), record][-3:]

    def prepare(self, messages, repeated_tool):
        scoped = self.scope(messages)
        if scoped is None:
            return None
        actor, key = scoped
        self.armed.pop(key, None)
        records = self.windows.get(key, [])
        if repeated_tool not in SUPPORTED or len(records) != 3:
            return None
        tail = messages[-6:]
        if len(tail) != 6:
            return None
        state = self.fingerprint()
        for record, action, observed in zip(records, tail[::2], tail[1::2]):
            if (not isinstance(action, AIMessage) or len(action.tool_calls) != 1
                    or not isinstance(observed, ToolMessage) or observed.status != "success"
                    or (action.id, action.tool_calls[0]["id"]) != (record["ai_id"], record["call_id"])
                    or observed.tool_call_id != record["call_id"] or state is None or record["state"] != state):
                return None
            trusted = self.trusted(actor, action.tool_calls[0])
            try:
                delivered = json.loads(observed.content)
            except (TypeError, ValueError):
                return None
            if trusted != record["proof"] or delivered != trusted["response"]:
                return None
        if not all(r["proof"] == records[0]["proof"] for r in records):
            return None
        return {"key": key, "proof": records[-1]["proof"], "state": state,
                "observed_call_ids": [r["call_id"] for r in records]}

    def after_model(self, prepared, response):
        if prepared is None:
            return
        outputs = getattr(response, "result", [])
        if len(outputs) != 1 or not isinstance(outputs[0], AIMessage) or not outputs[0].id:
            return
        message = outputs[0]
        if len(message.tool_calls) != 1 or message.invalid_tool_calls:
            return
        call, proof = message.tool_calls[0], prepared["proof"]
        if call["name"] == proof["tool"] and call["args"] == proof["args"]:
            self.armed[prepared["key"]] = {**prepared, "ai_id": message.id, "call_id": call["id"]}

    def intercept(self, call, messages):
        scoped = self.scope(messages)
        if scoped is None:
            return
        actor, key = scoped
        armed = self.armed.pop(key, None)  # Only the actual next chosen call can consume it.
        if armed is None:
            return
        ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if (ai is None or (ai.id, call["id"]) != (armed["ai_id"], armed["call_id"])
                or self.fingerprint() != armed["state"] or self.trusted(actor, call) != armed["proof"]):
            return
        self.workspace.store.event("known_write_repetition_stopped", {
            "actor_id": actor.id, "invocation": key[1], "instruction_digest": key[2], "human_message_id": key[3],
            "tool": call["name"], "operation_id": armed["proof"]["operation_id"],
            "request_digest": armed["proof"]["request_digest"], "state_digest": armed["state"],
            "observed_call_ids": armed["observed_call_ids"], "attempted_call_id": call["id"],
            "advisory_delivered": True, "attempted_write_executed": False})
        raise RuntimeError("REPEATED_ACTION_WITHOUT_STATE_PROGRESS")
