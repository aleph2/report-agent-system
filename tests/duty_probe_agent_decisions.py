"""Native, synthetic P05/P10 decision execution; provider/budget owned by caller.

Stored inputs below are explicitly synthetic fixtures, not model achievements.
Only P05's coordinator delegation is scripted. Every decision after delegation,
including any independent text work or child role, uses the injected factory.
The existing run_report graph executes model actions; this module has no loop,
HTTP client, repair, fallback selection, or substitute completion action.
"""
from report_agent import report_state
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, messages_to_dict

from report_agent.content_export import export_snapshot
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.content_workbook import export_workbook
from report_agent.deep_runtime import run_report
from report_agent.hierarchical_tools import actor_for
from test_decision_data import activate
from test_deep_runtime import Driver, invoke


CASES = ('writer-chapter-order', 'co-current-delivery')
EVIDENCE_A = 'A — Field record: five exposed joints were documented at Site S.'
CONCLUSION_B = ('B — Conclusion based on the field record in A: the documented joints '
                'require a focused stability assessment; stability is not yet established.')
UNREVIEWED = 'Synthetic working draft; not independently reviewed or engineering approved.'


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def ref_key(ref):
    return ref['type'], ref['id'], ref['version']


def node(kind, text, claim='structure', qualifiers=None):
    return {'kind': kind, 'body': {'text': text}, 'qualifiers': qualifiers or {}, 'claim_kind': claim}


def prepare_fixture(ws, case):
    """Typed stored originals only; no response/action example goes to the model."""
    cs, coordinator = ContentStore(ws.store), actor_for('coordinator')
    base_goal = ('Organize the existing A evidence and B conclusion as a synthetic report. '
                 'Display B before A, preserving B\'s stated dependence on A and both original bodies. '
                 'Save a snapshot of the report; this is not an engineering assessment.'
                 if case == CASES[0] else
                 'Select the current B working draft with its exact Word and issues-workbook pair. '
                 'The historical A files were re-exported later for an archive check; they are not '
                 'the current draft. Preserve the unreviewed status; do not revise or review content.')
    ws.store.set('manifest', {**ws.store.manifest, 'goal': base_goal, 'sources': [
        {'id': 's', 'title': 'Synthetic source', 'content': EVIDENCE_A, 'coverage': 'complete'}]})
    imported = cs.import_inputs(coordinator, 'agent-decision-inputs', ['s'])['result']
    task = {'id': 'synthetic-input-owner', 'args': {'subagent_type': 'writer', 'description': base_goal}}
    with delegated_task(ws, 'coordinator', task) as (_, writer):
        if case == CASES[0]:
            refs = cs.commit(writer, 'synthetic-existing-content', [
                {'client_key': 'root', 'type': 'ContentNode', 'payload': node('report', 'Synthetic dependency report')},
                {'client_key': 'a', 'type': 'ContentNode', 'payload': node('block', EVIDENCE_A, 'fact')},
                {'client_key': 'b', 'type': 'ContentNode', 'payload': node('block', CONCLUSION_B, 'inference', {'status': UNREVIEWED})},
            ])['result']['refs']
            fixture = {'case': case, 'writer_task_id': writer.task_id, 'writer_actor': writer.__dict__,
                       'refs': refs, 'inputs': imported, 'goal': base_goal}
            task_text = base_goal + '\nExisting saved content and independent inputs:\n' + json.dumps(
                {'content_refs': refs, 'requirement_ref': imported['requirement_ref'],
                 'source_refs': imported['source_refs']}, ensure_ascii=False)
            fixture['task_description'] = task_text
        else:
            refs = cs.commit(writer, 'synthetic-draft-a', [
                {'client_key': 'root', 'type': 'ContentNode', 'payload': node('report', 'Synthetic working report')},
                {'client_key': 'body', 'type': 'ContentNode', 'payload': node('block', 'Historical draft A: four joints are recorded.', 'fact', {'status': UNREVIEWED})},
                {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'root'},
                    'object_ref': {'client_key': 'body'}, 'predicate': 'contains', 'position': 0, 'provenance_kind': 'adopted_during_generation'}},
                {'client_key': 'issues', 'type': 'ContentNode', 'payload': {'kind': 'table',
                    'body': {'columns': ['Draft', 'Unresolved issue'], 'rows': [['A', 'Source count requires checking.']]},
                    'qualifiers': {}, 'claim_kind': 'fact'}},
                {'client_key': 'note', 'type': 'ContentNode', 'payload': node('block', UNREVIEWED, 'fact')},
            ])['result']['refs']
            shared = [imported['requirement_ref'], *imported['source_refs']]
            a_snap = cs.freeze(coordinator, 'synthetic-a-snapshot', refs['root'],
                               [*shared, *refs.values()], [refs['issues'], refs['note']])['result']['snapshot_ref']
            def pair(snapshot, table, operation):
                word = export_snapshot(cs, coordinator, operation + '-word', snapshot, {'toc': False})['result']
                workbook = export_workbook(cs, coordinator, operation + '-xlsx', snapshot,
                    [{'name': 'Issues', 'table_ref': table, 'note_refs': [refs['note']]}], word['export_ref'])['result']
                return {'snapshot_ref': snapshot, 'export_ref': word['export_ref'],
                        'workbook_export_ref': workbook['export_ref']}
            a_pair = pair(a_snap, refs['issues'], 'synthetic-a-first')
            b_refs = cs.commit(writer, 'synthetic-draft-b', [
                {'client_key': 'body', 'type': 'ContentNode', 'previous_ref': refs['body'],
                 'payload': node('block', 'Current draft B: five joints are recorded.', 'fact', {'status': UNREVIEWED})},
                {'client_key': 'issues', 'type': 'ContentNode', 'previous_ref': refs['issues'],
                 'payload': {'kind': 'table', 'body': {'columns': ['Draft', 'Unresolved issue'],
                    'rows': [['B', 'Independent review remains outstanding.']]}, 'qualifiers': {}, 'claim_kind': 'fact'}},
            ])['result']['refs']
            b_refs['edge'] = cs.commit(writer, 'synthetic-b-edge', [{'client_key': 'edge', 'type': 'Relation',
                'previous_ref': refs['edge'], 'payload': {**cs.read(refs['edge'])['payload'], 'object_ref': b_refs['body']}}])['result']['refs']['edge']
            b_snap = cs.derive_snapshot(coordinator, 'synthetic-b-snapshot', a_snap, [],
                [{'previous_ref': refs[k], 'new_ref': b_refs[k]} for k in ('body', 'issues', 'edge')])['result']['snapshot_ref']
            b_pair = pair(b_snap, b_refs['issues'], 'synthetic-b')
            # Genuine new files/ExportArtifacts from unchanged old A, after B.
            a_latest = pair(a_snap, refs['issues'], 'synthetic-a-reexport')
            fixture = {'case': case, 'goal': base_goal, 'inputs': imported,
                       'a_pair': a_pair, 'b_pair': b_pair, 'a_reexport': a_latest,
                       'a_refs': refs, 'b_refs': b_refs, 'writer_actor': writer.__dict__}
            ws.store.set('manifest', {**ws.store.manifest, 'goal': base_goal + '\nExact saved draft pairs:\n' +
                json.dumps({'historical_A': a_pair, 'current_B': b_pair, 'historical_A_later_reexport': a_latest})})
    fixture['originals'] = deepcopy(cs.list_objects())
    fixture['original_files'] = []
    for record in fixture['originals']:
        if record['ref']['type'] == 'ExportArtifact':
            path = ws.store.root / record['payload']['file_ref']
            fixture['original_files'].append({'file_ref': record['payload']['file_ref'],
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    fixture['initial_review_records'] = deepcopy(cs.list_objects('ReviewRecord'))
    fixture['initial_final_review'] = deepcopy(report_state.selected_final_review(ws.store))
    activate(ws)
    return fixture


class NativeTrace(BaseCallbackHandler):
    """Observe native model calls without replacing their model or tool executor."""
    def __init__(self, role, records):
        self.role, self.records, self.active = role, records, {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        record = {'role': self.role, 'run_id': str(run_id), 'messages': [messages_to_dict(m) for m in messages],
                  'invocation_params': deepcopy(kwargs.get('invocation_params', {}))}
        self.records.append(record)
        self.active[str(run_id)] = record

    def on_llm_end(self, response, *, run_id, **kwargs):
        self.active[str(run_id)]['response'] = [[g.message.model_dump() if hasattr(g, 'message') else g.dict()
            for g in group] for group in response.generations]

    def on_llm_error(self, error, *, run_id, **kwargs):
        self.active.get(str(run_id), {})['error'] = repr(error)


def traced_model(model, role, records):
    recorder = NativeTrace(role, records)
    existing = model.callbacks
    if existing is None or isinstance(existing, list):
        callbacks = [*(existing or []), recorder]
    else:
        callbacks = existing.copy()
        callbacks.add_handler(recorder)
    return model.model_copy(update={'callbacks': callbacks})


def evaluate_saved_state(ws, fixture):
    """Independent saved-state oracle; it never changes application state."""
    cs = ContentStore(ws.store)
    preserved = all(cs.read(o['ref']) == o for o in fixture['originals'])
    files_preserved = all(hashlib.sha256((ws.store.root / f['file_ref']).read_bytes()).hexdigest() == f['sha256']
                          for f in fixture['original_files'])
    result = {'original_records_preserved': preserved, 'original_files_preserved': files_preserved,
              'review_records': deepcopy(cs.list_objects('ReviewRecord')),
              'final_review': deepcopy(report_state.selected_final_review(ws.store)),
              'semantic_limit': 'Finite order/version checks. Neo must also read actual model reasoning and limitations.'}
    result['review_state_unchanged'] = (result['review_records'] == fixture['initial_review_records'] and
                                       result['final_review'] == fixture['initial_final_review'])
    if fixture['case'] == CASES[0]:
        originals = {ref_key(o['ref']) for o in fixture['originals']}
        snapshots = [o for o in cs.list_objects('DocumentSnapshot') if ref_key(o['ref']) not in originals]
        result['new_snapshots'] = snapshots
        result['snapshot_audits'] = []
        for snap in snapshots:
            records = {ref_key(r): cs.read(r) for r in snap['payload']['refs']}
            children = {}
            for record in records.values():
                p = record['payload']
                if record['ref']['type'] == 'Relation' and p['predicate'] == 'contains':
                    children.setdefault(ref_key(p['subject_ref']), []).append((p['position'], p['object_ref']))
            ordered = []
            def flatten(ref):
                ordered.append(ref)
                for _, child in sorted(children.get(ref_key(ref), []), key=lambda v: v[0]):
                    flatten(child)
            flatten(snap['payload']['root_ref'])
            order = [ref_key(r) for r in ordered]
            a, b = ref_key(fixture['refs']['a']), ref_key(fixture['refs']['b'])
            exact = a in order and b in order
            result['snapshot_audits'].append({'snapshot_ref': snap['ref'], 'root_ref': snap['payload']['root_ref'],
                'flattened_refs': ordered, 'both_original_refs_reachable': exact,
                'b_before_a': exact and order.index(b) < order.index(a),
                'original_dependency_text_preserved': exact and records[b]['payload']['body']['text'] == CONCLUSION_B,
                'noncontainment_relations': [o for o in records.values() if o['ref']['type'] == 'Relation' and o['payload']['predicate'] != 'contains']})
        if not snapshots:
            result['status'] = 'incomplete'
        elif len(snapshots) != 1:
            result['status'] = 'needs_review_multiple_snapshots'
        else:
            audit = result['snapshot_audits'][0]
            result['status'] = 'finite_state_satisfied' if preserved and files_preserved and all(
                audit[k] for k in ('both_original_refs_reachable', 'b_before_a', 'original_dependency_text_preserved')) else 'behavior_not_met'
    else:
        result['selected_delivery'] = deepcopy(report_state.selected_delivery(ws.store))
        selected = result['selected_delivery']
        result['exact_current_b_pair'] = bool(selected) and all(selected.get(k) == v for k, v in fixture['b_pair'].items())
        result['execution_decision'] = deepcopy(ws.store.get('content_execution_decision'))
        result['status'] = ('incomplete' if selected is None else 'finite_state_satisfied' if
            result['exact_current_b_pair'] and preserved and files_preserved and result['review_state_unchanged'] else 'behavior_not_met')
    return result


async def capture_agent_decision(ws, case, folder, model_factory):
    """Execute actual injected actions in run_report; archive even incomplete work."""
    if case not in CASES:
        raise ValueError(case)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_fixture(ws, case)
    dump(folder / 'fixture.json', fixture)
    for item in fixture['original_files']:
        (folder / Path(item['file_ref']).name).write_bytes((ws.store.root / item['file_ref']).read_bytes())
    calls, models, runtime_result = [], {}, None
    coordinator = (Driver(coordinator=[invoke('task', subagent_type='writer',
        resume_content_task_id=fixture['writer_task_id'], description=fixture['task_description']),
        AIMessage(content='The delegated run returned; no host completion or acceptance is inferred.')])
        if case == CASES[0] else None)
    def factory(role):
        if coordinator is not None and role == 'coordinator':
            return coordinator(role)
        if role not in models:
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]
    error = None
    try:
        runtime_result = await run_report(ws, factory)
    except Exception as exc:
        error = repr(exc)
    finally:
        oracle = evaluate_saved_state(ws, fixture)
        capture = {'case': case, 'native_model_calls': calls,
            'fixture_coordinator_calls': [] if coordinator is None else [
                {'role': r, 'step': n, 'messages': messages_to_dict(m)} for r, n, m in coordinator.calls],
            'runtime_result': runtime_result, 'raised_error': error, 'oracle': oracle,
            'paid_calls_owned_by_caller': True, 'host_completed_target_actions': False,
            'limits': 'Fake preparation and fake controls are not autonomous behavior evidence.'}
        dump(folder / 'agent-decision-capture.json', capture)
        dump(folder / 'final-saved-state.json', {'objects': cs.list_objects() if (cs := ContentStore(ws.store)) else [],
                                               'delivery': report_state.selected_delivery(ws.store)})
    return capture
