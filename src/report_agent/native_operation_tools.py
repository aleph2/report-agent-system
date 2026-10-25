"""Native injection for existing writes; business contracts stay unchanged."""
from functools import wraps
from inspect import signature
from typing import Annotated, get_type_hints

from langchain_core.tools import InjectedToolCallId, StructuredTool

from .operation_identity import NATIVE_WRITES, NATIVE, write_id, profile


def _native_write(workspace, role, function):
    from .text_work import actor_for_tool

    @wraps(function)
    def invoke(**kwargs):
        call_id = kwargs.pop('operation_id')
        identity = write_id(actor_for_tool(workspace, role).id, function.__name__, call_id)
        result = function(operation_id=identity, **kwargs)
        return {**result, 'operation_id': identity}

    annotations = get_type_hints(function, include_extras=True)
    annotations['operation_id'] = Annotated[str, InjectedToolCallId]
    original = signature(function)
    invoke.__annotations__ = annotations
    invoke.__signature__ = original.replace(parameters=[
        parameter.replace(annotation=annotations.get(name, parameter.annotation))
        for name, parameter in original.parameters.items()],
        return_annotation=annotations.get('return', original.return_annotation))
    return StructuredTool.from_function(invoke)


def native_write_tools(workspace, role, functions):
    if profile(workspace.store) != NATIVE:
        return functions
    return [_native_write(workspace, role, function)
            if getattr(function, '__name__', None) in NATIVE_WRITES else function
            for function in functions]
