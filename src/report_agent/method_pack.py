"""Versioned, source-bound method data. Selection belongs to the commission."""
from decimal import Decimal, InvalidOperation

from pydantic import Field, model_validator

from .content_models import Contract, SourceCitation


def number(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise ValueError('finite decimal string required')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('finite decimal string required') from exc
    if not result.is_finite() or (result and abs(result.adjusted()) > 100):
        raise ValueError('finite bounded decimal required')
    return result


def unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError('duplicate ' + label)


class GradeBand(Contract):
    id: str = Field(min_length=1)
    min_value: str
    max_value: str
    description: str = Field(min_length=1)

    @model_validator(mode='after')
    def bounds(self):
        if number(self.min_value) > number(self.max_value):
            raise ValueError('reversed grade bounds')
        return self


class IndicatorRule(Contract):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    category: str = ''
    notes: str = ''
    grades: list[GradeBand] = Field(min_length=1)

    @model_validator(mode='after')
    def distinct(self):
        unique([g.id for g in self.grades], 'grade')
        ordered = sorted(self.grades, key=lambda g: number(g.min_value))
        if any(number(a.max_value) >= number(b.min_value) for a, b in zip(ordered, ordered[1:])):
            raise ValueError('overlapping grade bands')
        return self


class RiskBand(Contract):
    level: str = Field(min_length=1)
    lower: str
    upper: str
    lower_inclusive: bool = True
    upper_inclusive: bool = False

    @model_validator(mode='after')
    def bounds(self):
        if number(self.lower) >= number(self.upper):
            raise ValueError('reversed risk band')
        return self


class WeightRow(Contract):
    indicator_count: int = Field(strict=True, ge=1, le=1000)
    weights: list[str]

    @model_validator(mode='after')
    def usable(self):
        if len(self.weights) != self.indicator_count or any(number(w) < 0 for w in self.weights):
            raise ValueError('invalid weight count or negative weight')
        if not any(number(w) > 0 for w in self.weights):
            raise ValueError('all weights are zero')
        return self


class WeightTable(Contract):
    id: str = Field(min_length=1)
    source: SourceCitation
    rows: list[WeightRow] = Field(min_length=1)

    @model_validator(mode='after')
    def distinct(self):
        unique([r.indicator_count for r in self.rows], 'weight count')
        return self


class MethodPack(Contract):
    method_id: str = Field(min_length=1)
    version: int = Field(strict=True, ge=1)
    sources: list[SourceCitation] = Field(min_length=1)
    indicators: list[IndicatorRule] = Field(min_length=1, max_length=1000)
    risk_bands: list[RiskBand] = Field(min_length=1)
    weight_tables: list[WeightTable] = Field(min_length=1)

    @model_validator(mode='after')
    def unambiguous(self):
        unique([i.id for i in self.indicators], 'indicator')
        unique([t.id for t in self.weight_tables], 'weight table')
        unique([b.level for b in self.risk_bands], 'risk level')
        bands = sorted(self.risk_bands, key=lambda b: number(b.lower))
        for a, b in zip(bands, bands[1:]):
            if number(a.upper) != number(b.lower) or a.upper_inclusive == b.lower_inclusive:
                raise ValueError('gap or overlap in risk bands')
        return self


def bind_guideline(source_ref, file_digest):
    """Bind the reviewed transcription only to the exact verified source bytes."""
    import json
    from importlib.resources import files
    data = json.loads(files('report_agent').joinpath('methods/high_slope_guideline.json').read_text(encoding='utf-8'))
    if file_digest != data['metadata']['file_sha256']:
        raise ValueError('METHOD_SOURCE_HASH_MISMATCH')
    def cite(page):
        return {'source_ref': source_ref, 'locator': f'page {page}', 'quote': ''}
    payload = {
        'method_id': data['metadata']['name'], 'version': 1,
        'sources': [cite(p) for p in data['metadata']['pages']],
        'indicators': [{k: v for k, v in i.items() if k != 'source_pages'} for i in data['indicators']],
        'risk_bands': [{k: v for k, v in b.items() if k != 'label'} for b in data['risk_bands']],
        'weight_tables': [{'id': t['id'], 'source': cite(t['source_page']), 'rows': t['rows']} for t in data['weight_tables']]}
    return MethodPack.model_validate(payload).model_dump(mode='json')


def register_reviewed_method_pack(store, pack, review_note):
    """Trusted host entry, never an agent tool; preserve the exact reviewed data hash."""
    from .store import digest, encode
    import json
    validated = MethodPack.model_validate(pack).model_dump(mode='json')
    if not isinstance(review_note, str) or not review_note.strip():
        raise ValueError('METHOD_REVIEW_NOTE_REQUIRED')
    pack_digest = digest(validated)
    identity = 'reviewed_method_identity:' + digest([validated['method_id'], validated['version']])
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute('SELECT value FROM state WHERE key=?', (identity,)).fetchone()
        if previous and json.loads(previous[0]) != pack_digest:
            raise ValueError('METHOD_VERSION_ALREADY_REVIEWED')
        db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (identity, encode(pack_digest)))
        db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('reviewed_method_pack:' + pack_digest,
            encode({'reviewer': 'operator', 'review_note': review_note})))


def reviewed_method_questions(cs, db, pack):
    from .commission_plan import _state
    from .store import digest
    for citation in pack['sources']:
        source = cs._read(db, citation['source_ref'])['payload']
        try:
            reviewed = bind_guideline(citation['source_ref'], source['file_digest'])
        except ValueError as exc:
            if str(exc) != 'METHOD_SOURCE_HASH_MISMATCH':
                raise
            continue
        if pack != reviewed:
            from .errors import ActionRejected
            raise ActionRejected('METHOD_REVIEWED_DATA_CHANGED')
        return []
    review = _state(db, 'reviewed_method_pack:' + digest(pack))
    return [] if review and review.get('reviewer') == 'operator' and review.get('review_note') else ['方法包数据尚未独立审查，不能开始编写']
