"""Caller-selected, business-read-only text analysis; no search or agent loop."""
from __future__ import annotations
from .prompt_sources import load_prompt

import hashlib
from openai import APITimeoutError, APIStatusError
from langchain_core.exceptions import ContextOverflowError
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .catalog import Catalog
from .errors import ActionRejected, ModelRequestDeadlineExceeded
from .input_capacity import CapacityAdmissionRejected, capacity_failure, capacity_handling, capacity_response_received
from .source_tables import with_source_tables
from .content_selection import selected_content
from .store import digest, encode


SourceTableView = Literal['references', 'full']


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str = Field(min_length=1)
    offset: int = Field(default=0, ge=0, description="Zero-based source text-block offset, not PDF page.")
    limit: int = Field(default=10, ge=1, le=50, description="Number of text blocks, not characters or physical pages.")
    table_detail: SourceTableView | None = Field(default=None,
        description="Omit for historical full whole-page table supplements. references retains all selected frozen text and defers mechanical table views with exact access locators; no tables are extracted. Changing view is not new evidence or permission to repeat an unknown request.")

    def packet_selection(self):
        # New default options must not alter historical paid input hashes.
        return self.model_dump(exclude_none=True)


class ResultSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    result_id: str = Field(min_length=1)
    offset: int = Field(default=0, ge=0, description="Zero-based character offset in the saved result body.")
    characters: int = Field(default=12000, ge=1, le=16000)


ANALYSIS_PROMPT = load_prompt('evidence-analysis')


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def model_identity(model):
    """Explicit non-secret parameter allowlist; never serialize clients/credentials."""
    identity = {key: getattr(model, key, None) for key in
            ("model_name", "reasoning_effort", "max_tokens", "temperature", "top_p",
             "seed", "model_kwargs", "extra_body", "disable_streaming")}
    # Equal model names on different providers are not equal checking requests.
    # Never copy authentication, userinfo or query strings into a receipt.
    from urllib.parse import urlsplit
    endpoint = getattr(model, "openai_api_base", None)
    if endpoint:
        parts = urlsplit(str(endpoint))
        identity["service"] = {"scheme": parts.scheme, "host": parts.hostname,
            "port": parts.port, "path": parts.path.rstrip("/")}
    else:
        identity["service"] = None
    return identity


def selected_evidence(workspace, source_selections, result_selections, snapshot_ref=None, content_selections=None,
                      *, material_receipts=None, actor=None, source_receipts=None):
    from .source_use import validate_source_versions
    validate_source_versions(workspace, actor,
        [SourceSelection.model_validate(s).source_id for s in source_selections])
    catalog = Catalog(workspace.store)
    evidence = []
    for raw in source_selections:
        selection = SourceSelection.model_validate(raw)
        page = catalog.read(selection.source_id, selection.offset, selection.limit)
        if not page["blocks"]:
            raise ActionRejected("EVIDENCE_SOURCE_SELECTION_EMPTY")
        # Same mechanical observation capability as source-reading tools. No new
        # extraction model, semantic selection, OCR or source search occurs here.
        if selection.table_detail is None or selection.table_detail == 'full':
            page = with_source_tables(workspace, page)
        else:
            from .source_tables import present_source_tables
            page = present_source_tables(workspace, page, selection.table_detail)
        if material_receipts is not None:
            import json
            from .source_materials import issue, verify, block_material
            text = json.dumps(page,ensure_ascii=False)
            receipt = issue(workspace,actor,'read_source_page',text,block_material(page))
            material_receipts.extend(verify(workspace,actor,receipt['receipt'],text,'read_source_page')['materials'])
            if source_receipts is not None:
                source_receipts[len(evidence)] = receipt['receipt']
        evidence.append({"kind": "source_blocks", "selection": selection.packet_selection(),
                         "selection_units": "zero-based text blocks",
                         "observation": page, "observation_sha256": digest(page)})
    results = workspace.results()
    delivery_id = (workspace.store.get("delivery") or {}).get("draft_id")
    for raw in result_selections:
        selection = ResultSelection.model_validate(raw)
        result = workspace.result(selection.result_id)
        body = result["body"]
        text = body[selection.offset:selection.offset + selection.characters]
        if not text:
            raise ActionRejected("EVIDENCE_RESULT_SELECTION_EMPTY")
        end = selection.offset + len(text)
        evidence.append({"kind": "saved_result_text", "selection": selection.model_dump(),
                         "selection_units": "zero-based Unicode characters",
                         "result_id": result["id"], "result_kind": result["kind"],
                         "title": result["title"], "body_sha256": _sha(body),
                         "text": text, "text_sha256": _sha(text), "total_characters": len(body),
                         "next_offset": end if end < len(body) else None,
                         "selected_delivery": result["id"] == delivery_id,
                         "replaced_by": [r["id"] for r in results if r.get("replaces_id") == result["id"]],
                         "artifact_note": "Saved body text, not a rendered export or visual observation; selection is partial unless it covers the entire body."})
    evidence.extend(selected_content(workspace, snapshot_ref, content_selections))
    if not evidence:
        raise ActionRejected("EVIDENCE_SELECTION_REQUIRED")
    return evidence


async def analyze_selected_evidence(workspace, model, question, source_selections, result_selections,
                                    snapshot_ref=None, content_selections=None, *, actor=None):
    if not isinstance(question, str) or not question.strip():
        raise ActionRejected("EVIDENCE_QUESTION_REQUIRED")
    # Validate every selection before cache lookup or paid call. Even a cached
    # observation cannot grant access to a result/source absent from this project.
    evidence = selected_evidence(workspace, source_selections, result_selections, snapshot_ref, content_selections, actor=actor)
    from .source_use import resolve_source_use_binding
    policy_ref = resolve_source_use_binding(workspace, actor)
    inputs = {"question": question, "evidence": evidence,
              **({'source_use_policy_ref': policy_ref} if policy_ref else {})}
    return await analyze_evidence_packet(workspace, model, inputs, ANALYSIS_PROMPT,
                                        "selected-evidence-v3", reserve_attempt=True, owner=actor)


def _empty_analysis(content):
    return not content or (isinstance(content, str) and not content.strip())


async def analyze_evidence_packet(workspace, model, inputs, system_prompt, contract, *, reserve_attempt=False,
                                  parent_reservation=None, allow_parent_readmission=True, owner=None, caller_operation_id=None):
    """Shared one-shot execution/cache for selected observations and bound review.

    The caller assembles and authorizes actual material before entering here.
    No tool dispatch, source search, semantic retry or business acceptance loop.
    A parent can receive admission facts without permitting a new caller ID to
    readmit an earlier refused raw operation. Existing Writer policy is retained.
    """
    identity = model_identity(model)
    from .prompt_provenance import analysis_source, check_static_prompt, prompt_call, PromptCompositionError
    prompt_source = analysis_source(contract, inputs, workspace.store)
    suffix = ''
    if prompt_source:
        from .prompt_sources import load_prompt
        suffix = (load_prompt('scoped-review-channel') if
            prompt_source in {'legacy-bounded-review','artifact-analysis'} and inputs.get('commission', {}).get('scoped_instructions') is not None else '')
        check_static_prompt(system_prompt, prompt_source, suffix=suffix)
    operation = digest({"system": system_prompt, "input": inputs, "model": identity, "contract": contract})
    saved = workspace.store.analysis(operation)
    if saved:
        if _empty_analysis(saved.get("analysis")):
            diagnostic = {"phase": "cache_read", "raw_operation": operation,
                "new_model_call": False, "historical_usage": saved.get("usage"),
                "note": "Historical cached content is empty. Original cache and attempt records remain unchanged; no automatic new request."}
            workspace.store.event("evidence_analysis_cached_response_rejected", diagnostic)
            raise ActionRejected("EVIDENCE_ANALYSIS_EMPTY_RESPONSE: " + encode(diagnostic))
        workspace.store.event("evidence_analysis_reused", {"operation": operation})
        return {**saved, "reused": True}
    if reserve_attempt:
        from .bounded_operations import reserve_once, record_outcome
        prior = reserve_once(workspace.store, 'bounded_review_attempt:' + operation,
            {'state':'reserved', 'operation':operation,
             **({'owner': owner.__dict__, 'caller_operation_id': caller_operation_id,
                 'task_id': owner.task_id, 'contract': contract,
                 'scope_ids': inputs.get('requested_scope_ids', []),
                 'target_refs': [r.get('target_ref') for r in inputs.get('assignment', {}).get('review_requirements', [])]} if owner is not None else {})},
            new_parent=parent_reservation if allow_parent_readmission else None)
        if prior is not None:
            if prior['state'] == 'not_dispatched':
                if parent_reservation is not None and not allow_parent_readmission:
                    from .bounded_operations import record_not_dispatched
                    # This parent was blocked by the original raw receipt. It
                    # had no new provider attempt or admission-hook refusal.
                    # Link only the new parent; never rewrite the original raw.
                    record_not_dispatched(workspace.store, [parent_reservation], prior['admission_proof'],
                        result={'proof_origin': 'prior_raw_receipt', 'raw_operation': operation,
                                'new_provider_attempt': False})
                raise ActionRejected('EVIDENCE_ANALYSIS_NOT_DISPATCHED: original local admission refusal; no response or usage; inspect before choosing another operation')
            raise ActionRejected("REVIEW_ANALYSIS_PREVIOUS_ATTEMPT_UNRESOLVED: inspect original response; no automatic retry")
    input_record = {
        "operation": operation, "system_prompt": system_prompt, "input": inputs,
        "model": identity, "business_artifacts_read_only": True}
    # Request identity describes material, not dispatch count. A verified local
    # refusal can later be explicitly readmitted, without duplicating the exact
    # input archive and making its fingerprint ambiguous to adoption/recovery.
    import json
    with workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute("SELECT data FROM events WHERE kind='evidence_analysis_input' "
                              "AND json_extract(data,'$.operation')=?", (operation,)).fetchall()
        if any(json.loads(row[0]) != input_record for row in existing):
            raise ActionRejected('EVIDENCE_ANALYSIS_INPUT_IDENTITY_CONFLICT')
        if not existing:
            db.execute('INSERT INTO events(kind,data) VALUES (?,?)', ('evidence_analysis_input', encode(input_record)))
    import time
    started = time.perf_counter()
    from .request_budget import logical_request_admission, RequestBudgetExceeded
    try:
        from .model_recovery import recovery_owner
        sources = [prompt_source] if prompt_source else []
        from . import prompt_sources
        if (contract == 'independent-text-tools-v1' and inputs.get('output_schema')
                and prompt_sources.review_interface_profile(workspace.store) == prompt_sources.REVIEW_INTERFACE_V4
                and prompt_sources.report_prompt_profile(workspace.store) == prompt_sources.CONCISE_PROMPTS):
            output_schema = inputs.get('output_schema', {})
            described, schema_sources = prompt_sources.describe_content_schema(output_schema)
            if schema_sources and described == output_schema:
                sources.append({'source':'analysis_output_schema', 'files':schema_sources, 'message_index':1})
        if suffix:
            sources.append('scoped-review-channel')
        try:
            commission = inputs.get('commission')
            packet = commission.get('scoped_instructions') if isinstance(commission, dict) else None
            references = {'input_sha256':digest(inputs), 'contract':contract}
            if isinstance(packet, dict):
                references.update(instruction_digest=packet.get('digest'),
                    instruction_refs=[r.get('ref') for r in packet.get('effective', []) if isinstance(r, dict)])
            sources.append({'source':'analysis_input/current_commission', 'references':references})
        except Exception as exc:
            # Diagnostic extraction cannot become a new inference/permission gate.
            sources.append({'source':'unexplained_analysis_source_metadata', 'exception_type':type(exc).__name__})
        with logical_request_admission() as admission, recovery_owner(workspace.store, owner, operation), prompt_call(
                workspace.store, prompt_source or 'custom_analysis:' + contract,
                sources=sources, status='exact' if prompt_source else 'unexplained',
                offered={'messages':[{'role':'system','content':system_prompt},{'role':'user','content':encode(inputs)}]}):
            response = await model.ainvoke([("system", system_prompt), ("user", encode(inputs))])
    except (RequestBudgetExceeded, CapacityAdmissionRejected, APIStatusError, ContextOverflowError,
            PromptCompositionError) as exc:
        capacity = capacity_failure(exc)
        if capacity is None and not isinstance(exc, (RequestBudgetExceeded, PromptCompositionError)):
            raise
        proof = admission.not_dispatched_proof(exc)
        if capacity is not None:
            received = capacity_response_received(exc)
            diagnostic = {'raw_operation': operation, 'raw_response_received': received,
                'provider_outcome': 'not_dispatched' if proof is not None else 'response_received' if received else 'unknown',
                'usage': None, 'adoptable_result': False, 'failure_phase': capacity['failure_phase'],
                'capacity': capacity, 'handling': capacity_handling(capacity, 'tool'), 'admission_proof': proof,
                'note': 'No automatic retry. Earlier admitted attempts remain unresolved; '
                        'new caller IDs or wording do not resolve them.'}
            if reserve_attempt:
                if proof is not None:
                    from .bounded_operations import record_not_dispatched
                    reservations = [('bounded_review_attempt:' + operation, {'operation': operation})]
                    if parent_reservation is not None:
                        reservations.append(parent_reservation)
                    record_not_dispatched(workspace.store, reservations, proof, result=diagnostic)
                else:
                    record_outcome(workspace.store, 'bounded_review_attempt:' + operation,
                                   'received_invalid' if received else 'unknown', result=diagnostic)
            workspace.store.event('evidence_analysis_capacity_blocked', diagnostic)
            raise ActionRejected('MODEL_CONTEXT_CAPACITY_REJECTED: ' + encode(diagnostic)) from exc
        if reserve_attempt and proof is not None:
            from .bounded_operations import record_not_dispatched
            reservations = [('bounded_review_attempt:' + operation, {'operation': operation})]
            if parent_reservation is not None:
                reservations.append(parent_reservation)
            record_not_dispatched(workspace.store, reservations, proof)
        raise
    except (ModelRequestDeadlineExceeded, APITimeoutError) as exc:
        # Only this adapter-owned deadline is an ordinary bounded-tool outcome.
        # External cancellation, host/budget stops and unrelated failures propagate.
        call_facts = getattr(exc, "model_call_facts", None)
        attempts = (call_facts or {}).get('observed_attempts', [])
        recorded = [{k: a.get(k) for k in ('attempt_id', 'accounting_state', 'recorded_tokens')}
                    for a in attempts if a.get('recorded_tokens') is not None]
        diagnostic = {"raw_operation": operation, "raw_response_received": False,
            "raw_response_received_meaning": "Parsed model response available to this tool, not HTTP body completion.",
            "model_response_parsed": False,
            "http_body_complete": any(a.get('response_complete') for a in attempts),
            "recorded_usage_by_attempt": recorded,
            "provider_outcome": "unknown", "usage": None,
            "deadline_seconds": getattr(exc, "deadline_seconds", None),
            "failure_phase": "local_request_deadline" if isinstance(exc, ModelRequestDeadlineExceeded) else "transport_timeout",
            "model_call": call_facts,
            "local_elapsed_seconds": time.perf_counter() - started,
            "adoptable_result": False,
            "note": "No parsed model response available to this tool. Per-attempt HTTP and accounting facts remain separate; recorded totals are not prompt/completion breakdowns or business success. Original reservations remain; no automatic retry or retry authority."}
        if recorded:
            diagnostic.pop('usage')
            diagnostic['usage_status'] = 'recorded_totals_available_without_parsed_model_usage'
        if reserve_attempt:
            record_outcome(workspace.store, 'bounded_review_attempt:' + operation,
                           'unknown', result=diagnostic)
        workspace.store.event("evidence_analysis_unresolved", {"operation": operation, **diagnostic})
        raise ActionRejected("EVIDENCE_ANALYSIS_OUTCOME_UNRESOLVED: " + encode(diagnostic)) from exc
    duration = time.perf_counter() - started
    metadata = getattr(response, "response_metadata", {}) or {}
    extras = getattr(response, "additional_kwargs", {}) or {}
    finish = metadata.get("finish_reason") or metadata.get("stop_reason")
    rejected = (finish in {"length", "max_tokens", "content_filter", "refusal", "error"}
                or extras.get("refusal") or getattr(response, "invalid_tool_calls", None)
                or getattr(response, "tool_calls", None) or _empty_analysis(response.content))
    if rejected:
        # Failed/partial outputs are evidence and usage, never a reusable success.
        workspace.store.event("evidence_analysis_rejected_response", {
            "operation": operation, "content": response.content, "response_metadata": metadata,
            "usage": getattr(response, "usage_metadata", None), "duration_seconds": duration,
            "finish_reason": finish, "refusal": bool(extras.get("refusal")),
            "tool_calls": getattr(response, "tool_calls", None),
            "invalid_tool_calls": getattr(response, "invalid_tool_calls", None)})
        code = ("EVIDENCE_ANALYSIS_RETURNED_TOOL_CALLS" if getattr(response, "tool_calls", None)
                else "EVIDENCE_ANALYSIS_EMPTY_RESPONSE" if _empty_analysis(response.content)
                else "EVIDENCE_ANALYSIS_INCOMPLETE_OR_INVALID_RESPONSE")
        diagnostic = {"raw_operation": operation, "raw_response_received": True,
            "finish_reason": finish, "usage": getattr(response, "usage_metadata", None),
            "duration_seconds": duration, "adoptable_result": False,
            "note": "Exact partial/rejected response preserved; it is not a complete reusable result. Inspect the actual failure before another request; changing caller id or wording does not resolve it."}
        if reserve_attempt:
            record_outcome(workspace.store, 'bounded_review_attempt:' + operation,
                           'received_invalid', result=diagnostic)
        raise ActionRejected(code + ": " + encode(diagnostic))
    result = {"operation": operation, "analysis": response.content,
              "model": identity, "evidence": inputs["evidence"],
              "usage": getattr(response, "usage_metadata", None), "duration_seconds": duration,
              "scope_note": "A bounded model observation of the supplied selections; not verified facts, complete source coverage or report acceptance."}
    if reserve_attempt:
        record_outcome(workspace.store, 'bounded_review_attempt:' + operation,
                       'completed', result=result, cache_operation=operation)
    else:
        workspace.store.analysis(operation, result)
    workspace.store.event("evidence_analysis_completed", {"operation": operation,
        "usage": result["usage"], "duration_seconds": duration})
    return {**result, "reused": False}
