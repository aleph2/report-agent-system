"""Source-derived, host-owned plan structure; coordinator answers bounded ambiguities."""
from . import plan_inputs
from . import legacy_state as legacy
from . import plan_authority
from copy import deepcopy
import re
from .store import digest, encode
from .commission_plan import SectionPlan
from .errors import ActionRejected, ActionForbidden

PROTECTED = ('section_id', 'title', 'kind', 'outline', 'derived_from', 'rule', 'result_bindings', 'result_composition', 'replacements', 'source_views')
FIXED = ('sources', 'text', 'extraction')


def fail(section, field, item, reason):
    raise ActionRejected('SKELETON_' + reason + ': ' + section + '/' + field + '/' + item,
        diagnostic={'fields': [{'section_id': section, 'field': field, 'item_id': item, 'reason': reason}]})


def requirement_digest(record):
    return digest({k: record['payload'].get(k, {}) for k in ('anchors', 'classifications')})


def _current(cs, db):
    value = plan_inputs.get_skeleton(db)
    if not value:
        return None
    if digest({k: v for k, v in value.items() if k != 'digest'}) != value['digest']:
        fail('plan', 'skeleton_digest', 'registry', 'REGISTRY_CHANGED')
    if value['requirements_ref'] != legacy.get_commission_requirements(db):
        fail('plan', 'requirements_ref', 'registry', 'REQUIREMENTS_CHANGED')
    if value['profiles'] != plan_inputs.get_text_profiles(db, {}):
        fail('plan', 'profiles', 'registry', 'PROFILES_CHANGED')
    for pin in value['source_pins']:
        if cs._read(db, pin['ref'])['payload']['file_digest'] != pin['file_digest']:
            fail('plan', 'source_pins', pin['ref']['id'], 'SOURCE_CHANGED')
    return value


def _heading(line):
    match = re.match(r'^(\d+(?:\.\d+)*)(?:[、.]?\s*)([^\d.\s].*)$', line.strip())
    if not match or re.search(r'[.．…·]{2,}', match[2]) or re.match(r'^(?:[A-Z]{0,3}K)?\d+\+', match[2]) or re.fullmatch(r'[ⅠⅡⅢⅣIVX√\s]+', match[2]):
        return None
    return match[1], re.sub(r'\s+', '', match[2])


def template_choices(cs, section, profiles, heading_titles=None):
    from .commission_planning import normalize_text, resolve_source_span
    from .document_tools import physical_page_number
    choices = []
    for profile in profiles.values():
        source = cs.read(profile['source_ref'])['payload']
        with cs.store.connect() as db:
            rows = list(db.execute('SELECT locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal', (source['source_id'],)))
        pages = {}
        for loc, text in rows:
            number = physical_page_number(loc)
            if number is not None:
                pages.setdefault(number, []).append(text)
        lines = [(page, line) for page in sorted(pages) for line in normalize_text('\n'.join(pages[page]), page, profile).splitlines() if line.strip()]
        headings = [(i, _heading(line)) for i, (_, line) in enumerate(lines) if _heading(line)]
        title = re.sub(r'\s+', '', section['title'])
        matches = [(i, h) for i, h in headings if h[0] == section['section_id'] and h[1].endswith(title)]
        for first, heading in matches:
            end = next((i for i, h in headings if i > first and len(h[0].split('.')) <= len(heading[0].split('.'))), len(lines))
            if end <= first + 1:
                continue
            selection = {'source_ref': profile['source_ref'], 'profile_id': profile['id'],
                'start_page': lines[first][0], 'end_page': lines[end-1][0],
                'start_sentence': lines[first][1], 'end_sentence': lines[end-1][1]}
            try:
                resolved = resolve_source_span(cs, selection)
            except ActionRejected:
                continue
            fields = {'sources': resolved['sources'], 'text': resolved['text'], 'extraction': {'selection': selection, **resolved}}
            choices.append({'id': digest(selection), 'selection': selection, 'fields': fields})
    return choices


def _pilot_spec(cs, record):
    from importlib.resources import files
    import json
    profile = json.loads(files('report_agent').joinpath('methods/pilot_planning.json').read_text())
    for anchor in record['payload']['anchors']:
        sha = cs.read(anchor['source']['source_ref'])['payload']['file_digest']
        if not any(row['source_hash'] == sha and row['locator'] == anchor['source']['locator'] and
                   row['quote_hash'] == __import__('hashlib').sha256(anchor['source']['quote'].encode()).hexdigest()
                   for row in profile['classifications']):
            fail(anchor.get('section_id', 'plan'), 'profile', anchor['id'], 'REVIEWED_PROFILE_REQUIRED')
    return {**deepcopy(profile['skeleton']), 'requirements_digest': requirement_digest(record)}


def bind_composition(section, rules):
    if not rules:
        return
    lines = section['text'].splitlines(keepends=True)
    offsets, cursor = [], 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    positions = []
    for rule in rules:
        matches = [offsets[i] for i, line in enumerate(lines) if (_heading(line) or ('',))[0] == rule['section_id']]
        if len(matches) != 1:
            fail(section['section_id'], 'result_composition', rule['section_id'], 'COMPOSITION_HEADING_NOT_UNIQUE')
        positions.append(matches[0])
    if positions != sorted(set(positions)):
        fail(section['section_id'], 'result_composition', 'order', 'COMPOSITION_ORDER_INVALID')
    parts = []
    for i, rule in enumerate(rules):
        original = section['text'][positions[i]:positions[i+1] if i+1 < len(positions) else len(section['text'])].strip()
        parts.append({**rule, 'text': original if rule['kind'] == 'source' else ''})
    section.update(result_composition=parts, result_bindings=[])


def prepare_skeleton(cs, source_refs, spec=None):
    from .commission_requirements import read_requirements, _write_items
    from .commission_planning import classified_item, reviewed_entry
    from .content_store import Actor
    from .content_models import Ref
    record = read_requirements(cs)
    spec = _pilot_spec(cs, record) if spec is None else deepcopy(spec)
    if spec.get('requirements_digest') != requirement_digest(record):
        fail('plan', 'requirements_digest', 'spec', 'REVIEWED_SPEC_STALE')
    if not spec.get('inventory_attributes') or len(set(spec['inventory_attributes'])) != len(spec['inventory_attributes']):
        fail('plan', 'inventory_attributes', 'spec', 'REVIEWED_ATTRIBUTES_REQUIRED')
    allowed = {Ref.model_validate(r).key() for r in source_refs}
    if any(Ref.model_validate(a['source']['source_ref']).key() not in allowed for a in record['payload']['anchors']):
        fail('plan', 'source_refs', 'outline', 'SOURCE_NOT_ENROLLED')
    with cs.store.connect() as db:
        profiles = plan_inputs.get_text_profiles(db, {})
        if any(Ref.model_validate(p['source_ref']).key() not in allowed for p in profiles.values()):
            fail('plan', 'source_refs', 'template', 'SOURCE_NOT_ENROLLED')
        if plan_inputs.get_skeleton(db):
            current = _current(cs, db)
            if current['spec_digest'] != digest(spec):
                fail('plan', 'spec', 'registry', 'SPEC_IMMUTABLE')
            return deepcopy(current)
        if plan_authority.plan_ref(db) or plan_inputs.get_draft(db, {}).get('revision'):
            fail('plan', 'state', 'registry', 'FRESH_PREPARATION_REQUIRED')
        bundle = legacy.get_commission_owner_records(db, {}).get('bundle', {})
        classifications = record['payload'].get('classifications', {})
        items = []
        for anchor in record['payload']['anchors']:
            c = classifications.get(anchor['id'])
            if c is None or anchor.get('parse_error'):
                fail(anchor.get('section_id', 'plan'), 'classification', anchor['id'], 'REVIEW_REQUIRED')
            if len(c['entry_ids']) > 1:
                fail(anchor.get('section_id', 'plan'), 'entry_ids', anchor['id'], 'REVIEWED_ENTRY_AMBIGUOUS')
            item = {'anchor_id': anchor['id'], 'status': 'required', 'interpretation': anchor['source']['quote'], 'capabilities': [], 'table_roles': []}
            if c['entry_ids']:
                item['reviewed_entry_id'] = c['entry_ids'][0]
            items.append(classified_item(cs, db, record, item))
    anchors = record['payload']['anchors']
    if not set(spec.get('derived', {})) <= {a.get('section_id') for a in anchors if a['kind'] == 'section'}:
        fail('plan', 'derived', 'spec', 'UNKNOWN_SECTION')
    heading_titles = {a['section_id']: re.sub(r'\s+', '', re.sub(r'^\s*' + re.escape(a['section_id']) + r'[、.\s]*', '', a['source']['quote'])) for a in anchors if a['kind'] == 'section'}
    sections, questions = [], []
    for anchor in anchors:
        if anchor['kind'] != 'section':
            continue
        sid = anchor['section_id']
        instructions = [a for a in anchors if a.get('section_id') == sid and a['kind'] == 'instruction']
        caps = {cap for a in instructions for cap in classifications[a['id']]['capabilities']}
        kind = 'derived' if 'result_bindings' in caps else 'fixed' if 'fixed_text' in caps else 'extracted'
        title = re.sub(r'^\s*' + re.escape(sid) + r'[、.\s]*', '', anchor['source']['quote'])
        section = {'section_id': sid, 'title': title, 'kind': kind, 'outline': anchor['source'], 'sources': [],
                   'notes': [a['source']['quote'] for a in instructions] or ['章节结构；具体内容见所属子节。']}
        needs_template = kind == 'fixed'
        composition = []
        if kind == 'derived':
            binding = spec.get('derived', {}).get(sid)
            if not binding or sid in binding['derived_from'] or not set(binding['derived_from']) <= {a.get('section_id') for a in anchors if a['kind'] == 'section'}:
                fail(sid, 'derived_from', sid, 'DERIVED_REVIEW_REQUIRED')
            binding = deepcopy(binding)
            needs_template = binding.pop('template', False)
            composition = binding.pop('composition', [])
            section.update(binding)
            if not needs_template:
                section['sources'] = [a['source'] for a in instructions]
        if needs_template:
            choices = template_choices(cs, section, profiles, heading_titles)
            if len(choices) == 1:
                section.update(choices[0]['fields'])
                bind_composition(section, composition)
                for slot in section.get('result_bindings', []):
                    if section['text'].count(slot['old']) != 1:
                        fail(sid, 'result_bindings', slot['old'], 'RESULT_SLOT_NOT_UNIQUE')
            else:
                questions.append({'question_id': 'template:' + sid, 'section_id': sid, 'field': 'template_span',
                    'composition': composition, 'reason': '请选择本节在模板中的唯一正文位置。' if choices else '未找到唯一匹配标题；请核对模板标题位置，需有来源的结构复核。', 'choices': choices})
        # A partial fixed section stays visible as an unresolved question, never guessed text.
        if kind != 'fixed' or section['sources']:
            section = SectionPlan.model_validate(section).model_dump(mode='json')
        sections.append(section)
    documents = []
    rules = deepcopy(spec.get('documents', []))
    for a in anchors:
        text = a['source']['quote'].strip()
        if a['kind'] == 'instruction' and re.fullmatch(r'第[^\s]{1,12}册.+', text) and not any(text == r['name'] for r in rules):
            rules.append({'id': 'document-' + digest(text)[:16], 'name': text, 'mentions': [text]})
    titles = [cs.read(ref)['payload']['source_metadata'].get('title', '') for ref in source_refs]
    compact = lambda t: re.sub(r'\s+', '', t)
    for rule in rules:
        served = [a for a in anchors if a['kind'] == 'instruction' and any(m in a['source']['quote'] for m in rule.get('mentions', [rule['name']]))]
        if not served:
            fail('plan', 'documents', rule['id'], 'DOCUMENT_NOT_IN_OUTLINE')
        if any(compact(rule['name']) == compact(re.sub(r'\.(pdf|docx?|md)$', '', title, flags=re.I)) for title in titles):
            continue
        documents.append({'id': rule['id'], 'name': rule['name'], 'section_ids': list(dict.fromkeys(a['section_id'] for a in served)), 'outline_sources': [a['source'] for a in served]})
    for doc in bundle.get('documents', []):
        expected = next((d for d in documents if d['id'] == doc['id']), None)
        if expected is None or expected['name'] != doc['name'] or set(expected['section_ids']) != set(doc['section_ids']):
            fail('plan', 'documents', doc['id'], 'OWNER_DOCUMENT_IDENTITY_MISMATCH')
    with cs.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = read_requirements(cs, db=db)
        if current['ref'] != record['ref']:
            fail('plan', 'requirements_ref', 'prepare', 'REQUIREMENTS_CHANGED')
        # Existing classified-item writer owns requirement versions and reviewed entry checks.
        updated = deepcopy(current['payload']['items'])
        for item in items:
            updated = [item if i['anchor_id'] == item['anchor_id'] else i for i in updated]
            ref = _write_items(cs, db, Actor('host', 'host', 'skeleton-preparation'), current, updated, relink_anchor=item['anchor_id'])
            current = cs._read(db, ref)
        value = {'sections': sections, 'documents': documents, 'questions': questions, 'deliverables': spec['deliverables'],
            'requirements_ref': current['ref'], 'profiles': profiles, 'source_pins': [{'ref': r, 'file_digest': cs._read(db,r)['payload']['file_digest']} for r in source_refs],
            'spec_digest': digest(spec), 'inventory_attributes': spec['inventory_attributes'], 'heading_titles': heading_titles, 'version': 1}
        value['digest'] = digest(value)
        plan_inputs.save_skeleton(db, value)
    return value


def apply_skeleton(cs, db, plan):
    registry = _current(cs, db)
    if registry is None:
        return plan
    result = deepcopy(plan)
    changes = {s['section_id']: s for s in plan.get('sections', [])}
    sections = []
    for original in registry['sections']:
        current = changes.pop(original['section_id'], {})
        for field in (*PROTECTED, *(FIXED if original.get('extraction') else ())):
            if field in current and current[field] != original.get(field, [] if field in ('derived_from','result_bindings','result_composition','replacements','source_views') else ''):
                fail(original['section_id'], field, original['section_id'], 'STRUCTURE_CHANGED')
        sections.append({**deepcopy(original), **current})
    if changes:
        fail('plan', 'sections', next(iter(changes)), 'UNKNOWN_SECTION')
    if result.get('deliverables') and result['deliverables'] != registry['deliverables']:
        fail('plan', 'deliverables', 'details', 'STRUCTURE_CHANGED')
    result.update(sections=sections, deliverables=registry['deliverables'], inventory_attributes=registry['inventory_attributes'], skeleton_digest=registry['digest'])
    if plan.get('inventory_attributes') and plan['inventory_attributes'] != registry['inventory_attributes']:
        fail('plan', 'inventory_attributes', 'details', 'STRUCTURE_CHANGED')
    result['skeleton_questions'] = deepcopy(registry['questions'])
    return result


def validate_skeleton(cs, db, plan):
    registry = _current(cs, db)
    if not registry:
        if plan.get('skeleton_digest'):
            fail('plan', 'skeleton_digest', 'unbound', 'REGISTRY_REQUIRED')
        return
    if plan.get('skeleton_digest') != registry['digest']:
        fail('plan', 'skeleton_digest', 'registry', 'BINDING_CHANGED')
    if plan.get('inventory_attributes') != registry['inventory_attributes']:
        fail('plan', 'inventory_attributes', 'registry', 'STRUCTURE_CHANGED')
    if plan.get('skeleton_questions', []) != registry['questions']:
        fail('plan', 'skeleton_questions', 'registry', 'QUESTIONS_CHANGED')
    assembled = apply_skeleton(cs, db, plan)
    if [s['section_id'] for s in plan.get('sections', [])] != [s['section_id'] for s in assembled['sections']]:
        fail('plan', 'sections', 'order', 'STRUCTURE_CHANGED')
    from .commission_owner_records import _documents
    bundle = legacy.get_commission_owner_records(db, {}).get('bundle', {'records': [], 'documents': []})
    for actual, expected in zip(plan['sections'], registry['sections']):
        for field in (*PROTECTED, *(FIXED if expected.get('extraction') else ())):
            if actual.get(field) != expected.get(field):
                fail(expected['section_id'], field, expected['section_id'], 'STRUCTURE_CHANGED')
        if actual.get('missing_documents', []) != _documents(bundle, expected['section_id'], registry):
            fail(expected['section_id'], 'missing_documents', expected['section_id'], 'DOCUMENTS_CHANGED')
    if plan.get('deliverables') != registry['deliverables']:
        fail('plan', 'deliverables', 'details', 'STRUCTURE_CHANGED')


def resolve_skeleton_question(cs, actor, operation_id, question_id, expected_digest, choice_id, selection=None):
    if actor.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: planning belongs to coordinator')
    def save(db):
        value = deepcopy(_current(cs, db))
        if not value or value['digest'] != expected_digest:
            fail('plan', 'skeleton_digest', question_id, 'ANSWER_STALE')
        question = next((q for q in value['questions'] if q['question_id'] == question_id), None)
        choice = next((c for c in (question or {}).get('choices', []) if c['id'] == choice_id), None)
        if choice is None and question and not question['choices'] and selection is not None:
            from .commission_planning import SourceSpan
            selector = SourceSpan.model_validate(selection).model_dump(mode='json')
            heading = _heading(selector['start_sentence'])
            if heading and heading[0] == question['section_id']:
                titles = {**value['heading_titles'], heading[0]: heading[1]}
                offered = template_choices(cs, {'section_id': heading[0], 'title': heading[1]}, value['profiles'], titles)
                choice = next((c for c in offered if c['selection'] == selector), None)
        if choice is None:
            fail((question or {}).get('section_id', 'plan'), 'choice_id', question_id, 'CHOICE_NOT_OFFERED')
        from .commission_planning import resolve_source_span
        resolved = resolve_source_span(cs, choice['selection'])
        for section in value['sections']:
            if section['section_id'] == question['section_id']:
                section.update(sources=resolved['sources'], text=resolved['text'], extraction={'selection': choice['selection'], **resolved})
                bind_composition(section, question.get('composition', []))
                for slot in section.get('result_bindings', []):
                    if section['text'].count(slot['old']) != 1:
                        fail(section['section_id'], 'result_bindings', slot['old'], 'RESULT_SLOT_NOT_UNIQUE')
                normalized = SectionPlan.model_validate(section).model_dump(mode='json')
                section.clear();section.update(normalized)
        value['questions'] = [q for q in value['questions'] if q['question_id'] != question_id]
        value['version'] += 1
        value.pop('digest');value['digest'] = digest(value)
        plan_inputs.save_skeleton(db, value, actor=actor)
        return {'digest': value['digest'], 'remaining_questions': len(value['questions'])}
    return cs.operation(actor, operation_id, {'question_id': question_id, 'expected_digest': expected_digest, 'choice_id': choice_id, 'selection': selection}, save)


def apply_dispositions(cs, db, plan):
    if not plan_inputs.get_skeleton(db):
        return plan
    result = deepcopy(plan)
    dispositions = deepcopy(list(plan_inputs.get_draft(db, {}).get('items', {}).get('disposition', {}).values()))
    owners = {r['target']: r for r in result.get('owner_records', []) if r['kind'] == 'scope_exclusion'}
    dispositions = [d for d in dispositions if d['object_id'] not in owners]
    dispositions += [{'object_id': identity, 'status': 'owner_excluded', 'owner_record_id': r['id'], 'reason': r['reason']}
                     for identity, r in owners.items()]
    result['candidate_dispositions'] = dispositions
    for d in dispositions:
        if d['status'] == 'proposed_exclusion':
            d['question_id'] = 'candidate-exclusion:' + d['object_id']
            question = d['question_id'] + '：是否同意排除该候选对象？理由：' + d['reason']
            if question not in result['open_questions']:
                result['open_questions'].append(question)
    return result


def disposition_gaps(cs, db, plan):
    if not plan_inputs.get_skeleton(db):
        return []
    gaps = []
    def gap(identity, field, reason):
        gaps.append({'anchor_id': None, 'path': field + '.' + identity, 'code': 'CANDIDATE_STATUS_REQUIRED', 'message': reason, 'item_id': identity})
    objects = {o['object_id']: o for o in plan.get('objects', [])}
    owners = {r['target']: r for r in plan.get('owner_records', []) if r['kind'] == 'scope_exclusion'}
    statuses = plan.get('candidate_dispositions', [])
    ids = [d.get('object_id') for d in statuses]
    for identity in objects:
        matches = [d for d in statuses if d.get('object_id') == identity]
        if len(matches) != 1:
            gap(identity, 'candidate_dispositions', 'Each candidate needs exactly one structured disposition')
            continue
        d = matches[0]; status = d.get('status')
        if status not in ('included', 'owner_excluded', 'proposed_exclusion') or not str(d.get('reason','')).strip():
            gap(identity, 'candidate_dispositions', 'Named status and reason required')
        elif status == 'included' and (objects[identity]['included'] is not True or identity in owners):
            gap(identity, 'candidate_dispositions', 'Inclusion contradicts object or owner record')
        elif status != 'included' and objects[identity]['included'] is not False:
            gap(identity, 'candidate_dispositions', 'Exclusion contradicts included object')
        elif status == 'owner_excluded' and (identity not in owners or d.get('owner_record_id') != owners[identity]['id']):
            gap(identity, 'candidate_dispositions', 'Exclusion needs the immutable owner record')
        elif status == 'proposed_exclusion':
            expected = 'candidate-exclusion:' + identity
            if identity in owners or d.get('question_id') != expected or not any(q.startswith(expected + '：') for q in plan.get('open_questions', [])):
                gap(identity, 'open_questions', 'Proposed exclusion must remain an explicit owner question')
    for identity in set(ids) - set(objects):
        gap(str(identity), 'candidate_dispositions', 'Disposition refers to an unknown object')
    return gaps
