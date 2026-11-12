"""Lossless geometry and experiment boundaries; no model judgment claims."""
from types import SimpleNamespace
from hashlib import sha256
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from report_agent.catalog import Catalog
from report_agent.document_tools import source_page_info
from report_agent.review import load_rules, native_review, reviewer_prompt, review_delivery
from report_agent.review_context import bind_context_experiment, configure_context_experiment
from report_agent.source_tables import _compact_table, source_tables, with_source_tables
from report_agent.store import digest
from test_acceptance_calibration import CANDIDATE, fresh_import
from test_deep_runtime import Driver
from test_document_tools import workspace as source_workspace, snapshot
from test_review_context import workspace
from test_source_tables import table_pdf


COMPACT = {**CANDIDATE, "compact_table_observations": True}
FIXTURES = Path(__file__).parent / 'fixtures'


def decoded_bounds(table):
    grid = table['geometry']
    xs, ys = grid['x_edges'], grid['y_edges']
    return {(r, c): (xs[c - 1], ys[r - 1], xs[c - 1 + cs], ys[r - 1 + rs])
            for r, c, rs, cs in grid['cells']}


@pytest.mark.parametrize('page_number', [1, 2, 3])
def test_independent_pdf_rows_and_complete_geometry_roundtrip(tmp_path, page_number):
    data = (FIXTURES / 'table_geometry027.pdf').read_bytes()
    expected = json.loads((FIXTURES / 'table_geometry027.expected.json').read_text(encoding='utf-8'))
    assert sha256(data).hexdigest() == expected['pdf_sha256']
    ws = source_workspace(tmp_path, data)
    page = next(p for p in expected['pages'] if p['page'] == page_number)
    raw = source_tables(ws, 'original', [page_number])[0]
    compact = source_tables(ws, 'original', [page_number], compact=True)[0]
    assert len(raw['tables']) == len(compact['tables']) == 1
    table = compact['tables'][0]
    assert table['geometry_representation'] == 'exact_grid_v1'
    assert table['rows'] == raw['tables'][0]['rows'] == page['rows']
    assert table['geometry']['x_edges'] == page['x_edges']
    assert table['geometry']['y_edges'] == page['y_edges']
    assert decoded_bounds(table) == {(c['row'], c['column']): tuple(c['bbox']) for c in page['cells']}
    assert sorted(table['geometry']['cells']) == sorted(
        [c['row'], c['column'], c['rowspan'], c['colspan']] for c in page['cells'])
    for bound in raw['tables'][0]['nonempty_cell_bounds']:
        assert decoded_bounds(table)[bound['row'], bound['column']] == bound['bbox']


def test_compact_cells_are_lossless_and_raw_access_stays_raw(tmp_path):
    ws = source_workspace(tmp_path, table_pdf())
    raw = source_tables(ws, 'original', [1])[0]
    ws.store.set('review_context_experiment', COMPACT)
    catalog = Catalog(ws.store)
    with ws.store.connect() as db:
        db.execute("UPDATE source_blocks SET locator='page 1; chars 1-31'")
    before = snapshot(ws)
    files = set(tmp_path.rglob('*'))
    retrieval = catalog.read('original')
    view = with_source_tables(ws, retrieval)
    assert all(view[k] == value for k, value in retrieval.items())
    compact = view['source_table_views'][0]
    for name, value in raw.items():
        if name != 'tables':
            assert compact[name] == value
    r, c = raw['tables'][0], compact['tables'][0]
    assert c['rows'] == r['rows']
    assert c['geometry_representation'] == 'exact_grid_v1'
    decoded = decoded_bounds(c)
    assert all(decoded[b['row'], b['column']] == b['bbox'] for b in r['nonempty_cell_bounds'])
    assert [1, 1, 1, 2] in c['geometry']['cells']  # Actual horizontal rectangle.
    assert (3, 2) in decoded and c['rows'][2][1] == ''  # Empty cell isn't a merge.
    assert (1, 2) not in decoded and c['rows'][0][1] is None
    access = compact['raw_geometry_access']
    assert access['tool'] == 'inspect_source_page'
    page = source_page_info(ws, **access['arguments'])
    assert page['table_view'] == {k: v for k, v in raw.items() if k != 'page_facts'}
    assert page['page_facts'] == {**raw['page_facts'], 'native_text_characters': len(page['native_text'])}
    assert snapshot(ws) == before and set(tmp_path.rglob('*')) == files


@pytest.mark.parametrize('cells,values', [
    ([(0, 0, 2, 1), (1, 0, 2, 1)], [['A', 'B']]),  # overlapping rectangles
    ([(0, 0, 1, 1), (1, 0, 2, 1), (0, 1, 1.5, 2), (1.5, 1, 2, 2)], [['A', 'B'], ['C', 'D']]),
    ([(0, 0, 1, 1), (2, 0, 3, 1)], [['A', 'B']]),  # extra boundary/gap
    ([(0, 0, 1, 1)], [[None]]),  # null is not evidence that a cell is absent
])
def test_ambiguous_geometry_retains_raw_table(cells, values):
    raw = {'table': 7, 'bbox': (0, 0, max(c[2] for c in cells), max(c[3] for c in cells)),
           'rows': values, 'nonempty_cell_bounds': []}
    xs = sorted({cell[i] for cell in cells for i in (0, 2)})
    ys = sorted({cell[i] for cell in cells for i in (1, 3)})
    anchors = {(cell[1], cell[0]): cell for cell in cells}
    native_rows = [SimpleNamespace(cells=[anchors.get((ys[r], xs[c])) for c in range(len(row))])
                   for r, row in enumerate(values)]
    table = SimpleNamespace(cells=cells, rows=native_rows)
    compact = _compact_table(table, raw)
    assert compact['geometry_representation'] == 'raw_fallback'
    assert all(compact[k] == value for k, value in raw.items())
    assert 'geometry' not in compact


def test_compact_keeps_hash_membership_and_original_text_boundary(tmp_path):
    ws = source_workspace(tmp_path, table_pdf(), sha256='0' * 64)
    ws.store.set('review_context_experiment', COMPACT)
    catalog = Catalog(ws.store)
    with ws.store.connect() as db:
        db.execute("UPDATE source_blocks SET locator='page 1; chars 1-31'")
    original = catalog.read('original')
    view = with_source_tables(ws, original)
    assert view['blocks'] == original['blocks']
    assert view['source_table_views'][0]['error'] == 'SOURCE_ORIGINAL_SHA256_MISMATCH'
    assert source_tables(ws, 'unknown', [1], compact=True)[0]['error'] == 'SOURCE_NOT_IN_PROJECT'


@pytest.mark.parametrize('replacement', [CANDIDATE, {**CANDIDATE, 'compact_table_observations': False}, None])
def test_compact_selection_is_bound_and_cannot_be_removed(workspace, replacement):
    store = workspace.store
    fresh_import(store)
    configure_context_experiment(store, COMPACT)
    bind_context_experiment(store)
    store.set('review_context_experiment', replacement)
    with pytest.raises(RuntimeError, match='SWITCH_REQUIRES_FRESH_FORK'):
        bind_context_experiment(store)


@pytest.mark.parametrize('invalid', [
    {**CANDIDATE, 'compact_table_observations': 1},
    {'input_mode': 'artifact', 'grounded_verdict': True, 'compact_table_observations': True},
])
def test_compact_invalid_configuration_does_not_write(workspace, invalid):
    fresh_import(workspace.store)
    with pytest.raises(ValueError, match='INVALID_REVIEW_CONTEXT_EXPERIMENT'):
        configure_context_experiment(workspace.store, invalid)
    assert workspace.store.get('review_context_experiment') is None


def test_representation_identity_invalidates_old_acceptance_without_changing_prompt_or_tools(workspace):
    store = workspace.store
    catalogs, targets = {}, {}
    for name, config in (('raw', CANDIDATE), ('compact', COMPACT)):
        store.set('review_context_experiment', config)
        review = native_review(workspace, Driver(rubric_grader=[AIMessage('Unused')])('rubric_grader'), [], load_rules())
        review._grader_input({'messages': [HumanMessage('Request')], 'rubric': load_rules(),
                              '_current_grading_run_id': name}, 0)
        assert review._system_prompt == reviewer_prompt(CANDIDATE)
        catalogs[name] = [(tool.name, tool.description, tool.args) for tool in review._tools]
        targets[name] = store.get('rubric_targets')[name + ':0']
    assert catalogs['raw'] == catalogs['compact']
    assert targets['raw']['reviewer_prompt_hash'] == targets['compact']['reviewer_prompt_hash']
    store.set('active_rubric_hash', digest(load_rules()))
    store.set('active_reviewer_prompt_hash', digest(reviewer_prompt(CANDIDATE)))
    store.set('rubric_reviews', [{'result': 'satisfied', 'unverified': False, 'target': targets['raw']}])
    store.set('review_context_experiment', CANDIDATE)
    assert review_delivery(workspace, targets['raw']['draft_id'])['status'] == 'reviewed_draft'
    store.set('review_context_experiment', COMPACT)
    assert review_delivery(workspace, targets['raw']['draft_id'])['status'] == 'unreviewed_draft'
