"""Persistent planning rejection containment on native middleware boundaries."""
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware
from langgraph.types import interrupt

from .commission_plan import _state, _set
from .commission_planning import enabled
from .errors import ActionRejected
from .store import encode

TOOLS = frozenset({'set_requirement_status', 'link_convention', 'set_scope_boundary', 'set_planning_details',
    'add_object', 'add_section', 'add_substitution', 'add_reconciliation', 'add_question', 'submit_plan',
    'save_commission_plan', 'request_commission_confirmation'})
KEY = 'commission_planning_rejections'


def fingerprint(workspace):
    with workspace.store.connect() as db:
        return [_state(db, key) for key in ('commission_requirements', 'commission_plan', 'commission_planning_draft')]


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
                _set(db, 'report_issues', [*_state(db, 'report_issues', []), issue])
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
        issues = _state(db, 'report_issues', [])
        issue = next((i for i in issues if i['id'] == issue_id), None)
        answer = encode(decision)
        if not issue or state.get('issue_id') != issue_id:
            raise ActionRejected('PLANNING_RESUME_ISSUE_MISMATCH')
        if not state.get('waiting'):
            if issue.get('decision_origin') == 'operator' and issue.get('decision') == answer:
                return issue
            raise ActionRejected('PLANNING_WAIT_NOT_ACTIVE')
        issue.update(decision=answer, decision_origin='operator', resolved=True)
        state.update(waiting=False, consecutive_rejections=0)
        _set(db, KEY, state)
        _set(db, 'report_issues', issues)
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
