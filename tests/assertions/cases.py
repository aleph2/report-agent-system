"""Frozen Run 06 inputs and the independently recorded outcomes at 53ee2d0."""
import hashlib
import json
from decimal import Decimal
from importlib.resources import files

from report_agent.errors import ActionRejected
from support.fake03 import REGISTER, qualitative_profile
from report_agent.writer_assessment import _grade, _step_value
from report_agent.writer_claims import apply_claims
from test_run06_claim_replay import FIXTURE, submission

from .sqlite_probe import Action


CASES = {
    'A/X21': ('committed', None),
    'A/X22': ('committed', None),
    'A/X23': ('committed', None),
    'A/X32': ('flagged', 'QUESTION_EFFECT_CONFLICT'),
    'A/X41': ('committed', None),
    'A/X42': ('refused', 'facility_presence'),
    'A/X51': ('flagged', 'UNSUPPORTED_ADJUSTMENT_RETAINED_MIDPOINT'),
    'A/X52': ('refused', 'design_file_coverage'),
    'B/X21': ('committed', None),
    'B/X22': ('committed', None),
    'B/X23': ('committed', None),
    'B/X32': ('refused', 'hazard_frequency'),
    'B/X41': ('committed', None),
    'B/X42': ('committed', None),
    'B/X51': ('refused', 'survey_section_count'),
    'B/X52': ('committed', None),
}

PROFILE = qualitative_profile(hashlib.sha256(REGISTER.read_bytes()).hexdigest())
CURRENT_X51 = PROFILE['facts']['A']['engineering_reviews']['X51']
RULES = {r['id']: r for r in json.loads(files('report_agent').joinpath(
    'methods/high_slope_guideline.json').read_text(encoding='utf-8'))['indicators']}
ORIGINAL = json.loads(FIXTURE.read_bytes())['rows']


def facts(slope):
    return list({r['fact_id']:r for obj in PROFILE['facts'].values() for r in obj['attestations']}.values())


def historical_action(label):
    slope, indicator = label.split('/')
    row = ORIGINAL[label]
    proposal = {'kind': row['kind'], **submission(label, row, facts(slope))}
    return Action(operation=label, slope=slope, indicator=indicator, proposal=proposal), row


def grade_data(action):
    return next((g for g in RULES[action.indicator]['grades'] if _grade(g) == action.proposal.get('grade')), None)


def evaluate(action):
    """Use the tagged native validation and never consult the expected verdicts."""
    offered = facts(action.slope)
    band = grade_data(action)
    value = _step_value(RULES[action.indicator], action.proposal, qualitative=True, facts=offered)
    midpoint = (Decimal(band['min_value']) + Decimal(band['max_value'])) / 2 if band else None
    excerpts = [r['quote'] for obj in PROFILE['facts'].values()
                for r in [*obj['observations'], *obj['attestations']] if r.get('quote')]
    return apply_claims(value, indicator_id=action.indicator, subject=action.slope,
                        attestations=offered, midpoint=midpoint, grade_id=band['id'] if band else None,
                        registered_excerpts=excerpts)


def current_x51_gap(action):
    """Apply the current decision only in its own case; preserve the historical oracle."""
    assert (action.slope, action.indicator) == ('A', 'X51')
    if action.proposal['kind'] != 'gap':
        raise ActionRejected('WRITER_ENGINEERING_REVIEW_PENDING: use save_gap. ' + CURRENT_X51['reason'])
    row, checks = evaluate(action)
    return row, {**checks, 'engineering_review': CURRENT_X51}
