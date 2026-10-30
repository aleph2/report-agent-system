"""Exact, caller-selected content views. No traversal policy or semantic assessment."""
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .content_models import Ref
from .content_store import ContentStore
from .errors import ActionRejected


class ContentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ref: Ref
    unit: Literal["text", "rows"] = "text"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=12000, ge=1, le=16000)


def snapshot_members(contents, snapshot_ref):
    ref = Ref.model_validate(snapshot_ref).model_dump()
    if ref["type"] != "DocumentSnapshot":
        raise ActionRejected("CONTENT_SELECTION_REQUIRES_SNAPSHOT")
    snapshot = contents.read(ref)
    return snapshot, {Ref.model_validate(r).key() for r in snapshot["payload"]["refs"]}


def selected_content(workspace, snapshot_ref, selections):
    if not selections:
        return []
    if snapshot_ref is None:
        raise ActionRejected("CONTENT_SELECTION_REQUIRES_SNAPSHOT")
    contents = ContentStore(workspace.store)
    snapshot, members = snapshot_members(contents, snapshot_ref)
    result = []
    for index, raw in enumerate(selections):
        selection = ContentSelection.model_validate(raw)
        if selection.ref.type != "ContentNode" or selection.ref.key() not in members:
            raise ActionRejected("CONTENT_SELECTION_OUTSIDE_SNAPSHOT", diagnostic={
                'reason': 'unsupported_selection_object_type' if selection.ref.type != 'ContentNode'
                    else 'object_not_in_snapshot', 'allowed_object_types': ['ContentNode'],
                'parameter_path': ['selections', index, 'ref'], 'snapshot_ref': snapshot_ref})
        record = contents.read(selection.ref.model_dump())
        payload, start = record["payload"], selection.offset
        body = payload["body"]
        if selection.unit == "rows":
            if payload["kind"] != "table" or selection.limit > 100:
                raise ActionRejected("TABLE_SELECTION_REQUIRES_ROWS_LIMIT_1_TO_100")
            values = body["rows"]
            view = {"columns": body["columns"], "rows": values[start:start + selection.limit]}
        else:
            if not isinstance(body.get("text"), str):
                raise ActionRejected("TEXT_SELECTION_REQUIRES_TEXT_BODY")
            values = body["text"]
            view = {"text": values[start:start + selection.limit]}
        total = len(values)
        if start >= total and not (start == 0 and total == 0):
            raise ActionRejected("CONTENT_SELECTION_EMPTY_RANGE")
        end = min(start + selection.limit, total)
        result.append({"kind": "content_node_selection", "selection": selection.model_dump(),
            "snapshot_ref": snapshot["ref"], "manifest_digest": snapshot["payload"]["manifest_digest"],
            "payload_digest": record["payload_digest"], "node_kind": payload["kind"],
            "claim_kind": payload["claim_kind"], "body": view, "qualifiers": payload["qualifiers"],
            "selected_range": [start, end], "total_units": total,
            "selection_units": "zero-based data rows" if selection.unit == "rows" else "zero-based Unicode characters",
            "next_offset": end if end < total else None, "complete_body_selection": start == 0 and end == total,
            "scope_note": "Selected saved content only. No descendants, related nodes or sources were implicitly read. "
                          "Complete selection is not completed review or verification of the claims."})
    return result


def content_index(contents, snapshot_ref, offset=0, limit=20):
    if isinstance(offset, bool) or isinstance(limit, bool) or offset < 0 or not 1 <= limit <= 100:
        raise ActionRejected("INVALID_PAGE")
    snapshot, _ = snapshot_members(contents, snapshot_ref)
    refs = snapshot["payload"]["refs"]
    relations = [contents.read(r) for r in refs if r["type"] == "Relation"]
    links = defaultdict(list)
    for relation in relations:
        p = relation["payload"]
        for side in ("subject_ref", "object_ref"):
            links[Ref.model_validate(p[side]).key()].append({"ref": relation["ref"],
                **{k: p[k] for k in ("subject_ref", "object_ref", "predicate", "position") if k in p}})
    nodes = [r for r in refs if r["type"] == "ContentNode"]
    page = nodes[offset:offset + limit]
    entries = []
    for ref in page:
        node = contents.read(ref)
        p, body = node["payload"], node["payload"]["body"]
        title = body.get("text", "").split("\n", 1)[0]
        if not title and p["kind"] == "table":
            title = " | ".join(str(v) for v in body["columns"])
        entries.append({"ref": ref, "kind": p["kind"], "claim_kind": p["claim_kind"],
            "title_preview": title[:160], "title_truncated": len(title) > 160,
            "text_characters": len(body.get("text", "")), "data_rows": len(body.get("rows", [])),
            "payload_digest": node["payload_digest"], "owner_id": node["owner_id"],
            "task_id": node["task_id"], "relations": links[Ref.model_validate(ref).key()]})
    return {"snapshot_ref": snapshot["ref"], "root_ref": snapshot["payload"]["root_ref"],
        "manifest_digest": snapshot["payload"]["manifest_digest"], "nodes": entries,
        "total_nodes": len(nodes), "offset": offset, "returned_refs": page,
        "next_offset": offset + limit if offset + limit < len(nodes) else None,
        "scope_note": "Metadata index, not content observation or review. Node order is manifest order; "
                      "contains relations give document structure and position. Choose local reads and related evidence as needed."}
