"""Lossless decoding of JSON objects sent as strings at a tool boundary.

This does not repair JSON, infer missing values or replace tool validation.
"""
import json
import math


def _types(schema, definitions, seen=()):
    if not isinstance(schema, dict):
        return set()
    ref = schema.get('$ref')
    if ref:
        if not ref.startswith('#/$defs/') or ref in seen:
            return set()
        return _types(definitions.get(ref[len('#/$defs/'):]), definitions, (*seen, ref))
    for key in ('anyOf', 'oneOf'):
        if key in schema:
            branches = [_types(s, definitions, seen) for s in schema[key]]
            return set().union(*branches) if branches and all(branches) else set()
    value = schema.get('type')
    return set(value) if isinstance(value, list) else {value} if isinstance(value, str) else set()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _no_constant(value):
    raise ValueError('NONFINITE_JSON_VALUE')


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('NONFINITE_JSON_VALUE')
    return result


def decode_object_arguments(arguments, schema):
    """Decode once only for top-level fields that allow objects but no strings.

    Invalid/ambiguous inputs remain unchanged so the native validator returns its
    normal error to the agent. Original arguments and schema are never mutated.
    """
    updated, fields = dict(arguments), []
    definitions = schema.get('$defs', {})
    for name, value in arguments.items():
        types = _types(schema.get('properties', {}).get(name), definitions)
        if not isinstance(value, str) or not types or 'object' not in types or types - {'object', 'null'}:
            continue
        try:
            decoded = json.loads(value, object_pairs_hook=_unique_object,
                                 parse_constant=_no_constant, parse_float=_finite_float)
        except (ValueError, RecursionError):
            continue
        if isinstance(decoded, dict):
            updated[name] = decoded
            fields.append(name)
    return updated, fields
