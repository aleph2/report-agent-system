"""G3 snapshot preflight and source-bound application of the reviewed format."""
from . import legacy_state as legacy
from copy import deepcopy
import re

from .assessment_projection import assessment_receipt, score_blocker
from . import content_layout as layout
from .content_models import Ref
from .errors import ActionRejected
from .store import digest

FORMAT_SOURCE_SHA256 = 'ca9fe227372741d7d81646dd66ee926bb7829d5fe2a1c2701a865036e3fda4cf'


_INTERNAL = re.compile(
    r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b'
    r'|\b(?:source_id|source_ref|current_limits|working_notes)\b'
    r'|\b(?:locator|calculation)[\'\"]?\s*[:=：]'
    r'|[\'\"][a-zA-Z_][a-zA-Z_0-9]*[\'\"]\s*[:：]'
    r'|\b[a-zA-Z]+_[a-zA-Z_0-9]*\s*[:：]'
    r'|\[\s*(?:[\'\"]|-?\d+(?:\.\d+)?\s*,)[^\]]*\]'
    r'|(?:下一步|接下来|稍后)(?:将|再|需|会)?(?:撰写|编写|补写|生成)'
    r'|(?:待撰写|待补写|此处待填|起草备注|生成备注|模型输出|as an AI)', re.I)


def _key(ref):
    return Ref.model_validate(ref).key()


def _plan(cs, snapshot, records):
    ref = snapshot['payload'].get('commission_plan_ref')
    if not ref:
        return None
    record = records.get(_key(ref))
    if record is None and cs is not None:
        record = cs.read(ref)
    if record is None:
        raise ActionRejected('G3_COMMISSION_PLAN_MISSING')
    plan = record['payload']
    return plan if plan.get('method_pack') else None


def _order(snapshot, records):
    edges = {}
    for key, record in records.items():
        p = record['payload']
        if key[0] == 'Relation' and p.get('predicate') == 'contains':
            edges.setdefault(_key(p['subject_ref']), []).append((p['position'], _key(p['object_ref'])))
    ordered = []
    def walk(key):
        if key in ordered:
            return
        ordered.append(key)
        for _, child in sorted(edges.get(key, [])):
            walk(child)
    walk(_key(snapshot['payload']['root_ref']))
    return ordered, edges


def _source(citation, records):
    key = _key(citation['source_ref'])
    if key[0] != 'SourceArtifact' or key not in records or not citation.get('locator', '').strip():
        raise ActionRejected('G3_CITATION_REQUIRES_PINNED_SOURCE_AND_LOCATION')
    return records[key]['payload']


def citation_text(node, records, plan=None):
    if plan and plan.get('format_source') and (node['kind'] == 'report' or node['body'].get('page_role') == 'title_page'):
        # Front-matter source bindings stay in the audit, outside the prescribed cover fields.
        return ''
    if plan and any(s['section_id'] == node['body'].get('section_id') and s['kind'] == 'fixed' for s in plan['sections']):
        return ''
    values = []
    for citation in node.get('citations', []):
        source = _source(citation, records)
        title = source.get('source_metadata', {}).get('title', '').strip()
        locator = citation['locator'].strip()
        page = re.fullmatch(r'page ([1-9][0-9]*)(?:;.*)?', locator)
        text_location = re.fullmatch(r'(line|body/paragraph) ([1-9][0-9]*)(?:; chars ([1-9][0-9]*)-([1-9][0-9]*))?', locator)
        if text_location and text_location[3] and int(text_location[3]) > int(text_location[4]):
            raise ActionRejected('G3_CITATION_LOCATION_NOT_READABLE')
        if page:
            place = f'PDF第{page[1]}页'
        elif text_location:
            place = (f'第{text_location[2]}行' if text_location[1] == 'line' else f'正文第{text_location[2]}段')
        elif locator == 'manifest text':
            place = '全文'
        elif re.fullmatch(r'[\u3400-\u9fff\d、，。；（）()\s.\-]+', locator):
            place = '，' + locator
        else:
            raise ActionRejected('G3_CITATION_LOCATION_NOT_READABLE')
        if not title or _INTERNAL.search(title) or re.search(r'[/\\]', title):
            raise ActionRejected('G3_CITATION_READABLE_SOURCE_TITLE_REQUIRED')
        text = title + place
        if text not in values:
            values.append(text)
    return '（' + '；'.join(values) + '）' if values else ''


def _visible(node):
    body = node['body']
    if node['kind'] == 'table':
        values = list(body['columns']) + [v for row in body['rows'] for v in row]
        values += [layout.caption(node), body.get('footnote', '')]
        values.extend(value for row in body.get('header_rows', []) for value in row)
    elif node['kind'] == 'figure':
        values = [body['caption']]
    else:
        values = [body['text']]
    for key, value in node.get('qualifiers', {}).items():
        if key not in layout.STRUCTURAL:
            values.append(('来源说明' if key == 'source_note' else key) + '：' + str(value))
    if body.get('material_issues'):
        from .material_issues import validate_node
        issues, _ = validate_node(node)
        values.extend(issue.comment() for issue in issues)
    return values


def validate_export(cs, snapshot, records, rendered_keys=None):
    plan = _plan(cs, snapshot, records)
    if plan is None:
        return
    ordered, _ = _order(snapshot, records)
    selected = set(ordered) if rendered_keys is None else rendered_keys
    problems, sections = [], {s['section_id']: s for s in plan['sections']}
    texts = {s: [] for s in sections}
    selected_assessments = set()
    receipts = {}

    def pinned(ref):
        key = _key(ref)
        if key not in receipts:
            with cs.store.connect() as db:
                receipts[key] = assessment_receipt(db, ref)
        return receipts[key]

    composition_groups = {sid: set() for sid, section in sections.items() if section.get('result_composition')}
    outcomes = snapshot['payload'].get('commission_outcome_refs', [])
    if cs is not None:
        for outcome_ref in outcomes:
            outcome = records.get(_key(outcome_ref)) or cs.read(outcome_ref)
            assessment = outcome['payload'].get('assessment_ref')
            if assessment:
                selected_assessments.add(_key(assessment))
                receipt = pinned(assessment)
                if receipt and (blocker := score_blocker(receipt)):
                    problems.append(outcome_ref['id'] + ': assessment score unavailable: ' + blocker)
                elif not receipt or any(not receipt.get(name) or _key(receipt[name]) not in selected for name in ('ranking_ref', 'evaluation_ref', 'level_ref')):
                    problems.append(outcome_ref['id'] + ': frozen outcome requires all three generated assessment nodes')
    if plan.get('format_source'):
        try:
            source = _source(plan['format_source'], records)
            if source.get('file_digest') != FORMAT_SOURCE_SHA256:
                problems.append('format_source: reviewed format capability unavailable for this source digest')
        except (ActionRejected, ValueError):
            problems.append('format_source: pinned source unavailable')
    for key in ordered:
        if key not in selected:
            continue
        node = records[key]['payload']
        body = node['body']
        location = key[1]
        if (node['kind'] == 'table' and body.get('assessment_ref')
                and body.get('assessment_part') == 'ranking'
                and body.get('columns') == ['指标', '重要性排序', '权重', '排序理由']):
            problems.append(location + ': legacy ranking reasons require regeneration from saved assessment')
        if body.get('source_views'):
            receipt = legacy.get_planned_section_receipt(cs.store, digest(records[key]['ref'])) if cs is not None else None
            section = sections.get(body.get('section_id'), {})
            if (node['kind'] != 'block' or section.get('kind') != 'fixed' or not receipt
                    or receipt.get('node_ref') != records[key]['ref']
                    or receipt.get('commission_plan_ref') != snapshot['payload']['commission_plan_ref']
                    or receipt.get('section_id') != body.get('section_id')
                    or receipt.get('text_digest') != digest(body.get('text'))
                    or receipt.get('source_views_digest') != digest(body['source_views'])):
                problems.append(location + ': fixed source view receipt mismatch')
            else:
                for view in body['source_views']:
                    try:
                        source = _source({'source_ref': view['source_ref'], 'locator': 'page ' + str(view['page'])}, records)
                        if source.get('source_id') != view['source_id']:
                            raise ValueError('source mismatch')
                    except (ActionRejected, KeyError, TypeError, ValueError):
                        problems.append(location + ': source view pinned source mismatch')
        if plan.get('format_source') and node['kind'] not in {'table', 'figure'}:
            from .exporting import markdown_table_spans
            if markdown_table_spans(body['text']):
                problems.append(location + ': convert Markdown tables to explicit typed table nodes for G3 formatting')
        for value in _visible(node):
            if isinstance(value, (dict, list, tuple)) or _INTERNAL.search(str(value)):
                problems.append(location + ': internal material in report text')
        for citation in node.get('citations', []):
            try:
                _source(citation, records)
            except (ActionRejected, ValueError):
                problems.append(location + ': invalid citation')
        if node['kind'] == 'report' or body.get('page_role') == 'title_page':
            continue
        sid = body.get('section_id')
        if sid not in sections:
            problems.append(location + ': planned section_id required')
            continue
        section = sections[sid]
        if body.get('section_heading'):
            title = section.get('title', '')
            if (node['kind'] not in {'chapter', 'block'} or not title
                    or body.get('text') not in {title, sid + ' ' + title}
                    or body.get('assessment_ref')):
                problems.append(location + ': section heading must be exact planned title')
            continue
        assessment = body.get('assessment_ref')
        if cs is not None and assessment:
            receipt = pinned(assessment)
            if receipt and (blocker := score_blocker(receipt)):
                problems.append(location + ': assessment score unavailable: ' + blocker)
            part = body.get('assessment_part')
            if (not receipt or part not in {'ranking', 'evaluation', 'level'}
                    or receipt.get(part + '_ref') != records[key]['ref']):
                problems.append(location + ': generated assessment receipt mismatch')
            if outcomes and _key(assessment) not in selected_assessments:
                problems.append(location + ': assessment not selected by frozen outcomes')
        if cs is not None and section['kind'] == 'derived':
            receipt = legacy.get_planned_section_receipt(cs.store, digest(records[key]['ref']))
            if (not receipt or receipt.get('node_ref') != records[key]['ref']
                    or receipt.get('commission_plan_ref') != snapshot['payload']['commission_plan_ref']
                    or receipt.get('section_id') != sid
                    or (receipt.get('body_digest') != digest(body) or receipt.get('composition_digest') != digest(section['result_composition'])
                        if section.get('result_composition') else receipt.get('text_digest') != digest(body.get('text')))):
                problems.append(location + ': derived section receipt mismatch')
            elif section.get('result_composition'):
                if any(p.get('applicability_question') for p in section['result_composition']):
                    confirmation = snapshot['payload'].get('commission_confirmation_ref')
                    saved = (records.get(_key(confirmation)) or cs.read(confirmation)) if confirmation else None
                    if (not saved or receipt.get('commission_confirmation_ref') != confirmation
                            or receipt.get('decision_digest') != digest(saved['payload'])):
                        problems.append(location + ': derived template decision receipt mismatch')
                composition_groups[sid].add(digest(receipt.get('group_ref')))
                group = legacy.get_planned_section_receipt(cs.store, digest(receipt.get('group_ref')))
                expected = [_key(r) for r in (group or {}).get('node_refs', [])]
                if not expected or any(k not in selected for k in expected) or [k for k in ordered if k in expected] != expected:
                    problems.append(location + ': derived composition incomplete or reordered')
                if outcomes and any(_key(r) not in selected_assessments for r in receipt.get('assessment_refs', [])):
                    problems.append(location + ': derived assessment not selected by frozen outcomes')
            elif outcomes and any(_key(r) not in selected_assessments for r in receipt.get('assessment_refs', [])):
                problems.append(location + ': derived assessment not selected by frozen outcomes')
            if receipt:
                for bound in receipt.get('assessment_refs', []):
                    saved = pinned(bound)
                    if not saved:
                        problems.append(location + ': derived section assessment receipt missing')
                    elif blocker := score_blocker(saved):
                        problems.append(location + ': derived section assessment score unavailable: ' + blocker)
        if section['kind'] == 'fixed':
            if node['kind'] in {'table', 'figure'}:
                problems.append(location + ': fixed section requires exact text spans')
            else:
                texts[sid].append(body['text'])
        if section['kind'] == 'extracted' and not (cs is not None and assessment):
            expected = {_key(c['source_ref']) for c in section['sources']}
            actual = {_key(c['source_ref']) for c in node.get('citations', [])}
            if not actual & expected:
                problems.append(location + ': extracted section must cite its planned sources')
    from .commission_plan import fixed_section_text
    for sid, section in sections.items():
        if section.get('result_composition') and len(composition_groups[sid]) != 1:
            problems.append(sid + ': exactly one complete derived composition required')
        if section['kind'] == 'fixed':
            try:
                expected = fixed_section_text(section)
                if '\n'.join(texts[sid]) != expected:
                    problems.append(sid + ': fixed source text changed or missing')
            except ActionRejected as exc:
                problems.append(str(exc))
    if problems:
        raise ActionRejected('G3_EXPORT_PREFLIGHT: ' + '; '.join(problems))


def _typography(**values):
    return dict(font_family='Times New Roman', east_asia_font='宋体', line_spacing=1.5,
                space_before_pt=0, space_after_pt=0, **values)


def _styles():
    styles = [dict(name='Normal', **_typography(font_size=12, first_line_indent_chars=2, alignment='justify'))]
    for level, size, indent, align in [(1, 18, 7.5, 'center'), (2, 15, 10, 'left'), (3, 14, 12.7, 'justify'), (4, 12, 0, 'justify')]:
        value = _typography(font_size=size, bold=level < 4, hanging_indent_mm=indent, alignment=align)
        if level == 1:
            value.update(space_before_pt=10, space_after_pt=10)
        if level == 2:
            value.update(space_before_pt=None, space_after_pt=None, space_before_lines=.2, space_after_lines=.2)
        styles.append(dict(name=f'Heading {level}', **value))
    for name, size, bold, align in [('Title', 22, True, 'center'), ('Caption', 10.5, True, 'center'),
                                    ('Header', 9, False, 'left'), ('Footer', 9, False, 'center'),
                                    ('TOC Heading', 16, True, 'center'), ('TOC 1', 12, True, 'left'),
                                    ('TOC 2', 12, False, 'left'), ('TOC 3', 12, False, 'left')]:
        styles.append(dict(name=name, **_typography(font_size=size, bold=bold, alignment=align, first_line_indent_mm=0)))
    return styles


def _front(record, title=False):
    node, ref = record['payload'], record['ref']
    fields = node['body'].get('front_matter', {})
    required = {'project_name', 'report_name', 'organization', 'date'} | ({'leader'} if title else set())
    lines = node['body'].get('text', '').split('\n')
    quoted = '\n'.join(c.get('quote', '') for c in node.get('citations', []))
    if not required <= fields.keys() or any(not isinstance(v, str) or not v or lines.count(v) != 1 or v not in quoted for v in fields.values()):
        raise ActionRejected('G3_front_matter_REQUIRES_UNIQUE_SOURCE_CITED_LINES: ' + ref['id'])
    if set(fields) - required - ({'stage'} if title else set()):
        raise ActionRejected('G3_front_matter_UNKNOWN_ROLE')
    if set(line for line in lines if line.strip()) != set(fields.values()):
        raise ActionRejected('G3_front_matter_UNCLASSIFIED_LINE')
    controls = []
    for role, text in fields.items():
        size = {'project_name': 22, 'report_name': 26 if title else 36, 'organization': 14 if title else 16, 'date': 16, 'leader': 14, 'stage': 22}[role]
        spacing = 2.5 if role == 'leader' else 1.5 if role == 'report_name' or title and role in {'organization', 'date'} else 1
        control = _typography(font_size=size, bold=True, alignment='left' if role == 'leader' else 'center', first_line_indent_mm=0)
        control.update(text=text, line_spacing=spacing, east_asia_font='黑体' if role == 'report_name' else '宋体')
        controls.append(control)
    return {'node_ref': ref, 'paragraphs': controls}


def _merge_required(base, override, location):
    result = deepcopy(base)
    for key, value in override.items():
        if value is None:
            continue
        if key in base and base[key] != value:
            raise ActionRejected('G3_FORMAT_OVERRIDE_CONFLICT: ' + location + '.' + key)
        if key in {'line_spacing_pt', 'space_before_lines', 'space_after_lines', 'first_line_indent_mm', 'first_line_indent_chars', 'hanging_indent_mm', 'left_indent_mm'} and key not in base and value:
            raise ActionRejected('G3_FORMAT_OVERRIDE_CONFLICT: ' + location + '.' + key)
        result[key] = deepcopy(value)
    return result


def _heading_level(line):
    for pattern, level in [(r'^第[一二三四五六七八九十百零\d]+章', 1),
                           (r'^\d+\.\d+\.\d+(?:\s|$)', 3),
                           (r'^\d+\.\d+(?:\s|$)', 2), (r'^（\d+）', 4)]:
        if re.match(pattern, line):
            return level
    return None


def prepare_export(cs, snapshot, records, rendered_keys, raw_layout):
    plan = _plan(cs, snapshot, records)
    if plan is None:
        return deepcopy(raw_layout or {})
    validate_export(cs, snapshot, records, rendered_keys)
    if not plan.get('format_source'):
        return deepcopy(raw_layout or {})
    ordered, edges = _order(snapshot, records)
    root = _key(snapshot['payload']['root_ref'])
    title_keys = [k for k in ordered if records[k]['payload']['body'].get('page_role') == 'title_page']
    direct = {k for _, k in edges.get(root, [])}
    if len(title_keys) != 1 or title_keys[0] not in direct:
        raise ActionRejected('G3_front_matter_REQUIRES_ONE_DIRECT_TITLE_PAGE')
    if edges.get(title_keys[0]):
        raise ActionRejected('G3_TITLE_PAGE_MUST_BE_LEAF')
    node_options = {root: _front(records[root]), title_keys[0]: _front(records[title_keys[0]], True)}
    front = records[root]['payload']['body']['front_matter']
    headers = [dict(node_ref=records[root]['ref'], text=front[role], position=position,
                    **_typography(font_size=9, first_line_indent_mm=0))
               for role, position in [('project_name', 'left'), ('report_name', 'right')]]
    headers = [layout.HeaderPart.model_validate(value).model_dump() for value in headers]
    base = dict(paper='A4', margin_mm=25, top_margin_mm=25, bottom_margin_mm=25, left_margin_mm=25,
                right_margin_mm=15, font_size=12, line_spacing=1.5, table_line_spacing=1.5,
                table_alignment='center', table_cell_first_line_indent_mm=0, outer_border_style='double',
                outer_border_width_pt=.5, paragraph_space_after_pt=0, toc=True, toc_depth=3,
                page_numbers=True, hide_first_page_header_footer=True, cover_vertical_alignment='center',
                header_parts=headers, header=None)
    styles = {s['name']: s for s in _styles()}
    for key in ordered:
        node = records[key]['payload']
        if node['kind'] == 'table':
            if not re.fullmatch(r'(?:表)?\d+\.\d+\.\d+-\d+\s+\S.*', layout.caption(node)):
                raise ActionRejected('G3_TABLE_CAPTION_REQUIRED: ' + key[1])
            node_options[key] = dict(node_ref=records[key]['ref'], table_font_size=10.5)
        elif node['kind'] == 'figure' and not re.fullmatch(r'图\d+\.\d+-\d+\s+\S.*', node['body']['caption']):
            raise ActionRejected('G3_FIGURE_CAPTION_REQUIRED: ' + key[1])
        control = node_options.setdefault(key, {'node_ref': records[key]['ref']})
        control['qualifier_font_size'] = 12
        if key not in {root, title_keys[0]} and node['kind'] not in {'table', 'figure'}:
            lines = node['body']['text'].split('\n')
            section_level = None
            if node['body'].get('section_heading'):
                sid = node['body']['section_id']
                if not re.fullmatch(r'\d+(?:\.\d+){0,2}', sid):
                    raise ActionRejected('G3_SECTION_HEADING_DEPTH_REQUIRED: ' + sid)
                section_level = sid.count('.') + 1
                control['heading_level'] = section_level
            headings = []
            for index, line in enumerate(lines):
                level = section_level if index == 0 and section_level else _heading_level(line)
                if level:
                    if lines.count(line) != 1:
                        raise ActionRejected('G3_HEADING_REQUIRES_UNIQUE_LINE: ' + key[1])
                    typography = {k: v for k, v in styles[f'Heading {level}'].items() if k != 'name'}
                    headings.append(dict(text=line, heading_level=level, **typography))
            if headings:
                control['paragraphs'] = headings
    raw = deepcopy(raw_layout or {})
    raw_nodes, raw_styles = raw.pop('nodes', []), raw.pop('styles', [])
    if len({_key(n['node_ref']) for n in raw_nodes}) != len(raw_nodes) or len({s['name'] for s in raw_styles}) != len(raw_styles):
        raise ActionRejected('G3_DUPLICATE_LAYOUT_CONTROL')
    result = _merge_required(base, raw, 'layout')
    for item in raw_styles:
        if item['name'] not in styles:
            raise ActionRejected('G3_UNREVIEWED_STYLE: ' + item['name'])
        styles[item['name']] = _merge_required(styles[item['name']], item, item['name'])
    for item in raw_nodes:
        key = _key(item['node_ref'])
        prior = node_options.get(key, {'node_ref': item['node_ref']})
        paragraphs = item.pop('paragraphs', [])
        existing = {p['text']: p for p in prior.get('paragraphs', [])}
        for p in paragraphs:
            expected = existing.get(p['text'], _typography(font_size=12, first_line_indent_chars=2, alignment='justify'))
            existing[p['text']] = _merge_required(expected, p, key[1] + ':' + p['text'])
        for field in ('table_line_spacing', 'table_alignment', 'table_cell_first_line_indent_mm', 'outer_border_style', 'outer_border_width_pt'):
            if item.get(field) is not None and item[field] != base[field]:
                raise ActionRejected('G3_FORMAT_OVERRIDE_CONFLICT: ' + key[1] + '.' + field)
        node_options[key] = _merge_required(prior, item, key[1])
        if existing:
            node_options[key]['paragraphs'] = list(existing.values())
    # Preserve v1 readability defaults; source-specified v2 tables use generic caller layout.
    for key in ordered:
        node = records[key]['payload']
        body = node['body']
        if (plan['method_pack'].get('version', 1) != 1 or node['kind'] != 'table'
                or not body.get('assessment_ref') or node_options[key].get('column_weights')):
            continue
        if body.get('assessment_part') == 'ranking' and body['columns'] == ['指标', '重要性排序', '权重']:
            node_options[key]['column_weights'] = [1.4, .8, .8]
        elif body.get('assessment_part') == 'evaluation' and body['columns'] == ['因素', '指标', '分级描述', '分值范围', '采用值', '权重', '得分', '指南注释']:
            node_options[key]['column_weights'] = [.8, 1.1, 3.5, 1.4, 1, 1.2, 1.3, 4.9]
    result.update(styles=list(styles.values()), nodes=list(node_options.values()))
    options = layout.LayoutOptions.model_validate(result)
    layout.validate_layout(options, records, rendered_keys)
    return result
