"""Human checkpoint projection; detailed evidence remains in a bound appendix."""
import json
from html import escape
from pathlib import Path
from .store import digest
from .commission_plan import boundary_display, unresolved_sources


def owner_rows(plan):
    labels = {o['object_id']: o['label'] for o in plan.get('objects', [])}
    kinds = {'scope_exclusion': '业主排除', 'object_fact': '业主提供值', 'withdrawal': '资料义务撤回',
             'substitution_authorization': '资料替代授权', 'indicators': '指标口径'}
    rows = []
    for r in plan.get('owner_records', []):
        value = r['value']
        if r['kind'] == 'scope_exclusion':
            adopted = '不纳入本次评估；保留需设计单位确认的事实。' if r.get('open_facts') else '不纳入本次评估。'
        elif r['kind'] == 'object_fact':
            adopted = '；'.join(('纳入评估' if v else '不纳入评估') if k == 'included' else str(k) + '：' + str(v) for k,v in value.items())
        elif r['kind'] == 'indicators':
            adopted = str(value['count']) + '项指标全部保留'
        elif r['kind'] == 'substitution_authorization':
            adopted = '适用于章节 ' + '、'.join(value['section_ids']) + '；替代原件与页码见资料替代。'
        else:
            adopted = r['reason']
        rows.append([kinds[r['kind']], labels.get(r['target'], '资料替代' if r['kind'] == 'substitution_authorization' else '评估方法' if r['kind'] == 'indicators' else r['target']), adopted])
    return rows


def write_brief(cs, plan, requirements, access, plan_ref, path, full_lines, *, policy_summary=()):
    path = Path(path)
    appendix = path.with_name(path.stem + '-appendix.md')
    audit = path.with_name(path.stem + '-audit.json')
    html = path.with_suffix('.html')
    bindings = {'plan_ref': plan_ref, 'requirements_ref': plan.get('requirements_ref'),
                'plan_sha256': digest(plan), 'requirements_sha256': digest(requirements['payload'])}
    from .commission_carryover import rows
    with cs.store.connect() as db:
        carried = rows(db,plan,True)
    audit.write_text(json.dumps({**bindings, 'plan': plan, 'requirements': requirements, 'source_access': access, 'carried_judgments':carried}, ensure_ascii=False, indent=2), encoding='utf-8')
    appendix.write_text('# 完整审查证据\n\n' + json.dumps(bindings, ensure_ascii=False) + '\n\n' + '\n'.join(full_lines) + '\n', encoding='utf-8')
    def source(c):
        if not c:
            return '未知值（见原始说明）'
        title = cs.read(c['source_ref'])['payload']['source_metadata'].get('title', c['source_ref']['id'])
        short = next((name for token,name in [('路基','设计册'),('勘察','地勘'),('总体风险评估报告','模板'),('评价指南','指南'),('范围说明','委托范围')] if token in title), title)
        return short + ' / ' + c['locator'].split(';')[0]
    def direct_read(obj):
        from .document_tools import physical_page_number
        known = {row['source_id']: row for row in access.get('sources', [])}
        wanted, seen = set(), set()
        for c in obj['sources']:
            page = physical_page_number(c['locator'])
            sid = cs.read(c['source_ref'])['payload']['source_id']
            if page is None:
                continue
            wanted.add((sid,page)); row = known.get(sid,{})
            returned = set(row.get('text_returned_pages', [])) | set(row.get('inspected_text_pages', []))
            returned |= {i['page'] for i in row.get('image_observations', [])}
            if page in returned:
                seen.add((sid,page))
        return '全部有直接返回记录' if wanted and seen == wanted else '部分有直接返回记录' if seen else '无直接页面返回记录'
    statuses = {r['object_id']: r for r in plan.get('candidate_dispositions', [])}
    candidates, proposals, warnings = [], [], []
    for o in plan.get('objects', []):
        disposition = statuses.get(o['object_id'], {})
        status = {'included':'纳入', 'owner_excluded':'业主已排除', 'proposed_exclusion':'建议排除（待决定）'}.get(disposition.get('status'), '未分类：不得提交')
        height = []
        locations = [source(c) for c in o['sources']]
        for a in o['attributes']:
            if '高' in a['name'] or 'height' in a['name'].lower():
                height += [v['value'] or '未知' for v in a['values']]
                locations += [source(v.get('source')) for v in a['values']]
            if len(a['values']) > 1:
                warnings.append(o['label'] + '：' + a['name'] + '存在多个记录值；差异及采用依据见附录。')
        candidates.append([o['label'], '；'.join(height) or '未知', status, '；'.join(dict.fromkeys(locations))])
        if disposition.get('status') == 'proposed_exclusion':
            proposals.append(o['label'] + '：' + disposition['reason'] + '；' + direct_read(o) + '（不代表已理解）；未经业主决定不算已排除。')
    for r in plan.get('owner_records', []):
        warnings += [f['object_label'] + '：' + f['question'] for f in r.get('open_facts', [])]
    substitutions = {}
    for section in plan['sections']:
        for sub in section.get('source_substitutions', []):
            key = sub['requested_source'] + ' → ' + '；'.join(dict.fromkeys(source(c) for c in sub['replacement_sources']))
            substitutions.setdefault(key, []).append(section['section_id'])
        warnings += [section['section_id'] + '：' + v for v in unresolved_sources(section)]
    conventions = [c['source']['quote'] for c in plan.get('conventions', [])]
    if order := plan.get('indicator_rank_order'):
        conventions.append('业主指标排序（最重要在先）：' + '、'.join(order['indicator_ids']) + '。' + source(order['source']))
    conventions += ['权重采用 ' + b['strategy_id'] + ' 的 n=' + str(len(plan.get('method_pack', {}).get('indicators', []))) + ' 指标行。' for b in plan.get('method_conventions', [])]
    conventions += [('排序表' if role == 'ranking' else '风险评价表') + '：' + spec['caption_pattern'].replace('{number}', '〔按对象编号〕').replace('{object_label}', '〔对象名称〕') + '；' + '、'.join(dict.fromkeys(source(c) for c in spec['sources'])) for role, spec in plan.get('table_specs', {}).items()]
    boundary = boundary_display(plan['scope_boundary']) if plan.get('scope_boundary') else '范围边界尚待确认'
    page1 = ['# 编制计划：决定与例外', '本版本仍须业主批准；以下为系统原始简报。', '## 候选边坡']
    def mdtable(head, rows):
        def cell(x): return str(x).replace('|','／').replace('\n',' ')
        return ['\n'.join(['| ' + ' | '.join(head) + ' |', '|' + '|'.join('---' for _ in head) + '|'] + ['| ' + ' | '.join(cell(c) for c in row) + ' |' for row in rows])]
    page1 += mdtable(['对象／里程与侧别','高度（m）','处置','来源页'], candidates)
    page1 += ['## 建议排除', *proposals] if proposals else []
    page1 += ['## 业主已记录决定', *mdtable(['类型','对象','采用内容'], owner_rows(plan)), '## 范围与约定', boundary, *conventions,
              '## 资料替代', *[','.join(ids) + '：' + text for text,ids in substitutions.items()],
              '## 待确认问题与警示', *plan.get('open_questions', []), *list(dict.fromkeys(warnings))]
    page1 += ['章节' + p['section_id'] + '：' + p['applicability_question'] + ' keep_verbatim（保留原文）／replace（逐项替换）。' for section in plan['sections'] for p in section.get('result_composition', []) if p.get('applicability_question')]
    sections = plan['sections'];fixed = [s for s in sections if s['kind']=='fixed']
    count = len([a for a in requirements['payload']['anchors'] if a['kind']=='section'])
    resolved = len([i for i in requirements['payload']['items'] if i['status'] != 'unresolved'])
    spans = ['章节' + s['section_id'] + '：' + '、'.join(dict.fromkeys(source(c) for c in s['sources'])) for s in fixed]
    bindings_text = ['章节' + s['section_id'] + '由章节' + '、'.join(s['derived_from']) + '结果生成。' for s in sections if s['kind']=='derived']
    page2 = ['# 编制计划：结构与证据', f"章节 {len(sections)}/{count}；固定章节 {len(fixed)}；要求已分类 {resolved}/{len(requirements['payload']['items'])}（不等于批准）。",
        *spans, *bindings_text, *[s['rule'] for s in sections if s.get('result_composition')],
        '交付物：' + '、'.join(plan['deliverables']),
        '方法：' + str(len(plan.get('method_pack',{}).get('indicators',[]))) + '项指标；方法、权重、评分及等级表的逐项引用见完整附录。',
        *policy_summary, '## 审查绑定', '计划版本：' + str(plan_ref['version']), '计划指纹：' + bindings['plan_sha256'],
        '要求指纹：' + bindings['requirements_sha256'],
        f'[完整要求、引用与读取记录]({appendix.name})', f'[完整JSON]({audit.name})']
    if plan.get('carried_items'):
        counts = {s:sum(r['status']==s for r in plan['carried_items']) for s in ('proposed','confirmed','revised')}
        page2 += ['承接判断：待复核 ' + str(counts['proposed']) + '；已复核 ' + str(counts['confirmed']) + '；已修订复核 ' + str(counts['revised']) + '。逐项原值、当前值、引用和复核状态见完整JSON；不承接旧计划批准。']
    path.write_text('\n\n'.join(page1) + '\n\n---\n\n' + '\n\n'.join(page2) + '\n', encoding='utf-8')
    from markdown_it import MarkdownIt
    render = MarkdownIt('commonmark').enable('table')
    css = '@page{size:A4 landscape;margin:9mm}*{box-sizing:border-box}body{font-family:"Microsoft YaHei",sans-serif;font-size:10px;color:#182534}h1{font-size:17px;margin:0 0 5px}h2{font-size:12px;margin:7px 0 3px}p{margin:3px 0}table{width:100%;border-collapse:collapse;font-size:9px}td,th{border:1px solid #adb8c5;padding:3px;text-align:left;vertical-align:top}th{background:#eef3f8}section{break-after:page}section:last-child{break-after:auto}.pair{display:grid;grid-template-columns:1.05fr 1fr;gap:12px}.pair table{font-size:9px}li{margin:1px 0}ol{padding-left:18px;margin:4px 0}a{color:#1b4d78}code{overflow-wrap:anywhere}'
    owner_start = page1.index('## 业主已记录决定')
    scope_start = page1.index('## 范围与约定')
    substitutions_start = page1.index('## 资料替代')
    fragment = lambda lines: render.render('\n\n'.join(lines))
    first = (fragment(page1[:owner_start]) + '<div class="pair"><div>' + fragment(page1[owner_start:scope_start])
             + '</div><div>' + fragment(page1[scope_start:substitutions_start]) + '</div></div>' + fragment(page1[substitutions_start:]))
    html.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>编制计划简报</title><style>'+css+'</style><body><section>'
                   + first + '</section><section>' + fragment(page2) + '</section></body></html>', encoding='utf-8')
    return {'appendix_path': str(appendix), 'audit_path': str(audit), 'html_path': str(html)}
