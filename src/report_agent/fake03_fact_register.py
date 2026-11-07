"""Load the owner-confirmed fact register for the isolated fake qualitative trial."""
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REGISTER = Path(__file__).resolve().parents[2] / 'tests/fake_data/mini_commission/confirmed-facts.json'


TYPED_REGISTER = Path(__file__).with_name('methods') / 'fake03-attestations.json'


class SurveyExtent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    upslope_h: float = Field(gt=0, allow_inf_nan=False)
    downslope_h: float = Field(gt=0, allow_inf_nan=False)


class FacilityLocation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    side: Literal['upslope','downslope']
    distance_h: float = Field(ge=0, allow_inf_nan=False)


class FactAttestation(BaseModel):
    """A source assertion with explicit subject, coverage and observation type."""

    model_config = ConfigDict(extra='forbid', strict=True)
    fact_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    applies_to: list[str]
    related_to: list[str] = Field(default_factory=list)
    source_class: Literal['initial','revision','requirements','design','survey','drawing','regional']
    state: Literal['known','unknown','explicit_absence']
    coverage: Literal['object','region','document']
    coverage_detail: str = Field(min_length=1)
    purpose: Literal['geometry','material','weathering','slope_structure','construction_date','revision_scope',
        'review_instruction','slope_ratio','bench_count','engineering_measure','location',
        'survey_section_count','borehole_count','test_pit_count','survey_coverage',
        'survey_investigation_quality','groundwater_condition','groundwater_survey_coverage',
        'rainfall','hazard_event','hazard_frequency','hazard_season','facility_presence',
        'drawing_reference','drawing_contents','design_file_coverage']
    indicator_ids: list[str]
    document: str = Field(min_length=1)
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    value: str | int | float | None
    unit: str | None = None
    event_count: int | None = Field(default=None, ge=0)
    period_years: int | None = Field(default=None, gt=0)
    months: list[Annotated[int, Field(ge=1,le=12)]] = Field(default_factory=list)
    survey_extent: SurveyExtent | None = None
    facility_location: FacilityLocation | None = None
    visual_verified: bool = False

    @model_validator(mode='after')
    def observation_bounds(self):
        if self.state=='unknown' and (self.value is not None or self.event_count is not None):
            raise ValueError('Unknown facts cannot carry a measured value or count')
        if self.purpose=='hazard_frequency' and (
                self.event_count is None or self.period_years is None or not self.applies_to):
            raise ValueError('A frequency requires an applicable event count and observation period')
        if self.event_count is not None and self.purpose not in ('hazard_event','hazard_frequency'):
            raise ValueError('Event counts belong only to event observations')
        if self.visual_verified and (self.source_class!='drawing' or self.purpose!='drawing_contents'):
            raise ValueError('Visual verification applies only to observed drawing contents')
        if (self.survey_extent or self.facility_location) and self.purpose!='facility_presence':
            raise ValueError('Facility survey and location measurements require a facility observation')
        if self.months and (self.purpose!='hazard_season' or len(set(self.months))!=len(self.months)):
            raise ValueError('Season months must be distinct and tied to a hazard-season observation')
        if self.purpose=='drawing_contents' and not self.visual_verified:
            raise ValueError('Drawing contents require verified inspection')
        return self


def load_attestations(path):
    rows = [FactAttestation.model_validate(row).model_dump(mode='json')
            for row in json.loads(Path(path).read_bytes())]
    if len({row['fact_id'] for row in rows}) != len(rows):
        raise ValueError('DUPLICATE_ATTESTED_FACT_ID')
    return rows


def attestations_for(rows, subject):
    """Area and coverage observations stay visible with their recorded subject."""
    return [row for row in rows if subject in row['applies_to'] or subject in row['related_to']
            or row['coverage'] in ('region','document')]


def qualitative_profile(expected_sha256):
    raw = REGISTER.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('FAKE03_REGISTER_PIN_MISMATCH')
    register = json.loads(raw)
    typed = load_attestations(TYPED_REGISTER)
    facts = {}
    for obj in ('A', 'B'):
        facts[obj] = {
            'source_roles': register['source_roles'],
            'scope': register['scope'],
            'attestations': attestations_for(typed, obj),
            'observations': [row for row in register['facts'] if row['applies_to'] in (obj, 'A, B', 'Region')],
            'unresolved': register['unresolved'][obj],
        }
    return {'facts': facts, 'midpoint_convention': register['midpoint_convention'],
            'register_sha256': expected_sha256}
