"""Offline Reviewer boundary over immutable snapshots of native Writer drafts."""
import pytest

from report_agent.content_store import ContentStore
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import digest
from report_agent.writer_runtime import writer_session
from report_agent.writer_assessment import _assignment
from test_fake03_qualitative_steps import mini


def test_qualitative_reviewer_freezes_task_scoped_rows_and_separate_findings(mini):
    from report_agent.qualitative_review import qualitative_reviewer_session
    ws, binding, profile = mini
    ws.store.set('fake03_qualitative_profile', profile)
    cs = ContentStore(ws.store)
    with writer_session(ws, '坡段 A', None, assessment_only=True, indicator_steps=True,
                        section_id=binding.assessment_section_id) as writer:
        ws.store.set('fake03_qualitative_actor:' + writer.actor.id,
                     dict(plan_ref=binding.plan_ref, object_id='A', profile_digest=digest(profile)))
        with ws.store.connect() as db:
            scope = _assignment(cs, db, writer.actor)
        from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
        step = read_indicator_step(cs, writer.actor)
        ind = step['indicator_id']
        question = 'Which rock subtype is documented?'
        outcome = {'kind':'gap', 'question':question, 'missing':'Rock subtype'}
        save_indicator_outcome(cs, writer.actor, 'writer-save', ind, outcome)
    key = 'writer_indicator_steps:' + scope['assignment_digest']
    draft = ws.store.get(key)
    row = draft['rows'][ind]
    from report_agent.hierarchical_tools import content_tools
    from report_agent.deep_runtime import business_tools
    cached_runtime = business_tools(ws, 'reviewer', None, None)
    cached_runtime_handles = business_tools(ws, 'reviewer', None, None, reviewer_handles=True)
    assert 'read_source_page' in {t.__name__ for t in cached_runtime}
    from langchain_core.tools import StructuredTool
    from report_agent.hierarchical_tools import general_reviewer_tool
    from report_agent.native_operation_tools import MessageTool
    from pydantic import BaseModel

    class Input(BaseModel):
        subject: str

    def read_subject(subject: str) -> str:
        """Example read with a native V4 schema."""
        return subject

    structured = StructuredTool.from_function(read_subject, args_schema=Input)
    message = MessageTool.from_function(read_subject, args_schema=Input, message_model=Input)
    guarded_sdk_tools = []
    for original in (structured, message):
        guarded = general_reviewer_tool(original)
        assert type(guarded) is type(original)
        assert guarded.args_schema is original.args_schema
        assert guarded.tool_call_schema.model_json_schema() == original.tool_call_schema.model_json_schema()
        assert guarded.invoke({'subject':'A'}) == 'A'
        guarded_sdk_tools.append(guarded)
    cached = content_tools(ws, 'reviewer')
    cached_handles = content_tools(ws, 'reviewer', reviewer_handles=True)
    with qualitative_reviewer_session(ws, scope['task_ref']) as tools:
        # The runtime may construct normal report tools before native delegation.
        # The scope check must precede parameter validation, reads, and writes.
        import inspect
        import asyncio
        for guarded in guarded_sdk_tools:
            with pytest.raises(ActionForbidden, match='QUALITATIVE_REVIEW_GENERAL_TOOL_FORBIDDEN'):
                guarded.invoke({'subject':'B'})
            with pytest.raises(ActionForbidden, match='QUALITATIVE_REVIEW_GENERAL_TOOL_FORBIDDEN'):
                asyncio.run(guarded.ainvoke({'subject':'B'}))
        for handles in (False, True):
            live = business_tools(ws, 'reviewer', None, None, reviewer_handles=handles)
            assert {tool.__name__ for tool in live} == set(tools)
        for tool in [*cached, *cached_handles, *cached_runtime, *cached_runtime_handles]:
            with pytest.raises(ActionForbidden, match='QUALITATIVE_REVIEW_GENERAL_TOOL_FORBIDDEN'):
                if inspect.iscoroutinefunction(tool):
                    asyncio.run(tool())
                else:
                    tool()

        assert set(tools) == {'read_qualitative_row', 'record_qualitative_finding'}
        read = tools['read_qualitative_row']
        index = read()
        view = read(ind)
        assert view['saved_row'] == row and view['indicator_method']['id'] == ind
        assert view['saved_row']['input']['question'] == question
        assert view['object_facts'] == profile['facts']['A']
        assert view['provenance']['plan_ref'] == binding.plan_ref
        assert view['provenance']['source_versions']
        assert view['provenance']['fact_digest'] == digest(profile['facts']['A'])
        assert index['rows'] == {ind: view['row_digest']}
        with pytest.raises(ActionRejected, match='ROW_OUTSIDE'):
            read('B/'+ind)
        write = tools['record_qualitative_finding']
        with pytest.raises(ActionRejected, match='ROW_DIGEST'):
            write('wrong-digest',ind,'bad','Period is open.')
        saved = write('record',ind,view['row_digest'],'Period is open.')
        assert ws.store.get(key) == draft
        assert write('record',ind,view['row_digest'],'Period is open.')['result'] == saved['result']
        assert cs.read(saved['result']['finding_ref'])['payload']['row_digest'] == view['row_digest']
        from report_agent.hierarchical_tools import content_tools
        ws.store.set('fake03_qualitative_profile', None)
        assert {t.__name__ for t in content_tools(ws,'reviewer')} == set(tools)
        assert view == read(ind)
        # Later Writer work cannot change what this Reviewer was assigned.
        ws.store.set(key, {**draft, 'rows': {}})
        assert read(ind) == view
        assert not cs.list_objects('Assessment')
    with pytest.raises(ActionForbidden):
        read(ind)
    ws.store.set('fake03_qualitative_profile', profile)
    foreign = {'source_ref':{'type':'SourceArtifact','id':'elsewhere','version':1},
               'locator':'p. 1','quote':'unauthorized'}
    ws.store.set(key, {**draft, 'rows':{ind:{**row, 'sources':[foreign]}}})
    with pytest.raises(ActionForbidden, match='SOURCE_OUTSIDE'):
        with qualitative_reviewer_session(ws, scope['task_ref']):
            pytest.fail('a foreign source was accepted')
