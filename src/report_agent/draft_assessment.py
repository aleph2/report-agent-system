"""Render immutable open assessment positions without inventing values or grades."""
from .errors import ActionRejected
from .store import digest


def display_rows(result):
    opened = [dict(**row, value='未评分', score='未评分', basis_kind='missing',
        rationale=row['reason'] + ('；条件分级：' + '、'.join(row['alternatives']) if row['alternatives'] else ''),
        rank_reason='已确认的重要性排序') for row in result.get('open_rows', [])]
    return sorted([*result['rows'], *opened], key=lambda row: row['rank'])


def tables(cs, db, plan, obj, assessment_ref, result, prefix):
    definitions = {r['id']:r for r in plan['payload']['method_pack']['indicators']}
    rows, ranking, issues, citations = [], [], [], []
    for saved in display_rows(result):
        key = saved['indicator_id']
        definition = definitions[key]
        rank, weight = saved['rank'], saved['weight']
        source_texts = []
        for citation in saved['sources']:
            source = cs._read(db, citation['source_ref'])['payload']
            title = source['source_metadata'].get('title')
            if not title:
                raise ActionRejected('ASSESSMENT_READABLE_SOURCE_TITLE_REQUIRED')
            source_texts.append(dict(document=title, page=citation['locator']))
            if citation not in citations:
                citations.append(citation)
        value, score, reason = saved['value'], saved['score'], saved['rationale']
        label = definition.get('display_label', definition['label'])
        rows.append([label, str(rank), weight, value, score, reason])
        ranking.append([label, str(rank), weight])
        if saved['basis_kind'] == 'missing' or saved['basis_kind'].endswith('assumption'):
            issues.append(dict(id=digest([assessment_ref, key]), kind=saved['basis_kind'],
                object_label=obj['label'] + ' / ' + label, basis=reason, sources=source_texts,
                adopted_value=value, question=saved['question'],
                anchor=dict(row=len(rows)-1, column=3), affects_level=not bool(result.get('level_robust'))))
    ranking_body = dict(columns=['指标', '重要性排序', '权重'], rows=ranking,
                        caption=prefix + '-1 ' + obj['label'] + '指标重要性排序表', assessment_part='ranking')
    evaluation_body = dict(columns=['指标', '重要性排序', '权重', '采用值', '得分', '取值依据或未评分原因'],
        rows=rows, material_issues=issues, caption=prefix + '-2 ' + obj['label'] + '施工安全风险评价表（草稿）', assessment_part='evaluation')
    return ranking_body, evaluation_body, citations
