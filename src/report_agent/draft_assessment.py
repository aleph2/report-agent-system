"""Render immutable open assessment positions without inventing values or grades."""


def display_rows(result, method_pack) -> list[dict]:
    grades = {rule['id']: {g['id']: g for g in rule['grades']} for rule in method_pack['indicators']}
    def alternative_text(row):
        return '、'.join(g['description'] + f"（{g['min_value']}–{g['max_value']}分）"
                        for key in row['alternatives'] for g in [grades[row['indicator_id']][key]])
    opened = [dict(**row, value='未评分', score='未评分', basis_kind='missing',
        rationale=row['reason'].rstrip('。；;') + ('；条件分级：' + alternative_text(row) if row['alternatives'] else ''),
        rank_reason='已确认的重要性排序') for row in result.get('open_rows', [])]
    return sorted([*result['rows'], *opened], key=lambda row: row['rank'])
