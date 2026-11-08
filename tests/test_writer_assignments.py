"""Per-slope navigation over pinned sources; no models or live case data."""
from copy import deepcopy
import hashlib
import pytest
from report_agent.content_store import Actor
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.catalog import Catalog
from report_agent.store import digest
from report_agent import writer_assignments as api
from test_m1_g3_integration import method_commission
from test_m1_commission_plan import save, approve
from test_ingestion import pdf_bytes


@pytest.fixture
def assigned(method_commission, request):
    f = method_commission
    old = f.sources['design']
    old_text = f.cite('design')['quote']
    inventory_page = request.param if isinstance(getattr(request, 'param', None), int) else 96
    texts = ['Unrelated K3+100', '', 'Drawing K1p250', 'Drawing K1 + 350'] + [''] * (inventory_page - 5) + [old_text]
    data = pdf_bytes(texts)
    source = Catalog(f.ws.store).import_file('design.pdf', data)['source']
    ref = f.cs.capture_sources(f.co, 'pdf-design', [source['id']])['result']['source_refs'][0]
    citation = {'source_ref': ref, 'locator': 'page ' + str(inventory_page), 'quote': old_text}
    def replace(value):
        if isinstance(value, dict):
            if value.get('source_ref') == old:
                return deepcopy(citation)
            return {key: replace(child) for key, child in value.items()}
        return [replace(child) for child in value] if isinstance(value, list) else value
    f.plan = replace(f.plan)
    f.plan['objects'][0]['label'] = 'K1+200--K1+400 right'
    if getattr(request, 'param', None) == 'aliases':
        alias = f.cs.capture_sources(f.co, 'pdf-alias', [source['id']])['result']['source_refs'][0]
        f.pdf_alias_ref = alias
        f.plan['objects'][0]['sources'].append({**citation, 'source_ref': alias})
        guide = deepcopy(f.cs.read(f.sources['guideline'])['payload'])
        guide['source_metadata']['title'] = 'design'
        with f.ws.store.connect() as db:
            alias_guide = f.cs._insert(db, f.co, 'SourceArtifact', guide)
        f.plan['objects'][0]['sources'].append({**f.cite('guideline'), 'source_ref': alias_guide})
    if "Owner rank order: B, A, D, C." in f.cs.read(f.sources['scope'])['payload']['content']:
        from test_writer_indicator_outcomes import attach_ranks
        attach_ranks(f)
    saved = save(f); approve(f, saved)
    def register(db):
        return f.cs._insert(db, f.co, 'DelegatedTask', {
            'role': 'writer', 'goal': 'Assess the assigned slope.', 'delegated_by': f.co.id,
            'commission_plan_ref': saved['plan_ref'], 'section_ids': ['4'],
            'assessment_object_id': 'S1'})
    task = f.cs.operation(f.co, 'assignment-task', {}, register)['result']
    f.actor = Actor('content:writer:' + task['id'], 'writer', task['id'])
    f.plan_ref, f.pdf_ref, f.pdf_source_id = saved['plan_ref'], ref, source['id']
    return f


def pdf_entry(f, packet):
    return next(source for source in packet['sources'] if source['title'] == 'design')


def test_assignment_scope_and_source_ids_are_system_bound(assigned):
    f = assigned
    with f.ws.store.connect() as db:
        bound = api.bound_assignment(f.cs, db, f.actor)
    assert bound['plan']['ref'] == f.plan_ref
    assert bound['object']['object_id'] == 'S1' and bound['section_id'] == '4'
    packet = api.read_assignment_pages(f.cs, f.actor)
    assert 'source_ref' not in str(packet) and f.pdf_source_id not in str(packet)
    source = pdf_entry(f, packet)
    pages = {row['page'] for row in source['pages']}
    assert {3, 4, 96} <= pages and 1 not in pages
    assert any('inventory' in reason for row in source['pages'] if row['page'] == 96 for reason in row['reasons'])
    assert packet['limitations']


def test_index_is_prepared_once_and_keeps_ambiguous_row_candidates(assigned, monkeypatch):
    f = assigned
    calls = []
    def tables(workspace, source_id, pages, **kwargs):
        calls.append((source_id, tuple(pages)))
        return [{'page': page, 'status': 'extracted', 'tables': [{'table': 1, 'rows': [
            ['K1+200--K1+400', 'first'], ['K3+100--K3+200', 'other'],
            ['K1p200--K1p400', 'second candidate']], 'nonempty_cell_bounds': []}]} for page in pages]
    monkeypatch.setattr('report_agent.source_tables.source_tables', tables)
    first = api.prepare_assignment_pages(f.cs, f.actor)
    second = api.read_assignment_pages(f.cs, f.actor)
    assert first == second
    assert len(calls) == 1
    row = next(row for row in pdf_entry(f, first)['pages'] if row['page'] == 96)
    assert [r['row'] for r in row['table_rows']] == [1, 3]
    assert row['table_rows'][0]['table'] == 1
    assert row['row_status'] == 'ambiguous_candidates'


def test_navigation_normalizes_only_station_spelling(assigned):
    f = assigned
    packet = api.read_assignment_pages(f.cs, f.actor)
    assert {3, 4} <= {row['page'] for row in pdf_entry(f, packet)['pages']}
    original = f.cs.read(f.pdf_ref)
    assert 'K1p250' in original['payload']['content']
    assert original == f.cs.read(f.pdf_ref)


@pytest.mark.parametrize('actor_kind', ['coordinator', 'wrong_task', 'wrong_actor'])
def test_foreign_or_unassigned_actor_is_rejected(assigned, actor_kind):
    f = assigned
    actor = f.co if actor_kind == 'coordinator' else Actor(
        f.actor.id if actor_kind == 'wrong_task' else 'content:writer:foreign',
        'writer', 'absent' if actor_kind == 'wrong_task' else f.actor.task_id)
    with pytest.raises((ActionRejected, ActionForbidden)):
        api.read_assignment_pages(f.cs, actor)


@pytest.mark.parametrize('assigned', ['aliases'], indirect=True)
def test_content_equal_capture_is_deduplicated_but_titles_are_not_authority(assigned):
    f = assigned
    with f.ws.store.connect() as db:
        bound = api.bound_assignment(f.cs, db, f.actor)
    pins = [tuple(f.cs.read(ref)['payload'].get(k) for k in ('source_id', 'file_digest', 'content')) for ref in bound['sources']]
    assert len(pins) == len(set(pins))
    assert f.pdf_ref in bound['sources'] and f.pdf_alias_ref not in bound['sources']
    assert len([s for s in api.read_assignment_pages(f.cs, f.actor)['sources'] if s['title'] == 'design']) == 2


def test_pages_are_hints_not_a_read_whitelist(assigned):
    f = assigned; source = pdf_entry(f, api.read_assignment_pages(f.cs, f.actor))
    assert 1 not in {row['page'] for row in source['pages']}
    result = api.read_assigned_page(f.cs, f.actor, source['source_handle'], 1)
    assert result['page'] == 1 and result['native_text'] == 'Unrelated K3+100'
    assert result['page_handle']
    with pytest.raises(ActionRejected, match='VISUAL'):
        with f.ws.store.connect() as db:
            api.resolve_visual_pages(f.cs, db, f.actor, [result['page_handle']])


@pytest.mark.parametrize('page', [0, -1, True, 97])
def test_invalid_pages_do_not_create_a_read_receipt(assigned, page):
    f = assigned; source = pdf_entry(f, api.read_assignment_pages(f.cs, f.actor))
    with pytest.raises(ActionRejected):
        api.read_assigned_page(f.cs, f.actor, source['source_handle'], page)
    with f.ws.store.connect() as db:
        from report_agent.writer_judgments import delivered_pages
        assert not delivered_pages(db)


def test_visual_citation_requires_actual_pixels_and_exact_actor_receipt(assigned):
    f = assigned; source = pdf_entry(f, api.read_assignment_pages(f.cs, f.actor))
    result = api.read_assigned_page(f.cs, f.actor, source['source_handle'], 2)
    assert result['native_text'] == ''
    assert result['image_data_url'].startswith('data:image/png;base64,')
    with pytest.raises(ActionRejected, match='VISUAL'):
        with f.ws.store.connect() as db:
            api.resolve_visual_pages(f.cs, db, f.actor, [result['page_handle']])
    api.mark_visual_page_delivered(f.cs, f.actor, result['page_handle'], result['image_sha256'])
    with f.ws.store.connect() as db:
        citations = api.resolve_visual_pages(f.cs, db, f.actor, [result['page_handle']])
    assert citations == [{'source_ref': f.pdf_ref, 'locator': 'page 2', 'quote': ''}]
    with pytest.raises((ActionForbidden, ActionRejected)):
        api.mark_visual_page_delivered(f.cs, f.actor, result['page_handle'], '0' * 64)
    with pytest.raises((ActionForbidden, ActionRejected)):
        with f.ws.store.connect() as db:
            api.resolve_visual_pages(f.cs, db, Actor('content:writer:other', 'writer', 'other'), [result['page_handle']])


@pytest.mark.parametrize('field', ['content', 'id'])
def test_changed_source_pin_invalidates_existing_index(assigned, field):
    f = assigned; api.read_assignment_pages(f.cs, f.actor)
    with f.ws.store.connect() as db:
        row = db.execute('SELECT data FROM source_versions WHERE id=?', (f.pdf_source_id,)).fetchone()
        import json
        value = json.loads(row[0]); value[field] += ' changed'
        db.execute('UPDATE source_versions SET data=? WHERE id=?', (json.dumps(value), f.pdf_source_id))
    with pytest.raises(ActionRejected, match='SOURCE.*CHANGED'):
        api.read_assignment_pages(f.cs, f.actor)


def test_unlocated_sources_are_not_assigned_a_fake_physical_page(assigned):
    packet = api.read_assignment_pages(assigned.cs, assigned.actor)
    sources = [row for row in packet['sources'] if row['title'] != 'design']
    assert sources and all(not row['pages'] for row in sources)
    assert all(row['status'] == 'physical_pages_unresolved' for row in sources)


@pytest.mark.parametrize('assigned', [12], indirect=True)
def test_inventory_page_comes_from_frozen_citation_not_a_page96_constant(assigned):
    f = assigned
    pages = {row['page'] for row in pdf_entry(f, api.read_assignment_pages(f.cs, f.actor))['pages']}
    assert 12 in pages and 96 not in pages


def test_cached_page_index_cannot_expand_assignment_sources(assigned):
    f = assigned
    api.read_assignment_pages(f.cs, f.actor)
    with f.ws.store.connect() as db:
        import json
        row = db.execute("SELECT key,value FROM state WHERE key LIKE 'writer_assignment_pages:%'").fetchone()
        value = json.loads(row[1])
        value['sources'][0]['source_ref'] = f.sources['template']
        db.execute('UPDATE state SET value=? WHERE key=?', (json.dumps(value), row[0]))
    with pytest.raises(ActionRejected, match='INDEX_CHANGED'):
        api.read_assignment_pages(f.cs, f.actor)


def test_chainage_discovered_page_also_offers_table_row_candidates(assigned, monkeypatch):
    f = assigned
    def tables(workspace, source_id, pages, **kwargs):
        return [{'page': page, 'status': 'extracted', 'tables': [{'table': 1,
            'rows': [['K1+200--K1+400', 'candidate']], 'nonempty_cell_bounds': []}]} for page in pages]
    monkeypatch.setattr('report_agent.source_tables.source_tables', tables)
    packet = api.read_assignment_pages(f.cs, f.actor)
    row = next(row for row in pdf_entry(f, packet)['pages'] if row['page'] == 3)
    assert row['table_rows'] == [{'table': 1, 'row': 1}]
    assert row['row_status'] == 'unique_candidate'


def test_text_page_does_not_render_pixels_or_issue_visual_credit(assigned, monkeypatch):
    f = assigned
    source = pdf_entry(f, api.read_assignment_pages(f.cs, f.actor))
    def forbidden(*args, **kwargs):
        raise AssertionError('Text-only page read rendered an image')
    monkeypatch.setattr('report_agent.document_tools.source_page_png', forbidden)
    result = api.read_assigned_page(f.cs, f.actor, source['source_handle'], 3, include_image=False)
    assert result['native_text'] == 'Drawing K1p250'
    assert result['visual_evidence'] == 'SYSTEM_VISUAL_CAPABILITY_UNAVAILABLE'
    assert not {'page_handle', 'image_data_url', 'image_sha256'} & result.keys()
    assert result['table_view']['page'] == 3
    with f.ws.store.connect() as db:
        from report_agent.writer_judgments import delivered_pages
        assert not delivered_pages(db)


def projected_page():
    return {
        'source_handle':'source-2', 'source_id':'PRIVATE_SOURCE', 'source_ref':{'id':'PRIVATE_REF'},
        'sha256':'a'*64, 'page':43, 'page_count':400, 'locator':'PDF physical page 43 of 400',
        'native_text':'Native PDF value 12; OCR correction is elsewhere.',
        'frozen_text_blocks':[{'ordinal':7,'locator':'page 43; chars 1-34','text':'Stored OCR value 21.\nExact spacing  retained.'}],
        'frozen_text_note':'Stored extraction/OCR; no OCR rerun.',
        'visual_evidence':'SYSTEM_VISUAL_CAPABILITY_UNAVAILABLE',
        'limitations':['Physical page only; not complete visual coverage.'],
        'limitation':'Drawing-only evidence is unverified, not missing.',
        'coverage':{'text':'page only','visual':'unverified'},
        'table_view':{'status':'extracted','derived':True,'page':43,'page_count':400,
            'source_id':'PRIVATE_SOURCE','source_sha256':'a'*64,'coordinate_system':'PDF points',
            'page_bbox':[0,0,100,100],'limitations':['Mechanical candidates; empty text is not zero.'],
            'tables':[{'table':1,'bbox':[1,2,3,4],
                'rows':[['A',None,''],['0','21.0','exact\nline']],
                'nonempty_cell_bounds':[{'row':1,'column':1,'bbox':[1,2,3,4]}],
                'geometry':{'cells':[[1,1,1,1]]},'geometry_representation':'exact_grid_v1'}]},
        'image_ref':'PRIVATE_IMAGE_REF','image_data_url':'PRIVATE_PIXELS','image_sha256':'b'*64,
    }


def test_page_view_default_preserves_exact_stored_text_and_only_one_representation():
    raw=projected_page(); before=deepcopy(raw)
    view=api.page_view(raw)
    assert view['view']=='text' and view['text_channel']=='frozen_text_blocks'
    assert view['frozen_text_blocks']==raw['frozen_text_blocks']
    assert not {'native_text','table_view','source_id','source_ref','sha256',
                'image_ref','image_data_url','image_sha256'} & view.keys()
    assert view['text_channels']=={'frozen_text_blocks':'available','native_text':'available'}
    assert view['source_handle']=='source-2' and view['page']==43
    assert view['visual_evidence']==raw['visual_evidence']
    assert view['coverage']==raw['coverage'] and view['limitations']==raw['limitations']
    assert view['frozen_text_note']==raw['frozen_text_note']
    assert raw==before
    view['frozen_text_blocks'][0]['text']='Projection edit'
    assert raw==before
    assert 'page_handle' not in view


def test_page_view_explicit_native_keeps_pdf_text_without_losing_ocr_availability():
    raw=projected_page()
    view=api.page_view(raw,'native_text')
    assert view['native_text']==raw['native_text']
    assert view['text_channel']=='native_text'
    assert view['text_channels']['frozen_text_blocks']=='available'
    assert 'frozen_text_blocks' not in view and 'table_view' not in view
    assert view['limitation']==raw['limitation']


@pytest.mark.parametrize('frozen,native,expected',[
    ([], 'Native only', 'native_text'),
    ([{'ordinal':0,'locator':'page 1','text':'OCR only'}], '', 'frozen_text_blocks'),
    ([], '', 'native_text'),
    ([{'ordinal':0,'locator':'page 1','text':'  \n'}], 'PDF text', 'native_text'),
])
def test_page_view_empty_channels_and_native_fallback_are_explicit(frozen,native,expected):
    raw=projected_page(); raw['frozen_text_blocks']=frozen; raw['native_text']=native
    view=api.page_view(raw)
    assert view['text_channel']==expected
    assert (view.get('native_text')==native if expected=='native_text'
            else view['frozen_text_blocks']==frozen)
    assert view['text_channels']['native_text']==('available' if native.strip() else 'empty')
    assert view['text_channels']['frozen_text_blocks']==('available' if any(b['text'].strip() for b in frozen) else 'empty')
    assert 'table_view' not in view


def test_page_view_tables_keep_all_cells_and_status_without_text_or_geometry():
    raw=projected_page(); before=deepcopy(raw)
    view=api.page_view(raw,'tables')
    table=view['table_view']
    assert table['status']=='extracted' and table['derived'] is True
    assert table['tables']==[{'table':1,'rows':raw['table_view']['tables'][0]['rows']}]
    assert table['limitations']==raw['table_view']['limitations']
    assert not {'native_text','frozen_text_blocks','source_id','source_ref','image_data_url'} & view.keys()
    assert not {'source_id','source_sha256','page_bbox','coordinate_system'} & table.keys()
    assert not {'bbox','nonempty_cell_bounds','geometry','geometry_representation'} & table['tables'][0].keys()
    table['tables'][0]['rows'][0][0]='changed'
    assert raw==before


@pytest.mark.parametrize('status',['unavailable','no_tables_detected'])
def test_page_view_does_not_turn_empty_table_channel_into_missing_evidence(status):
    raw=projected_page()
    raw['table_view']={'status':status,'tables':[],'limitations':['No detected table does not establish absent information.']}
    view=api.page_view(raw,'tables')
    assert view['table_view']==raw['table_view']
    assert view['visual_evidence']=='SYSTEM_VISUAL_CAPABILITY_UNAVAILABLE'
    assert view['text_channels']['frozen_text_blocks']=='available'


def test_page_view_preserves_only_an_existing_visual_handle():
    raw=projected_page()
    raw['page_handle']='page-verified-receipt'
    for mode in ('text','native_text','tables'):
        view=api.page_view(raw,mode)
        assert view['page_handle']=='page-verified-receipt'
        assert 'PRIVATE' not in str(view)
    raw.pop('page_handle')
    assert all('page_handle' not in api.page_view(raw,mode) for mode in ('text','native_text','tables'))


def test_page_view_unavailable_text_channels_remain_explicit():
    raw={'page':2,'limitations':['No channel proves absent source information.']}
    view=api.page_view(raw)
    assert view['native_text']==''
    assert view['text_channels']=={'frozen_text_blocks':'unavailable','native_text':'unavailable'}
    assert view['limitations']==raw['limitations']


def test_page_view_rejects_unknown_mode_without_mutation():
    raw=projected_page(); before=deepcopy(raw)
    with pytest.raises(ActionRejected,match='PAGE_VIEW'):
        api.page_view(raw,'guessed-summary')
    assert raw==before
