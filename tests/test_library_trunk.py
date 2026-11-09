"""Scripted protocol exercise, not an evaluation of model autonomy or content quality."""
from report_agent import report_state
from io import BytesIO
from typing import Any

from docx import Document
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

from report_agent.catalog import Catalog
from report_agent.exporting import export_docx
from report_agent.report_runtime import run_report
from report_agent.store import Store
from report_agent.workspace import Workspace


class LibraryModel(BaseLlm):
    model: str = 'scripted-library-fixture'
    ws: Any = Field(exclude=True)
    task_id: str
    script: list[str]
    position: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        action = self.script[self.position]
        self.position += 1
        if action == 'final':
            yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Synthetic protocol complete.')]))
            return
        results = self.ws.results()

        def latest(kind):
            return next(r for r in reversed(results) if r['kind'] == kind)

        if action == 'assess':
            change = next(c for c in self.ws.store.get('source_changes') if not c['assessment'])
            name, args = 'assess_source_change', {'change_id': change['id'], 'description': 'Synthetic assessment within the unchanged report scope.', 'affected_result_ids': []}
        elif action.startswith('request_'):
            kind = action.removeprefix('request_')
            required = {'plan': ['purpose'], 'materials': [], 'draft': ['plan', 'materials'], 'review': ['draft']}[kind]
            name, args = 'request_task', {'kind': kind, 'goal': 'Synthetic library ' + kind,
                                         'input_ids': [latest(k)['id'] for k in required]}
        elif action.startswith('revise_'):
            kind = action.removeprefix('revise_')
            name, args = 'request_revision', {'result_id': latest(kind)['id'], 'description': 'Incorporate the explicitly replaced synthetic source.'}
        elif action == 'run':
            name, args = 'run_requested_task', {'task_id': self.ws.tasks()[-1]['id']}
        elif action == 'search':
            name, args = 'search_sources', {'query': 'hours', 'limit': 1}
        elif action == 'bad_search':
            name, args = 'search_sources', {'query': '', 'limit': 1}
        elif action == 'history':
            prior = self.ws.result(self.ws.task(self.task_id)['replaces_id'])
            name, args = 'read_source_page', {'source_id': prior['source_ids'][0], 'limit': 1}
        elif action == 'read':
            source = next(s for s in self.ws.store.source_catalog() if s['current'] and s.get('filename') == 'hours.txt')
            name, args = 'read_source_page', {'source_id': source['id'], 'limit': 1}
        elif action == 'select':
            name, args = 'select_delivery', {'draft_id': latest('draft')['id'], 'review_id': latest('review')['id']}
        elif action == 'submit':
            task = self.ws.task(self.task_id)
            kind = task['kind']
            source_ids = []
            if kind == 'materials':
                source = next(s for s in self.ws.store.source_catalog() if s['current'] and s.get('filename') == 'hours.txt')
                body = self.ws.store.sources([source['id']])[0]['content']
                source_ids = [source['id']]
            elif kind == 'draft':
                body = '# Synthetic access report\n\n' + latest('materials')['body']
            else:
                body = 'Synthetic scope and evidence protocol only.'
            name, args = 'submit_result', {'title': 'Synthetic ' + kind, 'body': body, 'source_ids': source_ids, 'input_ids': []}
            if kind == 'review':
                args.update(outcome='accepted', target_id=latest('draft')['id'])
        else:
            raise AssertionError(action)
        yield LlmResponse(content=types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]))


class LibraryFactory:
    def __init__(self, ws, revision=False, assessment_only=False):
        self.ws, self.revision, self.assessment_only = ws, revision, assessment_only
        self.created = []

    def __call__(self, kind, task_id):
        self.created.append(kind)
        if kind == 'coordinator':
            script = ['assess', 'select', 'final'] if self.assessment_only else (
                ['assess', 'revise_materials', 'run', 'revise_draft', 'run', 'request_review', 'run', 'select', 'final'] if self.revision else
                ['assess', 'request_plan', 'run', 'request_materials', 'run', 'request_draft', 'run', 'request_review', 'run', 'select', 'final'])
        elif kind == 'materials':
            script = (['history'] if self.revision else []) + ['search', 'read', 'submit', 'final']
        else:
            script = ['submit', 'final']
        return LibraryModel(ws=self.ws, task_id=task_id, script=script)


async def exercise_library(project):
    store = Store(project)
    store.initialize({'name': 'Synthetic library and revision trial', 'goal': 'Compile the supplied daytime access information. No engineering approval.',
                      'sources': [{'id': 'brief', 'title': 'Synthetic brief', 'content': 'Scope: daytime access summary.', 'coverage': 'complete'}],
                      'document_uses': {'brief': 'User scope, not engineering facts'}})
    store.set('model_mode', 'scripted_fixture')
    ws = Workspace(store)
    ws.initialize()
    cat = Catalog(store)
    original = cat.import_file('hours.txt', b'Access hours: 08:00-17:00. Synthetic fixture only.')['source']['id']
    first = await run_report(ws, LibraryFactory(ws))
    assert first['status'] == 'reviewed_draft', first
    old_draft = first['delivery']['draft_id']
    old_material = next(r for r in ws.results() if r['kind'] == 'materials')
    plan = next(r for r in ws.results() if r['kind'] == 'plan')
    correction = ws.request_correction(old_material['id'], 'Use the updated synthetic hours.')
    cat.import_file('hours.txt', b'Access hours: 09:00-16:00. Synthetic fixture only.', original)
    assert ws.delivery(old_draft)['status'] != 'reviewed_draft'
    factory = LibraryFactory(ws, revision=True)
    second = await run_report(ws, factory)
    assert second['status'] == 'reviewed_draft', second
    assert 'plan' not in factory.created and 'purpose' not in factory.created
    assert next(r for r in ws.results() if r['kind'] == 'plan')['id'] == plan['id']
    assert ws.result(old_draft)['body'].find('08:00-17:00') >= 0
    new_draft = second['delivery']['draft_id']
    assert new_draft != old_draft and '09:00-16:00' in ws.result(new_draft)['body']
    addressed = next(c for c in store.get('corrections') if c['id'] == correction['id'])
    assert addressed['status'] == 'addressed' and not addressed['resolved']
    text = '\n'.join(p.text for p in Document(BytesIO(export_docx(ws, new_draft))).paragraphs)
    assert '09:00-16:00' in text and '08:00-17:00' not in text
    # An unrelated addition remains observable, not compulsory regeneration.
    cat.import_file('unrelated.txt', b'Synthetic unrelated meeting room inventory.')
    task_count = len(ws.tasks())
    last = await run_report(ws, LibraryFactory(ws, assessment_only=True))
    assert last['status'] == 'reviewed_draft' and len(ws.tasks()) == task_count
    assert last['delivery']['draft_id'] == new_draft
    assert not any(e['kind'] == 'model_request' for e in store.events())
    return ws


async def test_import_library_revision_review_export_protocol(tmp_path):
    # Explicit R7 interface migration: actual current whole-report source/revision
    # chain plus the unchanged historical correction-state transaction contract.
    from library_revision_fixture import current_library_revision_protocol, historical_correction_state_control
    await current_library_revision_protocol(tmp_path)
    historical_correction_state_control(tmp_path)


async def test_rejected_tool_request_returns_observation_and_worker_can_continue(tmp_path):
    import json
    from copy import deepcopy
    from langchain_core.messages import AIMessage, ToolMessage
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, invoke, observation
    from test_evidence_tools016 import native_source_investigation

    ws, cs, _, source_refs = native_source_investigation(tmp_path)
    before_objects = deepcopy(cs.list_objects())
    before_manifest = deepcopy(ws.store.manifest)
    before_blocks = Catalog(ws.store).read("original")
    original_pdf = (tmp_path / "sources/original.pdf").read_bytes()
    captured = {}

    def correct(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "search_sources")
        error = observation(messages, "search_sources")
        assert message.status == "error" and not error["accepted"]
        assert "SEARCH_QUERY_REQUIRED" in str(error)
        captured["error"] = deepcopy(error)
        return invoke("search_sources", query="Frozen", source_id="original")

    def read_found(messages):
        result = observation(messages, "search_sources")
        assert result["total"] == 1 and result["scope"]["searched_source_ids"] == ["original"]
        return invoke("read_source_page", source_id="original", offset=0, limit=50)

    def finish_read(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "read_source_page")
        result = observation(messages, "read_source_page")
        assert result["blocks"] == before_blocks["blocks"] and result["next_offset"] is None
        assert "Frozen OCR must not be replaced" in str(result["blocks"])
        receipt = message.artifact["source_material"]
        issued = ws.store.get("source_material:" + receipt["receipt"])
        assert issued["actor"]["role"] == "writer"
        task = cs.list_objects("DelegatedTask")[0]
        assert issued["actor"]["task_id"] == task["ref"]["id"]
        assert receipt["source_version_refs"] == source_refs
        captured["read"] = deepcopy(result)
        return AIMessage(content=json.dumps({"source_observation": result, "limitation": "Read only; no report or review completed."}))

    def parent(messages):
        returned = observation(messages, "task")
        assert returned["source_observation"] == captured["read"]
        captured["parent_received"] = True
        return AIMessage(content="Actual source observation received; no report or review approval.")

    driver = Driver(coordinator=[invoke("task", subagent_type="writer",
            description="Read the supplied original, correcting failed tool arguments; return observations without writing a report."), parent],
        writer=[invoke("search_sources", query="", source_id="original"), correct, read_found, finish_read])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert captured["parent_received"] and captured["error"]
    assert not cs.list_objects("ReviewRecord")
    assert [o for o in cs.list_objects() if o["ref"]["type"] != "DelegatedTask"] == before_objects
    assert len(cs.list_objects("DelegatedTask")) == 1
    assert not any(role in {"text_tool", "reviewer", "rubric_grader"} for role, _, _ in driver.calls)
    assert report_state.selected_delivery(ws.store) is None
    assert ws.store.manifest == before_manifest and Catalog(ws.store).read("original") == before_blocks
    assert (tmp_path / "sources/original.pdf").read_bytes() == original_pdf
