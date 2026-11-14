from copy import deepcopy
import pytest
from report_agent import assertions, commission_plan, commission_assertions, page_bindings, plan_authority
from report_agent.assertion_host import AssertionHost
from report_agent.content_store import Actor
from report_agent.source_use import source_version_material
from report_agent.store import encode
from support.plan_fixture import save
from test_m1_g3_integration import method_commission
from test_9a_page_bindings import issue


def test_actual_checkpoint_freezes_bindings_and_replays_saved_reply(method_commission, monkeypatch):
    f=method_commission
    saved=save(f)
    ref=saved["plan_ref"]
    host=AssertionHost(f.ws.store.root)
    ids=[]
    for rule in f.plan["method_pack"]["indicators"][:2]:
        row=page_bindings.propose(f.cs,f.co,"bind-"+rule["id"],"S1",rule["id"],[])
        ids.append(row["id"])
    checkpoint=commission_plan.request_checkpoint(f.ws)
    frozen=commission_assertions.checkpoint(f.ws.store,"plan",checkpoint["issue_id"])
    assert set(frozen["page_bindings"])==set(ids)
    answer=dict(plan_ref=ref,approved=True,corrections="",reductions=[],unconfirmed_page_bindings=[ids[1]])
    import sqlite3
    from contextlib import closing
    def logical_state():
        snapshot = {}
        for name in ('state.db', 'assertions.sqlite3'):
            with closing(sqlite3.connect((f.ws.store.root / name).as_uri() + '?mode=ro', uri=True)) as db:
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                    quoted = '"' + table.replace('"', '""') + '"'
                    snapshot[(name, table)] = sorted(db.execute('SELECT * FROM ' + quoted).fetchall(), key=repr)
        return snapshot, f.cs.list_objects(), {str(p): p.read_bytes() for p in (f.ws.store.root / 'outputs').rglob('*') if p.is_file()}
    before = logical_state()
    assert commission_plan.check_reply(f.ws.store.root, checkpoint['issue_id'], answer)['writes'] == 0
    assert logical_state() == before
    original=assertions.confirm
    interrupted=[]
    def stop_after_commit(ctx,**args):
        result=original(ctx,**args)
        if args["claim"]["target"]==ids[0] and not interrupted:
            interrupted.append(True)
            raise RuntimeError("reply lost after binding confirm")
        return result
    monkeypatch.setattr(assertions,"confirm",stop_after_commit)
    with pytest.raises(RuntimeError,match="reply lost"):
        commission_plan.reply(f.ws,checkpoint["issue_id"],answer)
    assert commission_assertions.checkpoint_answer(f.ws.store,"plan",checkpoint["issue_id"])
    monkeypatch.setattr(assertions,"confirm",original)
    commission_plan.reply(f.ws,checkpoint["issue_id"],answer)
    commission_plan.reply(f.ws,checkpoint["issue_id"],answer)
    states=host.commission.current_references(f.ws.store.root,ids)
    assert states[ids[0]]["status"]=="confirmed" and states[ids[1]]["status"]=="proposed"
    assert page_bindings.sheet_route(f.ws.store,ref)

    from report_agent.assertion_host import Grant
    from uuid import NAMESPACE_URL, uuid5
    operation = 'owner-retract-binding-after-completed-reply'
    grant = Grant(str(uuid5(NAMESPACE_URL, 'owner')), 'owner', 'owner', operation, 'plan',
                  {'S1'}, {ids[0]}, {'retract'})
    assertions.retract(host.issue_once(grant, 'retract', operation), subject='S1',
        claim=dict(kind='act', effect='retract', target=ids[0], reason='Owner revises page applicability.'))
    before = logical_state()
    assert commission_plan.check_reply(f.ws.store.root, checkpoint['issue_id'], answer)['already_answered']
    assert logical_state() == before
    commission_plan.reply(f.ws, checkpoint['issue_id'], answer)
