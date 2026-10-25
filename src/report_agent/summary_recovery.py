"""Paged actor-owned recovery of public returns selected for native compaction."""
import json
from typing import Annotated
from pydantic import Field, ValidationError
from langchain_core.messages import AIMessage, ToolMessage
from .errors import ActionRejected
from .observation_refs import ObservationRefPrefix, validate_prefix
from .store import encode
from .prompt_sources import load_prompt
from .task_context import actor_id, read_observation, save_observation

def key(workspace, role):
    return 'summary_observation_index:'+actor_id(workspace,role)

def _verify_delivery(workspace, role, message, call, ref):
    """Verify actual raw/field delivery, before trusting its range annotations."""
    delivery = message.additional_kwargs.get('report_observation_delivery',{})
    if delivery.get('representation') == 'focused-capability-v1':
        from .task_context import verify_capability_projection
        verify_capability_projection(workspace, role, message, ref)
        return
    if message.name != 'read_tool_observation' and delivery.get('representation') in {
            'exact-public-result-v2','metadata_and_literal_fragments'}:
        from .decision_data import deliver_controls
        artifact = message.artifact if isinstance(message.artifact,dict) else {}
        binding = artifact.get('report_public_delivery')
        if not isinstance(binding,dict) or binding.get('observation_ref') != ref:
            raise ActionRejected('RETURN_DELIVERY_BINDING_MISSING: original history retained')
        # The existing delivery verifier binds owner/call/status, immutable
        # original bytes and the public projection digest. A representation
        # string alone must never waive raw-range verification.
        deliver_controls(workspace,role,message)
        return
    try:
        packet = json.loads(message.content)
        args = call['args']
        expected = read_observation(workspace, role, ref,
            args.get('offset',0) if message.name=='read_tool_observation' else 0,
            args.get('characters',6000) if message.name=='read_tool_observation' else 6000,
            args.get('field_path') if message.name=='read_tool_observation' else None)
        if message.additional_kwargs.get('report_preview_cleared'):
            prior = packet['previously_presented_range']
            valid = ('text' not in packet and packet.get('preview_cleared') is True
                and packet.get('observation_ref')==ref and packet.get('sha256')==expected['sha256']
                and prior==delivery and all(delivery.get(k)==expected.get(k) for k in (
                    'offset','end','field_path','field_sha256','cursor_scope','complete_tool_result','complete_field'))
                and delivery.get('characters')==len(expected['text']))
        else:
            valid = all(packet.get(k)==expected.get(k) for k in (
                'observation_ref','sha256','text','offset','end','total_characters','next_offset',
                'field_path','field_sha256','cursor_scope','complete_field','complete_tool_result'))
        if not valid:
            raise ValueError('range mismatch')
    except (ValueError,TypeError,KeyError,AttributeError):
        raise ActionRejected('RETURN_DELIVERY_UNVERIFIED: original history retained') from None


def capture(workspace, role, messages, *, phase='summary_compaction'):
    calls={c['id']:c for m in messages if isinstance(m,AIMessage) for c in m.tool_calls}
    decisions={c['id']:m for m in messages if isinstance(m,AIMessage) for c in m.tool_calls}
    records=list(workspace.store.get(key(workspace,role),[]))
    seen={(r['call_id'],r['observation_ref']) for r in records}
    from .task_context import progress_enabled
    progress = progress_enabled(workspace)
    for message in messages:
        if not isinstance(message,ToolMessage) or not isinstance(message.content,str):continue
        call=calls.get(message.tool_call_id)
        if not call or (message.name is not None and message.name != call['name']):continue
        old_ref=message.additional_kwargs.get('report_observation_ref')
        if old_ref:
            observed=read_observation(workspace,role,old_ref,0,1)
            ref=old_ref
            if progress:
                _verify_delivery(workspace,role,message,call,ref)
        else:
            actual=message.model_copy(update={'name':message.name or call['name']})
            ref,saved=save_observation(workspace,role,actual)
            observed={'sha256':saved['sha256'],'total_characters':len(saved['text'])}
        identity=(message.tool_call_id,ref)
        if identity in seen:continue
        selection_keys = {'source_id','query','page','crop','offset','limit','characters','field_path',
            'target_ref','export_ref','render_ref','observation_ref','source_selections','observation_refs'}
        if progress:
            selection_keys |= {'snapshot_ref','inventory_digest','file_path','path','object_type','owner_id','current_only'}
        selection={k:v for k,v in call['args'].items() if k in selection_keys}
        delivery = {'preview_cleared':bool(message.additional_kwargs.get('report_preview_cleared')),
            'current_message_characters':len(message.content),
            'original_delivery':message.additional_kwargs.get('report_observation_delivery'),
            'note':'Provided text ranges do not prove reading or adoption.'}
        if progress:
            delivery['capture_phase'] = phase
        if old_ref and not delivery['preview_cleared']:
            try: packet=json.loads(message.content)
            except (ValueError,TypeError): packet={}
            if packet.get('observation_ref')==ref and isinstance(packet.get('text'),str):
                delivery['compacted_message_range']={k:packet[k] for k in ('offset','end','complete_tool_result',
                    'field_path','cursor_scope','field_sha256','complete_field') if k in packet}
                delivery['compacted_message_range']['characters']=len(packet['text'])
        elif not old_ref:
            delivery['compacted_message_range']={'offset':0,'end':len(message.content),
                'characters':len(message.content),'complete_tool_result':True}
        record = {'call_id':message.tool_call_id,'tool':call['name'],
          'observation_ref':ref,'sha256':observed['sha256'],
          'recoverable_characters':observed['total_characters'],'selection':selection,
          'delivery':delivery,
          'status':message.status,'receiving_actor':actor_id(workspace,role),
          'provided_preview':bool(old_ref),
          'note':'Recorded public return/recovery, not complete reading, source coverage, adoption or acceptance.'}
        from .task_context import navigation_metadata
        if progress:
            decision = decisions[message.tool_call_id]
            record['decision_id'] = decision.id
            record['decision_finish_reason'] = decision.response_metadata.get('finish_reason')
            record['decision_valid'] = not decision.invalid_tool_calls
            from .hierarchical_tools import actor_for
            from .content_tasks import bound_actor, current_invocation
            actor = bound_actor(workspace, role, actor_for(role))
            record['receiving_task'] = actor.task_id
            if role in {'writer','reviewer','layout'}:
                invocation = current_invocation(workspace, actor)
                record['invocation'] = {k:invocation[k] for k in ('delegate_operation_id','description_sha256')}
            metadata = navigation_metadata(message, observed['sha256'])
            if metadata is not None:
                record['decision_metadata'] = metadata
            if call['name'] == 'read_content_index' and message.status == 'success':
                # Only a known immutable producer contract can create host
                # navigation. Arbitrary source text is never parsed as control.
                from .content_selection import content_index
                from .content_store import ContentStore
                expected = content_index(ContentStore(workspace.store), call['args']['snapshot_ref'],
                    call['args'].get('offset',0),call['args'].get('limit',20))
                original = workspace.store.get('tool_observation:'+ref)['text']
                delivered = json.loads(original)
                if role == 'reviewer':
                    with workspace.store.connect() as db:
                        receipt = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                            (delivered.get('receipt_id'),)).fetchone() if isinstance(delivered,dict) else None
                    if (not receipt or receipt[0] != actor.id or set(delivered) != {'ok','result','receipt_id'}
                            or delivered['ok'] is not True or json.loads(receipt[1]) != delivered['result']
                            or delivered['result'] != {'snapshot_structure':expected}):
                        raise ActionRejected('RETURN_NAVIGATION_RECEIPT_MISMATCH: original history retained')
                    record['navigation_receipt_id'] = delivered['receipt_id']
                elif delivered != expected:
                    raise ActionRejected('RETURN_NAVIGATION_IDENTITY_MISMATCH: original history retained')
                record['navigation_page'] = expected
        records.append(record)
        seen.add(identity)
    if len(records)>4096:raise ActionRejected('SUMMARY_RECOVERY_INDEX_LIMIT: original history retained')
    if records != workspace.store.get(key(workspace,role),[]):
        workspace.store.set(key(workspace,role),records)
        workspace.store.event('summary_recovery_captured',{'actor_id':actor_id(workspace,role),'total':len(records)})
    return records


def current_returns(workspace, role, *, focused=False):
    """Small actor-owned index projection; pagination reuses the recovery tool."""
    records = workspace.store.get(key(workspace,role),[])
    # Bound nested navigation without inventing paths in authoritative state.
    from .decision_state import bounded_metadata
    def project(value, offset):
        def translate(item):
            if isinstance(item,list): return [translate(v) for v in item]
            if not isinstance(item,dict): return item
            result = {k:translate(v) for k,v in item.items() if k != 'read_state_path'}
            if 'read_state_path' in item:
                result['recovery_index'] = {'tool':'read_summary_observations','offset':offset,'limit':1}
            return result
        return translate(bounded_metadata(value, []))
    # Repeatedly receiving the same version/range must not push every other
    # useful page out of the current packet. The full delivery history remains
    # untouched and pageable; only this view groups equivalent returns.
    from .store import digest
    distinct = {}
    for i, record in enumerate(records):
        identity = digest({k:record.get(k) for k in ('tool','observation_ref','sha256','selection','invocation','status','receiving_task')})
        previous = distinct.pop(identity, None)
        distinct[identity] = (i, record, (previous[2] if previous else 0)+1)
    recent = list(distinct.values())[-20:]
    result = {'receiving_actor':actor_id(workspace,role),'total':len(records),
        'distinct_returns':len(distinct),
        'recent':[], 'projection_complete':False,
        'all_entries_tool':'read_summary_observations','exact_text_tool':'read_tool_observation',
        'note':load_prompt('progress-returns-note').strip()}
    partial = len(recent) < len(distinct)
    if focused:
        result['projection'] = 'focused-v1'
    for i,r,count in reversed(recent):
        if focused:
            # A later middleware can clear messages. Always retain the exact
            # recovery identity and historical range, even if text is visible now.
            delivery = {k: r['delivery'][k] for k in (
                'preview_cleared', 'original_delivery', 'compacted_message_range') if k in r['delivery']}
            r = {k: r[k] for k in ('call_id', 'tool', 'observation_ref', 'sha256',
                 'selection', 'status', 'receiving_actor', 'receiving_task', 'invocation',
                 'decision_metadata', 'navigation_page', 'navigation_receipt_id') if k in r}
            r.update(delivery=delivery, delivery_is_historical=True)
            r['recovery_index'] = {'tool': 'read_summary_observations', 'offset': i, 'limit': 1}
        row = dict(project(r,i),index_offset=i,repeated_deliveries=count)
        if len(encode(row)) > (6000 if focused else 4000):
            row = {k:row[k] for k in ('tool','call_id','observation_ref','sha256','status','receiving_actor','index_offset','repeated_deliveries')}
            row.update(navigation_deferred=True,recovery_index={'tool':'read_summary_observations','offset':i,'limit':1})
            partial = True
        if len(encode({**result,'recent':[row,*result['recent']]})) <= 12000:
            result['recent'].insert(0,row)
        else:
            partial = True
    result['projection_complete'] = not partial
    return result

def recovery_tool(workspace,role):
    def read_summary_observations(offset: Annotated[int,Field(ge=0)]=0,
                                 limit: Annotated[int,Field(ge=1,le=20)]=20,
                                 observation_ref_prefix: ObservationRefPrefix | None = None)->dict:
        """Page your own public returns retained across compaction. Reopen exact text
        with read_tool_observation using the full returned observation_ref, never an
        abbreviated/reconstructed identifier. offset is >=0; limit is 1..20, in records.
        Use next_offset. Optional observation_ref_prefix filters this actor's captured
        index by exact hex prefix, including entries older than the recent summary.
        Inspect full returned identities and ambiguity; a prefix is lookup-only and
        must never be passed to reading/production as if it were an exact identity.
        Offsets count filtered records. This index is not a completed business check."""
        if type(offset)!=int or offset<0 or type(limit)!=int or not 1<=limit<=20:
            raise ActionRejected('INVALID_SUMMARY_INDEX_RANGE: offset must be >=0 and limit must be 1..20 records; use next_offset')
        if observation_ref_prefix is not None:
            try:
                observation_ref_prefix = validate_prefix(observation_ref_prefix)
            except ValidationError as error:
                raise ActionRejected('INVALID_OBSERVATION_LOOKUP_PREFIX: expected 1..64 lowercase hex characters; no guessing or padding') from error
        records=workspace.store.get(key(workspace,role),[])
        if observation_ref_prefix is None:
            return {'observations':records[offset:offset+limit],'total':len(records),
                'next_offset':offset+limit if offset+limit<len(records) else None}
        matched=[r for r in records if r['observation_ref'].startswith(observation_ref_prefix)]
        identities={r['observation_ref'] for r in matched}
        return {'observations':matched[offset:offset+limit],'total':len(matched),
            'next_offset':offset+limit if offset+limit<len(matched) else None,
            'lookup':{'observation_ref_prefix':observation_ref_prefix,
                'distinct_reference_count':len(identities),
                'status':'no_match' if not identities else 'unique' if len(identities)==1 else 'ambiguous',
                'note':'Only your captured public index was searched. Match count does not establish source coverage or permission to another actor. Select a full returned identity; no reference was guessed or consumed.'}}
    return read_summary_observations

def continuation_index(records):
    preview=[{k:r[k] for k in ['tool','call_id','observation_ref','selection','status','delivery','provided_preview']} for r in records[-20:]]
    return '\n\nPublic return recovery index (not facts or completed checks):\n'+encode({
      'total':len(records),'recent':preview,'all_entries_tool':'read_summary_observations',
      'exact_text_tool':'read_tool_observation','note':'Older references remain paged and actor-owned. Source and check authority come from current application state.'})
