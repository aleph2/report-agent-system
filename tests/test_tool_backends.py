"""Deterministic catalog eligibility; no selector model or financial reservation."""
from pathlib import Path
import pytest
from langchain.agents.middleware.types import ModelRequest

from report_agent.tool_selection import tool_scope, scope_catalog, validate_catalog, TOOL_BACKENDS
from test_context_editing import offered
from test_deep_runtime import Driver


def request(names):
    return ModelRequest(model=Driver()('coordinator'),messages=[],state={'messages':[]},tools=[offered(n) for n in names])


@pytest.mark.parametrize('vision',[False,True])
def test_catalog_depends_on_exact_authorized_backend(vision):
    original=request(['read_source_page','analyze_source_image','analyze_text','task','request_system_delivery'])
    services={'coordinator':'glm-5.3','text_tool':'glm-5.3','vision':'deepseek-v4.1-flash-1017'}
    allowed={'glm-5.3'}|({'deepseek-v4.1-flash-1017'} if vision else set())
    with tool_scope(allowed,services,excluded={'task','request_system_delivery'}):
        outgoing=scope_catalog(original)
        names={t['function']['name'] for t in outgoing.tools}
        assert names=={'read_source_page','analyze_text'}|({'analyze_source_image'} if vision else set())
        validate_catalog(outgoing.tools)
        with pytest.raises(Exception,match='TOOL_BACKEND_NOT_AUTHORIZED'):
            validate_catalog([offered('task')])
    assert scope_catalog(original) is original


def test_static_check_fails_for_unclassified_or_unapproved_offered_backend():
    with tool_scope({'glm-5.3'},{'vision':'not-approved'}):
        for name in ['new_unclassified_tool','analyze_source_image']:
            with pytest.raises(Exception,match='TOOL_BACKEND_NOT_AUTHORIZED'):
                validate_catalog([offered(name)])
    assert TOOL_BACKENDS['read_source_page']==()
    assert TOOL_BACKENDS['analyze_source_image']==('vision',)


def test_every_registered_business_tool_has_a_backend_declaration(tmp_path):
    from report_agent.fake_draft_flow import prepare
    from report_agent.workspace import Workspace
    from report_agent.store import Store
    from report_agent.deep_runtime import business_tools
    from test_fake_draft_flow import PROFILES
    prepared=prepare(Path(__file__).parent/"fake_data/mini_commission/inputs",tmp_path/"case",PROFILES)
    ws=Workspace(Store(Path(prepared["case_path"])))
    for role in ("coordinator","writer","reviewer","layout"):
        names={getattr(t,"name",None) or t.__name__ for t in business_tools(ws,role,None,None)}
        assert names<=TOOL_BACKENDS.keys(), (role,names-TOOL_BACKENDS.keys())
