"""Opt-in native repetition feedback/protection, not a semantic progress judge.

Observations stay in the existing actor-owned index. These small state/events
records hold only window references, feedback proof and host recovery controls.
"""
import json
from contextlib import contextmanager
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware

from .content_store import Actor, ContentStore
from .errors import ActionRejected, ActionForbidden
from .store import digest, encode

KIND = 'execution_progress_attention'
PREFIX = 'execution_progress:'
EPISODES = 'execution_progress_episode:'
SUPPORTED = frozenset({'read_tool_observation','read_content_index'})


def progress_signals(observations, *, window):
    """Compare public call observations; these signals never stop or replay work."""
    if type(window) is not int or window < 2:
        raise ValueError('PROGRESS_WINDOW_MUST_BE_AT_LEAST_TWO')
    fields = ('role', 'purpose', 'task_id', 'phase')
    groups = {}
    for row in observations:
        if not all(isinstance(row.get(k), str) and row[k] for k in fields):
            continue
        key = tuple(row[k] for k in fields)
        groups.setdefault(key, []).append(row)
    signals = []
    for key, records in groups.items():
        recent = records[-window:]
        if len(recent) != window:
            continue
        kinds = []
        tokens = [r.get('tokens') for r in recent]
        if (all(type(n) is int and n >= 0 for n in tokens)
                and all(a < b for a, b in zip(tokens, tokens[1:]))):
            kinds.append('increasing_tokens')
        rejections = [r.get('rejection_signature') for r in recent]
        if all(isinstance(s, str) and s and s == rejections[0] for s in rejections):
            kinds.append('repeated_rejection')
        saved = [r.get('saved_record_refs') for r in recent]
        if all(isinstance(refs, list) for refs in saved):
            seen = {digest(ref) for ref in saved[0]}
            if all(digest(ref) in seen for refs in saved[1:] for ref in refs):
                kinds.append('no_new_saved_records')
        signals.extend({'kind': kind, **dict(zip(fields, key)), 'window': window} for kind in kinds)
    return signals


def validate_policy(workspace):
    value = workspace.store.manifest.get('execution_progress_policy')
    if value is None: return None
    if (not isinstance(value,dict) or set(value)!={'version','window','repeats','after_notice'}
            or any(type(value[k]) is not int for k in value)
            or value['version']!=1 or not 2<=value['repeats']<=value['window']<=256
            or not 1<=value['after_notice']<=8):
        raise ActionRejected('PROGRESS_POLICY_INVALID')
    from .task_context import progress_enabled
    if not progress_enabled(workspace):
        raise ActionRejected('PROGRESS_POLICY_REQUIRES_STATEFUL_V2')
    return dict(value)


def active_episodes(workspace):
    with workspace.store.connect() as db:
        rows=db.execute('SELECT value FROM state WHERE key LIKE ?', (EPISODES+'%',)).fetchall()
    return [v for v in (json.loads(row[0]) for row in rows)
        if v['state'] in {'observing','degraded','recovery_observe','observation_limit'}]


def protected(workspace):
    return [e for e in active_episodes(workspace) if e['state'] in {'degraded','observation_limit'}]


def _scope(workspace, role):
    from .content_tasks import bound_actor, current_invocation
    from .hierarchical_tools import actor_for
    actor=bound_actor(workspace,role,actor_for(role))
    result={**actor.__dict__,'actor_id':actor.id}
    if role in {'writer','reviewer','layout'}:
        result['invocation']=current_invocation(workspace,actor)
        # Dynamic caller wording/IDs do not erase an immutable task's history.
        result['invocation']={k:result['invocation'][k] for k in ('delegate_operation_id','description_sha256')}
    return result


@contextmanager
def _host_actor(workspace, scope):
    """Read-only host verification under the exact persisted task permissions."""
    from .content_tasks import _binding
    actor=Actor(scope['id'],scope['role'],scope['task_id'])
    if actor.role=='coordinator':
        yield actor; return
    task=ContentStore(workspace.store).read({'type':'DelegatedTask','id':actor.task_id,'version':1})
    if task['payload']['role']!=actor.role or actor.id!='content:'+actor.role+':'+actor.task_id:
        raise ActionRejected('PROGRESS_RECOVERY_TASK_CHANGED')
    token=_binding.set((str(workspace.store.root.resolve()),actor,scope.get('invocation',{})))
    try: yield actor
    finally: _binding.reset(token)


def _instructions(workspace, scope):
    from .prompt_instructions import instruction_context
    return instruction_context(workspace.store,scope['role'],task_id=scope['task_id'])


def _ledger():
    from .token_budget import _active
    budget=_active.get()
    return ({'path':str(budget.path.resolve()),'maximum':budget.maximum,'bounds':budget.model_bounds,
        'observation':budget.snapshot()} if budget is not None else None)


def _response(workspace, row, role):
    with workspace.store.connect() as db:
        rows=db.execute("SELECT s.value FROM events e JOIN state s ON s.key=json_extract(e.data,'$.capture_key') "
            "WHERE e.kind='prompt_response_fact' AND json_extract(e.data,'$.purpose')=? "
            "AND json_extract(s.value,'$.ai_message_id')=? ORDER BY e.sequence DESC LIMIT 8",
            (role,row['decision_id'])).fetchall()
    for raw, in rows:
        fact=json.loads(raw)
        if row['call_id'] in fact['tool_call_ids'] and fact['completed']:
            return fact
    return None


def _navigation(workspace, scope, snapshot_ref):
    cs=ContentStore(workspace.store)
    snap=cs.read(snapshot_ref)
    if snap['ref']['type']!='DocumentSnapshot':return None
    criteria=snap['payload']['criteria_refs']
    if scope['role']!='coordinator':
        from .task_supervision import assignment
        task=assignment(cs,scope['task_id'])
        if task.get('review_snapshot_ref')!=snapshot_ref:return None
        assigned={encode(r['criterion_ref']) for r in task.get('review_requirements',[])}
        criteria=[r for r in criteria if encode(r) in assigned]
    if not criteria:return None
    instructions=_instructions(workspace,scope)
    from .source_use import resolve_source_use_binding
    with _host_actor(workspace,scope) as actor:
        source_binding=resolve_source_use_binding(workspace,actor)
    return {'scope_kind':'requested_snapshot_scope' if scope['role']=='coordinator' else 'saved_assignment_scope',
        'snapshot_ref':snapshot_ref,'root_ref':snap['payload']['root_ref'],'criterion_refs':criteria,
        'goal_digest':digest(workspace.store.manifest['goal']),
        'instruction_digest':instructions['digest'] if instructions else None,
        'source_use_ref':source_binding}


def _eligible(workspace, scope, row):
    if (row['tool'] not in SUPPORTED or not row.get('decision_id') or not row.get('decision_valid')
            or row.get('decision_finish_reason') not in {'stop','tool_calls'}):return None
    args=row['selection']; binding=None
    if row['tool']=='read_content_index' and row['status']=='success':
        page=row.get('navigation_page')
        if page is None:return None
        binding=_navigation(workspace,scope,page['snapshot_ref'])
        comparison={'navigation_page':page}  # Already exact producer/receipt-verified.
    elif row['tool']=='read_tool_observation' and row['status']=='success':
        from .task_context import read_observation
        page=read_observation(workspace,scope['role'],args['observation_ref'],args.get('offset',0),
            args.get('characters',6000),args.get('field_path'))
        comparison={k:page.get(k) for k in ('observation_ref','sha256','offset','end','field_path','field_sha256','text')}
        saved=workspace.store.get('tool_observation:'+args['observation_ref'])
        if saved and saved['tool']=='read_content_index':
            original=json.loads(saved['text'])
            candidate=original.get('result',{}).get('snapshot_structure') if scope['role']=='reviewer' else original
            if isinstance(candidate,dict) and candidate.get('snapshot_ref'):
                from .content_selection import content_index
                expected=content_index(ContentStore(workspace.store),candidate['snapshot_ref'],candidate['offset'],
                    max(1,len(candidate['returned_refs'])))
                # Continuation depends on requested limit; compare the returned
                # immutable nodes, not guessed text/target names.
                if all(candidate.get(k)==expected.get(k) for k in ('nodes','returned_refs','manifest_digest','root_ref')):
                    binding=_navigation(workspace,scope,candidate['snapshot_ref'])
    elif row['status']=='error':
        # Reproduce only these readonly deterministic validations. Arbitrary
        # error strings, provider text and failed writes are never signatures.
        try:
            if row['tool']=='read_tool_observation':
                from .task_context import read_observation
                read_observation(workspace,scope['role'],args['observation_ref'],args.get('offset',0),
                    args.get('characters',6000),args.get('field_path'))
            else:
                from .content_selection import content_index
                content_index(ContentStore(workspace.store),args['snapshot_ref'],args.get('offset',0),args.get('limit',20))
        except ActionRejected as exc:
            code=str(exc).partition(':')[0]
            original=json.loads(workspace.store.get('tool_observation:'+row['observation_ref'])['text'])
            if original.get('code')!=code:return None
            comparison={'deterministic_rejection':code}
        else:return None
    else:return None
    pattern=digest({'tool':row['tool'],'arguments':args,'comparison':comparison})
    return {'index':row['index'],'decision_id':row['decision_id'],'call_id':row['call_id'],
        'pattern':pattern,'signature':digest([pattern,binding]),'binding':binding,
        'binding_digest':digest(binding),'observation_ref':row['observation_ref'],'sha256':row['sha256'],
        'tool':row['tool'],'arguments_digest':digest(args)}


class ExecutionProgress(AgentMiddleware):
    def __init__(self,workspace,role):
        self.workspace,self.role,self.policy=workspace,role,validate_policy(workspace)

    def control(self):
        scope=_scope(self.workspace,self.role); key=PREFIX+digest([scope['actor_id'],scope['task_id']])
        value=self.workspace.store.get(key)
        if value is None:value={'scope':scope,'policy':self.policy,'cursor':0,'window':[],'episode_id':None}
        if value['policy']!=self.policy:raise ActionRejected('PROGRESS_POLICY_CHANGED_DURING_EPISODE')
        return key,value

    def save(self,key,value,episode=None):
        with self.workspace.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',(key,encode(value)))
            if episode is not None:db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',(EPISODES+episode['episode_id'],encode(episode)))

    def reconcile(self):
        from .summary_recovery import key as index_key
        key,control=self.control(); scope=control['scope']
        records=self.workspace.store.get(index_key(self.workspace,self.role),[])
        episode=self.workspace.store.get(EPISODES+control['episode_id']) if control['episode_id'] else None
        groups={}
        for i,row in enumerate(records[control['cursor']:],control['cursor']):
            try:item=_eligible(self.workspace,scope,{**row,'index':i})
            except (ActionForbidden,ActionRejected,KeyError,TypeError,ValueError) as exc:
                # Only the read-only observation replay is optional. Policy,
                # current actor admission and durable guard persistence remain
                # outside this narrow diagnostic boundary.
                item=None
                from .transport_observation import observe_safely
                observe_safely(lambda:self.workspace.store.event('execution_progress_observation_gap',{
                    'index':i,'actor_id':scope['actor_id'],'exception_type':type(exc).__name__}))
            # Unknown/other actual returns cannot establish continued repetition
            # of the warned family. Preserve them as a break, not as progress.
            groups.setdefault(row.get('decision_id') or 'unpaired:'+str(i),[]).append((row,item))
        for decision_id,pairs in groups.items():
            known={r['signature'] for r in control['window']}
            items=[p[1] for p in pairs if p[1] is not None]
            novel=len(items)!=len(pairs) or any(r['signature'] not in known for r in items)
            control['window']=[*control['window'],*items][-self.policy['window']:]
            if episode and episode['state']=='observing' and any(
                    r['binding_digest']!=episode['binding_digest'] for r in items):
                # An unprotected episode must not pin future observation to an
                # old scope forever. Keep its evidence; the new scope gets its
                # own candidate and delivered-feedback sequence.
                episode.update(state='binding_changed',outcome='changed_binding_not_semantic_progress')
                self.workspace.store.set(EPISODES+episode['episode_id'],episode)
                self.workspace.store.event('execution_progress_binding_changed',{
                    'episode_id':episode['episode_id'],'semantic_progress_verified':False})
                episode=None;control['episode_id']=None
            if episode and episode['state'] in {'observing','recovery_observe'}:
                facts=[_response(self.workspace,row,self.role) for row,_ in pairs]
                fact=next((f for f in facts if f),None)
                proof=next((n for n in (fact or {}).get('notices',[]) if n['episode_id']==episode['episode_id']),None)
                if proof and fact['call_id'] not in {p['call_id'] for p in episode['notice_deliveries']}:
                    episode['notice_deliveries']=[*episode['notice_deliveries'],{'call_id':fact['call_id'],**proof}][-16:]
                    episode['warned_family']=proof['family']
                    if not novel and all(r['signature'] in proof['family'] for r in items):
                        episode['post_count']+=1
                    else:
                        episode['post_count']=0
                        self.workspace.store.event('execution_progress_new_return',{'episode_id':episode['episode_id'],'decision_id':decision_id,'semantic_progress':False})
                elif novel:episode['post_count']=0
            if not episode or episode['state']=='observation_completed':
                counts={}
                for r in control['window']:counts.setdefault(r['signature'],set()).add(r['decision_id'])
                repeated={s for s,v in counts.items() if len(v)>=self.policy['repeats']}
                candidate=next((r for r in reversed(items) if r['signature'] in repeated),None)
                if candidate:
                    family=[r for r in control['window'] if r['signature'] in repeated and r['binding_digest']==candidate['binding_digest']]
                    instructions=_instructions(self.workspace,scope)
                    episode={'episode_id':str(uuid4()),'state':'observing','scope':scope,'binding':candidate['binding'],
                        'binding_digest':candidate['binding_digest'],'family':sorted({r['signature'] for r in family}),
                        'patterns':sorted({r['pattern'] for r in family}),'warned_family':[], 'post_count':0,
                        'observed_refs':[{k:r[k] for k in ('index','observation_ref','sha256','tool','call_id')} for r in family[-6:]],
                        'notice_deliveries':[],'policy':self.policy,'policy_digest':digest(self.policy),
                        'initial_effective_refs':[r['ref'] for r in (instructions or {}).get('effective',[])],
                        'ledger':_ledger(),'outcome':'suspected_repetition_not_semantic_failure'}
                    control['episode_id']=episode['episode_id']
                    self.workspace.store.event('execution_progress_observed',episode)
            elif episode and episode['state'] in {'observing','recovery_observe'}:
                counts={}
                for r in control['window']:
                    counts.setdefault(r['signature'],set()).add(r['decision_id'])
                if episode['state']=='recovery_observe' and not episode['family']:
                    candidate=next((r for r in reversed(items) if len(counts[r['signature']])>=self.policy['repeats']),None)
                    if candidate:
                        episode['binding']=candidate['binding'];episode['binding_digest']=candidate['binding_digest']
                episode['family']=sorted(s for s,v in counts.items() if len(v)>=self.policy['repeats'])
                episode['family']=[s for s in episode['family'] if any(
                    r['signature']==s and r['binding_digest']==episode['binding_digest'] for r in control['window'])]
                episode['patterns']=sorted({r['pattern'] for r in control['window'] if r['signature'] in episode['family']})
        control['cursor']=len(records)
        if groups:self.save(key,control,episode)
        return key,control,episode

    async def abefore_model(self,state,runtime):
        key,control,episode=self.reconcile()
        if episode and episode['binding'] and episode['post_count']>=self.policy['after_notice'] and episode['state'] in {'observing','recovery_observe'}:
            episode['state']='degraded'; episode['outcome']='suspected_repetition_pause_not_semantic_failure'
            episode['received_index_count']=control['cursor']
            episode['ledger']=_ledger(); self.save(key,control,episode)
            self.workspace.store.event('execution_progress_degraded',episode)
            _learning_observation(self.workspace,episode)
        if episode and episode['state'] in {'degraded','observation_limit'}:
            event={'kind':KIND,'episode_id':episode['episode_id'],'actor_id':episode['scope']['actor_id'],
                'automatic_resume':False,'reason':'SUSPECTED_REPETITION_DIAGNOSIS_REQUIRED'}
            from .native_admission import wait_for_exact_resume
            wait_for_exact_resume(event,lambda e:resume_answer(self.workspace,e))
            consume_recovery(self.workspace,episode['episode_id'])
        return None

    async def awrap_model_call(self,request,handler):
        key,control=self.control()
        episode=self.workspace.store.get(EPISODES+control['episode_id']) if control['episode_id'] else None
        if episode and episode['state'] in {'observing','recovery_observe'} and episode['family']:
            from .prompt_provenance import append_declared_system
            source='execution-progress-bound-notice' if episode['binding'] else 'execution-progress-unbound-notice'
            family=episode['family'][:8]
            notice_id=digest([episode['episode_id'],family,source])
            binding=episode['binding']
            compact_binding=({**{k:binding[k] for k in ('scope_kind','snapshot_ref','root_ref','instruction_digest','source_use_ref')},
                'criterion_refs_preview':binding['criterion_refs'][:3],
                'criterion_count':len(binding['criterion_refs']),
                'partial':len(binding['criterion_refs'])>3,'binding_digest':episode['binding_digest']}
                if binding else {'scope_kind':'unbound_advisory'})
            packet={'episode_id':episode['episode_id'],'notice_id':notice_id,'role':self.role,
                'actor_id':episode['scope']['actor_id'],'task_id':episode['scope']['task_id'],
                'binding':compact_binding,
                'family':family,'family_partial':len(episode['family'])>len(family),
                'observed':episode['observed_refs'][-3:],
                'policy':self.policy,
                'recovery':{'binding':({'tool':'read_review_obligation_coverage','arguments':{'snapshot_ref':binding['snapshot_ref']}}
                    if self.role=='coordinator' and binding else {'tool':'read_task_assignment','arguments':{}}
                    if binding else None),
                    'observations':{'tool':'read_summary_observations','arguments':{
                        'offset':min(r['index'] for r in episode['observed_refs']) if episode['observed_refs'] else 0,'limit':3}}},
                'limits':'Mechanical identities only; not correctness, relevance, reading or semantic progress.'}
            if len(encode(packet))>4096:
                packet['observed']=[]
                packet['binding']={'scope_kind':compact_binding['scope_kind'],
                    'binding_digest':episode['binding_digest'],'partial':True,
                    **({'snapshot_ref':binding['snapshot_ref']} if binding else {})}
            request=append_declared_system(request,encode(packet),'execution_progress/repetition',
                references={'episode_id':episode['episode_id'],'notice_id':notice_id,'family':family})
        if episode and episode['state']=='recovery_observe':
            from .prompt_provenance import append_declared_system
            request=append_declared_system(request,encode({'origin':'host_verified_changed_condition_not_semantic_repair',
                'execution_progress_recovery':episode.get('recovery')}),'execution_progress/recovery_condition',
                references={'episode_id':episode['episode_id'],'condition_digest':digest(episode['recovery'])})
        response=await handler(request)
        if episode and episode['state']=='recovery_observe':
            # A final response has no subsequent tool return to reconcile.
            # Require the same actual SDK/complete-response receipt nonetheless.
            messages=getattr(response,'result',[])
            if len(messages)==1 and not getattr(messages[0],'tool_calls',None):
                with self.workspace.store.connect() as db:
                    facts=db.execute("SELECT s.value FROM events e JOIN state s ON s.key=json_extract(e.data,'$.capture_key') "
                        "WHERE e.kind='prompt_response_fact' AND json_extract(s.value,'$.ai_message_id')=? "
                        "AND json_extract(s.value,'$.purpose')=? AND json_extract(s.value,'$.completed')=1",
                        (getattr(messages[0],'id',None),self.role)).fetchall()
                found=any(c.get('episode_id')==episode['episode_id'] and c.get('condition_digest')==digest(episode['recovery'])
                    for row in facts for c in json.loads(row[0]).get('recovery_conditions',[]))
                if found:
                    episode['state']='observation_completed'
                    episode['outcome']='completed_response_observed_not_semantic_repair'
                    self.save(key,control,episode)
                    self.workspace.store.event('execution_progress_recovery_observed',{
                        'episode_id':episode['episode_id'],'outcome':episode['outcome'],'semantic_progress_verified':False})
                    _learning_observation(self.workspace,episode)
        return response


def _condition(workspace,episode,condition):
    if not isinstance(condition,dict):raise ActionRejected('PROGRESS_RECOVERY_CONDITION_REQUIRED')
    if condition.get('kind')=='effective_instruction':
        context=_instructions(workspace,episode['scope'])
        ref=condition.get('ref')
        if (not context or ref in episode['initial_effective_refs']
                or ref not in [r['ref'] for r in context['effective']]):
            raise ActionRejected('PROGRESS_RECOVERY_INSTRUCTION_NOT_NEW_EFFECTIVE')
        return {'kind':'effective_instruction','ref':ref,'context_digest':context['digest']}
    if condition.get('kind')=='authorized_material':
        cs=ContentStore(workspace.store); obj=cs.read(condition['ref'])
        binding=episode['binding'] or {}
        if obj['ref']['type']!='SourceArtifact' or condition.get('target_ref')!=binding.get('root_ref'):
            raise ActionRejected('PROGRESS_RECOVERY_MATERIAL_RELATION_REQUIRED')
        from .source_use import validate_source_versions
        with _host_actor(workspace,episode['scope']) as actor:
            authorized=validate_source_versions(workspace,actor,source_refs=[obj['ref']])
        if authorized is None:raise ActionRejected('PROGRESS_RECOVERY_MATERIAL_NOT_AUTHORIZED')
        members=cs.read(binding['snapshot_ref'])['payload']['refs']
        previous=[cs.read(r) for r in members if r['type']=='SourceArtifact']
        # Renaming/re-importing identical file bytes changes source metadata and
        # payload identity, but does not create a new recovery condition.
        if any(obj['payload_digest']==old['payload_digest'] or
                obj['payload']['file_digest']==old['payload']['file_digest'] for old in previous):
            raise ActionRejected('PROGRESS_RECOVERY_UNCHANGED_MATERIAL')
        # Only existing actor-owned, origin-issued return receipts count as
        # already received outside the snapshot. Catalog enrollment, arbitrary
        # prose and another actor's observations are not evidence of reception.
        from .summary_recovery import key as index_key
        from .source_materials import owned_materials
        with _host_actor(workspace,episode['scope']) as actor:
            records=workspace.store.get(index_key(workspace,actor.role),[])
            for row in records[:episode.get('received_index_count',len(records))]:
                if row['status']!='success' or row.get('receiving_actor')!=actor.id:continue
                saved=workspace.store.get('tool_observation:'+row['observation_ref'])
                if not saved or saved['sha256']!=row['sha256']:continue
                materials=owned_materials(workspace,actor,row['observation_ref'],saved['text'],saved['tool']) or []
                if any(m['file_digest']==obj['payload']['file_digest'] for m in materials):
                    raise ActionRejected('PROGRESS_RECOVERY_UNCHANGED_MATERIAL')
        return {'kind':'authorized_material','ref':obj['ref'],'payload_digest':obj['payload_digest'],
            'target_ref':condition['target_ref'],'source_use_ref':authorized}
    raise ActionRejected('PROGRESS_RECOVERY_CONDITION_UNSUPPORTED')


def _resources(episode,maximum):
    from .request_budget import current_budget_observation
    current=_ledger(); original=episode.get('ledger'); request=current_budget_observation()
    if (not original or not current or any(current[k]!=original[k] for k in ('path','maximum','bounds'))
            or current['observation']['remaining_for_new_reservations']<max(current['bounds'].values())
            or not request or request.get('remaining_http_attempts',0)<1 or type(maximum) is not int or maximum<1):
        raise ActionRejected('PROGRESS_RECOVERY_RESOURCES_OR_LEDGER_REQUIRED')


def authorize_recovery(workspace,episode_id,condition,*,authorization_basis,reason,max_http_attempts):
    """Trusted host only; record one bounded observation, never dispatch a model."""
    episode=workspace.store.get(EPISODES+episode_id)
    if (not episode or episode['state'] not in {'degraded','observation_limit'}
            or not authorization_basis.strip() or not reason.strip()):
        raise ActionRejected('PROGRESS_RECOVERY_EXACT_HOST_AUTHORIZATION_REQUIRED')
    verified=_condition(workspace,episode,condition); _resources(episode,max_http_attempts)
    key='execution_progress_recovery:'+digest([episode_id,verified])
    value={'episode_id':episode_id,'condition':verified,'state':'authorized','used':0,
        'maximum_http_attempts':max_http_attempts,'authorization_basis':authorization_basis,'reason':reason}
    with workspace.store.run_lock(),workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM state WHERE key=?',(key,)).fetchone():raise ActionRejected('PROGRESS_RECOVERY_CONDITION_ALREADY_USED')
        # Re-read under the writer lock; a different condition cannot overwrite
        # an already active grant or race a resumed native task.
        episode=json.loads(db.execute('SELECT value FROM state WHERE key=?',(EPISODES+episode_id,)).fetchone()[0])
        previous=db.execute('SELECT value FROM state WHERE key=?',(episode.get('recovery_key',''),)).fetchone()
        if (episode['state'] not in {'degraded','observation_limit'} or
                previous and json.loads(previous[0])['state']=='authorized'):
            raise ActionRejected('PROGRESS_RECOVERY_ACTIVE_GRANT')
        db.execute('INSERT INTO state VALUES (?,?)',(key,encode(value)))
        episode['recovery_key']=key
        db.execute('UPDATE state SET value=? WHERE key=?',(encode(episode),EPISODES+episode_id))
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)',('execution_progress_recovery_authorized',encode(value)))
    return {'key':key,**value}


def resume_answer(workspace,event):
    if not isinstance(event,dict) or event.get('kind')!=KIND:return None
    episode=workspace.store.get(EPISODES+event['episode_id'])
    grant=workspace.store.get(episode.get('recovery_key','')) if episode else None
    if not grant or grant['state']!='authorized':return None
    try:
        if _condition(workspace,episode,grant['condition'])!=grant['condition']:return None
        _resources(episode,grant['maximum_http_attempts'])
    except (ActionRejected,KeyError):return None
    return {'kind':KIND,'episode_id':episode['episode_id'],'condition_digest':digest(grant['condition'])}


def consume_recovery(workspace,episode_id):
    with workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        episode=json.loads(db.execute('SELECT value FROM state WHERE key=?',(EPISODES+episode_id,)).fetchone()[0])
        grant=json.loads(db.execute('SELECT value FROM state WHERE key=?',(episode['recovery_key'],)).fetchone()[0])
        if grant['state']!='authorized':raise ActionRejected('PROGRESS_RECOVERY_ALREADY_CONSUMED')
        grant['state']='consumed'; episode.update(state='recovery_observe',post_count=0,recovery=grant['condition'],resume_boundary=None)
        # Retain the original raw index/events and episode evidence, while the
        # changed condition starts a fresh bounded repetition observation.
        episode.update(family=[],warned_family=[],
            origin_notice_deliveries=[*episode.get('origin_notice_deliveries',[]),*episode['notice_deliveries']][-16:],
            notice_deliveries=[])
        control_key=PREFIX+digest([episode['scope']['actor_id'],episode['scope']['task_id']])
        control_row=db.execute('SELECT value FROM state WHERE key=?',(control_key,)).fetchone()
        control=json.loads(control_row[0]);control['window']=[]
        db.execute('UPDATE state SET value=? WHERE key=?',(encode(control),control_key))
        db.execute('UPDATE state SET value=? WHERE key=?',(encode(grant),episode['recovery_key']))
        db.execute('UPDATE state SET value=? WHERE key=?',(encode(episode),EPISODES+episode_id))
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)',('execution_progress_recovery_consumed',encode(grant)))


def reserve_recovery_request(workspace,key):
    """Additional durable reservation cap for one host-authorized observation.

    This is a conservative reservation count, not proof of a provider send.
    Exceptions stay typed local refusals at the existing request admission hook.
    """
    from .request_budget import RequestBudgetExceeded
    try:
        with workspace.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
            grant=json.loads(row[0]) if row else None
            if (not grant or grant['state']!='consumed' or type(grant['used']) is not int
                    or type(grant['maximum_http_attempts']) is not int
                    or not 0<=grant['used']<grant['maximum_http_attempts']):
                raise RequestBudgetExceeded('RECOVERY_OBSERVATION_HTTP_LIMIT')
            grant['used']+=1
            db.execute('UPDATE state SET value=? WHERE key=?',(encode(grant),key))
    except RequestBudgetExceeded as exc:
        exc.execution_progress_recovery_key=key
        raise
    except Exception as exc:
        error=RequestBudgetExceeded('RECOVERY_RESERVATION_PERSISTENCE_FAILED')
        error.execution_progress_recovery_key=key
        raise error from exc


def _zero_send_model(workspace,call_key,proof=None):
    from .model_recovery import PREFIX as MODEL_PREFIX
    if not isinstance(call_key,str) or not call_key.startswith(MODEL_PREFIX):return None
    call=workspace.store.get(call_key)
    if (not call or call.get('role')!='coordinator' or call.get('active') is not False
            or call.get('invocation_owner')!={'case_root':str(workspace.store.root),'actor':'coordinator'}
            or call.get('state')!='local_admission_blocked' or call.get('provider_outcome')!='not_dispatched'):
        return None
    actual=call.get('admission_proof') or {}
    if (actual.get('provider_outcome')!='not_dispatched' or actual.get('admitted_http_attempts')!=0
            or not actual.get('refused_before_send') or proof is not None and actual!=proof):return None
    return actual


def mark_observation_limit(workspace,keys,error=None):
    for key in keys:
        grant=workspace.store.get(key)
        if not grant:continue
        episode=workspace.store.get(EPISODES+grant['episode_id'])
        if episode:
            from .deep_models import error_data
            own_cap = getattr(error, 'execution_progress_recovery_key', None) == key
            code = str(error) if own_cap and str(error) in {
                'RECOVERY_OBSERVATION_HTTP_LIMIT', 'RECOVERY_RESERVATION_PERSISTENCE_FAILED'} else error_data(error)['message']
            origin = 'own_recovery_cap' if own_cap else 'outer_admission'
            episode.update(state='observation_limit',outcome='bounded_observation_stopped_not_semantic_repair',resume_boundary=None)
            episode.update(stop_origin=origin, stop_reason_code=code)
            call_key=getattr(error,'report_local_admission_key',None)
            proof=_zero_send_model(workspace,call_key)
            if (proof and episode['scope']['role']=='coordinator'
                    and getattr(error,'execution_progress_recovery_key',None)==key
                    and getattr(error,'execution_progress_pending_nodes',None)==['model']):
                episode['resume_boundary']={'kind':'root_model_zero_send','node':'model','model_call_key':call_key,
                    'recovery_key':key,'proof':proof,'scope':episode['scope']}
            workspace.store.set(EPISODES+episode['episode_id'],episode)
            workspace.store.event('execution_progress_observation_limit',{
                'episode_id':episode['episode_id'],'used':grant['used'],'semantic_progress_verified':False,
                'stop_origin':origin,'reason_code':code})
            _learning_observation(workspace,episode)


def limited_model_resume_keys(workspace,snapshot):
    """Read-only exact host gate; unsupported checkpoints stay paused.

    A native model-node checkpoint and durable whole-logical zero-send receipt
    are both required. A sent/unknown attempt, tool/summary node, stale scope or
    a missing proof never becomes a new dispatch permission.
    """
    if tuple(snapshot.next)!=('model',):return None
    episodes=protected(workspace)
    if not episodes or any(e['state']!='observation_limit' for e in episodes):return None
    keys=[]
    for episode in episodes:
        boundary=episode.get('resume_boundary') or {}
        if (boundary.get('kind')!='root_model_zero_send' or boundary.get('node')!='model'
                or boundary.get('scope')!=episode['scope']
                or not _zero_send_model(workspace,boundary.get('model_call_key'),boundary.get('proof'))
                or boundary.get('recovery_key')==episode.get('recovery_key')
                or resume_answer(workspace,{'kind':KIND,'episode_id':episode['episode_id']}) is None):
            return None
        old=workspace.store.get(boundary['recovery_key'])
        if not old or old['state']!='consumed' or old['episode_id']!=episode['episode_id']:return None
        keys.append(episode['recovery_key'])
    return keys


def _learning_observation(workspace,episode):
    from .learning import binding
    configured=binding(workspace)
    if configured:
        try: configured[0].runtime_observation(configured[1],episode)
        except Exception as exc:
            workspace.store.event('execution_progress_learning_gap',{'episode_id':episode['episode_id'],'exception_type':type(exc).__name__})
