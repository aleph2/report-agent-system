"""Reversible DeepSeek strict wire format; business contracts stay unchanged.

Optional fields use an explicit absent/present envelope. Open maps use entries,
and arbitrary JSON containers use tagged recursion. No semantic repair occurs.
"""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

VERSION = 'deepseek-strict-v1'
JSON_REF = '#/$defs/StrictJsonValue'


class WireError(ValueError):
    pass


def obj(properties, **extra):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False, **extra}


def tagged(kind, **properties):
    return obj({'kind': {'type': 'string', 'enum': [kind]}, **properties})


def exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise WireError('Object keys do not match the strict wire schema')


def json_value(value, encode):
    if value is None or type(value) in (str, int, float, bool):
        return value
    if encode:
        if type(value) is list:
            return {'kind': 'array', 'items': [json_value(v, True) for v in value]}
        if type(value) is dict:
            return {'kind': 'object', 'entries': map_value(value, True, lambda v: json_value(v, True))}
    elif type(value) is dict:
        if value.get('kind') == 'array':
            exact(value, ['kind', 'items'])
            if type(value['items']) is not list:
                raise WireError('Array items must be a list')
            return [json_value(v, False) for v in value['items']]
        if value.get('kind') == 'object':
            exact(value, ['kind', 'entries'])
            return map_value(value['entries'], False, lambda v: json_value(v, False))
    raise WireError('Invalid tagged JSON value')


def map_value(value, encode, convert):
    if encode:
        if type(value) is not dict or any(type(k) is not str for k in value):
            raise WireError('Map requires string keys')
        return [{'key': k, 'value': convert(v)} for k, v in value.items()]
    if type(value) is not list:
        raise WireError('Map entries must be a list')
    result = {}
    for entry in value:
        exact(entry, ['key', 'value'])
        key = entry['key']
        if type(key) is not str or key in result:
            raise WireError('Map keys must be unique strings')
        result[key] = convert(entry['value'])
    return result


def entries_schema(value):
    return {'type': 'array', 'items': obj({'key': {'type': 'string'}, 'value': value})}


JSON_SCHEMA = {'anyOf': [
    {'type': 'string'}, {'type': 'number'}, {'type': 'boolean'}, {'type': 'null'},
    tagged('array', items={'type': 'array', 'items': {'$ref': JSON_REF}}),
    tagged('object', entries=entries_schema({'$ref': JSON_REF}))]}


@dataclass
class Node:
    schema: dict
    encode: Callable
    decode: Callable


def compile_node(source):
    source = deepcopy(source)
    supported = {'type', 'properties', 'required', 'additionalProperties', 'items', 'anyOf', 'oneOf',
                 'description', 'enum', 'const', 'pattern', 'format', 'minimum', 'maximum',
                 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf', 'title', 'default',
                 'minLength', 'maxLength', 'minItems', 'maxItems', 'discriminator'}
    if set(source) - supported:
        raise WireError('Unsupported source schema keywords: ' + ','.join(sorted(set(source) - supported)))
    description = source.get('description')
    choices = source.get('anyOf', source.get('oneOf'))
    if choices is not None:
        nodes = [compile_node(s) for s in choices]
        def choose(value, encode):
            for node in nodes:
                try:
                    return (node.encode if encode else node.decode)(value)
                except WireError:
                    pass
            raise WireError('No union branch matches the supplied value')
        node = Node({'anyOf': [n.schema for n in nodes]},
                    lambda v: choose(v, True), lambda v: choose(v, False))
    elif source.get('type') == 'object' or 'properties' in source:
        properties = source.get('properties', {})
        additional = source.get('additionalProperties', not bool(properties))
        if additional is not False:
            if properties:
                raise WireError('Mixed fixed/open objects require an explicit adapter')
            child = compile_node(additional if isinstance(additional, dict) else {})
            def encode_map(value):
                return {'entries': map_value(value, True, child.encode)}
            def decode_map(value):
                exact(value, ['entries'])
                return map_value(value['entries'], False, child.decode)
            node = Node(obj({'entries': entries_schema(child.schema)},
                description='Open dictionary encoded as unique key/value entries.'), encode_map, decode_map)
        else:
            children = {k: compile_node(s) for k, s in properties.items()}
            required = set(source.get('required', []))
            schema = {}
            for key, child in children.items():
                schema[key] = child.schema if key in required else {'anyOf': [tagged('absent'),
                    tagged('present', value=child.schema)],
                    'description': 'Optional field: absent preserves the existing default; present supplies value, including null if allowed.'}
            def encode_object(value):
                if type(value) is not dict or set(value) - set(children) or required - set(value):
                    raise WireError('Object fields do not match the business schema')
                return {k: c.encode(value[k]) if k in required else
                    ({'kind': 'present', 'value': c.encode(value[k])} if k in value else {'kind': 'absent'})
                    for k, c in children.items()}
            def decode_object(value):
                exact(value, children)
                result = {}
                for k, c in children.items():
                    v = value[k]
                    if k in required:
                        result[k] = c.decode(v)
                    elif type(v) is dict and v.get('kind') == 'absent':
                        exact(v, ['kind'])
                    else:
                        exact(v, ['kind', 'value'])
                        if v['kind'] != 'present':
                            raise WireError('Optional field must be absent or present')
                        result[k] = c.decode(v['value'])
                return result
            node = Node(obj(schema), encode_object, decode_object)
    elif source.get('type') == 'array':
        child = compile_node(source.get('items', {}))
        def array(value, encode):
            if type(value) is not list:
                raise WireError('Expected array')
            return [(child.encode if encode else child.decode)(v) for v in value]
        node = Node({'type': 'array', 'items': child.schema}, lambda v: array(v, True), lambda v: array(v, False))
    elif 'type' not in source and not any(k in source for k in ('enum', 'const')):
        node = Node({'$ref': JSON_REF}, lambda v: json_value(v, True), lambda v: json_value(v, False))
    else:
        schema = {k: v for k, v in source.items() if k in {'type', 'enum', 'pattern', 'format', 'minimum',
            'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf'}}
        if 'const' in source:
            schema['enum'] = [source['const']]
        def primitive(value):
            types = {'string': (str,), 'number': (int, float), 'integer': (int,), 'boolean': (bool,), 'null': (type(None),)}
            if source.get('type') not in types or type(value) not in types[source['type']]:
                raise WireError('Primitive type does not match schema')
            if 'enum' in schema and value not in schema['enum']:
                raise WireError('Value not in enum')
            return value
        node = Node(schema, primitive, primitive)
    if description:
        node.schema['description'] = description
    return node


class StrictCodec:
    def __init__(self, function):
        self.node = compile_node(function['parameters'])
        self.function = deepcopy(function)
        self.function['strict'] = True
        self.function['parameters'] = deepcopy(self.node.schema)
        if JSON_REF in str(self.node.schema):
            self.function['parameters']['$defs'] = {'StrictJsonValue': deepcopy(JSON_SCHEMA)}

    def encode(self, arguments):
        return self.node.encode(arguments)

    def decode(self, arguments):
        return self.node.decode(arguments)
