"""Review-only probes of current contracts. In-memory records; no SQLite/provider."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from report_agent import bounded_review
from report_agent.content_store import ContentStore
from report_agent.errors import ActionRejected
from report_agent.store import encode
from report_agent.task_supervision import ReviewRequirement, validate_requirements


def ref(kind, identifier):
    return dict(type=kind, id=identifier, version=1)


snap, first, foreign, second, criterion = [ref(*r) for r in [
    ('DocumentSnapshot', 'snapshot'), ('ContentNode', 'first'),
    ('ContentNode', 'outside'), ('ContentNode', 'second'), ('Criterion', 'criterion')]]
records = {}
for r in [first, foreign, second]:
    records[encode(r)] = dict(ref=r, payload=dict(kind='block', body={'text': r['id']}, qualifiers={}, claim_kind='structure'))
records[encode(criterion)] = dict(ref=criterion, payload=dict(purpose='Offline contract probe'))
records[encode(snap)] = dict(ref=snap, payload=dict(refs=[first, second, criterion],
    criteria_refs=[criterion], root_ref=first, manifest_digest='offline'))


def requirement(target=first, extra=()):
    return ReviewRequirement(target_ref=target, criterion_ref=criterion, scope_id='same-scope',
        required_checks=['Inspect the assigned body'], required_read_refs=list(extra),
        required_materials=[dict(requirement_index=0, purpose='Assigned body', refs=[target])]).model_dump()


class MemoryStore:
    manifest = {'review_execution_mode': 'bounded-tool-v1', 'goal': 'Offline contract probe'}
    def get(self, key, default=None):
        return default


class MemoryContents:
    store = MemoryStore()
    requirements = []
    def read(self, r):
        if r['type'] == 'DelegatedTask':
            return dict(payload=dict(role='reviewer', review_snapshot_ref=snap, review_requirements=self.requirements))
        return records[encode(r)]
    def _read(self, db, r):
        return self.read(r)
    def operation(self, actor, operation_id, request, execute):
        cs = self
        class Db:
            def execute(self, query, args=()):
                assert 'DelegatedTask' in query, query
                return SimpleNamespace(fetchone=lambda: [json.dumps({'payload': {'review_requirements': cs.requirements}})])
        return execute(Db())


actor = SimpleNamespace(role='reviewer', id='content:reviewer:task', task_id='task')
cs = MemoryContents()
workspace = SimpleNamespace(store=cs.store)
model = SimpleNamespace(model_name='offline-no-provider')
observed = {}


class DispatchIntercepted(Exception):
    pass


async def intercept(workspace, model, inputs, *args, **kwargs):
    observed['supplied_saved_refs'] = [e['object']['ref'] for e in inputs['evidence'] if e['kind'] == 'saved_object']
    raise DispatchIntercepted('Stopped before provider call')


async def probe():
    cs.requirements = [requirement(extra=[foreign])]
    outside = {'readiness': validate_requirements(cs, snap, cs.requirements)}
    with patch.object(bounded_review, 'ContentStore', return_value=cs), patch.object(bounded_review, 'analyze_evidence_packet', intercept):
        try:
            await bounded_review.perform_review(workspace, actor, model, 'probe', ['same-scope'])
        except DispatchIntercepted:
            outside['dispatch_boundary_reached'] = True
    outside.update(observed)
    item = dict(target_ref=first, criterion_ref=criterion, scope='Offline', scope_id='same-scope',
        execution_state='not_started', verdict=None, observations=[],
        coverage=dict(checked=[], unchecked=['Offline'], blocked=[], basis='No model ran'), reason='Offline probe')
    submission = dict(target_ref=first, snapshot_ref=snap, scope='Offline', criteria_refs=[criterion],
        dependency_refs=[first, foreign], items=[item])
    try:
        ContentStore.submit_review(cs, actor, 'probe-save', submission, {'mode': 'bounded-review-v1'})
    except ActionRejected as exc:
        outside['submission_rejection'] = str(exc)
    cs.requirements = [requirement(first), requirement(second)]
    repeated = {'readiness': validate_requirements(cs, snap, cs.requirements), 'execution_attempts': []}
    with patch.object(bounded_review, 'ContentStore', return_value=cs):
        for ids in [['same-scope'], ['same-scope', 'same-scope']]:
            try:
                await bounded_review.perform_review(workspace, actor, model, 'probe-duplicate', ids)
            except ActionRejected as exc:
                repeated['execution_attempts'].append({'scope_ids': ids, 'rejection': str(exc)})
    result = {'method': 'Current Python functions; in-memory content/storage doubles; provider boundary intercepted; no database',
        'outside_required_read_ref': outside, 'duplicate_scope_ids': repeated, 'provider_calls': 0}
    root = Path(__file__).resolve().parents[3]
    result['source_hashes'] = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [root/'src/report_agent'/name for name in ['task_supervision.py','bounded_review.py','content_store.py']]}
    Path(__file__).with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


asyncio.run(probe())
