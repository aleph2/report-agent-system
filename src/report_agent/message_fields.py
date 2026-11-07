"""Internal dictionary and diagnostics derived from the same business field model."""
from copy import deepcopy
from pydantic import ValidationError

from .errors import ActionRejected


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
    try:
        return model.model_validate(value)
    except ValidationError as error:
        dictionary = field_dictionary(model)
        issues = []
        for item in error.errors(include_input=False, include_context=False, include_url=False):
            issue = {'field': list(item['loc']), 'reason': item['type'],
                     'definition': dictionary.get(item['loc'][0]) if item['loc'] else None}
            if not item['loc']:
                for code, (related, explanation) in getattr(model, 'diagnostic_errors', {}).items():
                    if item['type'] == 'value_error' and item['msg'] == 'Value error, ' + code:
                        issue.update(reason=code, related_fields=related, message=explanation)
                        break
            if model.__name__.removesuffix('Invocation') in {'WriterGap','WriterEvidence','WriterAssumption'} or getattr(model,'writer_outcome_contract',False):
                field = '.'.join(str(part) for part in item['loc'])
                if item['type']=='extra_forbidden':
                    correction = f'Remove {field}; this save tool does not accept it.'
                elif item['type']=='missing':
                    correction = f'Provide {field}. ' + (issue['definition'] or {}).get('description','')
                else:
                    correction = item['msg'] + ' ' + (issue['definition'] or {}).get('description','')
                if item['type']=='adopted_grade_not_plausible':
                    issue['field']=['plausible_grades']
                issue['correction'] = correction.strip()
            issues.append(issue)
        fields = ', '.join(item['reason'] if 'related_fields' in item else str(item['field']) for item in issues)
        raise ActionRejected('MESSAGE_FIELDS_INVALID: ' + fields, diagnostic={'fields': issues}) from None
