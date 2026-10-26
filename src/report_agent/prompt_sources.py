"""Packaged instructions and diagnostic versions; no model or permission policy.

Names are internal call-site constants. Task text never selects a file. Legacy
files retain their exact string values so existing paid request identities stay
historical, rather than being silently reinterpreted by a new default.
"""
from pathlib import Path
import hashlib
from importlib.metadata import PackageNotFoundError, version
import io
import re

RULES = Path(__file__).with_name('rules')
NATIVE_REVIEW = 'native-reviewer-v2'
BOUNDED_REVIEW = 'bounded-tool-v1'
FULL_ROLE_DESCRIPTION = 'full-role-description-v1'
SEPARATE_DESCRIPTION = 'separate-description-v1'
REVIEW_INTERFACE_V1 = 'review-interfaces-v1'
REVIEW_INTERFACE_V2 = 'review-interfaces-v2'
REVIEW_INTERFACE_V3 = 'review-interfaces-v3'
REVIEW_INTERFACE_V4 = 'review-interfaces-v4'
CONTENT_INPUT_V1 = 'content-inputs-v1'
RELATION_ENDPOINTS_V2 = 'relation-endpoints-v2'
REPORT_EXPRESSION_V1 = 'report-expression-v1'
READER_EXPRESSION_V2 = 'reader-expression-v2'
LEGACY_PROMPTS = 'legacy-v1'
CONCISE_PROMPTS = 'concise-v1'


def validate_review_submission_contract(manifest):
    from .review_scope_selectors import validate_contract
    return validate_contract(manifest)


def validate_review_plan_contract(manifest):
    from .errors import ActionRejected
    if 'review_plan_contract' not in manifest:
        return None
    if manifest['review_plan_contract'] != 'work-units-v1':
        raise ActionRejected('UNKNOWN_REVIEW_PLAN_CONTRACT')
    if (manifest.get('review_interface_profile') != REVIEW_INTERFACE_V4
            or manifest.get('review_execution_mode') != NATIVE_REVIEW
            or manifest.get('context_policy') != 'stateful-tools-v2'
            or manifest.get('context_projection') != 'review-materials-v1'):
        raise ActionRejected('REVIEW_PLAN_REQUIRES_NATIVE_COMPLETE_MATERIALS')
    return manifest['review_plan_contract']


def validate_report_prompt_profile(manifest):
    from .errors import ActionRejected
    value = manifest.get('report_prompt_profile', LEGACY_PROMPTS)
    if not isinstance(value, str) or value not in {LEGACY_PROMPTS, CONCISE_PROMPTS}:
        raise ActionRejected('UNKNOWN_REPORT_PROMPT_PROFILE')
    if value == CONCISE_PROMPTS and (manifest.get('review_interface_profile') != REVIEW_INTERFACE_V4
            or manifest.get('report_expression_profile') != READER_EXPRESSION_V2):
        raise ActionRejected('CONCISE_PROMPTS_REQUIRE_V4_READER_EXPRESSION')
    return value


def report_prompt_profile(store):
    from .handoff_release import manifest
    return validate_report_prompt_profile(manifest(store))


def report_rule_source(name, prompt_profile=LEGACY_PROMPTS):
    return name + '-concise' if prompt_profile == CONCISE_PROMPTS else name


def submit_review_source(prompt_profile=LEGACY_PROMPTS, review_submission_contract=None):
    from .review_scope_selectors import CONTRACT
    if review_submission_contract not in (None, CONTRACT):
        from .errors import ActionRejected
        raise ActionRejected('UNKNOWN_REVIEW_SUBMISSION_CONTRACT')
    return report_rule_source('native-submit-review-selectors' if review_submission_contract
                              else 'native-submit-review-v4', prompt_profile)


def validate_report_expression_profile(manifest):
    from .errors import ActionRejected
    value = manifest.get('report_expression_profile', REPORT_EXPRESSION_V1)
    if not isinstance(value, str) or value not in {REPORT_EXPRESSION_V1, READER_EXPRESSION_V2}:
        raise ActionRejected('UNKNOWN_REPORT_EXPRESSION_PROFILE')
    return value


def report_expression_profile(store):
    from langgraph.config import get_config
    try:
        metadata = get_config().get('metadata', {})
    except RuntimeError:
        metadata = {}
    if 'report_expression_profile' in metadata:
        return validate_report_expression_profile({'report_expression_profile': metadata['report_expression_profile']})
    return validate_report_expression_profile(store.manifest)


def expression_source(name, profile=REPORT_EXPRESSION_V1):
    if profile == READER_EXPRESSION_V2 and name in {'content-writer', 'text-work', 'qualifier-work'}:
        return name + '-v2'
    return name


def validate_content_input_profile(manifest):
    from .errors import ActionRejected
    value = manifest.get('content_input_profile', CONTENT_INPUT_V1)
    if not isinstance(value, str) or value not in {CONTENT_INPUT_V1, RELATION_ENDPOINTS_V2}:
        raise ActionRejected('UNKNOWN_CONTENT_INPUT_PROFILE')
    return value


def content_input_profile(store):
    from langgraph.config import get_config
    try:
        metadata = get_config().get('metadata', {})
    except RuntimeError:
        metadata = {}
    if 'report_content_input_profile' in metadata:
        return validate_content_input_profile({'content_input_profile': metadata['report_content_input_profile']})
    return validate_content_input_profile(store.manifest)


def load_prompt(name):
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', name):
        raise ValueError('INVALID_INTERNAL_PROMPT_NAME')
    return (RULES / (name + '.md')).read_text(encoding='utf-8')


def source_manifest(store, sources, offered):
    """Snapshot declared files in the existing Store, never render instructions.

    Versions identify the observed source bytes. A literal/template observation
    is only a composition link, not proof of authority or semantic correctness.
    Missing or stale files stay explicit gaps; callers keep their actual input.
    The caller runs this diagnostic within its existing failsoft capture.
    """
    from .store import digest
    names, unresolved = [], []
    for source in sources:
        if isinstance(source, str):
            names.append(source)
        elif isinstance(source, dict):
            names.extend(source.get('files', []))
            if source.get('source', '').startswith('unexplained'):
                unresolved.append(source['source'])
    def strings(value, path):
        if isinstance(value, str):
            yield path, value
        elif isinstance(value, list):
            for index, part in enumerate(value):
                yield from strings(part, path + '/' + str(index))
        elif isinstance(value, dict) and value.get('type') == 'text':
            yield from strings(value.get('text'), path + '/text')
    def parameter_descriptions(schema, path):
        if not isinstance(schema, dict):
            return
        if isinstance(schema.get('description'), str):
            yield path + '/description', schema['description']
        # Only schema positions are instructions; defaults and examples are data.
        for key in ('properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'):
            for name, child in schema.get(key, {}).items():
                yield from parameter_descriptions(child, path + '/' + key + '/' + name)
        for key in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
            for index, child in enumerate(schema.get(key, [])):
                yield from parameter_descriptions(child, path + '/' + key + '/' + str(index))
        for key in ('items', 'additionalProperties', 'not', 'contains', 'propertyNames',
                    'if', 'then', 'else', 'unevaluatedProperties', 'unevaluatedItems'):
            yield from parameter_descriptions(schema.get(key), path + '/' + key)
    # Inspect the already offered public input; never reassemble or alter it.
    locations = []
    if isinstance(offered, dict):
        for index, message in enumerate(offered.get('messages', [])):
            role = message.get('role', message.get('type', 'unknown'))
            for path, text in strings(message.get('content'), 'messages/' + str(index) + '/content'):
                locations.append((path, role, text))
        for index, tool in enumerate(offered.get('tools', [])):
            function = tool.get('function', {})
            locations.append(('tools/' + str(index) + '/function/description', 'tool_definition',
                              function.get('description', '')))
            locations.extend((path, 'tool_definition', text) for path, text in parameter_descriptions(
                function.get('parameters'), 'tools/' + str(index) + '/function/parameters'))
        for source in sources:
            if isinstance(source, dict) and source.get('source') == 'analysis_output_schema':
                import json
                index = source['message_index']
                packet = json.loads(offered['messages'][index]['content'])
                locations.extend((path, 'output_schema', text) for path, text in parameter_descriptions(
                    packet['output_schema'], 'messages/' + str(index) + '/content/output_schema'))
    files = []
    for name in dict.fromkeys(names):
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', name):
            unresolved.append(str(name))
            continue
        path = RULES / (name + '.md')
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            unresolved.append(name)
            continue
        text = io.StringIO(raw.decode('utf-8'), newline=None).read()
        file_sha = hashlib.sha256(raw).hexdigest()
        key = 'prompt_source:' + name + ':' + file_sha
        snapshot = {'name': name, 'path': 'rules/' + name + '.md', 'text': text,
            'file_sha256': file_sha, 'text_sha256': hashlib.sha256(text.encode()).hexdigest()}
        if store is not None and store.get(key) is None:
            store.set(key, snapshot)
        matches, match = [], 'not_observed'
        for location, role, value in locations:
            observed = ('literal' if text and text in value else
                        'trimmed_literal' if text.strip() and text.strip() in value else None)
            # Only the known summary envelope is formatted into a Human message.
            if observed is None and name in {'working-summary', 'working-summary-concise'} and text.count('{messages}') == 1:
                prefix, suffix = text.split('{messages}')
                if value.startswith(prefix) and value.endswith(suffix):
                    observed = 'summary_template_envelope'
            if observed:
                matches.append({'path':location, 'role':role, 'match':observed})
                if role in {'system', 'tool_definition', 'output_schema'} or (name in {'working-summary', 'working-summary-concise'} and observed == 'summary_template_envelope'):
                    match = observed
        if match == 'not_observed':
            unresolved.append(name)
        files.append({k: v for k, v in snapshot.items() if k != 'text'} |
                     {'snapshot_key': key if store is not None else None, 'offered_match': match,
                      'matched_locations':matches})
    frameworks = {}
    for package in ('deepagents', 'langchain', 'langchain-core', 'langchain-openai', 'langgraph', 'openai'):
        try:
            frameworks[package] = version(package)
        except PackageNotFoundError:
            frameworks[package] = 'unavailable'
    return {'files': files, 'framework_versions': frameworks,
        'unresolved_sources': list(dict.fromkeys(unresolved)),
        'offered_tool_schema_sha256': digest(offered['tools']) if isinstance(offered, dict) and 'tools' in offered else None,
        'semantic_guarantee': 'none'}


def record_runtime_version(store):
    """Once per native graph construction, not once per model request.

    A disk-source identity is not proof of every loaded instruction. Runtime
    sources must remain frozen during execution; unbound direct calls stay gaps.
    No source file, permission or business state is changed by this diagnostic.
    """
    from .store import digest
    from .transport_observation import observe_safely
    captured = {}
    def record():
        root = Path(__file__).resolve().parent
        paths = [*root.rglob('*.py'), *root.joinpath('rules').glob('*.md')]
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(paths)}
        project = root.parents[1] / 'pyproject.toml'
        value = {'import_root':root.as_posix(), 'source_files':files,
            'project_file_sha256':hashlib.sha256(project.read_bytes()).hexdigest() if project.exists() else None,
            'limitation':'Disk sources observed at graph construction; keep sources frozen. Not proof of every loaded module or semantic behavior.'}
        key = 'prompt_runtime_version:' + digest(value)
        if store.get(key) is None:
            store.set(key, value)
        captured['ref'] = key
        store.event('prompt_runtime_bound', {'runtime_version_ref':key})
    observe_safely(record)
    return captured.get('ref')


def review_profile(store):
    # Absent mode belongs to older projects. Never migrate a saved case on read.
    from .handoff_release import manifest
    value = manifest(store).get('review_execution_mode', BOUNDED_REVIEW)
    if value not in {NATIVE_REVIEW, BOUNDED_REVIEW}:
        from .errors import ActionRejected
        raise ActionRejected('UNKNOWN_REVIEW_EXECUTION_PROFILE')
    return value


def native_reviewer(store):
    return review_profile(store) == NATIVE_REVIEW


def separate_description_supported(manifest):
    return (manifest.get('content_contract') == 'hierarchical-review-v1'
        and manifest.get('review_execution_mode') == NATIVE_REVIEW
        and manifest.get('review_entrypoint') == 'delegated-reviewer-v1')


def validate_delegation_profile(manifest):
    """Thin host configuration selection, not a new review protocol or migration."""
    from .errors import ActionRejected
    value = manifest.get('delegation_prompt_profile', FULL_ROLE_DESCRIPTION)
    if not isinstance(value, str) or value not in {FULL_ROLE_DESCRIPTION, SEPARATE_DESCRIPTION}:
        raise ActionRejected('UNKNOWN_DELEGATION_PROMPT_PROFILE')
    if value == SEPARATE_DESCRIPTION and not separate_description_supported(manifest):
        raise ActionRejected('DELEGATION_PROMPT_PROFILE_REQUIRES_NATIVE_HIERARCHICAL')
    return value


def delegation_profile(store):
    from .handoff_release import manifest
    return validate_delegation_profile(manifest(store))


def validate_review_interface_profile(manifest):
    from .errors import ActionRejected
    value = manifest.get('review_interface_profile', REVIEW_INTERFACE_V1)
    if not isinstance(value, str) or value not in {REVIEW_INTERFACE_V1, REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3, REVIEW_INTERFACE_V4}:
        raise ActionRejected('UNKNOWN_REVIEW_INTERFACE_PROFILE')
    if value in {REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3} and not separate_description_supported(manifest):
        raise ActionRejected('REVIEW_INTERFACE_PROFILE_REQUIRES_NATIVE_HIERARCHICAL')
    if value == REVIEW_INTERFACE_V4 and (not separate_description_supported(manifest)
            or manifest.get('delegation_prompt_profile') != SEPARATE_DESCRIPTION
            or manifest.get('operation_identity_profile') != 'native-tool-runtime-v1'):
        raise ActionRejected('REVIEW_INTERFACE_V4_REQUIRES_NATIVE_RELEASE')
    return value


def review_interface_profile(store):
    """Use the built graph's fixed release; direct fixtures use explicit Store config."""
    from .handoff_release import manifest
    bound = manifest(store)
    from langgraph.config import get_config
    try:
        metadata = get_config().get('metadata', {})
    except RuntimeError:
        metadata = {}
    if 'report_review_interface_profile' in metadata:
        value = metadata['report_review_interface_profile']
        if value not in {REVIEW_INTERFACE_V1, REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3, REVIEW_INTERFACE_V4}:
            from .errors import ActionRejected
            raise ActionRejected('UNKNOWN_REVIEW_INTERFACE_PROFILE')
        return value
    return validate_review_interface_profile(bound)


def review_handoff_source(interface_profile, prompt_profile=LEGACY_PROMPTS):
    if interface_profile == REVIEW_INTERFACE_V4:
        return report_rule_source('native-review-handoff-v4', prompt_profile)
    return 'native-review-handoff-v2' if interface_profile in {REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3} else 'native-review-handoff'


def role_sources(role, expression_profile, interface_profile, prompt_profile=LEGACY_PROMPTS,
                 review_submission_contract=None):
    source = expression_source('content-'+role, expression_profile)
    current = validate_report_prompt_profile({'report_prompt_profile':prompt_profile,
        'review_interface_profile':interface_profile, 'report_expression_profile':expression_profile}) == CONCISE_PROMPTS
    if interface_profile == REVIEW_INTERFACE_V4 and role == 'coordinator':
        source = report_rule_source('content-coordinator-v4', prompt_profile)
    elif current:
        source = 'content-' + role + '-v4'
    if review_submission_contract is not None:
        from .review_scope_selectors import CONTRACT
        if review_submission_contract != CONTRACT:
            from .errors import ActionRejected
            raise ActionRejected('UNKNOWN_REVIEW_SUBMISSION_CONTRACT')
        if interface_profile != REVIEW_INTERFACE_V4:
            from .errors import ActionRejected
            raise ActionRejected('REVIEW_SUBMISSION_SELECTORS_REQUIRE_NATIVE_V4')
        if role == 'reviewer':
            source = 'content-reviewer-v4'
    sources = ['content-common-v4' if current else 'content-common', source]
    if interface_profile == REVIEW_INTERFACE_V4 and role in {'writer','reviewer'}:
        sources.append(report_rule_source('deliverable-declaration-v4' if role == 'writer' else 'review-basis-v4', prompt_profile))
    return sources


def context_source(role, interface_profile, prompt_profile=LEGACY_PROMPTS):
    if role == 'reviewer':
        return 'agent-context-reviewer'
    return 'agent-context-general-v4' if prompt_profile == CONCISE_PROMPTS else 'agent-context-general'


def describe_content_schema(schema):
    """Project current prose onto schema positions, never defaults or example data."""
    from copy import deepcopy
    result, sources = deepcopy(schema), []

    def visit(node):
        if not isinstance(node, dict):
            return
        properties = node.get('properties', {})
        if isinstance(properties, dict) and {'kind', 'body', 'claim_kind', 'qualifiers'} <= properties.keys():
            for field in ('body', 'qualifiers'):
                source = 'content-' + field + '-description'
                properties[field]['description'] = load_prompt(source).strip()
                if source not in sources:
                    sources.append(source)
        for key in ('properties', '$defs', 'definitions', 'patternProperties'):
            children = node.get(key)
            if isinstance(children, dict):
                for child in children.values():
                    visit(child)
        for key in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
            for child in node.get(key, []):
                visit(child)
        for key in ('items', 'additionalProperties', 'if', 'then', 'else', 'not'):
            visit(node.get(key))

    visit(result)
    return result, sources


def describe_current_tools(tools):
    """Keep native handlers/contracts intact; only current model-facing prose changes."""
    from copy import deepcopy
    result, sources = deepcopy(tools), []
    for tool in result:
        function = tool.get('function', {})
        name = function.get('name')
        if name in {'read_decision_state', 'read_source_page', 'analyze_evidence',
                    'process_report_content', 'commit_objects'}:
            source = 'tool-' + name.replace('_', '-')
            function['description'] = load_prompt(source).strip()
            if name == 'commit_objects':
                function['description'] += '\n\n' + load_prompt('deliverable-save-tool-v4-concise')
            sources.append(source)
        if 'parameters' in function:
            function['parameters'], fields = describe_content_schema(function['parameters'])
            sources.extend(source for source in fields if source not in sources)
    return result, sources
