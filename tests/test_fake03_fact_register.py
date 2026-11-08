import hashlib
import json

from pypdf import PdfReader
import pytest

from support.fake03 import REGISTER, qualitative_profile
from test_fake03_qualitative_steps import mini


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


def test_fixture_publishes_confirmed_records_and_revoked_writer_cannot_downgrade(mini, tmp_path):
    from report_agent.assertion_host import AssertionHost
    from report_agent.content_store import ContentStore
    from report_agent.errors import ActionRejected
    from report_agent.writer_assessment import read_indicator_step
    from report_agent.writer_fact_packet import packet_grant
    from report_agent.writer_runtime import writer_session
    from support.fake03 import install

    ws, binding, _ = mini
    install(ws, binding.plan_ref)
    host = AssertionHost(ws.store.root)
    archive = tmp_path / "assertions.jsonl"
    host.commission.export(archive)
    rows = [r["assertion"] for line in archive.read_bytes().splitlines() if "assertion" in (r := json.loads(line))]
    claims = [r for r in rows if r["claim"]["kind"] != "act"]
    confirmed = {r["claim"]["target"] for r in rows if r["claim"].get("effect") == "confirm"}
    assert {r["id"] for r in claims} == confirmed
    observations = [r for r in claims if r["claim"].get("predicate") == "document_observation"]
    typed = [r for r in claims if r["claim"].get("evidence_receipts")]
    unknown = [r for r in claims if r["claim"].get("state") == "unknown" and not r["claim"]["citation"]]
    assert len(observations) == 17 and len(typed) == 21
    rain, = (r["claim"] for r in typed if r["claim"]["predicate"] == "rainfall")
    assert rain["period"] == "P5Y" and rain["value"] == 720
    assert [r["subject"] for r in unknown].count("A") == 3 and [r["subject"] for r in unknown].count("B") == 7
    conflict, = (r["claim"] for r in claims if r["claim"]["kind"] == "conflict")
    assert {r["claim"]["value"] for r in typed if r["id"] in conflict["observations"]} == {"1:0.75","1:1.0"}
    grant = packet_grant(ws.store.root, binding.plan_ref, "A", binding.assessment_section_id)
    precedence = grant.resources["conventions"][conflict["precedence_convention"]]
    assert next(r["claim"]["value"] for r in typed if r["id"] == precedence["preferred"]) == "1:0.75"
    assert not {r["id"] for r in observations+typed if r["subject"] == "C"} & grant.packet
    with writer_session(ws, "坡段 A", None, assessment_only=True, indicator_steps=True,
                        section_id=binding.assessment_section_id) as writer:
        cs = ContentStore(ws.store)
        step = read_indicator_step(cs, writer.actor)
        from uuid import NAMESPACE_URL, uuid5
        issued = host.lookup((str(uuid5(NAMESPACE_URL, writer.actor.id)), "writer", writer.actor.task_id,
                              step["assignment_digest"]))
        assert not issued.actions and issued.packet == grant.packet
        host.revoke(issued)
        with pytest.raises(ActionRejected, match="WRITER_ASSIGNED_FACT_PACKET_REQUIRED"):
            read_indicator_step(cs, writer.actor)
        host.revoke(grant)
        with pytest.raises(ActionRejected, match="WRITER_ASSIGNED_FACT_PACKET_REQUIRED"):
            read_indicator_step(cs, writer.actor)
    with pytest.raises(ActionRejected, match="WRITER_ASSIGNED_FACT_PACKET_REQUIRED"):
        with writer_session(ws, "坡段 A", None, assessment_only=True, indicator_steps=True,
                            section_id=binding.assessment_section_id):
            pytest.fail("Revoked assignment template started another Writer")
