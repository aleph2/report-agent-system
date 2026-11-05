"""Project result regions generated only from saved, commission-bound assessments."""
from .content_models import ContentNode
from .errors import ActionRejected
from .method_pack import number


# shortcut: pilot wording and specialist criterion remain here; move to source-bound method/table data after this pilot.
def composed_nodes(plan, section, bound, template_decisions=(), applicability_issues=(), *, positional_anchors=False):
    from .commission_plan import template_decision_texts, template_issue
    adopted = template_decision_texts({"sections": [section]}, template_decisions)
    frozen_issues = {issue["id"]: issue for issue in applicability_issues}
    definitions = {i['id']: i for i in plan['method_pack']['indicators']}
    bands = {b['level']: b for b in plan['method_pack']['risk_bands']}
    threshold = next((b for b in bands.values() if b['level'] in ('Ⅲ', 'III')), None)
    if threshold is None:
        raise ActionRejected('COMPOSITION_SPECIAL_LEVEL_III_REQUIRED')
    objects = {o['object_id']: o for o in plan['objects']}
    if not set(bound) <= objects.keys():
        raise ActionRejected('COMPOSITION_UNKNOWN_OBJECT')
    ids = [o['object_id'] for o in plan['objects'] if o['object_id'] in bound]
    nodes = []
    def node(kind, body, citations):
        nodes.append(ContentNode.model_validate({'kind': kind, 'body': {**body, 'section_id': section['section_id'], 'composition_section_id': sid},
            'qualifiers': {}, 'citations': citations, 'claim_kind': 'calculation' if kind == 'table' else 'structure'}).model_dump(mode='json'))
    def label(oid):
        return objects[oid]['label']
    def qualification(result):
        if result['affects_level']:
            return '含假设取值；风险等级受取值影响，补充资料后须复核。'
        return '含假设取值，补充资料后须复核。' if any(r['basis_kind'].endswith('assumption') for r in result['rows']) else ''
    citations = []
    for result in bound.values():
        if len(result['rows']) != len(definitions) or {r['indicator_id'] for r in result['rows']} != definitions.keys():
            raise ActionRejected('COMPOSITION_COMPLETE_INDICATORS_REQUIRED')
        if result['adopted']['level'] not in bands:
            raise ActionRejected('COMPOSITION_UNKNOWN_RISK_LEVEL')
        for row in result['rows']:
            for c in row['sources']:
                if c not in citations:
                    citations.append(c)
    for part in section['result_composition']:
        sid, kind = part['section_id'], part['kind']
        if kind == 'source':
            text = adopted.get(sid, part['text'])
            anchor = (text.splitlines()[0] if text.splitlines() else '') if positional_anchors else next((line.strip() for line in text.splitlines() if line.strip() and text.count(line.strip()) == 1), None)
            if not anchor:raise ActionRejected('TEMPLATE_MATERIAL_ISSUE_ANCHOR_REQUIRED: ' + sid)
            issue = frozen_issues.get('template-applicability:' + sid) or template_issue(part, [], next((c['choice'] for c in template_decisions if c['section_id'] == sid), None))
            issue = {**issue, 'adopted_value': anchor, 'anchor': {'paragraph_index': 0, 'start': 0, 'end': None} if positional_anchors else {'text': anchor}, 'affects_level': False}
            node('block', {'text': text, 'material_issues': [issue]}, section['sources'])
        elif kind == 'assessment_summary':
            counts = '；'.join(level + '级' + str(sum(r['adopted']['level'] == level for r in bound.values())) + '处'
                              for level in sorted(bands, key=lambda v: number(bands[v]['lower'])))
            node('block', {'text': sid + ' 风险等级汇总\n依据本次已保存的第4章评估结果，共评估' + str(len(ids)) + '处路堑高边坡。' + counts + '。'}, citations)
            node('table', {'caption': '表 ' + sid + '-1 路堑高边坡施工安全总体风险评估结果',
                'columns': ['序号', '对象／桩号及侧别', '综合评分', '风险等级', '取值限定'],
                'rows': [[str(n), label(oid), bound[oid]['adopted']['total'], bound[oid]['adopted']['level'], qualification(bound[oid])] for n, oid in enumerate(ids, 1)]}, citations)
        elif kind == 'indicator_list':
            node('block', {'text': sid + ' 重要性指标清单\n逐对象列出全部' + str(len(definitions)) + '项指标及已保存的重要性排序，不另行筛选重要指标子集。'}, citations)
            rows = []
            for oid in ids:
                for row in sorted(bound[oid]['rows'], key=lambda r: r['rank']):
                    d = definitions[row['indicator_id']]
                    rows.append([label(oid), str(row['rank']), d.get('display_label', d['label']), row['value'], row['weight'], row['rank_reason'], row['rationale'], qualification(bound[oid])])
            node('table', {'caption': '表 ' + sid + '-1 路堑高边坡全部指标重要性排序及取值依据',
                'columns': ['对象', '排序', '指标', '采用值', '权重', '排序依据', '取值依据', '限定'], 'rows': rows}, citations)
        elif kind == 'special_assessments':
            rows = []
            for oid in ids:
                result = bound[oid]
                reasons = []
                if number(bands[result['adopted']['level']]['lower']) >= number(threshold['lower']):
                    reasons.append('风险等级Ⅲ级及以上')
                for row in result['rows']:
                    d = definitions[row['indicator_id']]
                    if number(row['value']) == max(number(g['max_value']) for g in d['grades']):
                        reasons.append(d.get('display_label', d['label']) + '采用值达到单项最大分值')
                if reasons:
                    rows.append([label(oid), result['adopted']['total'], result['adopted']['level'], '；'.join(reasons), qualification(result)])
            node('block', {'text': sid + ' 专项风险评估对象\n按模板规则：Ⅲ级及以上或任一指标采用值达到该指标最大分值，筛得' + str(len(rows)) + '处；仅上界达到最大值不作为已满足条件。假设及设计变更须复核。'}, section['sources'] + citations)
            node('table', {'caption': '表 ' + sid + '-1 施工安全专项风险评估建议评估对象',
                'columns': ['对象／桩号及侧别', '综合评分', '风险等级', '入选依据', '取值限定'], 'rows': rows}, citations)
    return nodes
