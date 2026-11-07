"""Load the owner-confirmed fact register for the isolated fake qualitative trial."""
import hashlib
import json
from pathlib import Path

REGISTER = Path(__file__).resolve().parents[2] / 'tests/fake_data/mini_commission/confirmed-facts.json'


def qualitative_profile(expected_sha256):
    raw = REGISTER.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('FAKE03_REGISTER_PIN_MISMATCH')
    register = json.loads(raw)
    facts = {}
    for obj in ('A', 'B'):
        facts[obj] = {
            'source_roles': register['source_roles'],
            'scope': register['scope'],
            'observations': [row for row in register['facts'] if row['applies_to'] in (obj, 'A, B', 'Region')],
            'unresolved': register['unresolved'][obj],
        }
    return {'facts': facts, 'midpoint_convention': register['midpoint_convention'],
            'register_sha256': expected_sha256}
