"""Paged actor-owned recovery of public returns selected for native compaction."""
import json
from typing import Annotated
from pydantic import Field, ValidationError
from langchain_core.messages import AIMessage, ToolMessage
from .errors import ActionRejected
from .observation_refs import ObservationRefPrefix, validate_prefix
from .store import encode
from .task_context import actor_id, read_observation, save_observation

def key(workspace, role):
    return 'summary_observation_index:'+actor_id(workspace,role)

def capture(workspace, role, messages):
    calls={c['id']:c for m in messages if isinstance(m,AIMessage) for c in m.tool_calls}
    records=list(workspace.store.get(key(workspace,role),[]))
    seen={(r['call_id'],r['observation_ref']) for r in records}
    for message in messages:
        if not isinstance(message,ToolMessage) or not isinstance(message.content,str):continue
        call=calls.get(message.tool_call_id)
        if not call:continue
        old_ref=message.additional_kwargs.get('report_observation_ref')
        if old_ref:
            observed=read_observation(workspace,role,old_ref,0,1)
            ref=old_ref
        else:
            actual=message.model_copy(update={'name':message.name or call['name']})
            ref,saved=save_observation(workspace,role,actual)
            observed={'sha256':saved['sha256'],'total_characters':len(saved['text'])}
        identity=(message.tool_call_id,ref)
        if identity in seen:continue
        selection={k:v for k,v in call['args'].items() if k in {
            'source_id','query','page','crop','offset','limit','characters','field_path','target_ref','export_ref','render_ref','observation_ref','source_selections','observation_refs'}}
        delivery = {'preview_cleared':bool(message.additional_kwargs.get('report_preview_cleared')),
            'current_message_characters':len(message.content),
            'original_delivery':message.additional_kwargs.get('report_observation_delivery'),
            'note':'Provided text ranges do not prove reading or adoption.'}
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
        records.append({'call_id':message.tool_call_id,'tool':call['name'],
          'observation_ref':ref,'sha256':observed['sha256'],
          'recoverable_characters':observed['total_characters'],'selection':selection,
          'delivery':delivery,
          'status':message.status,'receiving_actor':actor_id(workspace,role),
          'provided_preview':bool(old_ref),
          'note':'Recorded public return/recovery, not complete reading, source coverage, adoption or acceptance.'})
        seen.add(identity)
    if len(records)>4096:raise ActionRejected('SUMMARY_RECOVERY_INDEX_LIMIT: original history retained')
    workspace.store.set(key(workspace,role),records)
    workspace.store.event('summary_recovery_captured',{'actor_id':actor_id(workspace,role),'total':len(records)})
    return records

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
