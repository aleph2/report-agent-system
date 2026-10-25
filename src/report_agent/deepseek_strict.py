"""Reversible DeepSeek strict wire format; business contracts stay unchanged.

Optional fields use an explicit absent/present envelope. Open maps use entries,
and arbitrary JSON containers use tagged recursion. No semantic repair occurs.
"""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable
import json

from jsonschema import Draft202012Validator, ValidationError as SchemaValidationError
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT202012

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
    if type(value) is not dict:
        raise WireError('Expected object, received ' + type(value).__name__)
    if set(value) != set(keys):
        raise WireError('Object fields differ: missing=' + str(sorted(set(keys) - set(value)))
                        + ', unexpected=' + str(sorted(set(value) - set(keys))))


def at(path, convert, value):
    try:
        return convert(value)
    except WireError as exc:
        raise WireError(path + ': ' + str(exc)) from exc


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


SUPPORTED = {'type', 'properties', 'required', 'additionalProperties', 'items', 'anyOf', 'oneOf',
             'description', 'enum', 'const', 'pattern', 'format', 'minimum', 'maximum',
             'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf', 'title', 'default',
             'minLength', 'maxLength', 'minItems', 'maxItems', 'discriminator',
             'allOf', 'if', 'then', 'else', '$defs', '$ref'}


def schema_grammar(source):
    """Fail closed even inside an adapted subtree; never fetch schema documents."""
    if type(source) is not dict:
        raise WireError('Unsupported non-object source schema')
    if set(source) - SUPPORTED:
        raise WireError('Unsupported source schema keywords: ' + ','.join(sorted(set(source) - SUPPORTED)))
    if '$ref' in source and (not isinstance(source['$ref'], str) or not source['$ref'].startswith('#')):
        raise WireError('External schema references are not supported')
    for key in ('properties', '$defs'):
        for child in source.get(key, {}).values():
            schema_grammar(child)
    for key in ('anyOf', 'oneOf', 'allOf'):
        for child in source.get(key, []):
            schema_grammar(child)
    for key in ('items', 'if', 'then', 'else'):
        if key in source:
            schema_grammar(source[key])
    if isinstance(source.get('additionalProperties'), dict):
        schema_grammar(source['additionalProperties'])


def deny_schema_retrieval(uri):
    raise NoSuchResource(ref=uri)


def validate_original(validator, value):
    try:
        validator.validate(value)
    except SchemaValidationError as exc:
        path = '/'.join(str(part) for part in exc.absolute_path) or '$'
        raise WireError('Business schema at ' + path + ': ' + exc.message) from exc
    except Unresolvable as exc:
        raise WireError('Unresolvable local schema reference') from exc
    return value


def compile_node(source, validator=None, resolver=None, references=()):
    source = deepcopy(source)
    if validator is None:
        schema_grammar(source)
        Draft202012Validator.check_schema(source)
        registry = Registry(retrieve=deny_schema_retrieval)
        validator = Draft202012Validator(source, registry=registry)
        resolver = registry.resolver_with_root(Resource.from_contents(source, default_specification=DRAFT202012))
    if '$ref' in source:
        reference = source['$ref']
        if reference in references:
            raise WireError('Recursive business references require an explicit adapter')
        if set(source) - {'$ref', '$defs', 'title', 'description', 'default'}:
            raise WireError('Schema reference siblings require an explicit adapter')
        try:
            resolved = resolver.lookup(reference)
        except Unresolvable as exc:
            raise WireError('Unresolvable local schema reference') from exc
        node = compile_node(resolved.contents, validator, resolved.resolver, (*references, reference))
        if source.get('description'):
            node.schema['description'] = source['description'] + '\n' + node.schema.get('description', '')
        return node
    description = source.get('description')
    local = validator.evolve(schema=source)
    is_object = source.get('type') == 'object' or 'properties' in source
    conditional = any(key in source for key in ('allOf', 'if', 'then', 'else'))
    mixed_open = bool(source.get('properties')) and source.get('additionalProperties', False) is not False
    if is_object and (conditional or mixed_open):
        # Reuse the existing reversible representation. The provider enforces
        # this wire shape; the original schema remains authoritative locally.
        def encode_adapted(value):
            return json_value(validate_original(local, value), True)
        def decode_adapted(value):
            return validate_original(local, json_value(value, False))
        wire_description = ('Tagged JSON representation of this object. Original business schema '
            '(validated locally, including conditional and open fields): ' + json.dumps(source, ensure_ascii=False))
        return Node({'$ref': JSON_REF, 'description': wire_description}, encode_adapted, decode_adapted)
    if conditional:
        raise WireError('Conditional non-object schemas require an explicit adapter')
    def child(schema):
        return compile_node(schema, validator, resolver, references)
    choices = source.get('anyOf', source.get('oneOf'))
    if choices is not None:
        nodes = [child(s) for s in choices]
        validators = [validator.evolve(schema=s) for s in choices]
        def choose(value, encode):
            # An explicit literal discriminator selects diagnostic scope, not a
            # repaired business value. Without one, retain all branch errors.
            selected = [n for n in nodes if type(value) is dict and any(
                k in value and value[k] in p.get('enum', [])
                for k, p in n.schema.get('properties', {}).items())]
            errors = []
            for node, branch in zip(nodes, validators):
                try:
                    if encode:
                        validate_original(branch, value)
                        return node.encode(value)
                    return validate_original(branch, node.decode(value))
                except WireError as exc:
                    errors.append((node, str(exc)))
            raise WireError('No union branch matches: ' + ' | '.join(
                e for n, e in errors if not selected or any(n is s for s in selected)))
        node = Node({'anyOf': [n.schema for n in nodes]},
                    lambda v: choose(v, True), lambda v: choose(v, False))
    elif source.get('type') == 'object' or 'properties' in source:
        properties = source.get('properties', {})
        additional = source.get('additionalProperties', not bool(properties))
        if additional is not False:
            if properties:
                raise WireError('Mixed fixed/open objects require an explicit adapter')
            map_child = child(additional if isinstance(additional, dict) else {})
            def encode_map(value):
                return {'entries': map_value(value, True, map_child.encode)}
            def decode_map(value):
                exact(value, ['entries'])
                return map_value(value['entries'], False, map_child.decode)
            node = Node(obj({'entries': entries_schema(map_child.schema)},
                description='Open dictionary encoded as unique key/value entries.'), encode_map, decode_map)
        else:
            children = {k: child(s) for k, s in properties.items()}
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
                        result[k] = at(k, c.decode, v)
                    elif type(v) is dict and v.get('kind') == 'absent':
                        exact(v, ['kind'])
                    else:
                        at(k + ' (optional wire field)', lambda x: exact(x, ['kind', 'value']), v)
                        if v['kind'] != 'present':
                            raise WireError('Optional field must be absent or present')
                        result[k] = at(k, c.decode, v['value'])
                return result
            node = Node(obj(schema), encode_object, decode_object)
    elif source.get('type') == 'array':
        array_child = child(source.get('items', {}))
        def array(value, encode):
            if type(value) is not list:
                raise WireError('Expected array')
            return [at('[' + str(i) + ']', array_child.encode if encode else array_child.decode, v)
                    for i, v in enumerate(value)]
        node = Node({'type': 'array', 'items': array_child.schema}, lambda v: array(v, True), lambda v: array(v, False))
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
        self.original = deepcopy(function['parameters'])
        schema_grammar(self.original)
        Draft202012Validator.check_schema(self.original)
        registry = Registry(retrieve=deny_schema_retrieval)
        self.validator = Draft202012Validator(self.original, registry=registry)
        resolver = registry.resolver_with_root(Resource.from_contents(self.original, default_specification=DRAFT202012))
        self.node = compile_node(self.original, self.validator, resolver)
        self.function = deepcopy(function)
        self.function['strict'] = True
        self.function['parameters'] = deepcopy(self.node.schema)
        if JSON_REF in str(self.node.schema):
            self.function['parameters']['$defs'] = {'StrictJsonValue': deepcopy(JSON_SCHEMA)}

    def encode(self, arguments):
        validate_original(self.validator, arguments)
        return self.node.encode(arguments)

    def decode(self, arguments):
        return validate_original(self.validator, self.node.decode(arguments))
