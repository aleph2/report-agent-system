import hashlib
import json

from pypdf import PdfReader
import pytest

from report_agent.fake03_fact_register import REGISTER, qualitative_profile


def test_reviewed_register_binds_exact_quotes_page_roles_and_owner_qualifications():
    raw = REGISTER.read_bytes()
    register = json.loads(raw)
    profile = qualitative_profile(hashlib.sha256(raw).hexdigest())
    assert len(register['facts']) == 17
    for fact in register['facts']:
        page = PdfReader(REGISTER.parent / 'inputs' / fact['document']).pages[fact['page'] - 1]
        assert fact['quote'] in page.extract_text()
    for obj, packet in profile['facts'].items():
        assert packet['source_roles']['03_requirements.pdf'].startswith('审核要求')
        assert 'groundwater' in ' '.join(packet['unresolved']).lower()
        assert any('720 mm' in row['quote'] for row in packet['observations'])
        assert '中点' in profile['midpoint_convention']
        assert 'scripted' in packet['scope']
        if obj == 'A':
            assert sum('placement' in row['fact'] for row in packet['observations']) == 2
            assert 'geophysics' in ' '.join(packet['unresolved'])
        else:
            assert 'support' in ' '.join(packet['unresolved']).lower()
            assert not any('三个钻孔' in row['quote'] for row in packet['observations'])
            assert any('距坡段 A' in row['quote'] and row['applies_to'] == 'Region' for row in packet['observations'])
    with pytest.raises(ValueError, match='REGISTER_PIN'):
        qualitative_profile('0' * 64)
