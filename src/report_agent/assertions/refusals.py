"""Apply the versioned assertion checks to a single trusted transaction view."""
from decimal import Decimal, InvalidOperation
from importlib.resources import files
import json

from .ids import canonical_json
from .schema.kinds import is_canonical_id

_RESOURCES = files("report_agent.assertions.schema")
CATALOG_JSON = _RESOURCES.joinpath("actions.json").read_text(encoding="utf-8")
CATALOG = json.loads(CATALOG_JSON)
_CHECKS = _RESOURCES.joinpath("checks.sql").read_text(encoding="utf-8")


def _between(value, low, high):
    try:
        v, lo, hi = (Decimal(str(x)) for x in (value, low, high))
        return all(x.is_finite() for x in (v, lo, hi)) and lo <= v <= hi
    except InvalidOperation:
        return False


def enforce(db, row, projection):
    db.create_function("is_canonical_id", 1, is_canonical_id, deterministic=True)
    db.create_function("decimal_between", 3, _between, deterministic=True)
    failed = db.execute(_CHECKS, dict(row=row.model_dump_json(), ctx=canonical_json(projection),
                                     catalog=CATALOG_JSON)).fetchall()
    if failed:
        raise ValueError("; ".join(f"{code}: {reason}" for code, reason in failed))
