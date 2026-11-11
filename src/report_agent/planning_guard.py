"""Persistent planning rejection containment on native middleware boundaries."""
from . import issue_state
from . import plan_inputs
from . import legacy_state as legacy
from . import plan_authority
from .commission_requirements import requirements_ref
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware, hook_config
from langgraph.types import interrupt

from .commission_plan import _state, _set
from .commission_planning import enabled
from .errors import ActionRejected
from .store import encode

TOOLS = frozenset({'set_requirement_status', 'link_convention', 'set_scope_boundary', 'set_planning_details',
    'add_object', 'add_section', 'add_substitution', 'add_reconciliation', 'add_question', 'submit_plan',
    'publish_planning_draft', 'save_commission_plan', 'request_commission_confirmation'})
KEY = 'commission_planning_rejections'


def fingerprint(workspace):
    with workspace.store.connect() as db:
        return [requirements_ref(db), plan_authority.plan_ref(db),
                plan_inputs.get_draft(db)]


def record_planning_result(workspace, role, tool_name, native_call_id, *, rejected, error_code=None, changed=False):
    if role != 'coordinator' or not enabled(workspace.store):
        return {'consecutive_rejections': 0, 'waiting': False}
    with workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = _state(db, KEY, {'consecutive_rejections': 0, 'waiting': False, 'seen': []})
        if tool_name not in TOOLS or native_call_id in state['seen']:
            return state
        if not isinstance(native_call_id, str) or not native_call_id.strip():
            raise ActionRejected('PLANNING_NATIVE_CALL_ID_REQUIRED')
        state['seen'].append(native_call_id)
        if not state['waiting']:
            if rejected:
                state['consecutive_rejections'] += 1
                state['last_error_code'] = error_code
            elif changed:
                state['consecutive_rejections'] = 0
            if state['consecutive_rejections'] >= 5:
                identity = str(uuid4())
                issue = {'id': identity, 'category': 'requirement', 'description':
                    'Planning paused after five consecutive rejected submissions. Review the preserved errors and explicitly resume this planning wait.',
                    'source_ids': [], 'resolved': False}
                issue_state.set_report_issues(db, [*issue_state.get_report_issues(db, []), issue])
                _set(db, 'report_status', 'waiting_for_human')
                _set(db, 'context_revision', _state(db, 'context_revision', 0) + 1)
                state.update(waiting=True, issue_id=identity)
                db.execute('INSERT INTO events(kind,data) VALUES (?,?)', ('planning_rejection_wait', encode({'issue_id': identity})))
        _set(db, KEY, state)
        return state


def require_resumed(workspace):
    state = workspace.store.get(KEY, {})
    if not state.get('waiting'):
        return
    issue_id = state['issue_id']
    path = workspace.store.root / 'outputs' / ('planning-resume-' + issue_id + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode({'issue_id': issue_id, 'consecutive_rejections': state['consecutive_rejections'],
        'reply_command': 'report-agent commission-reply --project CASE --issue-id ' + issue_id + ' --file DECISION.json',
        'decision_shape': {'decision': 'resume_planning', 'note': ''},
        'note': 'Review the preserved errors and explain the corrected action. This resumes planning only; it does not approve a report plan.'}) + '\n', encoding='utf-8')
    interrupt({'issue_id': issue_id, 'category': 'requirement', 'description':
               'Five planning submissions were rejected. An explicit operator planning resume is required.',
               'reply_template': str(path.relative_to(workspace.store.root))})
    # A raw LangGraph resume value is not an authorization record.
    if workspace.store.get(KEY, {}).get('waiting'):
        raise ActionRejected('PLANNING_OPERATOR_RESUME_REQUIRED')


def resume_planning(workspace, issue_id, decision):
    """Only called from the existing trusted operator reply command."""
    if set(decision) != {'decision', 'note'} or decision['decision'] != 'resume_planning' or not isinstance(decision['note'], str) or not decision['note'].strip():
        raise ActionRejected('PLANNING_RESUME_NOTE_REQUIRED')
    with workspace.store.run_lock(), workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = _state(db, KEY, {})
        issues = issue_state.get_report_issues(db, [])
        issue = next((i for i in issues if i['id'] == issue_id), None)
        answer = encode(decision)
        if not issue or state.get('issue_id') != issue_id:
            raise ActionRejected('PLANNING_RESUME_ISSUE_MISMATCH')
        if not state.get('waiting'):
            if issue.get('decision_origin') == 'operator' and issue.get('decision') == answer:
                return issue
            raise ActionRejected('PLANNING_WAIT_NOT_ACTIVE')
        # Commit the validated human answer before its runtime projection.
        db.commit()
        from .issue_authority import record_answer
        record_answer(workspace.store, issue, answer, True)
        db.execute('BEGIN IMMEDIATE')
        issue.update(decision=answer, decision_origin='operator', resolved=True)
        state.update(waiting=False, consecutive_rejections=0)
        _set(db, KEY, state)
        issue_state.set_report_issues(db, issues)
        _set(db, 'report_status', 'ready')
        _set(db, 'context_revision', _state(db, 'context_revision', 0) + 1)
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)', ('planning_operator_resume', encode({'issue_id': issue_id, 'note': decision['note']})))
        return issue


class PlanningGuard(AgentMiddleware):
    def __init__(self, workspace):
        self.workspace = workspace

    async def abefore_model(self, state, runtime):
        require_resumed(self.workspace)

    async def awrap_model_call(self, request, handler):
        require_resumed(self.workspace)
        return await handler(request)


    @hook_config(can_jump_to=['model'])
    async def aafter_model(self, state, runtime):
        from langchain_core.messages import AIMessage, HumanMessage
        from .content_store import ContentStore
        from .commission_plan import _confirmed
        from .commission_planning import read_draft_page
        from .text_work import actor_for_tool
        from .store import digest

        if not enabled(self.workspace.store):
            return None
        messages = state['messages']
        latest = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if latest is None or latest.tool_calls or latest.invalid_tool_calls:
            return None
        cs = ContentStore(self.workspace.store)
        try:
            with cs.store.connect() as db:
                _confirmed(cs, db)
            return None
        except ActionRejected as error:
            confirmation_error = str(error)
        # A final answer cannot discard an unapproved commission's resumable wait.
        identity = digest({'message_id': latest.id, 'content': latest.content, 'message_count': len(messages)})
        key = 'commission_planning_completion_wait'
        waiting = self.workspace.store.get(key, {})
        if waiting.get('message_id') != identity:
            try:
                view = read_draft_page(cs, actor_for_tool(self.workspace, 'coordinator'))
                gaps = {k: view[k] for k in ('gaps', 'gap_count', 'next_gap_page', 'view_ref', 'requirements_ref')}
            except ActionRejected as error:
                gaps = {'gaps': [{'path': 'planning', 'code': str(error).split(':')[0]}], 'gap_count': 1}
            description = ('Planning cannot finish before the owner checkpoint. Submit a complete plan, '
                'or ask a blocking question with pause=True. Provide guidance to continue planning; '
                'this wait does not approve a plan. Turn: ' + identity + '\n' + encode(gaps))
            issue = self.workspace.issue('requirement', description, [])
            waiting = {'message_id': identity, 'issue_id': issue['id'], 'gaps': gaps,
                       'confirmation_error': confirmation_error}
            self.workspace.store.set(key, waiting)
            self.workspace.store.event('planning_completion_refused', waiting)
        interrupt({'issue_id': waiting['issue_id'], 'category': 'requirement',
            'kind': 'planning_completion', 'description': 'Planning ended without a confirmed plan or a blocking pause. Owner guidance is required.',
            **waiting['gaps']})
        issue = next((i for i in issue_state.get_report_issues(self.workspace.store, []) if i['id'] == waiting['issue_id']), {})
        if issue.get('decision_origin') != 'operator' or not issue.get('decision', '').strip():
            raise ActionRejected('PLANNING_COMPLETION_OPERATOR_DECISION_REQUIRED')
        # Resume guidance is not a replacement for the original report goal.
        from .task_state_delivery import MODEL_COMMAND
        return {'messages': [HumanMessage(content='Operator guidance for planning wait ' + issue['id'] + ':\n' + issue['decision'],
            additional_kwargs={MODEL_COMMAND: True})],
                'jump_to': 'model'}
