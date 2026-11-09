"""Import source-bound judgments as proposals; prior approvals never cross runs."""
from . import plan_inputs
from . import plan_authority
from copy import deepcopy
from typing import Literal
from pydantic import Field
from .content_models import Contract, Ref
from .commission_plan import _state, _set, _validate_sources
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode

KEY = 'commission_carryover'


class CarriedReview(Contract):
    item_id: str
    expected_digest: str
    status: Literal['confirmed', 'revised']
    note: str = ''


def _value(item, plan):
    if item['kind'] == 'object':
        return next((o for o in plan['objects'] if o['object_id'] == item['target']), None)
    if item['kind'] == 'reconciliation':
        rows = plan['reconciliations']
        return rows[item['index']] if len(rows) > item['index'] else None
    if item['kind'] == 'question':
        return plan['open_questions']
    section = next((s for s in plan['sections'] if s['section_id'] == item['target']), None)
    return {k: section.get(k, [] if k != 'rule' else '') for k in ('section_id','sources','examples','rule')} if section else None


def rows(db, plan, details=False):
    registry = _state(db, KEY)
    if not registry:
        return []
    result = []
    for item in registry['items']:
        current = _value(item, plan)
        current_digest = digest(current)
        review = registry['reviews'].get(item['item_id'], {})
        status = review.get('status', 'proposed') if review.get('expected_digest') == current_digest else 'proposed'
        row = {k: item[k] for k in ('item_id','kind','target')}
        row.update(current_digest=current_digest, status=status, note=review.get('note','') if status != 'proposed' else '')
        if details:
            row.update(original=item['original'], current=current, initial_digest=item['initial_digest'])
        result.append(row)
    return result


def decorate(db, plan):
    registry = _state(db, KEY)
    if registry:
        plan = {**plan, 'carryover_digest': registry['digest'], 'carried_items': rows(db, plan)}
    return plan


def gaps(cs, db, plan):
    registry = _state(db, KEY)
    if not registry:
        if plan.get('carryover_digest') or plan.get('carried_items'):
            raise ActionRejected('CARRYOVER_REGISTRY_REQUIRED')
        return []
    if plan.get('carryover_digest') != registry['digest'] or plan.get('carried_items') != rows(db, plan):
        raise ActionRejected('CARRYOVER_REVIEW_BINDING_CHANGED')
    result = [{'anchor_id': None, 'path': 'carried_items.' + r['item_id'], 'code': 'CARRYOVER_REVIEW_REQUIRED',
             'message': 'Review this current source-bound proposal; prior approval is not imported.'}
            for r in rows(db, plan) if r['status'] == 'proposed']
    owners = {r['target'] for r in plan.get('owner_records',[]) if r['kind']=='scope_exclusion'}
    carried = {r['target'] for r in registry['items'] if r['kind']=='object'}
    excluded = [o for o in plan['objects'] if o['object_id'] in carried - owners and o['included'] is False]
    if excluded:
        from .source_access import coverage
        from .document_tools import physical_page_number
        access = {r['source_id']:r for r in coverage(cs,plan,include_page_totals=False)['sources']}
        for obj in excluded:
            wanted = []
            for citation in obj['sources']:
                page = physical_page_number(citation['locator'])
                sid = cs._read(db,citation['source_ref'])['payload']['source_id']
                row = access.get(sid,{})
                seen = set(row.get('text_returned_pages',[])) | set(row.get('inspected_text_pages',[])) | {x['page'] for x in row.get('image_observations',[])}
                wanted.append(page is not None and page in seen)
            if not wanted or not all(wanted):
                result.append({'anchor_id':None,'path':'objects.'+obj['object_id'],'code':'CARRYOVER_EXCLUSION_PAGE_READ_REQUIRED',
                               'message':'Read each cited exclusion page in this run or bind an owner exclusion record.'})
    return result


def install_carryover(cs, package, source_refs):
    from .commission_planning import _assemble
    from .content_models import InventoryObject
    from .commission_plan import Reconciliation
    from .hierarchical_tools import actor_for
    if set(package) != {'contract','origin','source_pins','judgments'} or package['contract'] != 'judgment-carryover-v1':
        raise ActionRejected('CARRYOVER_PACKAGE_INVALID')
    judgments = package['judgments']
    if set(judgments) != {'objects','reconciliations','questions','section_source_choices'} or any(not isinstance(v,list) for v in judgments.values()):
        raise ActionRejected('CARRYOVER_JUDGMENT_FIELDS_ONLY')
    available = {}
    for ref in source_refs:
        if ref['type'] != 'SourceArtifact':
            raise ActionRejected('CARRYOVER_SOURCE_REQUIRED')
        available.setdefault(cs.read(ref)['payload']['file_digest'], {})[Ref.model_validate(ref).key()] = ref
    remap = {}
    for pin in package['source_pins']:
        key = Ref.model_validate(pin['ref']).key()
        matches = available.get(pin['file_digest'], {})
        if key in remap or len(matches) != 1:
            raise ActionRejected('CARRYOVER_SOURCE_MISSING_OR_AMBIGUOUS: ' + str(key))
        remap[key] = next(iter(matches.values()))
    def bind(value):
        if isinstance(value, dict):
            if 'source_ref' in value:
                key = Ref.model_validate(value['source_ref']).key()
                if key not in remap:
                    raise ActionRejected('CARRYOVER_SOURCE_UNPINNED: ' + str(key))
                value = {**value, 'source_ref': remap[key]}
                return {k: (v if k == 'source_ref' else bind(v)) for k,v in value.items()}
            return {k: bind(v) for k,v in value.items()}
        return [bind(v) for v in value] if isinstance(value,list) else value
    mapped = bind(judgments)
    fingerprint = digest(package)
    with cs.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = _state(db, KEY)
        if previous:
            if previous['digest'] != fingerprint:
                raise ActionRejected('CARRYOVER_PACKAGE_IMMUTABLE')
            return fingerprint
        if not plan_inputs.get_skeleton(db) or plan_inputs.get_draft(db, {}).get('revision') or plan_authority.plan_ref(db) or plan_authority.decision_ref(db):
            raise ActionRejected('CARRYOVER_FRESH_SKELETON_REQUIRED')
        _validate_sources(cs, db, actor_for('coordinator'), mapped)
        items, proposals = {}, []
        def add(kind, target, original, index=0):
            identity = kind + ':' + target
            if any(p['item_id'] == identity for p in proposals):
                raise ActionRejected('CARRYOVER_DUPLICATE_ITEM: ' + identity)
            proposals.append({'item_id':identity,'kind':kind,'target':target,'index':index,'original':deepcopy(original)})
        for obj in mapped['objects']:
            obj = InventoryObject.model_validate(obj).model_dump(mode='json')
            add('object', obj['object_id'], obj)
            items.setdefault('object', {})[obj['object_id']] = obj
        for i, value in enumerate(mapped['reconciliations']):
            value = Reconciliation.model_validate(value).model_dump(mode='json')
            target = 'carryover-' + str(i+1)
            add('reconciliation', target, value, i)
            items.setdefault('reconciliation', {})[target] = {**value, 'reconciliation_id':target}
        # Historical free-text questions cannot silently become resolved owner decisions.
        from .commission_planning import PlanningQuestion
        for i, value in enumerate(mapped['questions']):
            question = PlanningQuestion.model_validate({'question_id':'carryover-'+str(i+1),'text':value,'resolved':False}).model_dump(mode='json')
            add('question', question['question_id'], question)
            items.setdefault('question', {})[question['question_id']] = question
        skeleton = {s['section_id']:s for s in plan_inputs.get_skeleton(db)['sections']}
        for value in mapped['section_source_choices']:
            if set(value) != {'section_id','sources','examples','rule'} or value['section_id'] not in skeleton:
                raise ActionRejected('CARRYOVER_SECTION_JUDGMENT_INVALID')
            add('section', value['section_id'], value)
            section = skeleton[value['section_id']]
            if section['kind'] == 'extracted' and not section.get('extraction'):
                items.setdefault('section_judgment',{})[value['section_id']] = {k:value[k] for k in ('section_id','sources','examples')}
        plan_inputs.save_draft(db, {'revision':1,'items':items})
        _, _, plan = _assemble(cs,db)
        for item in proposals:
            item['initial_digest'] = digest(_value(item,plan))
        _set(db, KEY, {'digest':fingerprint,'origin':package['origin'],'source_pins':package['source_pins'],
                      'items':proposals,'reviews':{}})
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)', ('carryover_proposed',encode({'digest':fingerprint,'count':len(proposals),'approved':False})))
    return fingerprint


def review_carried_items(cs, actor, operation_id, reviews):
    from .commission_planning import _assemble
    if actor.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: carryover review belongs to coordinator')
    reviews = [CarriedReview.model_validate(r).model_dump(mode='json') for r in reviews]
    def save(db):
        registry = _state(db,KEY)
        if not registry or not reviews or len({r['item_id'] for r in reviews}) != len(reviews):
            raise ActionRejected('CARRYOVER_REVIEW_SET_INVALID')
        draft, _, plan = _assemble(cs,db)
        current = {r['item_id']:r for r in rows(db,plan,True)}
        for review in reviews:
            item = current.get(review['item_id'])
            if not item or review['expected_digest'] != item['current_digest']:
                raise ActionRejected('CARRYOVER_REVIEW_STALE: ' + review['item_id'])
            if review['status'] == 'confirmed' and item['current_digest'] != item['initial_digest']:
                raise ActionRejected('CARRYOVER_REVISED_ACK_REQUIRED: ' + review['item_id'])
            if review['status'] == 'revised' and not review['note'].strip():
                raise ActionRejected('CARRYOVER_REVISION_NOTE_REQUIRED: ' + review['item_id'])
            registry['reviews'][review['item_id']] = review
        _set(db,KEY,registry)
        draft['revision'] += 1
        plan_inputs.save_draft(db, draft, actor=actor)
        return {'reviewed':len(reviews),'revision':draft['revision']}
    return cs.operation(actor,operation_id,{'reviews':reviews},save)
