"""Temporary accessors for the Stage 1 migration of legacy state families.

A Store opens a connection for each call. Passing a SQLite connection keeps the
operation in the caller's existing transaction.
"""
import json
import sqlite3

from .store import encode


COMMISSION_REQUIREMENTS_KEY = 'commission_requirements'
COMMISSION_SKELETON_KEY = 'commission_skeleton'
COMMISSION_OWNER_RECORDS_KEY = 'commission_owner_records'
COMMISSION_PLANNING_DRAFT_KEY = 'commission_planning_draft'


def _get(storage, key, default):
    if isinstance(storage, sqlite3.Connection):
        row = storage.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default
    return storage.get(key, default)


def _set(storage, key, value):
    if isinstance(storage, sqlite3.Connection):
        storage.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, encode(value)))
    else:
        storage.set(key, value)


def get_fake03_qualitative_profile(storage, default=None):
    return _get(storage, 'fake03_qualitative_profile', default)


def set_fake03_qualitative_profile(storage, value):
    _set(storage, 'fake03_qualitative_profile', value)


def get_fake03_qualitative_actor(storage, suffix, default=None):
    return _get(storage, 'fake03_qualitative_actor:' + suffix, default)


def set_fake03_qualitative_actor(storage, suffix, value):
    _set(storage, 'fake03_qualitative_actor:' + suffix, value)


def get_writer_indicator_steps(storage, suffix, default=None):
    return _get(storage, 'writer_indicator_steps:' + suffix, default)


def set_writer_indicator_steps(storage, suffix, value):
    _set(storage, 'writer_indicator_steps:' + suffix, value)


def get_writer_page_read(storage, suffix, default=None):
    return _get(storage, 'writer_page_read:' + suffix, default)


def set_writer_page_read(storage, suffix, value):
    _set(storage, 'writer_page_read:' + suffix, value)


def get_writer_assessment_draft(storage, suffix, default=None):
    return _get(storage, 'writer_assessment_draft:' + suffix, default)


def set_writer_assessment_draft(storage, suffix, value):
    _set(storage, 'writer_assessment_draft:' + suffix, value)


def get_assessment_receipt(storage, suffix, default=None):
    return _get(storage, 'assessment_receipt:' + suffix, default)


def set_assessment_receipt(storage, suffix, value):
    _set(storage, 'assessment_receipt:' + suffix, value)


def get_g6_assessment(storage, suffix, default=None):
    return _get(storage, 'g6_assessment:' + suffix, default)


def set_g6_assessment(storage, suffix, value):
    _set(storage, 'g6_assessment:' + suffix, value)


def get_g6_assessment_producer(storage, suffix, default=None):
    return _get(storage, 'g6_assessment_producer:' + suffix, default)


def set_g6_assessment_producer(storage, suffix, value):
    _set(storage, 'g6_assessment_producer:' + suffix, value)


def get_commission_plan(storage, default=None):
    return _get(storage, 'commission_plan', default)


def set_commission_plan(storage, value):
    _set(storage, 'commission_plan', value)


def get_commission_confirmation(storage, default=None):
    return _get(storage, 'commission_confirmation', default)


def set_commission_confirmation(storage, value):
    _set(storage, 'commission_confirmation', value)


def get_commission_skeleton(storage, default=None):
    return _get(storage, COMMISSION_SKELETON_KEY, default)


def set_commission_skeleton(storage, value):
    _set(storage, COMMISSION_SKELETON_KEY, value)


def get_commission_planning_draft(storage, default=None):
    return _get(storage, COMMISSION_PLANNING_DRAFT_KEY, default)


def set_commission_planning_draft(storage, value):
    _set(storage, COMMISSION_PLANNING_DRAFT_KEY, value)


def get_commission_text_profiles(storage, default=None):
    return _get(storage, 'commission_text_profiles', default)


def set_commission_text_profiles(storage, value):
    _set(storage, 'commission_text_profiles', value)


def get_commission_requirements(storage, default=None):
    return _get(storage, COMMISSION_REQUIREMENTS_KEY, default)


def set_commission_requirements(storage, value):
    _set(storage, COMMISSION_REQUIREMENTS_KEY, value)


def get_commission_requirements_checkpoint(storage, suffix, default=None):
    return _get(storage, 'commission_requirements_checkpoint:' + suffix, default)


def set_commission_requirements_checkpoint(storage, suffix, value):
    _set(storage, 'commission_requirements_checkpoint:' + suffix, value)


def get_commission_source_roles(storage, default=None):
    return _get(storage, 'commission_source_roles', default)


def set_commission_source_roles(storage, value):
    _set(storage, 'commission_source_roles', value)


def get_commission_owner_records(storage, default=None):
    return _get(storage, COMMISSION_OWNER_RECORDS_KEY, default)


def set_commission_owner_records(storage, value):
    _set(storage, COMMISSION_OWNER_RECORDS_KEY, value)


def get_commission_checkpoint(storage, suffix, default=None):
    return _get(storage, 'commission_checkpoint:' + suffix, default)


def set_commission_checkpoint(storage, suffix, value):
    _set(storage, 'commission_checkpoint:' + suffix, value)


def get_report_issues(storage, default=None):
    return _get(storage, 'report_issues', default)


def set_report_issues(storage, value):
    _set(storage, 'report_issues', value)


def get_g6_issue_record(storage, suffix, default=None):
    return _get(storage, 'g6_issue_record:' + suffix, default)


def set_g6_issue_record(storage, suffix, value):
    _set(storage, 'g6_issue_record:' + suffix, value)


def get_g6_issue_binding(storage, suffix, default=None):
    return _get(storage, 'g6_issue_binding:' + suffix, default)


def set_g6_issue_binding(storage, suffix, value):
    _set(storage, 'g6_issue_binding:' + suffix, value)


def get_g6_issue_route(storage, suffix, default=None):
    return _get(storage, 'g6_issue_route:' + suffix, default)


def set_g6_issue_route(storage, suffix, value):
    _set(storage, 'g6_issue_route:' + suffix, value)


def get_planned_section_receipt(storage, suffix, default=None):
    return _get(storage, 'planned_section_receipt:' + suffix, default)


def set_planned_section_receipt(storage, suffix, value):
    _set(storage, 'planned_section_receipt:' + suffix, value)


def get_assembly_receipt(storage, suffix, default=None):
    return _get(storage, 'assembly_receipt:' + suffix, default)


def set_assembly_receipt(storage, suffix, value):
    _set(storage, 'assembly_receipt:' + suffix, value)


def get_commission_outcome(storage, suffix, default=None):
    return _get(storage, 'commission_outcome:' + suffix, default)


def set_commission_outcome(storage, suffix, value):
    _set(storage, 'commission_outcome:' + suffix, value)


def get_rescue_projection(storage, suffix, default=None):
    return _get(storage, 'rescue_projection:' + suffix, default)


def set_rescue_projection(storage, suffix, value):
    _set(storage, 'rescue_projection:' + suffix, value)


def get_content_delivery(storage, default=None):
    return _get(storage, 'content_delivery', default)


def set_content_delivery(storage, value):
    _set(storage, 'content_delivery', value)


def get_content_final_review(storage, default=None):
    return _get(storage, 'content_final_review', default)


def set_content_final_review(storage, value):
    _set(storage, 'content_final_review', value)


def get_corrections(storage, default=None):
    return _get(storage, 'corrections', default)


def set_corrections(storage, value):
    _set(storage, 'corrections', value)


def get_source_changes(storage, default=None):
    return _get(storage, 'source_changes', default)


def set_source_changes(storage, value):
    _set(storage, 'source_changes', value)


def get_result_impact_assessments(storage, default=None):
    return _get(storage, 'result_impact_assessments', default)


def set_result_impact_assessments(storage, value):
    _set(storage, 'result_impact_assessments', value)


def get_decision_observation(storage, default=None):
    return _get(storage, 'decision_observation', default)


def set_decision_observation(storage, value):
    _set(storage, 'decision_observation', value)


def read_probe_plan_pin_rows(db):
    return db.execute("SELECT key,value FROM state WHERE key IN ('commission_plan','commission_confirmation')").fetchall()


def read_completion_authority_rows(db):
    return db.execute("SELECT key,value FROM state WHERE key IN ('manifest','content_delivery') ORDER BY key").fetchall()


def read_repetition_state_rows(db):
    return db.execute(
        "SELECT key,value FROM state WHERE key IN "
        "('manifest','feedback','report_issues','issues','context_revision','source_changes','corrections',"
        "'content_delivery','content_execution_decision','context_policy','knowledge_enabled',"
        "'acceptance_mode','acceptance_default','active_rubric_hash','decision_observation') "
        "OR key LIKE 'operator_%' ORDER BY key"
    ).fetchall()


def iter_g6_issue_record(db):
    return db.execute('SELECT key,value FROM state WHERE key>=? AND key<?', ('g6_issue_record:', 'g6_issue_record;'))


def iter_g6_issue_record_ordered(db):
    return db.execute('SELECT key,value FROM state WHERE key>=? AND key<? ORDER BY key', ('g6_issue_record:', 'g6_issue_record;'))


def iter_g6_issue_route_ordered(db):
    return db.execute('SELECT key,value FROM state WHERE key>=? AND key<? ORDER BY key', ('g6_issue_route:', 'g6_issue_route;'))


def issue_record_key(suffix):
    return 'g6_issue_record:' + suffix


def iter_commission_outcomes(db, object_digest):
    prefix = 'commission_outcome:' + object_digest
    return db.execute('SELECT value FROM state WHERE key>=? AND key<? ORDER BY key',
                      (prefix + ':', prefix + ';'))


BUSINESS_STATE = frozenset({
    'manifest', 'acceptance_default', 'acceptance_mode',
    'commission_plan', 'commission_confirmation', 'commission_requirements',
    'commission_owner_records', 'commission_skeleton', 'commission_source_roles',
    'commission_text_profiles', 'commission_reviewed_entries', 'commission_carryover',
    'source_use_authority_binding',
})


def read_probe_business_state(db):
    return {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM state')
            if key in BUSINESS_STATE or key.startswith('reviewed_method_pack:')}


def insert_probe_business_state(db, state):
    db.executemany('INSERT INTO state VALUES (?,?)', [(key, encode(value)) for key, value in state.items()])


def read_review_trial_state(db):
    keys = ("delivery", "report_status", "rubric_reviews", "rubric_status", "report_error",
            "checkpoint_resume", "native_interrupts", "knowledge_project_id", "knowledge_enabled", "report_issues",
            "active_rubric_hash", "active_reviewer_prompt_hash", "manifest")
    return {k: json.loads(v) for k, v in db.execute(
        "SELECT key,value FROM state WHERE key IN (" + ",".join("?" for _ in keys) + ")", keys)}
