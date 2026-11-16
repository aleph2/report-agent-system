"""Typed observation qualifiers for source-grounded assessment packets."""
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SurveyExtent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    upslope_h: float = Field(allow_inf_nan=False)
    downslope_h: float = Field(allow_inf_nan=False)


class FacilityLocation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    side: Literal['upslope','downslope']
    distance_h: float = Field(allow_inf_nan=False)


class FactAttestation(BaseModel):
    """A source assertion with explicit subject, coverage and observation type."""

    model_config = ConfigDict(extra='forbid', strict=True)
    fact_id: str = Field(min_length=1)
    subject: str
    applies_to: list[str]
    related_to: list[str] = Field(default_factory=list)
    source_class: Literal['initial','revision','requirements','design','survey','drawing','regional']
    state: Literal['known','unknown','explicit_absence']
    coverage: Literal['object','region','document']
    coverage_detail: str
    purpose: Literal['geometry','material','weathering','slope_structure','construction_date','revision_scope',
        'review_instruction','slope_ratio','bench_count','engineering_measure','location',
        'survey_section_count','borehole_count','test_pit_count','survey_coverage',
        'survey_investigation_quality','groundwater_condition','groundwater_survey_coverage',
        'rainfall','hazard_event','hazard_frequency','hazard_season','facility_presence',
        'drawing_reference','drawing_contents','design_file_coverage']
    indicator_ids: list[str]
    document: str
    page: int = Field(ge=1)
    quote: str
    value: str | int | float | None
    unit: str | None = None
    event_count: int | None = Field(default=None)
    period_years: int | None = Field(default=None)
    months: list[Annotated[int, Field(ge=1,le=12)]] = Field(default_factory=list)
    survey_extent: SurveyExtent | None = None
    facility_location: FacilityLocation | None = None
    visual_verified: bool = False

    @model_validator(mode='after')
    def observation_bounds(self):
        return self


def load_attestations(path):
    rows = [FactAttestation.model_validate(row).model_dump(mode='json')
            for row in json.loads(Path(path).read_bytes())]
    return rows


def attestations_for(rows, subject):
    """Area and coverage observations stay visible with their recorded subject."""
    return [row for row in rows if subject in row['applies_to'] or subject in row['related_to']
            or row['coverage'] in ('region','document')]
