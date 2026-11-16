"""Internal dictionary and diagnostics derived from the same business field model."""
from copy import deepcopy

def field_dictionary(model):
    schema = model.model_json_schema()
    result = {}
    for key, prop in schema['properties'].items():
        result[key] = {'description': prop.get('description', ''),
            'required': key in schema.get('required', []), 'schema': deepcopy(prop),
            'nullable': prop.get('type') == 'null' or any(
                option.get('type') == 'null' for option in prop.get('anyOf', []))}
        if 'default' in prop:
            result[key]['default'] = deepcopy(prop['default'])
    return result


def validate_message(model, value):
    return model.model_validate(value)
