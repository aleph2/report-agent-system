"""Replay the real saved business fields. Only the new claim-to-register links are annotated."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from support.fake03 import install
from langchain_core.messages import HumanMessage

from report_agent import fake_verification
from support.fake03 import REGISTER, qualitative_profile
from report_agent.mini_commission import prepare_mini_commission
from report_agent.qualitative_review import qualitative_reviewer_session
from report_agent.store import Store, digest
from report_agent.workspace import Workspace
from report_agent.writer_indicator_steps import run_mini_assessment
from test_deep_runtime import Driver
from test_writer_five_slopes import action

FIXTURE = Path(__file__).parent / 'fixtures/fake03_run06_saved_inputs.json'
REFUSE = {
    'A/X42': 'Provide observed facility locations or a survey covering the required distances.',
    'A/X52': 'Confirm which A-specific drawings were inspected and what their coverage establishes.',
    'B/X32': 'Provide a hazard history covering B with a defined observation period.',
    'B/X51': 'Provide counts or an explicit zero finding from an investigation covering B.',
}
# Map each historical proposition to the observations it actually relied upon.
# These are replay inputs, never expected outcomes or runtime configuration.
GRADE = {
    'A/X21': ('Strongly weathered rock', ['A-WEATHERING']),
    'A/X32': ('Occasional local hazards are provisionally plausible', ['OFFSITE-ROCKFALL']),
    'A/X41': ('The frame-beam anchorage is an anchor treatment', ['A-PROTECTION']),
    'A/X42': ('All listed facilities are outside the distance thresholds', ['ROCKFALL-LOCATION','A-MATERIAL']),
    'A/X51': ('One section and three investigation points are documented', ['A-SURVEY-SECTIONS','A-BOREHOLES']),
    'A/X52': ('A has a relatively complete drawing set', ['A-PROTECTION','B-DRAWING-REFERENCE']),
    'B/X32': ('Only one rockfall in five years in the area of B', ['OFFSITE-ROCKFALL','REGIONAL-RAIN']),
    'B/X51': ('Zero investigation sections and points on B', ['SURVEY-COVERAGE','B-WATER-RECORD']),
}


def claim(statement, ids):
    return {'statement': statement, 'fact_ids': ['F03-' + value for value in ids]}


def submission(label, original, facts):
    keep = {'question', 'rationale', 'quotes'}
    if original['kind'] == 'gap':
        keep.add('missing')
    else:
        keep.update(('grade', 'value'))
        if original['kind'] == 'assumption':
            keep.add('plausible_grades')
        else:
            keep.add('basis_kind')
        if original.get('value_reason'):
            keep.add('value_reason')
    payload = {k:deepcopy(original[k]) for k in keep if k in original and original[k] != ''}
    ids, external = [], []
    for quote in payload.pop('quotes', []):
        matches = [f['fact_id'] for f in facts if f.get('quote') and quote in f['quote']]
        if matches:
            ids.extend(matches)
        else:
            external.append(quote)
    if external:
        payload['quotes'] = external
    if original['kind'] == 'gap':
        payload['fact_ids'] = list(dict.fromkeys(ids))
        return payload
    payload['context_fact_ids'] = list(dict.fromkeys(ids))
    payload['grade_claim'] = claim(*GRADE[label])
    if label in ('A/X32','A/X52'):
        event = label == 'A/X32'
        payload['assumption_basis'] = {
            **claim('Use the nearby offsite event as a provisional proxy.' if event else 'Assume this drawing also supports A.',
                    ['OFFSITE-ROCKFALL','ROCKFALL-LOCATION'] if event else ['B-DRAWING-REFERENCE','A-PROTECTION']),
            'relationship': 'Small event outside A, about 2 km away.' if event else 'The same package contains a B cross-section reference.',
            'narrowing': 'Rare or occasional remain plausible.' if event else 'The file list omits other drawings, leaving the two least complete bands.',
        }
    if label in ('A/X32','A/X51'):
        payload['adjustment_claim'] = {**claim(original['value_reason'],
            ['OFFSITE-ROCKFALL','ROCKFALL-LOCATION'] if label=='A/X32' else ['A-BOREHOLES','SURVEY-COVERAGE']),
            'direction':'lower' if label=='A/X32' else 'higher'}
    if label == 'A/X32':
        payload['question_effect'] = 'grade'  # The original question explicitly requests raising the grade.
    if label == 'B/X32':
        payload['event_frequency'] = {'fact_id':'F03-REGIONAL-RAIN','event_count':1,'period_years':5}
    if label in ('A/X51','B/X51'):
        items = [('A-SURVEY-SECTIONS','survey_section_count',1),('A-BOREHOLES','borehole_count',3)] if label=='A/X51' else [
            ('SURVEY-COVERAGE','survey_section_count',0),('SURVEY-COVERAGE','borehole_count',0)]
        payload['investigation_counts'] = [{'fact_id':'F03-'+fid,'purpose':p,'count':n} for fid,p,n in items]
    return payload


@pytest.mark.asyncio
async def test_all_run06_rows_through_native_tools(tmp_path, monkeypatch):
    baseline = json.loads(FIXTURE.read_bytes())
    original = baseline['rows']
    case = tmp_path/'case'
    prepared = prepare_mini_commission(REGISTER.parent/'inputs', case)
    ws = Workspace(Store(case))
    profile = qualitative_profile(hashlib.sha256(REGISTER.read_bytes()).hexdigest())
    install(ws, prepared['plan_ref'], profile)
    binding = SimpleNamespace(plan_ref=prepared['plan_ref'], assessment_section_id=prepared['assessment_section_id'],
                              qualitative_only=True)
    def verify_binding(obj, workspace):
        assert obj is binding and workspace is ws
    monkeypatch.setattr(fake_verification, 'assert_active_fake_run', verify_binding)
    attempts = Counter()
    annotations = {}
    diagnostics = {}
    def choose(messages):
        packet = json.loads(next(m.content for m in messages if isinstance(m, HumanMessage)))
        oid = next(o for o in ('A','B') if packet['object_facts'] == profile['facts'][o])
        # Taken from the pre-M1 register projection at a1e2d4b, including the exact list order.
        expected = {'A':'2685dffdc6ab29db0a1323e9ab7578a9666b59f3155c5f85dcadfe4c88f9c7a8',
                    'B':'aba3e0d0cb876443eed59570a16d4971af51b8d418902d0cad5946661cb1d96a'}
        content = json.dumps([packet['object_facts'], packet['midpoint_convention']],
                             sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        assert hashlib.sha256(content).hexdigest() == expected[oid]
        label = oid + '/' + packet['indicator_id']
        attempts[label] += 1
        if label == 'A/X51':
            assert packet['engineering_review']['conditional_grades'] == ['low','moderate']
            return action('save_gap', label+'-deferred', missing='X51 band interpretation is deferred.',
                          fact_ids=['F03-A-SURVEY-SECTIONS','F03-A-BOREHOLES'],
                          question='Which low-band reading and overlap convention apply?')
        if attempts[label] == 1:
            facts = [*packet['object_facts']['attestations'], *packet.get('other_context_facts', [])]
            payload = submission(label, original[label], facts)
            annotations[label] = deepcopy(payload)
            return action('save_'+original[label]['kind'], label+'-original', **payload)
        assert label in REFUSE and attempts[label]==2, (label, str(messages[-1].content)[:650])
        diagnostics[label] = json.loads(messages[-1].content)
        return action('save_gap', label+'-offline-followup',
                      missing=REFUSE[label], question=REFUSE[label])
    result = await run_mini_assessment(ws, Driver(writer=[choose]*24)('writer'), verified_run=binding)
    assert result['status']=='qualitative_rows_saved', result
    assert set(attempts) == set(original)
    assert {label for label,n in attempts.items() if n==2} == set(REFUSE)
    for label, diagnostic in diagnostics.items():
        assert 'save_gap' in json.dumps(diagnostic), (label, diagnostic)
    report = {'source_run':baseline['run_id'], 'receipt_sha256':baseline['receipt_sha256'],
              'register_sha256':profile['register_sha256'], 'rows':{},'writer_task_refs':{}}
    report['reviewer_views'] = {}
    with ws.store.connect() as db:
        tasks = [json.loads(v) for v, in db.execute("SELECT data FROM content_versions WHERE type='DelegatedTask' AND version=1")]
    for task in tasks:
        oid = task['payload']['assessment_object_id']
        report['writer_task_refs'][oid] = task['ref']
        with qualitative_reviewer_session(ws, task['ref']) as tools:
            assert set(tools) == {'read_qualitative_row', 'record_qualitative_finding'}
            index = tools['read_qualitative_row']()
            assert index['object_id'] == oid and len(index['rows']) == 8
            for ind, row_digest in index['rows'].items():
                view = tools['read_qualitative_row'](ind)
                e = view['saved_row']
                assert digest(e) == view['row_digest'] == row_digest
                assert view['object_facts'] == profile['facts'][oid]
                report['reviewer_views'][oid+'/'+ind] = view
                label=oid+'/'+ind
                checks=e.get('claim_checks',{})
                after=e['input']
                if label in REFUSE:
                    assert after['kind']=='gap' and 'WRITER_CLAIM_UNSUPPORTED' in json.dumps(diagnostics[label]), label
                    disposition='original refused; scripted gap saved'
                elif label=='A/X51':
                    assert e['kind']=='gap' and after['grade'] is None and after['value'] is None
                    assert 'judgment' not in e
                    key = json.loads((REGISTER.parents[3]/'docs/verification/fake03-qualitative-x51-answer-key.json').read_bytes())
                    assert key['decision_sha256'] == hashlib.sha256(REGISTER.with_name('engineering-review.json').read_bytes()).hexdigest()
                    assert (e['kind'], after['grade'], after['value']) == (key['kind'], key['grade'], key['value'])
                    assert checks['engineering_review']['conditional_grades'] == key['conditional_grades'] == ['low','moderate']
                    disposition='owner-deferred unscored gap with conditional low and moderate'
                elif label=='A/X32':
                    assert after['kind']=='assumption' and after['grade']==original[label]['grade']
                    assert 'QUESTION_EFFECT_CONFLICT' in json.dumps(checks), checks
                    assert after['question']==original[label]['question']
                    disposition='assumption preserved; original question flagged'
                else:
                    assert all(after[k]==original[label][k] for k in ('kind','grade','value','rationale','question','missing')), label
                    disposition='control retained'
                report['rows'][label]={'disposition':disposition,'old':original[label], 'annotations':annotations.get(label),
                                     'stored_input':after,'claim_checks':checks,'rejection':diagnostics.get(label),
                                     'saved_row_digest':digest(e)}
            if oid == 'A':
                before = tools['read_qualitative_row']('X32')
                finding = tools['record_qualitative_finding'](
                    'offline-A-X32', 'X32', before['row_digest'],
                    'Offline scripted finding. The question raises the grade, but season affects the value within the band.')
                assert tools['read_qualitative_row']('X32') == before
                report['scripted_finding'] = finding['result']
    assert len(report['rows']) == len(report['reviewer_views']) == 16
    from report_agent.assertions.launch import Commission
    archive = tmp_path / "m3-fake03.jsonl"
    Commission(case).export(archive)
    records = [json.loads(line) for line in archive.read_bytes().splitlines()]
    results = [entry["assertion"] for entry in records if entry.get("action") == "derive_result"
               and entry["assertion"]["claim"].get("assessment")]
    assert sorted(row["subject"] for row in results) == ["A", "B"]
    report["derived_results"] = {}
    for row in results:
        subject, result_claim = row["subject"], row["claim"]
        assessment = result_claim["assessment"]
        observed = {view["saved_row"]["assertion_id"] for key, view in report["reviewer_views"].items()
                    if key.startswith(subject + "/")}
        assert len(observed) == len(result_claim["inputs"]) == 8
        assert set(result_claim["inputs"]) == observed
        assert assessment["status"] == "unscored" and assessment.get("adopted") is None
        assert result_claim["value"] is None and result_claim["strength"] == "undetermined"
        assert {"X11", "X12", "X31"} <= set(assessment["missing_indicators"])
        report["derived_results"][subject] = {"assertion_id": row["id"], **result_claim}
    cold = Commission(tmp_path / "restored-calculator")
    cold.restore(archive)
    restored = tmp_path / "restored.jsonl"
    cold.export(restored)
    assert restored.read_bytes() == archive.read_bytes()
    if dest:=os.environ.get('FAKE03_OFFLINE_REPLAY_RECORD'):
        Path(dest).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
