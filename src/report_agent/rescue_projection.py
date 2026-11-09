"""Audited prose-only rescue projection; original authors and records are immutable."""
from . import report_state
from .assessment_projection import assessment_receipt, score_blocker, selected_assessment
from copy import deepcopy
import json
import re

from .commission_plan import _confirmed
from .content_layout import STRUCTURAL
from .content_models import ContentNode, Ref
from .errors import ActionForbidden, ActionRejected
from .material_issues import IssueSource, MaterialIssue, validate_node
from .store import digest

CONTRACT = 'rescue-prose-projection-v1'


def _key(ref):
    return Ref.model_validate(ref).key()


def _origin(cs, db, snapshot_ref, source_ref, sid, plan, coordinator):
    if coordinator.role != 'coordinator' or plan['owner_id'] != coordinator.id:
        raise ActionForbidden('FORBIDDEN: rescue projection requires commission coordinator')
    section = next((s for s in plan['payload']['sections'] if s['section_id'] == sid), None)
    if section is None or section['kind'] != 'extracted':
        raise ActionRejected('RESCUE_EXTRACTED_SECTION_REQUIRED: ' + sid)
    snapshot = cs._read(db, snapshot_ref)
    if (snapshot_ref['type'] != 'DocumentSnapshot' or snapshot['payload'].get('commission_plan_ref') != plan['ref'] or
            _key(source_ref) not in {_key(r) for r in snapshot['payload']['refs']}):
        raise ActionRejected('RESCUE_SOURCE_NOT_FROZEN_IN_PLAN: ' + str(source_ref))
    decision = cs._read(db, snapshot['payload']['commission_confirmation_ref'])
    if (decision['owner_id'] != 'operator' or decision['payload'].get('approved') is not True or
            decision['payload'].get('plan_ref') != plan['ref']):
        raise ActionRejected('RESCUE_SOURCE_CONFIRMATION_INVALID')
    source = cs._read(db, source_ref)
    task_id = source.get('task_id')
    if (source_ref['type'] != 'ContentNode' or not task_id or
            source['owner_id'] != 'content:writer:' + task_id or source['created_by'] != source['owner_id']):
        raise ActionForbidden('FORBIDDEN: rescue source writer identity')
    task = cs._read(db, {'type': 'DelegatedTask', 'id': task_id, 'version': 1})
    assignment = task['payload']
    if (task['owner_id'] != coordinator.id or assignment.get('delegated_by') != coordinator.id or
            assignment.get('role') != 'writer' or assignment.get('commission_plan_ref') != plan['ref'] or
            sid not in assignment.get('section_ids', [])):
        raise ActionForbidden('FORBIDDEN: rescue source writer section assignment')
    node = source['payload']; body = node['body']
    if (node['kind'] not in {'block', 'chapter'} or body.get('section_id', sid) != sid or
            body.get('assessment_ref') or body.get('planned_section')):
        raise ActionRejected('RESCUE_SOURCE_NOT_EXTRACTED_PROSE: ' + str(source_ref))
    titles = {s['section_id'] + ' ' + s['title']: s['section_id'] for s in plan['payload']['sections']}
    first = body['text'].splitlines()[0]
    labelled = titles.get(first)
    if labelled is not None and labelled != sid:
        raise ActionRejected('RESCUE_SECTION_IDENTITY_AMBIGUOUS: ' + str(source_ref))
    parents = {}
    for ref in snapshot['payload']['refs']:
        if ref['type'] == 'Relation':
            relation = cs._read(db, ref)['payload']
            if relation.get('predicate') == 'contains':
                parents[_key(relation['object_ref'])] = relation['subject_ref']
    cursor, visited = source_ref, set()
    exact_ancestor = False
    while cursor != snapshot['payload']['root_ref']:
        key = _key(cursor)
        if key in visited or key not in parents:
            raise ActionRejected('RESCUE_SOURCE_NOT_IN_RENDERED_TREE: ' + str(source_ref))
        visited.add(key); cursor = parents[key]
        ancestor = cs._read(db, cursor)['payload']
        if ancestor['kind'] == 'report':
            continue
        ancestor_body = ancestor['body']
        exact_ancestor |= ancestor_body.get('text', '').splitlines()[:1] == [sid + ' ' + section['title']]
        ancestor_sid = ancestor_body.get('section_id') or titles.get(ancestor_body.get('text', '').split('\n')[0])
        if ancestor_sid and ancestor_sid != sid and not sid.startswith(ancestor_sid + '.'):
            raise ActionRejected('RESCUE_SECTION_ANCESTRY_CONFLICT: ' + str(source_ref))
    if body.get('section_id') is None and labelled != sid and not exact_ancestor:
        raise ActionRejected('RESCUE_SECTION_IDENTITY_AMBIGUOUS: ' + str(source_ref))
    return snapshot, source, task, section, decision


def _text_projection(text, sid, title):
    first = text.splitlines(keepends=True)[0]
    removed = None
    if first.rstrip('\r\n') == sid + ' ' + title:
        removed = {'start': 0, 'end': len(first), 'text': first}
        text = text[len(first):]
    if not text.strip():
        raise ActionRejected('RESCUE_HEADING_ONLY_REQUIRES_SYSTEM_SECTION: ' + sid)
    return text, removed


def _items(qualifiers):
    for key, value in qualifiers.items():
        if key in STRUCTURAL or key == 'source_note' and isinstance(value, str):
            continue
        if isinstance(value, list) and value:
            yield from ((key, index, item) for index, item in enumerate(value))
        else:
            yield key, None, value


def _caveat(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def _issue_sources(cs, db, source, section):
    result = set()
    for citation in [*source['payload'].get('citations', []), *section.get('sources', [])]:
        ref = citation['source_ref']
        record = cs._read(db, ref)
        if ref['type'] != 'SourceArtifact':
            raise ActionRejected('RESCUE_CITATION_SOURCE_ARTIFACT_REQUIRED')
        title = record['payload'].get('source_metadata', {}).get('title')
        if not title:
            raise ActionRejected('RESCUE_CITATION_READABLE_TITLE_REQUIRED')
        result.add(IssueSource(document=title, page=citation['locator']).readable())
    return result


def _project(cs, db, source, section, dispositions, required):
    node = deepcopy(source['payload'])
    sid = section['section_id']
    text, removed = _text_projection(node['body']['text'], sid, section['title'])
    expected = {(key, index): value for key, index, value in _items(node['qualifiers'])}
    supplied = {}
    if not isinstance(dispositions, dict):
        raise ActionRejected('RESCUE_QUALIFIER_DISPOSITION_MAPPING_REQUIRED')
    for key, entries in dispositions.items():
        if not isinstance(entries, list):
            raise ActionRejected('RESCUE_QUALIFIER_DISPOSITION_LIST_REQUIRED: ' + key)
        for entry in entries:
            if not isinstance(entry, dict):
                raise ActionRejected('RESCUE_QUALIFIER_DISPOSITION_RECORD_REQUIRED: ' + key)
            index = entry.get('index')
            if index is not None and type(index) is not int:
                raise ActionRejected('RESCUE_QUALIFIER_INDEX_INVALID: ' + key)
            slot = (key, index)
            if slot in supplied or slot not in expected:
                raise ActionRejected('RESCUE_QUALIFIER_DISPOSITION_UNEXPECTED: ' + str(slot))
            supplied[slot] = entry
    missing = [{'ref': source['ref'], 'key': key, 'index': index} for key, index in expected.keys() - supplied.keys()]
    if missing:
        raise ActionRejected('RESCUE_QUALIFIER_DISPOSITIONS_INCOMPLETE', diagnostic={'missing': missing})
    allowed_sources = _issue_sources(cs, db, source, section)
    issues = deepcopy(node['body'].get('material_issues', [])); accounted = []
    for (key, index), value in expected.items():
        entry = supplied[(key, index)]; kind = entry.get('kind')
        if kind == 'visible_issue':
            if set(entry) - {'index', 'kind', 'issue'}:
                raise ActionRejected('RESCUE_ISSUE_DISPOSITION_FIELDS_INVALID')
            issue = MaterialIssue.model_validate(entry.get('issue')).model_dump(mode='json')
            if _caveat(value) not in issue['basis']:
                raise ActionRejected('RESCUE_CAVEAT_NOT_PRESERVED: ' + issue['id'])
            if any(IssueSource.model_validate(s).readable() not in allowed_sources for s in issue['sources']):
                raise ActionRejected('RESCUE_ISSUE_SOURCE_NOT_BOUND: ' + issue['id'])
            if not issue['sources'] and issue['kind'] != 'no_evidence_assumption':
                raise ActionRejected('RESCUE_ISSUE_SOURCE_REQUIRED: ' + issue['id'])
            registry = required.get(issue['id'])
            if registry and any(issue[k] != registry[k] for k in ('id', 'kind', 'object_label', 'basis', 'sources', 'question')):
                raise ActionRejected('RESCUE_REQUIRED_ISSUE_FIELDS_CHANGED: ' + issue['id'])
            existing = next((i for i in issues if i['id'] == issue['id']), None)
            if existing is not None and {k:v for k,v in existing.items() if k != 'anchor'} != {k:v for k,v in issue.items() if k != 'anchor'}:
                raise ActionRejected('RESCUE_ISSUE_ID_CONFLICT: ' + issue['id'])
            if existing is None:
                issues.append(issue)
        elif kind == 'generation_record':
            if (set(entry) - {'index', 'kind', 'classification', 'rationale', 'evidence', 'replacement_ref'} or
                    entry.get('classification') not in {'execution_only', 'superseded'} or
                    not isinstance(entry.get('rationale'), str) or not entry['rationale'].strip() or
                    not isinstance(entry.get('evidence'), str) or not entry['evidence'].strip()):
                raise ActionRejected('RESCUE_DIAGNOSTIC_DISPOSITION_EVIDENCE_REQUIRED: ' + key)
            if entry['classification'] == 'superseded':
                replacement = entry.get('replacement_ref')
                if not replacement or replacement == source['ref']:
                    raise ActionRejected('RESCUE_DIAGNOSTIC_REPLACEMENT_REQUIRED: ' + key)
                saved = cs._read(db, replacement)
                body = saved['payload'].get('body', {})
                task = cs._read(db, {'type': 'DelegatedTask', 'id': source['task_id'], 'version': 1})
                plan_ref = task['payload']['commission_plan_ref']
                planned = report_state.planned_section(db, replacement)
                assessment = body.get('assessment_ref')
                scored = assessment_receipt(db, assessment) if assessment else None
                valid_planned = (planned and planned.get('node_ref') == replacement and
                    planned.get('commission_plan_ref') == plan_ref and
                    (report_state.native(db, 'SectionProvenance', replacement)
                     or planned.get('body_digest') == digest(body) or planned.get('text_digest') == digest(body.get('text'))))
                if scored and (blocker := score_blocker(scored)):
                    raise ActionRejected('RESCUE_ASSESSMENT_SCORE_UNAVAILABLE: ' + blocker)
                valid_scored = (scored and scored.get(body.get('assessment_part', '') + '_ref') == replacement and
                    cs._read(db, assessment)['payload'].get('commission_plan_ref') == plan_ref)
                if replacement['type'] != 'ContentNode' or not (valid_planned or valid_scored):
                    raise ActionRejected('RESCUE_DIAGNOSTIC_SYSTEM_REPLACEMENT_REQUIRED: ' + key)
        else:
            raise ActionRejected('RESCUE_QUALIFIER_DISPOSITION_KIND_REQUIRED: ' + key)
        accounted.append({'key': key, 'index': index, 'original_value': deepcopy(value), 'disposition': deepcopy(entry)})
    node['kind'] = 'block'; node['body'].update(text=text, section_id=sid)
    node['qualifiers'] = {k: deepcopy(v) for k,v in node['qualifiers'].items() if k in STRUCTURAL or k == 'source_note' and isinstance(v, str)}
    if issues:
        node['body']['material_issues'] = [{**i, 'anchor': {'paragraph_index': 0, 'start': 0, 'end': None}} for i in issues]
    payload = ContentNode.model_validate(node).model_dump(mode='json')
    validate_node(payload, source['ref'])
    return payload, removed, accounted



def _assessment_replacement(cs, db, source, section, plan, assessment_ref):
    """Remove one observed terminal result, retaining exact source span provenance."""
    from .risk_scoring import validate_outcome
    text = source['payload']['body']['text']
    matches = [obj for obj in plan['payload']['objects'] if obj['included'] and
        re.match(re.escape(obj['object_id'].split('-K', 1)[0]) + r'(?![A-Za-z0-9-])', text)]
    if section['section_id'] != '4' or len(matches) != 1:
        raise ActionRejected('RESCUE_ASSESSMENT_SOURCE_OBJECT_AMBIGUOUS: ' + str(source['ref']))
    obj = matches[0]
    if assessment_ref.get('type') != 'Assessment':
        raise ActionRejected('RESCUE_ASSESSMENT_REF_REQUIRED')
    saved = cs._read(db, assessment_ref)['payload']
    receipt = assessment_receipt(db, assessment_ref)
    if (not receipt or receipt.get('assessment_ref') != assessment_ref or
            saved.get('commission_plan_ref') != plan['ref'] or saved.get('object_id') != obj['object_id']):
        raise ActionRejected('RESCUE_ASSESSMENT_PLAN_OBJECT_RECEIPT_REQUIRED')
    blocker = score_blocker(receipt)
    if blocker:
        raise ActionRejected('RESCUE_ASSESSMENT_SCORE_UNAVAILABLE: ' + blocker)
    if any(cs._read(db, receipt[part + '_ref'])['payload']['body'].get('section_id') != section['section_id']
            for part in ('evaluation', 'level')):
        raise ActionRejected('RESCUE_ASSESSMENT_SECTION_MISMATCH')
    checked = validate_outcome(cs, db, plan, obj['object_id'], receipt['evaluation_ref'],
        receipt['level_ref'], [receipt['evidence_ref']], [])
    current = selected_assessment(db, plan['ref'], obj['object_id'])
    if checked != assessment_ref or current is not None and current != assessment_ref:
        raise ActionRejected('RESCUE_ASSESSMENT_CANONICAL_REF_MISMATCH')
    pattern = r'本边坡综合得分F＝[0-9]+\.[0-9]{2}，风险等级(?:Ⅲ级，需|Ⅱ级，不需)开展专项施工安全风险评估。'
    found = list(re.finditer(pattern, text))
    if (len(found) != 1 or text.count('本边坡综合得分') != 1 or found[0].end() != len(text) or
            found[0].start() == 0 or text[found[0].start() - 1] not in '。！？\n\r'):
        raise ActionRejected('RESCUE_RESULT_SINGLE_TERMINAL_SENTENCE_REQUIRED: ' + str(source['ref']))
    span = {'start': found[0].start(), 'end': found[0].end(), 'text': found[0].group()}
    return {'assessment_ref': assessment_ref, 'object_id': obj['object_id'], 'removed_result_span': span}

def project_rescue_prose(cs, coordinator, operation_id, *, source_snapshot_ref, bindings, qualifier_dispositions,
                         assessment_replacements=None):
    """Create coordinator-owned derived copies only; no source record is changed."""
    if coordinator.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: rescue projection coordinator required')
    assessment_replacements = {} if assessment_replacements is None else assessment_replacements
    if not isinstance(assessment_replacements, dict):
        raise ActionRejected('RESCUE_ASSESSMENT_REPLACEMENT_MAPPING_REQUIRED')
    request = dict(source_snapshot_ref=source_snapshot_ref, bindings=bindings, qualifier_dispositions=qualifier_dispositions)
    if assessment_replacements:
        request['assessment_replacements'] = assessment_replacements
    def execute(db):
        plan, _ = _confirmed(cs, db)
        prepared, selected = [], set()
        if not isinstance(bindings, dict) or not bindings:
            raise ActionRejected('RESCUE_EXPLICIT_SECTION_BINDINGS_REQUIRED')
        for sid, refs in bindings.items():
            if not isinstance(refs, list) or not refs:
                raise ActionRejected('RESCUE_ORDERED_PROSE_REFS_REQUIRED: ' + sid)
            for ref in refs:
                if _key(ref) in selected:
                    raise ActionRejected('RESCUE_DUPLICATE_SOURCE_BINDING')
                selected.add(_key(ref))
                snapshot, source, task, section, decision = _origin(cs, db, source_snapshot_ref, ref, sid, plan, coordinator)
                required = {i['id']:i for i in decision['payload'].get('required_material_issues', [])}
                dispositions = qualifier_dispositions.get(ref['id'], {})
                payload, removed, accounting = _project(cs, db, source, section, dispositions, required)
                replacement = None
                if ref['id'] in assessment_replacements:
                    replacement = _assessment_replacement(cs, db, source, section, plan, assessment_replacements[ref['id']])
                    sentence = replacement['removed_result_span']['text']
                    payload['body']['text'] = payload['body']['text'][:-len(sentence)]
                    if not payload['body']['text'].strip():
                        raise ActionRejected('RESCUE_RESULT_SITE_FACTS_REQUIRED')
                prepared.append((sid, snapshot, source, task, payload, removed, accounting, dispositions, replacement))
        if set(qualifier_dispositions) - {key[1] for key in selected}:
            raise ActionRejected('RESCUE_DISPOSITIONS_OUTSIDE_SELECTED_NODES')
        if set(assessment_replacements) - {key[1] for key in selected}:
            raise ActionRejected('RESCUE_ASSESSMENT_REPLACEMENTS_OUTSIDE_SELECTED_NODES')
        output = {sid: [] for sid in bindings}; receipts = []
        for sid, snapshot, source, task, payload, removed, accounting, dispositions, replacement in prepared:
            ref = cs._insert(db, coordinator, 'ContentNode', payload)
            receipt = {'contract': CONTRACT, 'projection_ref': ref,
                'source_snapshot_ref': source_snapshot_ref,
                'source_ref': source['ref'], 'source_task_ref': task['ref'],
                'section_id': sid, 'commission_plan_ref': plan['ref'],
                'removed_structural_span': removed, 'archived_qualifiers': deepcopy(source['payload']['qualifiers']),
                'qualifier_accounting': accounting, 'qualifier_dispositions': deepcopy(dispositions)}
            if replacement is not None:
                receipt['assessment_replacement'] = replacement
            report_state.record_projection(db, ref, receipt)
            output[sid].append(ref); receipts.append(receipt)
        return {'section_bindings': output, 'projection_receipts': receipts,
                'refs': {str(i): ref for i, ref in enumerate(r for refs in output.values() for r in refs)}}
    return cs.operation(coordinator, operation_id, {'rescue_prose_projection': request}, execute,
                        binding_identity=lambda db, result: _confirmed(cs, db)[0]['ref'])


def verify_projection(cs, db, record, sid, plan, co_actor):
    """Verify the exact derived copy and original assignment; never adopt producer identity."""
    receipt = report_state.projection(db, record['ref'])
    native = report_state.native(db, 'RescueProjection', record['ref'])
    if (not receipt or receipt.get('contract') != CONTRACT or receipt.get('projection_ref') != record['ref'] or
            record.get('owner_id') != co_actor.id or record.get('created_by') != co_actor.id or
            receipt.get('section_id') != sid or receipt.get('commission_plan_ref') != plan['ref']):
        raise ActionRejected('RESCUE_PROJECTION_RECEIPT_REQUIRED_OR_INVALID')
    if not native and receipt.get('payload_digest') != digest(record['payload']):
        raise ActionRejected('RESCUE_PROJECTION_PAYLOAD_DIGEST_MISMATCH')
    snapshot, source, task, section, decision = _origin(cs, db, receipt['source_snapshot_ref'], receipt['source_ref'], sid, plan, co_actor)
    if (receipt.get('source_task_ref') != task['ref'] or (not native and (
            receipt.get('source_snapshot_digest') != digest(snapshot['payload']) or
            receipt.get('source_record_digest') != digest(source) or
            receipt.get('source_task_digest') != digest(task)))):
        raise ActionRejected('RESCUE_PROJECTION_SOURCE_DIGEST_MISMATCH')
    required = {i['id']:i for i in decision['payload'].get('required_material_issues', [])}
    expected, removed, accounting = _project(cs, db, source, section, receipt['qualifier_dispositions'], required)
    replacement = receipt.get('assessment_replacement')
    if replacement is not None:
        checked = _assessment_replacement(cs, db, source, section, plan, replacement['assessment_ref'])
        if replacement != checked:
            raise ActionRejected('RESCUE_ASSESSMENT_REPLACEMENT_TRANSFORM_MISMATCH')
        expected['body']['text'] = expected['body']['text'][:-len(checked['removed_result_span']['text'])]
    if record['payload'] != expected:
        raise ActionRejected('RESCUE_PROJECTION_PAYLOAD_DIGEST_MISMATCH')
    if (receipt.get('removed_structural_span') != removed or
            receipt.get('archived_qualifiers') != source['payload']['qualifiers'] or
            receipt.get('qualifier_accounting') != accounting):
        raise ActionRejected('RESCUE_PROJECTION_TRANSFORM_MISMATCH')
    return receipt
