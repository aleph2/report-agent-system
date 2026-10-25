"""Count presentation changes in committed project exports, not agent tasks.

The project is the commissioned report identity. New roots, tasks and snapshots
cannot reset its allowance. This is a deterministic business constraint, not an
agent workflow or a layout correctness judgment.
"""
import json

from .errors import ActionRejected
from .store import digest


def _fingerprint(config):
    from .content_layout import LayoutOptions
    raw = config.get("layout", {})
    # Current defaults make omitted and explicit defaults equivalent. Unknown
    # historical controls retain their raw identity rather than disappearing.
    try:
        options = LayoutOptions.model_validate(raw).model_dump()
    except ValueError:
        options = raw

    def normalize(value):
        if isinstance(value, dict):
            if set(value) == {"type", "id", "version"}:
                return {"type": value["type"], "id": value["id"]}
            return {key: normalize(child) for key, child in value.items()}
        if isinstance(value, list):
            return [normalize(child) for child in value]
        return value

    # A code release or content-driven reflow is not an author layout revision.
    # Count normalized selected controls, not source-code bytes or DOCX zip metadata.
    return digest(normalize(options))


def status(db):
    configured = db.execute("SELECT value FROM state WHERE key='layout_revision_limit'").fetchone()
    limit = json.loads(configured[0]) if configured else 1
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ActionRejected("INVALID_LAYOUT_REVISION_LIMIT")
    previous, count, initial, latest = None, 0, None, None
    for row in db.execute("SELECT data FROM content_versions WHERE type='ExportArtifact' ORDER BY rowid"):
        record = json.loads(row[0])
        payload = record["payload"]
        if not payload.get("file_ref", "").endswith(".docx"):
            continue
        fingerprint = _fingerprint(payload.get("export_config", {}))
        if previous is not None and fingerprint != previous:
            count += 1
        previous = fingerprint
        initial = initial or record["ref"]
        latest = record["ref"]
    return {"max_revisions": limit, "revisions_used": count,
            "initial_export_ref": initial, "latest_export_ref": latest,
            "latest_fingerprint": previous,
            "scope": "commissioned report in this project; cumulative across tasks and snapshots"}


def check(db, config):
    current = status(db)
    fingerprint = _fingerprint(config)
    changed = current["latest_fingerprint"] not in (None, fingerprint)
    used = current["revisions_used"] + int(changed)
    if changed and current["max_revisions"] is not None and used > current["max_revisions"]:
        raise ActionRejected("LAYOUT_REVISION_LIMIT_REACHED")
    return {**current, "revisions_used": used, "layout_changed": changed,
            "fingerprint": fingerprint}
