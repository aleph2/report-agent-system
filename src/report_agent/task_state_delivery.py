"""Verified context changes in native message history, not an instance cache."""
from copy import deepcopy
from uuid import uuid4

from langchain.agents.middleware.types import ExtendedModelResponse
from langchain_core.messages import HumanMessage, convert_to_messages

from .store import digest, encode

FRAME = 'report_task_state_frame'
MODEL_COMMAND = 'report_model_command_message'


def model_response(response):
    """Keep the native command intact while identifying its program-authored notes."""
    if not isinstance(response, ExtendedModelResponse):
        return response
    command = response.command
    if command is not None and isinstance(command.update, dict):
        messages = command.update.get('messages')
        if messages is not None:
            messages = convert_to_messages(messages if isinstance(messages, list) else [messages])
            for message in messages:
                if isinstance(message, HumanMessage):
                    message.additional_kwargs[MODEL_COMMAND] = True
            command.update['messages'] = messages
    return response.model_response


def verified_frame(store, message):
    if not isinstance(message, HumanMessage):
        return None
    metadata = message.additional_kwargs.get(FRAME)
    if not isinstance(metadata, dict) or not isinstance(metadata.get('receipt'), str):
        return None
    key = metadata['receipt']
    if not key.startswith('task_state_frame:'):
        return None
    receipt = store.get(key)
    if not isinstance(receipt, dict) or receipt.get('content_digest') != digest(message.content):
        return None
    return receipt


def prepare_delivery(store, messages, context):
    """Reconstruct only this actor's authenticated chain; a missing base resets it."""
    import json
    state, chain, business = None, [], []
    for message in messages:
        receipt = verified_frame(store, message)
        if receipt is None:
            business.append(message)
            if isinstance(message, HumanMessage) and FRAME in message.additional_kwargs:
                state, chain = None, []
            continue
        # Host state from another actor is neither an instruction nor business data.
        if receipt.get('actor_id') != context['actor_id']:
            state, chain = None, []
            continue
        try:
            frame = json.loads(message.content)
            if frame['kind'] == 'full':
                state, chain = deepcopy(frame['state']), []
            elif frame['kind'] == 'delta' and state is not None:
                if frame['base_digest'] != digest(state):
                    raise ValueError('state base changed')
                for path in frame['removed_paths']:
                    if len(path) != 1:
                        raise ValueError('unsupported state path')
                    del state[path[0]]
                state.update(deepcopy(frame['changes']))
            else:
                raise ValueError('state base missing')
            if not isinstance(state, dict) or digest(state) != frame['state_digest']:
                raise ValueError('state digest changed')
            chain.append(frame)
        except (ValueError, TypeError, KeyError):
            state, chain = None, []
    new = None
    if state != context:
        if state is None:
            frame = {'kind': 'full', 'state': deepcopy(context), 'state_digest': digest(context)}
        else:
            frame = {'kind': 'delta', 'base_digest': digest(state),
                'changes': {k: deepcopy(v) for k, v in context.items() if k not in state or state[k] != v},
                'removed_paths': [[k] for k in state if k not in context],
                'state_digest': digest(context)}
        new = HumanMessage(content=encode(frame), id=str(uuid4()),
            additional_kwargs={FRAME: {'receipt': 'task_state_frame:' + uuid4().hex}})
        chain.append(frame)
    return business, chain, new


def persist_frame(store, actor, message):
    # Written only after a successful model response; never replay to save context.
    from .live_messages import _once
    _once(store, message.additional_kwargs[FRAME]['receipt'],
          {'actor_id': actor, 'content_digest': digest(message.content)})
