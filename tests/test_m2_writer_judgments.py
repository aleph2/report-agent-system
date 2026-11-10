"""One real Writer save is a durable assertion; an interrupted step remains runtime work."""
from report_agent import issue_state
import json
import pytest

from report_agent.assertion_host import AssertionHost
from report_agent.content_store import ContentStore
from report_agent.writer_assessment import interrupt_indicator_step, read_indicator_step, save_indicator_outcome
from report_agent.writer_runtime import writer_session
from support.fake03 import install
from test_fake03_qualitative_steps import mini


def records(host, path):
    host.commission.export(path)
    return [r["assertion"] for line in path.read_bytes().splitlines() if "assertion" in (r := json.loads(line))]


def test_save_and_interrupt_have_distinct_durable_effects(mini, tmp_path):
    ws, binding, _ = mini
    install(ws, binding.plan_ref)
    cs, host = ContentStore(ws.store), AssertionHost(ws.store.root)
    with writer_session(ws, "坡段 A", None, assessment_only=True, indicator_steps=True, section_id="3") as run:
        first = read_indicator_step(cs, run.actor)
        outcome = {"kind":"gap", "question":"What rock subtype is documented?", "missing":"Rock subtype",
                   "fact_ids":["F03-A-WEATHERING"]}
        saved = save_indicator_outcome(cs, run.actor, "gap-call", first["indicator_id"], outcome)
        assert save_indicator_outcome(cs, run.actor, "gap-call", first["indicator_id"], outcome) == saved
        rows = records(host, tmp_path/"saved.jsonl")
        row, = [r for r in rows if r["claim"]["kind"] == "judgment"]
        assert row["subject"] == "A" and row["was_generated_by"] == run.actor.task_id
        assert row["claim"]["basis"] == "gap" and row["claim"]["value"] is None and row["grounds"]
        assert "submission_receipt" not in row["claim"]
        assert host.commission.judgment_details(row["id"])["original"] == outcome
        second = read_indicator_step(cs, run.actor)
        refusals = [dict(tool="save_gap", code="bad", tool_call_id=f"r-{n}") for n in (1,2)]
        interrupt_indicator_step(cs, run.actor, second["indicator_id"], refusals)
        assert read_indicator_step(cs, run.actor)["interrupted_indicators"][second["indicator_id"]]["refusals"] == refusals
        assert records(host, tmp_path/"interrupted.jsonl") == rows


@pytest.mark.parametrize('domain_failure', [False, True])
def test_lost_task_commit_recovers_original_judgment_without_second_save(mini, tmp_path, monkeypatch, domain_failure):
    from report_agent.errors import ActionRejected, LocalStorageBusy
    from report_agent import writer_judgments as journal
    ws, binding, _ = mini
    install(ws, binding.plan_ref)
    cs, host = ContentStore(ws.store), AssertionHost(ws.store.root)
    with writer_session(ws, "坡段 A", None, assessment_only=True, indicator_steps=True, section_id="3") as run:
        first = read_indicator_step(cs, run.actor)
        original = {"kind":"gap", "question":"Which lithology was recorded?", "missing":"Lithology"}
        if domain_failure:
            original["contrary_evidence"] = dict(
                basis="Design and survey give different slope ratios.", adopted_value="Use the design ratio.",
                quotes=['设计坡率为 1:0.75，分三级开挖。','坡段 A：实测坡率为 1:1.0。'],
                question="Which slope ratio is current?", affects_level=True)
        def interrupt(*args):
            if domain_failure:
                raise ActionRejected("projection failed after the assertion commit")
            raise RuntimeError("simulated loss after the assertion commit")
        with monkeypatch.context() as patch:
            patch.setattr(journal, "record_save", interrupt)
            with pytest.raises(LocalStorageBusy if domain_failure else RuntimeError,
                               match="PROJECTION_PENDING" if domain_failure else "simulated loss"):
                save_indicator_outcome(cs, run.actor, "save-lost", first["indicator_id"], original)
        before = records(host, tmp_path/"committed.jsonl")
        assert sum(r["claim"]["kind"] == "judgment" for r in before) == 1
        if domain_failure:
            from report_agent import writer_issues
            write_conflict = writer_issues.save_indicator_conflict
            def mismatched_receipt(*args):
                return {**write_conflict(*args), "proposal_digest":"different-proposal"}
            with monkeypatch.context() as patch:
                patch.setattr(writer_issues, "save_indicator_conflict", mismatched_receipt)
                with pytest.raises(RuntimeError, match="WRITER_COMMITTED_ISSUE_RECEIPT_MISMATCH"):
                    read_indicator_step(cs, run.actor)
            assert not journal.read_progress(ws.store, first["assignment_digest"])["rows"]
        next_step = read_indicator_step(cs, run.actor)
        assert next_step["progress"]["recorded"] == 1 and next_step["indicator_id"] != first["indicator_id"]
        replay = save_indicator_outcome(cs, run.actor, "save-lost", first["indicator_id"], original)
        assert replay["result"]["saved_indicator"] == first["indicator_id"]
        if domain_failure:
            assert replay["result"]["issue_id"]
            with ws.store.connect() as db:
                assert len(issue_state.iter_g6_issue_record(db)) == 1
        assert records(host, tmp_path/"recovered.jsonl") == before


def test_revocation_after_native_commit_does_not_cache_a_failed_save(mini, monkeypatch):
    from report_agent import writer_judgments as journal
    from report_agent.writer_fact_packet import _writer_key
    ws, binding, _ = mini
    install(ws, binding.plan_ref)
    cs, host = ContentStore(ws.store), AssertionHost(ws.store.root)
    with writer_session(ws, "坡段 A", None, assessment_only=True, indicator_steps=True, section_id="3") as writer:
        step = read_indicator_step(cs, writer.actor)
        record = journal.record_save
        def revoke_after_commit(db, scope, *rest):
            record(db, scope, *rest)
            host.revoke(host.lookup(_writer_key(writer.actor,scope)))
        monkeypatch.setattr(journal, 'record_save', revoke_after_commit)
        result = save_indicator_outcome(cs, writer.actor, 'late-revoke', step['indicator_id'],
                                        dict(kind='gap', missing='Subtype', question='Which subtype?'))
        assert result['ok'] and cs.receipt(writer.actor, 'late-revoke')['state']=='known_success'
        row = journal.read_progress(ws.store, step['assignment_digest'])['rows'][step['indicator_id']]
        assert row['claim']['basis']=='gap'


def test_two_valid_writer_packets_cannot_choose_a_second_producer(mini, tmp_path):
    from report_agent.errors import ActionRejected
    ws, binding, _ = mini
    install(ws, binding.plan_ref)
    cs, host = ContentStore(ws.store), AssertionHost(ws.store.root)
    args = dict(assessment_only=True, indicator_steps=True, section_id="3")
    outcome = dict(kind="gap", missing="Rock subtype", question="Which subtype?")
    with writer_session(ws, "坡段 A", None, **args) as first:
        step = read_indicator_step(cs, first.actor)
        save_indicator_outcome(cs, first.actor, "first-producer", step["indicator_id"], outcome)
    with writer_session(ws, "坡段 A", None, **args) as other:
        step = read_indicator_step(cs, other.actor)
        from report_agent.errors import ActionForbidden
        with pytest.raises(ActionForbidden, match="assessment producer ownership"):
            save_indicator_outcome(cs, other.actor, "other-producer", step["indicator_id"], outcome)
        assert read_indicator_step(cs, other.actor)["progress"]["recorded"] == 0
    rows = records(host, tmp_path/"producers.jsonl")
    assert sum(r["claim"]["kind"] == "judgment" for r in rows) == 1


def test_writer_packet_without_the_assigned_slope_cannot_reserve_production(mini):
    from dataclasses import replace
    from report_agent.errors import ActionRejected
    from report_agent.store import digest
    from report_agent.writer_assignments import bound_assignment
    from report_agent.writer_fact_packet import _writer_key
    ws, binding, _ = mini
    install(ws, binding.plan_ref)
    cs, host = ContentStore(ws.store), AssertionHost(ws.store.root)
    with writer_session(ws, "坡段 A", None, assessment_only=True, indicator_steps=True, section_id="3") as writer:
        with ws.store.connect() as db:
            scope = bound_assignment(cs, db, writer.actor)
        step = read_indicator_step(cs, writer.actor)
        grant = host.lookup(_writer_key(writer.actor, scope))
        host.authorize(replace(grant, subjects=frozenset({"B"})))
        with pytest.raises(ActionRejected, match="WRITER_ASSIGNED_FACT_NO_LONGER_CONFIRMED"):
            save_indicator_outcome(cs, writer.actor, "wrong-slope-packet", step["indicator_id"],
                                   dict(kind="gap", missing="Rock subtype", question="Which subtype?"))
        with ws.store.connect() as db:
            assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='assessment_producers'").fetchone()
        assert host.commission.producer(digest(scope["plan"]["ref"]), "A") is None


@pytest.mark.parametrize("method_commission", ["with-owner-ranks"], indirect=True)
def test_foreign_or_undelivered_visual_is_rejected_before_judgment(assigned, tmp_path):
    from report_agent import writer_assignments as pages
    from report_agent.errors import ActionForbidden, ActionRejected
    f = assigned
    f.ws.store.set("manifest", {**f.ws.store.manifest, "assembly_contract": "system-assembler-v1"})
    with writer_session(f.ws, f.plan["objects"][0]["label"], None, assessment_only=True, indicator_steps=True) as writer:
        step = read_indicator_step(f.cs, writer.actor)
        index = pages.read_assignment_pages(f.cs, writer.actor)
        source = next(s for s in index["sources"] if s["title"] == "design")
        image = pages.read_assigned_page(f.cs, writer.actor, source["source_handle"], 2)
        original = dict(kind="gap", missing="Details", question="Which details?", visual_pages=[image["page_handle"]])
        with pytest.raises(ActionRejected, match="NOT_DELIVERED"):
            save_indicator_outcome(f.cs, writer.actor, "undelivered-image", step["indicator_id"], original)
        pages.mark_visual_page_delivered(f.cs, writer.actor, image["page_handle"], image["image_sha256"])
        other = pages.read_assigned_page(f.cs, f.actor, source["source_handle"], 2)
        pages.mark_visual_page_delivered(f.cs, f.actor, other["page_handle"], other["image_sha256"])
        with pytest.raises(ActionForbidden, match="visual page receipt"):
            save_indicator_outcome(f.cs, writer.actor, "other-image", step["indicator_id"],
                                   {**original, "visual_pages":[other["page_handle"]]})
        host = AssertionHost(f.ws.store.root)
        assert not any(r["claim"]["kind"] == "judgment" for r in records(host, tmp_path/"before.jsonl"))
        from report_agent.writer_runtime import writer_tools
        def read_native(include_images, page):
            tool = next(t for t in writer_tools(f.ws, writer.actor, include_images=include_images, assessment_only=True)
                        if t.name == 'read_assigned_page')
            return tool.invoke(dict(type='tool_call', id='page-read', name=tool.name,
                                    args=dict(source_handle=source["source_handle"], page=page)))
        message = read_native(True, 3)
        assert [block["type"] for block in message.content] == ["text", "image_url"]
        actual = message.artifact["writer_page_delivery"]
        save_indicator_outcome(f.cs, writer.actor, "valid-image", step["indicator_id"],
                               {**original, "visual_pages":[actual]})
        second = read_indicator_step(f.cs, writer.actor)
        text = read_native(False, 3)
        save_indicator_outcome(f.cs, writer.actor, "same-page-text", second["indicator_id"],
                               dict(kind="gap", missing="Details", question="Which details?", quotes=["Drawing K1p250"]),
                               read_locations=[dict(source_handle=source["source_handle"], page=3,
                                                    delivery=text.artifact["writer_page_delivery"])])
        rows = {r["operation_id"]:r for r in records(host, tmp_path/"both.jsonl") if r["claim"]["kind"] == "judgment"}
        receipts = [host.commission.judgment_details(row["id"]) for row in rows.values()]
        first_receipt, = next(r["evidence_receipts"] for r in receipts if r["operation"]=="valid-image")
        second_receipt, = next(r["evidence_receipts"] for r in receipts if r["operation"]=="same-page-text")
        assert first_receipt["id"] == actual and first_receipt["modality"] == "image"
        assert first_receipt["actor"] == writer.actor.__dict__ and first_receipt["page"] == 3
        assert second_receipt["modality"]=="text" and "image_sha256" not in second_receipt
        assert second_receipt["source_version"] == first_receipt["source_version"]


@pytest.mark.parametrize("method_commission", ["with-owner-ranks"], indirect=True)
def test_scored_source_ground_links_only_the_actual_read(ranked):
    from report_agent.writer_assignments import read_assignment_pages
    from report_agent.writer_runtime import writer_tools
    from test_writer_indicator_outcomes import evidence
    f = ranked
    with writer_session(f.ws, 'Slope 1', None, assessment_only=True, indicator_steps=True) as writer:
        step = read_indicator_step(f.cs, writer.actor)
        source = next(s for s in read_assignment_pages(f.cs, writer.actor)['sources'] if s['title']=='S1-survey')
        read = next(t for t in writer_tools(f.ws,writer.actor,include_images=False) if t.name=='read_assigned_page')
        message = read.invoke(dict(type='tool_call',id='actual-text',name=read.name,
                                   args=dict(source_handle=source['source_handle'],page=1)))
        handle = message.artifact['writer_page_delivery']
        loc = dict(source_handle=source['source_handle'],page=1,delivery=handle)
        save_indicator_outcome(f.cs, writer.actor, 'scored', step['indicator_id'], evidence(f,step), read_locations=[loc])
        from report_agent.writer_judgments import read_progress
        row = read_progress(f.ws.store, step['assignment_digest'])['rows'][step['indicator_id']]
        ground, = row['ground_details']
        witness, = row['evidence_receipts']
        assert ground['assertion_id'] == row['grounds'][0]['assertion_id']
        assert ground['delivery_receipts'] == [handle] and witness['id'] == handle
        assert ground['claim']['citation']['source_version'] == witness['source_version']
        assert ground['claim']['citation']['page'] == witness['page'] == 1
        assert witness['modality'] == 'text' and witness['actor']==writer.actor.__dict__


from test_writer_assignments import assigned
from test_m1_g3_integration import method_commission

from test_writer_indicator_outcomes import ranked


@pytest.mark.parametrize("method_commission", ["with-owner-ranks"], indirect=True)
def test_stale_step_cannot_request_schema_save_or_interrupt_its_successor(ranked):
    from report_agent.errors import ActionRejected
    from report_agent.writer_assessment import step_outcome_schema
    f = ranked
    first = read_indicator_step(f.cs, f.actor)["indicator_id"]
    outcome = dict(kind="gap", missing="Survey data", question="Which survey covers the object?")
    saved = save_indicator_outcome(f.cs, f.actor, "accepted-first", first, outcome)
    next_step = read_indicator_step(f.cs, f.actor)
    assert next_step["indicator_id"] != first
    refusals = [dict(tool="save_gap", code="invalid", tool_call_id=i) for i in ("call-1","call-2")]
    with pytest.raises(ActionRejected, match="WRITER_INDICATOR_STEP_MISMATCH"):
        step_outcome_schema(f.cs, f.actor, first, "gap")
    with pytest.raises(ActionRejected, match="WRITER_INDICATOR_STEP_MISMATCH"):
        save_indicator_outcome(f.cs, f.actor, "late-save", first, outcome)
    with pytest.raises(ActionRejected, match="WRITER_INDICATOR_STEP_MISMATCH"):
        interrupt_indicator_step(f.cs, f.actor, first, refusals)
    with pytest.raises(ActionRejected, match="WRITER_TWO_DISTINCT_SAVE_REFUSALS_REQUIRED"):
        interrupt_indicator_step(f.cs, f.actor, next_step["indicator_id"], [refusals[0], refusals[0]])
    assert save_indicator_outcome(f.cs, f.actor, "accepted-first", first, outcome) == saved
    assert read_indicator_step(f.cs, f.actor) == next_step


@pytest.mark.parametrize("method_commission", ["with-owner-ranks"], indirect=True)
def test_invalid_save_kind_and_excluded_adopted_grade_leave_assignment_open(ranked):
    from report_agent.errors import ActionRejected
    from test_writer_indicator_outcomes import evidence
    f = ranked
    step = read_indicator_step(f.cs, f.actor)
    indicator = step["indicator_id"]
    row = evidence(f, step)
    with pytest.raises(ActionRejected, match="WRITER_INDICATOR_KIND_INVALID"):
        save_indicator_outcome(f.cs, f.actor, "invalid-kind", indicator, {**row, "kind":"derived"})
    row.update(kind="assumption", basis_kind="indirect_assumption", question="Can this grade be verified?",
               plausible_grades=[step["grades"][0]["choice"]])
    with pytest.raises(ActionRejected, match="MESSAGE_FIELDS_INVALID") as rejected:
        save_indicator_outcome(f.cs, f.actor, "excluded-grade", indicator, row)
    assert any(issue["reason"]=="adopted_grade_not_plausible" for issue in rejected.value.diagnostic["fields"])
    assert read_indicator_step(f.cs, f.actor)==step


@pytest.mark.parametrize("method_commission", ["with-owner-ranks"], indirect=True)
def test_historical_whole_slope_draft_requires_new_indicator_assignment(ranked):
    from report_agent.errors import ActionRejected
    from report_agent.store import digest
    from report_agent.writer_assignments import bound_assignment
    f = ranked
    with f.ws.store.connect() as db:
        scope = bound_assignment(f.cs, db, f.actor)
    old_key = digest([f.actor.id, scope["task_ref"], scope["plan"]["ref"], scope["object"]["object_id"]])
    historical = {"rows":{"A":{"rationale":"Archived whole-slope working state."}}}
    f.ws.store.set("writer_assessment_draft:"+old_key, historical)
    with pytest.raises(ActionRejected, match="WRITER_FRESH_INDICATOR_ASSIGNMENT_REQUIRED"):
        read_indicator_step(f.cs, f.actor)
    assert f.ws.store.get("writer_assessment_draft:"+old_key)==historical
