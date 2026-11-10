"""Case provenance is immutable operational data; export checks referenced assertions."""
import pytest

from report_agent import report_state
from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.store import Store, encode
from test_m1_g3_integration import method_commission
from test_section_writing import reviewed_writing


def case(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic provenance test', 'sources': [
        {'id': 'source', 'content': 'Synthetic supplied material', 'coverage': 'complete'}],
                      'content_contract': 'hierarchical-review-v1'})
    cs = ContentStore(store)
    actor = Actor('content:coordinator', 'coordinator', 'synthetic')
    root = cs.commit(actor, 'root', [{'client_key': 'root', 'type': 'ContentNode',
        'payload': {'kind': 'report', 'body': {'text': 'Synthetic report'},
                    'qualifiers': {}, 'claim_kind': 'structure'}}])['result']['refs']['root']
    snapshot = cs.freeze(actor, 'snapshot', root, [root])['result']['snapshot_ref']
    return store, cs, actor, root, snapshot


@pytest.mark.parametrize('kind,write,read', [
    ('SectionProvenance', report_state.record_section, report_state.planned_section),
    ('AssemblyProvenance', report_state.record_assembly, report_state.assembly),
    ('RescueProjection', report_state.record_projection, report_state.projection)])
def test_generation_record_is_immutable_hash_free_and_same_transaction(tmp_path, kind, write, read):
    store, cs, actor, node, snapshot = case(tmp_path)
    ref = snapshot if kind == 'AssemblyProvenance' else node
    payload = {'node_ref': ref, 'section_id': '4', 'nested': {'source_ref': node}}
    with pytest.raises(RuntimeError), store.connect() as db:
        write(db, ref, payload)
        raise RuntimeError('case transaction failed')
    assert not report_state.native(store, kind, ref)
    first = write(store, ref, payload)
    assert write(store, ref, payload) == first
    saved = read(store, ref)
    assert saved == payload
    assert cs.read(first)['created_by'] == 'system:report-assembler'
    with pytest.raises(ActionForbidden):
        cs.read_context(Actor('content:writer', 'writer', 'unoffered'), first)
    with store.connect() as db:
        wrapped = cs._insert(db, actor, 'DocumentSnapshot', {'refs': [first]})
    with pytest.raises(ActionForbidden):
        cs.read_context(Actor('content:writer', 'writer', 'unoffered'), wrapped)
    with pytest.raises(ActionRejected, match='IMMUTABLE'):
        write(store, ref, {**payload, 'section_id': '5'})
    assert read(store, ref) == saved
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM content_versions WHERE type=?", (kind,)).fetchone()[0] == 1


def test_prose_selection_versions_preserve_original_without_legacy_state(tmp_path):
    store, cs, actor, node, snapshot = case(tmp_path)
    scope = 'prose:' + encode([{'type': 'CommissionPlan', 'id': 'plan', 'version': 1}, '4', None])
    first = report_state.select_prose(store, scope, node, actor=actor)
    second = report_state.select_prose(store, scope, snapshot, actor=actor)
    assert report_state.prose_ref(store, scope) == snapshot
    assert cs.read(first)['payload'] == node
    assert cs.read(second)['previous_ref'] == first
    assert report_state.select_prose(store, scope, snapshot, actor=actor) == second
    assert store.get(scope) is None


def test_export_preflight_rejects_superseded_input_even_without_a_new_export_call(tmp_path):
    from uuid import NAMESPACE_URL, uuid5
    from report_agent import assertions
    from report_agent.assertion_host import AssertionHost, Grant
    from report_agent.commission_requirements import export_preflight
    store, cs, actor, node, snapshot = case(tmp_path)
    host = AssertionHost(tmp_path)
    principal = str(uuid5(NAMESPACE_URL, 'synthetic-coordinator'))
    def source(call, subject='A'):
        grant = Grant(principal, 'coordinator', 'source', call, 'plan',
            frozenset([subject]), frozenset(), frozenset(['assert_source']))
        return assertions.assert_source(host.issue_once(grant, 'assert_source', call),
            subject=subject, claim=dict(kind='source', predicate='condition', state='unknown', coverage=subject))
    old, new, other = source('old'), source('new'), source('other', 'B')
    report_state.record_assembly(store, snapshot, {'snapshot_ref': snapshot, 'assertion_refs': [old['id'], other['id']]})
    export_preflight(cs, actor, snapshot, None)
    owner = Grant(str(uuid5(NAMESPACE_URL, 'operator')), 'owner', 'review', 'replace', 'plan',
        frozenset(['A']), frozenset([old['id'], new['id']]), frozenset(['supersede']))
    assertions.supersede(host.issue_once(owner, 'supersede', 'replace'), subject='A',
        claim=dict(kind='act', effect='supersede', target=old['id'], successor=new['id'], reason='Corrected input'))
    with pytest.raises(ActionRejected, match='REPORT_INPUT_ASSERTION_NOT_CURRENT'):
        export_preflight(cs, actor, snapshot, None)
    assert cs.read(snapshot)['ref'] == snapshot


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_cached_word_excel_pair_rechecks_transitive_judgment_withdrawal(reviewed_writing):
    from report_agent.assessment_projection import selected_assessment
    from report_agent.assertion_host import AssertionHost
    from report_agent.content_export import export_snapshot
    from report_agent.section_writing import save_section_prose
    from report_agent.system_assembler import assemble_current_report
    from test_assessment_refresh import act
    f = reviewed_writing
    save_section_prose(f.cs, f.writer, 'context', '4', 'S1 design height is 30 metres.', [f.cite('design')])
    snapshot = assemble_current_report(f.cs, f.co, 'assembly')['result']['snapshot_ref']
    provenance = report_state.assembly(f.cs.store, snapshot)
    with f.cs.store.connect() as db:
        assessment = f.cs._read(db, selected_assessment(db, f.plan_ref, 'S1'))['payload']
    assert assessment['derived_assertion_id'] in provenance['assertion_refs']
    pair = export_snapshot(f.cs, f.co, 'frozen-pair', snapshot, {'toc': False})['result']
    paths = [f.cs.store.root / pair['file_ref'], f.cs.store.root / pair['workbook']['file_ref']]
    original = [path.read_bytes() for path in paths]
    # M10's complete synthetic pair complements Fake03's intentional refusal.
    from docx import Document
    from openpyxl import load_workbook
    from zipfile import ZipFile
    import json
    import os
    assert all(path.is_file() for path in paths)
    assert all(cs_ref['payload']['snapshot_ref'] == snapshot for cs_ref in (
        f.cs.read(pair['export_ref']), f.cs.read(pair['workbook']['export_ref'])))
    with ZipFile(paths[0]) as package:
        assert package.testzip() is None
    doc = Document(paths[0])
    assert doc.tables and any('S1' in cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    book = load_workbook(paths[1])
    assert book.sheetnames
    book.close()
    if dest := os.environ.get('M10_SYNTHETIC_PAIR_RECORD'):
        from pathlib import Path
        Path(dest).write_text(json.dumps({'fixture': 'complete synthetic four-indicator S1; not Fake03',
            'snapshot_ref': snapshot, 'word_ref': pair['export_ref'],
            'excel_ref': pair['workbook']['export_ref'],
            'bytes': [len(data) for data in original], 'engineering_acceptance': False}, indent=2))
    assert export_snapshot(f.cs, f.co, 'frozen-pair', snapshot, {'toc': False})['result'] == pair
    host = AssertionHost(f.cs.store.root)
    derived = host.recover_receipt(assessment['derive_operation_id'])['result']
    act(host, f.plan_ref, 'S1', derived['claim']['inputs'][0], 'retract')
    with pytest.raises(ActionRejected, match='G3_EXPORT_PREFLIGHT'):
        export_snapshot(f.cs, f.co, 'frozen-pair', snapshot, {'toc': False})
    assert [path.read_bytes() for path in paths] == original


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_output_and_provenance_roll_back_together_then_redo_once(reviewed_writing, monkeypatch):
    from report_agent.section_writing import save_section_prose
    from report_agent.system_assembler import assemble_current_report
    f = reviewed_writing
    save_section_prose(f.cs, f.writer, 'context', '4', 'S1 design height is 30 metres.', [f.cite('design')])
    before = f.cs.list_objects()
    record = report_state.record_assembly
    def interrupted(*args, **kwargs):
        record(*args, **kwargs)
        raise RuntimeError('interrupted before case commit')
    monkeypatch.setattr(report_state, 'record_assembly', interrupted)
    with pytest.raises(RuntimeError, match='before case commit'):
        assemble_current_report(f.cs, f.co, 'same-operation')
    assert f.cs.list_objects() == before
    monkeypatch.setattr(report_state, 'record_assembly', record)
    first = assemble_current_report(f.cs, f.co, 'same-operation')
    complete = f.cs.list_objects()
    assert assemble_current_report(f.cs, f.co, 'same-operation') == first
    assert f.cs.list_objects() == complete
