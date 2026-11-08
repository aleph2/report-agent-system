"""Offline routing and host-owned arithmetic on the restricted fake03 qualitative run."""
import hashlib
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from support.fake03 import install
from langchain_core.messages import HumanMessage

from report_agent.content_store import ContentStore
from report_agent.errors import ActionRejected
from report_agent.mini_commission import prepare_mini_commission
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.writer_indicator_steps import run_mini_assessment
from test_deep_runtime import Driver
from test_writer_five_slopes import action


@pytest.fixture
def mini(tmp_path, monkeypatch):
    from report_agent import fake_verification
    case = tmp_path/'case'
    prepared = prepare_mini_commission(Path(__file__).parent/'fake_data'/'mini_commission'/'inputs', case)
    ws = Workspace(Store(case))
    binding = SimpleNamespace(qualitative_only=True, plan_ref=prepared['plan_ref'],
                              assessment_section_id=prepared['assessment_section_id'])
    def verify(run, workspace):
        assert run is binding and workspace is ws
    monkeypatch.setattr(fake_verification, 'assert_active_fake_run', verify)
    from support.fake03 import REGISTER, qualitative_profile
    profile = qualitative_profile(hashlib.sha256(REGISTER.read_bytes()).hexdigest())
    return ws, binding, profile


@pytest.mark.asyncio
async def test_fresh_profile_and_verified_qualitative_authority_must_agree(mini):
    ws, binding, profile = mini
    with pytest.raises(ActionRejected, match='FAKE_QUALITATIVE_PROFILE_MISMATCH'):
        await run_mini_assessment(ws, None, verified_run=binding)
    install(ws, binding.plan_ref, profile)
    binding.qualitative_only=False
    with pytest.raises(ActionRejected, match='FAKE_QUALITATIVE_PROFILE_MISMATCH'):
        await run_mini_assessment(ws, None, verified_run=binding)


@pytest.mark.asyncio
@pytest.mark.parametrize('interrupt',[False,True])
async def test_verified_mini_saves_true_subset_and_preserves_full_ranks_without_scoring(mini, interrupt):
    ws, binding, profile = mini
    # This historical routing/arithmetic driver proposes synthetic grades. Replay its original
    # untyped contract; test_run06_claim_replay exercises the current native scored contract.
    for assigned in profile['facts'].values():
        assigned.pop('attestations', None)
        assigned.pop('engineering_reviews', None)  # This fixture replays the pre-deferral routing contract.
    install(ws, binding.plan_ref, profile)
    cs=ContentStore(ws.store)
    plan=cs.read(binding.plan_ref)['payload']
    rank_order=plan['indicator_rank_order']['indicator_ids']
    seen=[]
    expected={}
    count={}
    labels={o['label']:o['object_id'] for o in plan['objects']}
    def choose(messages):
        packet=json.loads(next(m.content for m in messages if isinstance(m,HumanMessage)))
        oid=labels[packet['object_label']]
        ind=packet['indicator_id']
        assert packet['rank']==rank_order.index(ind)+1 and packet['approved_method']['indicator_count']==11
        assert packet['object_facts']==profile['facts'][oid] and packet['midpoint_convention']==profile['midpoint_convention']
        assert profile['register_sha256'] not in json.dumps(packet)
        assert packet['progress']['total']==8
        token=(oid,ind)
        count[token]=count.get(token,0)+1
        seen.append(token)
        band=packet['grades'][(len(set(seen))-1)%4]
        midpoint=(Decimal(band['min_value'])+Decimal(band['max_value']))/2
        quote=next(a['values'][0]['source']['quote'] for a in packet['inventory_facts'] if a['name']=='坡高（m）')
        judgment=dict(grade=band['choice'],quotes=[quote],basis_kind='direct_evidence',rationale='Synthetic routing exercise.')
        if ind=='X21' and oid=='A':
            judgment['value']=str(midpoint+1)
            if not interrupt and count[token]==2:
                judgment['value_reason']='The recorded condition is more severe within the adopted band.'
            expected[token]=midpoint+1
        else:
            expected[token]=midpoint
        return action('save_evidence',f'test-{len(seen)}',**judgment)
    result=await run_mini_assessment(ws, Driver(writer=[choose]*25)('writer'), verified_run=binding)
    assert result['scope']=='qualitative_writer_only'
    assert result['status']==('incomplete' if interrupt else 'qualitative_rows_saved'), result['slopes'][0]['indicator_steps']['interrupted_indicators'].get('X22')
    expected_ids={'X21','X22','X23','X32','X41','X42','X51','X52'}
    assert set(seen)=={(oid,i) for oid in ('A','B') for i in expected_ids}
    assert len(seen)==17
    for slope in result['slopes']:
        oid=slope['object_id']
        partial=interrupt and oid=='A'
        assert slope['indicator_steps']['progress']=={'recorded':7 if partial else 8,'total':8}
        assert set(slope['indicator_steps']['interrupted_indicators'])==({'X21'} if partial else set())
        assert slope['indicator_steps']['assessment_ref'] is None and not slope['indicator_steps']['gap_indicators']
    with cs.store.connect() as db:
        drafts=[json.loads(x[0]) for x in db.execute("SELECT value FROM state WHERE key LIKE 'writer_indicator_steps:%' ORDER BY rowid")]
    assert len(drafts)==2
    for oid,draft in zip(('A','B'),drafts,strict=True):
        for ind,row in draft['rows'].items():
            assert Decimal(row['input']['value'])==expected[oid,ind]
            assert row['rank']==rank_order.index(ind)+1
        if oid=='A' and not interrupt:
            assert draft['rows']['X21']['input']['value_reason'].startswith('The recorded condition')
    assert not cs.list_objects('Assessment')
