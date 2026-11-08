"""Small, exact decision-state projections; no model, scheduler or semantic judge."""
from . import legacy_state as legacy
import json
from copy import deepcopy
from typing import Annotated

from pydantic import Field

from .errors import ActionRejected
from .store import digest, encode


def completion_state_token(db):
    """Detect business evidence changes while preparing a completion declaration."""
    return digest({
        'heads':db.execute('SELECT type,id,version FROM content_heads ORDER BY type,id').fetchall(),
        'observations':db.execute('SELECT count(*),max(rowid) FROM content_observations').fetchone(),
        'authority':legacy.read_completion_authority_rows(db),
        'sources':db.execute('SELECT id,operation FROM source_versions ORDER BY id').fetchall()
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='source_versions'").fetchone() else [],
    })


def execution_evidence(contents):
    """Describe saved scope/page access independently of correction allowances.

    Page access is an inventory, not an automatically invented review requirement.
    Assigned completion never supplies whole-report or engineering acceptance.
    """
    from .task_supervision import reconcile
    selected = legacy.get_content_delivery(contents.store)
    # Filter immutable task records before reconciliation. Older snapshots remain
    # available but need not repeatedly expand every historical review here.
    assigned = [t for t in contents.list_objects('DelegatedTask')
        if t['payload'].get('review_requirements') and (not selected or
            t['payload'].get('review_snapshot_ref') == selected['snapshot_ref'])]
    tasks = [{'task_ref':t['ref'], **reconcile(contents,t['ref']['id'])} for t in assigned]
    remaining = [{'task_ref':t['task_ref'], 'scope_id':r['requirement']['scope_id'],
        'target_ref':r['requirement']['target_ref'], 'state':r['state'],
        'reason':r['reason'],
        **{k:r.get(k,[]) for k in ('missing_checks','missing_read_refs',
            'missing_required_materials','missing_artifact_refs','artifact_coverage_gaps')}}
        for t in tasks for r in t['remaining']]
    renders = []
    if selected:
        reference_digests = {s['id']:s.get('sha256') or digest(s['content'])
            for s in contents.store.sources([s['id'] for s in contents.store.source_catalog()])
            if s.get('current', True)}
        for render in contents.list_objects('RenderArtifact'):
            p = render['payload']
            if p['export_ref'] != selected['export_ref'] or p['snapshot_ref'] != selected['snapshot_ref']:
                continue
            with contents.store.connect() as db:
                rows = db.execute("SELECT data FROM content_observations WHERE json_extract(data,'$.status')='observed' AND json_extract(data,'$.source.render_ref.id')=?", (render['ref']['id'],)).fetchall()
            seen, paired = set(), set()
            for (raw,) in rows:
                observation = json.loads(raw)
                src = observation.get('source') or {}
                number = src.get('page')
                if (src.get('render_ref') != render['ref'] or src.get('export_ref') != selected['export_ref']
                        or src.get('coverage') != 'full_page_image' or src.get('crop') is not None
                        or not observation.get('observation') or not observation.get('image_sha256')
                        or type(number) is not int or not 1 <= number <= len(p['page_assets'])):
                    continue
                seen.add(number)
                ref = src.get('presentation_reference') or {}
                current_digest = reference_digests.get(ref.get('source_id'))
                if (current_digest and ref.get('source_sha256') == current_digest
                        and ref.get('coverage') == 'full_page_image' and ref.get('crop') is None
                        and type(ref.get('page')) is int and ref['page'] > 0):
                    paired.add(number)
            all_pages = set(range(1, len(p['page_assets'])+1))
            renders.append({'render_ref':render['ref'], 'pages':len(all_pages),
                'observed_full_pages':sorted(seen), 'paired_full_pages':sorted(paired),
                'unobserved_full_pages':sorted(all_pages-seen), 'without_paired_full_page':sorted(all_pages-paired),
                'semantic_comparison_verified':False})
    return {'snapshot_ref':selected['snapshot_ref'] if selected else None,
        'assigned_tasks':len(tasks), 'remaining_assigned_checks':remaining,
        'assigned_checks_complete':bool(tasks) and not remaining,
        'render_access_inventory':renders,
        'inspection_consumes_content_or_layout_correction':False,
        'whole_report_acceptance':None,
        'limitation':'Saved assignments and access receipts only. Pair access is not proof of relevant sections or permitted reference pages. Unassigned work and correctness require the commission and actual judgments; correction exhaustion does not prohibit reading or checking.'}


def preview(value, path, limit=800):
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return {'preview':value[:limit], 'characters':len(value), 'sha256':digest(value),
        'complete':False, 'read_state_path':path}


def feedback_projection(records):
    """Instructions remain exact; native state delivery removes unchanged repeats."""
    return deepcopy(records)


def bounded_metadata(value, path):
    """Bound bookkeeping only; retain exact paths rather than summarizing meaning."""
    if isinstance(value, str):
        return preview(value, path)
    if isinstance(value, dict):
        if 'read_state_path' in value:
            return value  # Already a projection with paths into the original state.
        return {k:bounded_metadata(v, [*path,k]) for k,v in value.items()}
    if isinstance(value, list):
        items = [bounded_metadata(v,[*path,i]) for i,v in enumerate(value[:20])]
        return items if len(value)<=20 else {'items':items,'total':len(value),
            'next_offset':20,'complete':False,'read_state_path':path}
    return value


def assigned_structure(contents, snapshot_ref, targets):
    """Exact assigned topology, never an observation of omitted child bodies."""
    members = contents.read(snapshot_ref)['payload']['refs']
    relations = [contents.read(r)['payload'] for r in members if r['type']=='Relation']
    return [{'target_ref':target, 'children':[
        r['object_ref'] for r in relations if r['predicate']=='contains' and r['subject_ref']==target],
        'parents':[r['subject_ref'] for r in relations
            if r['predicate']=='contains' and r['object_ref']==target],
        'child_bodies_observed':False} for target in targets]


def snapshot_assignment_inventory(contents):
    """Current saved assignment metadata, never a selection or semantic judgment."""
    from .task_supervision import obligation_coverage
    selected = legacy.get_content_delivery(contents.store)
    if selected:
        refs = [selected['snapshot_ref']]
        total = 1
    else:
        with contents.store.connect() as db:
            total = db.execute("SELECT count(*) FROM content_heads WHERE type='DocumentSnapshot'").fetchone()[0]
            refs = [json.loads(row[0])['ref'] for row in db.execute(
                "SELECT v.data FROM content_heads h JOIN content_versions v USING(type,id,version) "
                "WHERE h.type='DocumentSnapshot' ORDER BY h.id LIMIT 20")]
    snapshots = []
    for ref in refs:
        coverage = obligation_coverage(contents, ref)
        missing = coverage['criteria_without_assignment']
        snapshots.append({'snapshot_ref':ref,
            'root_ref':contents.read(ref)['payload']['root_ref'],
            'criteria_count':len(coverage['criteria']),
            'criteria_without_assignment':missing[:20],
            'criteria_without_assignment_total':len(missing),
            'criteria_without_assignment_partial':len(missing)>20,
            'coverage_tool':{'name':'read_review_obligation_coverage','arguments':{'snapshot_ref':ref}}})
    return {'selection':'selected_delivery' if selected else 'available_current_heads_not_selected',
        'snapshots':snapshots, 'catalog_total':total, 'catalog_complete':len(refs)==total,
        'catalog_tool':{'name':'read_object_index','arguments':{
            'object_type':'DocumentSnapshot','current_only':True,'offset':0,'limit':20}},
        'semantic_coverage_verified':False}


def compact_context(context):
    """Lossless references to full server state, not an LLM summary of authority."""
    result = {k:bounded_metadata(v,[k]) for k,v in context.items() if k not in {
        'scope_instruction','assignment','review_tasks','operator_feedback','issues','execution_decision','learned_guidance','scoped_instructions','current_invocation'}}
    if 'current_invocation' in context:
        # This is the actual instruction, not metadata about a retrievable body.
        result['current_invocation'] = context['current_invocation']
    if context.get('scoped_instructions') is not None:
        # Exact currently applicable instructions and unresolved alternatives
        # must survive both metadata projection and conversation compaction.
        result['scoped_instructions'] = context['scoped_instructions']
    if context.get('learned_guidance') is not None:
        guidance = context['learned_guidance']
        # Released customer preferences are current instructions with their
        # applicability conditions, not bookkeeping previews. Preserve exact
        # learner wording; optional experience stays progressively accessible.
        result['learned_guidance'] = {
            **guidance,
            'available_experience': bounded_metadata(guidance['available_experience'],
                                                     ['learned_guidance','available_experience'])}
    result['goal'] = context['goal']
    scope = context.get('scope_instruction')
    result['scope_instruction'] = deepcopy(scope)
    if context.get('assignment'):
        assignment = context['assignment']
        result['assignment'] = deepcopy(assignment)
        requirements = assignment.get('review_requirements') or []
        result['assignment']['review_scope_inventory'] = {
            'total':len(requirements), 'read_state_path':['assignment','review_requirements'],
            'next_offset':20 if len(requirements)>20 else None,
            'scopes':[{'scope_id':r['scope_id'],'target_ref':r['target_ref'],'criterion_ref':r['criterion_ref'],
                **({'assigned_scope_index':i} if assignment.get('review_submission_contract') == 'task-scope-selectors-v1' else {}),
                'required_checks':bounded_metadata(r['required_checks'], ['assignment','review_requirements',i,'required_checks']),
                'required_materials_declared':len(r.get('required_materials', [])),
                'read_state_path':['assignment','review_requirements',i]} for i,r in enumerate(requirements[:20])]}
        if assignment.get('review_interface_profile') == 'review-interfaces-v4':
            result['assignment']['review_commission_basis'] = assignment.get('review_commission_basis')
            for entry, required in zip(result['assignment']['review_scope_inventory']['scopes'], requirements):
                entry['required_checks'] = required['required_checks']
    if context.get('review_tasks'):
        page = context['review_tasks']
        result['review_tasks'] = {**page, 'tasks':[
            {k:v for k,v in t.items() if k not in {'remaining','completion_followup'}} |
            {'remaining_count':len(t['remaining']), 'remaining_scope_ids':[r['scope_id'] for r in t['remaining'][:20]],
             'read_state_path':['review_tasks','tasks',i]} for i,t in enumerate(page['tasks'])]}
        if any(t.get('review_commission_basis') for t in page['tasks']):
            result['review_tasks']['tasks'] = result['review_tasks']['tasks'][:20]
            result['review_tasks']['next_offset'] = 20 if page['total'] > 20 else None
            for index, task in enumerate(result['review_tasks']['tasks']):
                basis = task.get('review_commission_basis')
                if basis:
                    task['review_commission_basis'] = {'digest':basis['digest'],
                        'criterion_count':len(basis['criterion_refs']),
                        'original_requirement_count':len(basis['original_requirement_refs']),
                        'complete':False, 'read_state_path':['review_tasks','tasks',index,'review_commission_basis']}
    result['operator_feedback'] = feedback_projection(context.get('operator_feedback') or [])
    for key in ('issues',):
        records = context.get(key) or []
        result[key] = [{k:preview(v, [key,i,k],600) for k,v in r.items()} if isinstance(r,dict)
            else preview(r,[key,i],600) for i,r in enumerate(records)]
    decision = context.get('execution_decision')
    result['execution_decision'] = ({k:preview(v,['execution_decision',k],600) for k,v in decision.items()
        if k not in {'task_supervision_remaining','execution_evidence'}} if isinstance(decision,dict) else decision)
    result['read_state_tool'] = 'read_decision_state'
    result['projection_note'] = 'Exact live metadata; previews are explicitly incomplete. Read structured paths for full current authority/assignment. History and summaries are working notes; these fields do not establish semantic acceptance. A child omitted from checking input is not absent from the report; topology metadata does not inspect its body. Correction exhaustion does not prohibit inspection.'
    # Older feedback stays retrievable, while the newest operator instructions
    # remain visible when the saved feedback list grows beyond one packet.
    for key in ('issues',):
        if len(result[key])>20:
            result[key] = {'items':result[key][-20:],'total':len(result[key]),
                'offset':len(result[key])-20,'complete':False,'read_state_path':[key]}
    return result


def read_state(workspace, role, path, offset=0, limit=20, characters=6000, expected_state_digest=None):
    from .task_context import exact_task_context
    if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50
            or type(characters) is not int or not 1 <= characters <= 6000):
        raise ActionRejected('INVALID_STATE_PAGE')
    state = exact_task_context(workspace, role)  # Enforces server-bound actor/task.
    if state.get('assignment', {}).get('review_submission_contract') is not None:
        from .review_scope_selectors import requirements_view
        state = {**state, 'assignment': {**state['assignment'],
            'review_requirements': requirements_view(state['assignment'])}}
    if expected_state_digest is not None and expected_state_digest != state['state_digest']:
        raise ActionRejected('STATE_CHANGED_READ_CURRENT_PACKET')
    value = state
    for index, key in enumerate(path):
        if isinstance(value,dict) and isinstance(key,str) and key in value:
            value = value[key]
        elif isinstance(value,list) and type(key) is int and 0 <= key < len(value):
            value = value[key]
        else:
            raise ActionRejected('STATE_PATH_NOT_FOUND', diagnostic={
                'parameter_path': ['path', index], 'resolved_path': path[:index],
                **({'available_keys': sorted(value)} if isinstance(value, dict) else
                   {'selected_type': type(value).__name__})})
    if isinstance(value,list):
        if offset > len(value): raise ActionRejected('STATE_OFFSET_OUTSIDE_VALUE')
        end = min(offset+limit,len(value)); page = value[offset:end]
    elif isinstance(value,str):
        if offset > len(value): raise ActionRejected('STATE_OFFSET_OUTSIDE_VALUE')
        end = min(offset+characters,len(value)); page = value[offset:end]
    else:
        if offset:
            raise ActionRejected('STATE_OFFSET_REQUIRES_LIST_OR_TEXT', diagnostic={
                'parameter_path': ['offset'], 'read_state_path': path,
                'selected_type': type(value).__name__, 'allowed_offset': 0})
        page = value; end = None
    size = len(value) if isinstance(value,(list,str)) else None
    return {'state_digest':state['state_digest'],'path':path,'value':page,'offset':offset,
        'next_offset':end if size is not None and end < size else None,
        'total':size,'complete_value':offset==0 and (size is None or end==size),
        'observation_receipt':None,'semantic_acceptance':False}


def state_tool(workspace, role):
    def read_decision_state(path: list[str | int],
            offset: Annotated[int,Field(ge=0)]=0,
            limit: Annotated[int,Field(ge=1,le=50)]=20,
            characters: Annotated[int,Field(ge=1,le=6000)]=6000,
            expected_state_digest: str | None = None) -> dict:
        """Read exact current server-bound decision fields by structured path.

        Use read_state_path from the current packet, e.g. ['assignment',
        'review_requirements',0] or ['scope_instruction','text']. Empty path reads
        the full state. Lists page by limit, text by characters. next_offset is a
        continuation, not missing evidence. No other actor/task can be selected.
        For continued paging pass the prior state_digest as expected_state_digest;
        changed state is rejected so text from different versions is not mixed.
        This is bookkeeping, not a business observation or completed check.
        """
        return read_state(workspace,role,path,offset,limit,characters,expected_state_digest)
    from .prompt_sources import review_interface_profile, REVIEW_INTERFACE_V3, load_prompt
    if review_interface_profile(workspace.store) == REVIEW_INTERFACE_V3:
        read_decision_state.__doc__ = load_prompt('state-paths-v3')
    return read_decision_state
