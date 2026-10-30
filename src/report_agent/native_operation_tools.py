"""Native injection for existing writes; business contracts stay unchanged."""
from functools import wraps
from inspect import signature
from typing import Annotated, get_type_hints

from langchain_core.tools import InjectedToolCallId, StructuredTool
from pydantic import BaseModel, Field, create_model

from .operation_identity import NATIVE_WRITES, NATIVE, write_id, profile


class MessageTool(StructuredTool):
    """The declared business model owns both public validation and field documentation."""
    message_model: type[BaseModel] = Field(exclude=True)

    @property
    def tool_call_schema(self):
        return self.message_model


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
    message_model = getattr(function, 'message_model', None)
    if message_model is not None:
        schema = create_model(function.__name__ + 'Invocation', __base__=message_model,
            operation_id=(Annotated[str, InjectedToolCallId], ...))
        return MessageTool.from_function(invoke, args_schema=schema, message_model=message_model)
    return StructuredTool.from_function(invoke)


def native_write_tools(workspace, role, functions):
    if profile(workspace.store) != NATIVE:
        return functions
    return [_native_write(workspace, role, function)
            if getattr(function, '__name__', None) in NATIVE_WRITES else function
            for function in functions]
