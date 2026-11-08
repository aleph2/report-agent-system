"""Stable identifiers for an assertion's content and the request that produced it."""
import hashlib
import json

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from .schema.kinds import Claims, Ground

_CLAIM = TypeAdapter(Claims)
_GROUNDS = TypeAdapter(tuple[Ground, ...])


def canonical_json(value):
    return json.dumps(to_jsonable_python(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def request_digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def assertion_id(subject, claim, grounds, actor, task, operation_id):
    """Normalize typed defaults before hashing. Wall-clock timestamps are metadata."""
    return request_digest({
        "subject": subject, "claim": _CLAIM.validate_python(claim),
        "grounds": _GROUNDS.validate_python(grounds), "was_attributed_to": actor,
        "was_generated_by": task, "operation_id": operation_id,
    })
