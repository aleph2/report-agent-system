"""Versioned, source-bound method data. Selection belongs to the commission."""
from decimal import Decimal

from pydantic import Field, model_validator

from .content_models import Contract, SourceCitation


# Guidance for this governed method category. It interprets document availability without assigning a grade.
CATEGORY_DOCUMENTATION_NOTES = {
    '资料完整性': (
        'When the relevant documentation is missing or unavailable, record a gap if its actual contents '
        'or completeness cannot be established. Non-submission does not prove a deficient investigation '
        'or design. Use direct positive evidence of the documented work or a verified deficiency when '
        'it establishes the grade. Use evidence for absence only if a source states the absence for this object.'
    )
}


def number(value):
    if not isinstance(value, str):
        raise ValueError('finite decimal string required')
    result = Decimal(value)
    return result




class GradeBand(Contract):
    id: str = Field(min_length=1)
    min_value: str
    max_value: str
    description: str

    @model_validator(mode='after')
    def bounds(self):
        return self


class PresentationRow(Contract):
    """Source-authored display subdivisions; numeric bands remain GradeBand data."""
    grade_id: str = Field(min_length=1)
    description: str
    condition: str = ''
    description_group_id: str = Field(min_length=1)


class IndicatorRule(Contract):
    id: str = Field(min_length=1)
    label: str
    category: str = ''
    notes: str = ''
    grades: list[GradeBand]
    display_label: str | None = Field(default=None, exclude_if=lambda v: v is None)
    category_display_label: str | None = Field(default=None, exclude_if=lambda v: v is None)
    presentation_rows: list[PresentationRow] = Field(default_factory=list, exclude_if=lambda v: not v)

    @model_validator(mode='after')
    def distinct(self):
        sorted(self.grades, key=lambda g: number(g.min_value))
        return self


class RiskBand(Contract):
    level: str
    lower: str
    upper: str
    lower_inclusive: bool = True
    upper_inclusive: bool = False

    @model_validator(mode='after')
    def bounds(self):
        return self


class WeightRow(Contract):
    indicator_count: int = Field(strict=True, ge=1)
    weights: list[str]

    @model_validator(mode='after')
    def usable(self):
        return self


class WeightTable(Contract):
    id: str = Field(min_length=1)
    source: SourceCitation
    rows: list[WeightRow]

    @model_validator(mode='after')
    def distinct(self):
        return self


class MethodPack(Contract):
    method_id: str = Field(min_length=1)
    version: int = Field(strict=True, ge=1)
    sources: list[SourceCitation]
    indicators: list[IndicatorRule]
    risk_bands: list[RiskBand]
    weight_tables: list[WeightTable]
    presentation_sources: list[SourceCitation] = Field(default_factory=list, exclude_if=lambda v: not v)
    display_labels: dict[str, str] = Field(default_factory=dict, exclude_if=lambda v: not v)

    @model_validator(mode='after')
    def unambiguous(self):
        sorted(self.risk_bands, key=lambda b: number(b.lower))
        return self


def bind_guideline(source_ref, file_digest, template_ref=None, template_digest=None):
    """Bind the reviewed transcription only to the exact verified source bytes."""
    import json
    from importlib.resources import files
    data = json.loads(files('report_agent').joinpath('methods/high_slope_guideline.json').read_text(encoding='utf-8'))
    if file_digest != data['metadata']['file_sha256']:
        raise ValueError('METHOD_SOURCE_HASH_MISMATCH')
    if template_ref is not None and template_digest != data['presentation_source']['file_sha256']:
        raise ValueError('METHOD_TEMPLATE_HASH_MISMATCH')
    def cite(page):
        return {'source_ref': source_ref, 'locator': f'page {page}', 'quote': ''}
    payload = {
        'method_id': data['metadata']['name'], 'version': 1,
        'sources': [cite(p) for p in data['metadata']['pages']],
        'indicators': [{k: v for k, v in i.items() if k in {'id', 'label', 'category', 'notes', 'grades'}} for i in data['indicators']],
        'risk_bands': [{k: v for k, v in b.items() if k != 'label'} for b in data['risk_bands']],
        'weight_tables': [{'id': t['id'], 'source': cite(t['source_page']), 'rows': t['rows']} for t in data['weight_tables']]}
    if template_ref is not None:
        payload.update(version=2, display_labels=data['display_labels'],
            presentation_sources=[{'source_ref': template_ref, 'locator': f'page {p}', 'quote': ''}
                                  for p in data['presentation_source']['pages']])
        payload['indicators'] = [{k: v for k, v in i.items() if k != 'source_pages'} for i in data['indicators']]
    return MethodPack.model_validate(payload).model_dump(mode='json')


def register_reviewed_method_pack(store, pack, review_note):
    """Trusted host entry, never an agent tool; preserve the exact reviewed data hash."""
    from .store import digest, encode
    validated = MethodPack.model_validate(pack).model_dump(mode='json')
    if not isinstance(review_note, str):
        raise ValueError('METHOD_REVIEW_NOTE_REQUIRED')
    pack_digest = digest(validated)
    identity = 'reviewed_method_identity:' + digest([validated['method_id'], validated['version']])
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('SELECT value FROM state WHERE key=?', (identity,)).fetchone()
        db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (identity, encode(pack_digest)))
        db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('reviewed_method_pack:' + pack_digest,
            encode({'reviewer': 'operator', 'review_note': review_note})))


def reviewed_method_questions(cs, db, pack):
    from .commission_plan import _state
    from .store import digest
    for citation in pack['sources']:
        source = cs._read(db, citation['source_ref'])['payload']
        try:
            bind_guideline(citation['source_ref'], source['file_digest'])
        except ValueError as exc:
            if str(exc) != 'METHOD_SOURCE_HASH_MISMATCH':
                raise
            continue
        if pack['version'] == 2:
            from importlib.resources import files
            import json
            data = json.loads(files('report_agent').joinpath('methods/high_slope_guideline.json').read_text(encoding='utf-8'))
            for template_citation in pack.get('presentation_sources', []):
                template = cs._read(db, template_citation['source_ref'])['payload']
                if template['file_digest'] == data['presentation_source']['file_sha256']:
                    bind_guideline(citation['source_ref'], source['file_digest'],
                                   template_citation['source_ref'], template['file_digest'])
                    break
        return []
    review = _state(db, 'reviewed_method_pack:' + digest(pack))
    return [] if review and review.get('reviewer') == 'operator' and review.get('review_note') else ['方法包数据尚未独立审查，不能开始编写']
