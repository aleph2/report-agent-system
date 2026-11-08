"""Persistent export-failure wait for the system-assembled delivery contract."""
from . import legacy_state as legacy
import re
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware
from langgraph.types import interrupt

from .commission_plan import _state, _set
from .errors import ActionRejected
from .handoff_release import manifest
from .store import encode

TOOLS = frozenset({'export_content_snapshot', 'request_system_delivery'})
KEY = 'delivery_export_rejections'


def enabled(store):
    return manifest(store).get('assembly_contract') == 'system-assembler-v1'


def record_export_result(workspace, role, tool_name, native_call_id, *, rejected,
                         error_code=None, changed=False, actor_id=None):
    """Count native attempts once; only a new successful export resets the streak."""
    if not enabled(workspace.store):
        return {'consecutive_rejections': 0, 'waiting': False}
    if tool_name not in TOOLS:
        return workspace.store.get(KEY, {'consecutive_rejections': 0, 'waiting': False})
    if not isinstance(native_call_id, str) or not native_call_id.strip():
        raise ActionRejected('DELIVERY_NATIVE_CALL_ID_REQUIRED')
    if actor_id is None:
        from .content_tasks import model_owner_identity
        identity = model_owner_identity(workspace.store)
        actor_id = identity['actor']['id'] if identity else 'content:' + role
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise ActionRejected('DELIVERY_ACTOR_ID_REQUIRED')
    call_key = [actor_id, native_call_id]
    with workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = _state(db, KEY, {'consecutive_rejections': 0, 'waiting': False, 'seen': [], 'failures': []})
        if call_key in state['seen']:
            return state
        state['seen'].append(call_key)
        if rejected:
            # Store identifiers only, never raw error messages containing report sources.
            code = error_code.split(':', 1)[0] if isinstance(error_code, str) else ''
            code = code if re.fullmatch(r'[A-Z][A-Z0-9_]{0,119}', code) else 'EXPORT_REJECTED'
            state['failures'].append({'actor_id': actor_id, 'role': role,
                'native_call_id': native_call_id, 'error_code': code})
        if not state['waiting']:
            if rejected:
                state['consecutive_rejections'] += 1
            elif changed:
                state['consecutive_rejections'] = 0
            if state['consecutive_rejections'] >= 3:
                identity = str(uuid4())
                issue = {'id': identity, 'category': 'system_failure', 'description':
                    'Delivery paused after three consecutive failed exports. Review the preserved failures and explicitly resume delivery after correcting the cause.',
                    'source_ids': [], 'resolved': False}
                legacy.set_report_issues(db, [*legacy.get_report_issues(db, []), issue])
                _set(db, 'report_status', 'waiting_for_human')
                _set(db, 'context_revision', _state(db, 'context_revision', 0) + 1)
                state.update(waiting=True, issue_id=identity)
                db.execute('INSERT INTO events(kind,data) VALUES (?,?)',
                    ('delivery_export_wait', encode({'issue_id': identity, 'consecutive_rejections': 3})))
        _set(db, KEY, state)
        return state


def require_resumed(workspace):
    if not enabled(workspace.store):
        return
    state = workspace.store.get(KEY, {})
    if not state.get('waiting'):
        return
    issue_id = state['issue_id']
    path = workspace.store.root / 'outputs' / ('delivery-resume-' + issue_id + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode({'issue_id': issue_id, 'consecutive_rejections': state['consecutive_rejections'],
        'reply_command': 'report-agent commission-reply --project CASE --issue-id ' + issue_id + ' --file DECISION.json',
        'decision_shape': {'decision': 'resume_delivery', 'note': ''},
        'note': 'Review the preserved failures and explain the corrected action. This resumes delivery only; it does not approve a plan or engineering results.'}) + '\n', encoding='utf-8')
    interrupt({'issue_id': issue_id, 'category': 'system_failure', 'kind': 'delivery_export_failures',
        'description': 'Three consecutive exports failed. An explicit operator delivery resume is required.',
        'reply_template': str(path.relative_to(workspace.store.root))})
    # A raw LangGraph resume value is not an authorization record.
    if workspace.store.get(KEY, {}).get('waiting'):
        raise ActionRejected('DELIVERY_OPERATOR_RESUME_REQUIRED')


def resume_delivery(workspace, issue_id, decision):
    """Only the trusted operator reply command may call this function."""
    if (not isinstance(decision, dict) or set(decision) != {'decision', 'note'}
            or decision['decision'] != 'resume_delivery' or not isinstance(decision['note'], str)
            or not decision['note'].strip()):
        raise ActionRejected('DELIVERY_RESUME_NOTE_REQUIRED')
    if not enabled(workspace.store):
        raise ActionRejected('DELIVERY_CONTRACT_REQUIRED')
    with workspace.store.run_lock(), workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = _state(db, KEY, {})
        issues = legacy.get_report_issues(db, [])
        issue = next((i for i in issues if i['id'] == issue_id), None)
        answer = encode(decision)
        if not issue or state.get('issue_id') != issue_id:
            raise ActionRejected('DELIVERY_RESUME_ISSUE_MISMATCH')
        if not state.get('waiting'):
            if issue.get('decision_origin') == 'operator' and issue.get('decision') == answer:
                return issue
            raise ActionRejected('DELIVERY_WAIT_NOT_ACTIVE')
        issue.update(decision=answer, decision_origin='operator', resolved=True)
        state.update(waiting=False, consecutive_rejections=0)
        _set(db, KEY, state)
        legacy.set_report_issues(db, issues)
        _set(db, 'report_status', 'ready')
        _set(db, 'context_revision', _state(db, 'context_revision', 0) + 1)
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)',
            ('delivery_operator_resume', encode({'issue_id': issue_id, 'note': decision['note']})))
        return issue


class DeliveryGuard(AgentMiddleware):
    def __init__(self, workspace):
        self.workspace = workspace

    async def abefore_model(self, state, runtime):
        require_resumed(self.workspace)

    async def awrap_model_call(self, request, handler):
        require_resumed(self.workspace)
        return await handler(request)
