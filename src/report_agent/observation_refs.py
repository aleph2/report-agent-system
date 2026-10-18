"""Public observation identities: exact consumption versus explicit lookup."""
from typing import Annotated
from pydantic import Field, TypeAdapter, StrictStr, StrictInt

ObservationRef = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$',
    description='Full actor-owned 64-character lowercase hex observation identity. Recover abbreviated references through read_summary_observations; never guess or pad.')]
ObservationRefPrefix = Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[0-9a-f]+$',
    description='Lookup prefix only, 1..64 lowercase hex characters. May match zero or several owned references; not accepted for reading or text production.')]

_prefix_adapter = TypeAdapter(ObservationRefPrefix)
ObservationPath = Annotated[list[StrictStr | StrictInt], Field(max_length=64,
    description='Exact JSON path in the original owned return: string object keys or integer array indexes. Selects a string value, whose offsets are Unicode characters within that value. Omit for raw returned-text coordinates; [] selects a JSON root string.')]
_path_adapter = TypeAdapter(ObservationPath)

def validate_path(value):
    return _path_adapter.validate_python(value, strict=True)

def validate_prefix(value):
    """Direct callers and the native tool schema share one prefix contract."""
    return _prefix_adapter.validate_python(value, strict=True)
