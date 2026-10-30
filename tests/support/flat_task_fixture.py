"""Explicit scripted V4 choices; production never translates old model responses."""
from copy import deepcopy


def task_arguments(cs, actor, raw):
    from report_agent.deliverables import resolve_snapshot
    from report_agent.live_messages import _MODEL
    value = deepcopy(raw)
    selection = value.pop('review')
    snapshot = cs.operation(actor, 'fixture-model-snapshot', selection['deliverable'],
        lambda db: {'snapshot': resolve_snapshot(cs, db, actor, selection['deliverable'])})['result']['snapshot']
    offer = _MODEL.get()
    if offer is None:
        records = [r for r in cs.list_objects() if r['ref']['type'] in {
            'DocumentSnapshot', 'ContentNode', 'Criterion', 'ExportArtifact', 'RenderArtifact', 'DelegatedTask'}]
        resources = [{'scope': 's'+str(i), 'resource': r['ref']} for i, r in enumerate(records)]
    else:
        assert offer['kind'] == 'coordinator'
        resources = offer['resources']
    def scope(ref):
        matches = [e['scope'] for e in resources if e['resource'] == ref]
        assert len(matches) == 1, ref
        return matches[0]
    standards = selection['standards']
    assert standards['kind'] == 'criteria'
    value.update(snapshot_scope=scope(snapshot),
        commission_criterion_scopes=[scope(r) for r in standards['criterion_refs']])
    extent = selection['scope']
    if extent['kind'] == 'whole_content':
        value['review_scope'] = 'whole_content'
    else:
        assert extent['kind'] == 'mapped'
        items = extent['items']
        assert items and all({k:v for k,v in i.items() if k != 'criterion_ref'} ==
            {k:v for k,v in items[0].items() if k != 'criterion_ref'} for i in items)
        first = items[0]
        value.update(review_scope='targeted', target_scope=scope(first['target_ref']),
            criterion_scopes=[scope(i['criterion_ref']) for i in items],
            assessment_kind=first.get('assessment_kind', 'content'))
        if first.get('artifact_refs'):
            value['artifact_scopes'] = [scope(r) for r in first['artifact_refs']]
        if isinstance(first.get('extent'), str):
            value['content_extent'] = first['extent']
        elif first.get('extent') is not None:
            pages = first['extent']
            assert pages['kind'] == 'render_pages' and value['assessment_kind'] == 'render'
            assert first.get('artifact_refs') == [pages['artifact_ref']]
            assert pages.get('requirement_index', 0) == 0
            value['artifact_pages'] = pages['pages']
    return value
