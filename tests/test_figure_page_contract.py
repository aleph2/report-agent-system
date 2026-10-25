"""Figure output contract, native received failure, and actual nonfirst-page DOCX."""
import hashlib
import json
from io import BytesIO
from zipfile import ZipFile

import jsonschema
import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError
from pypdf import PdfWriter

from report_agent.content_models import ContentNode
from report_agent.content_inputs import NodeInput
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.content_export import export_snapshot
from report_agent.document_tools import vision_source_image
from report_agent.deep_runtime import run_report
from report_agent.store import Store
from report_agent.text_work import output_contract
from report_agent.workspace import Workspace
from test_bounded_review import Model
from test_deep_runtime import Driver, invoke, observation
from test_task_supervision import ws, offline
from test_text_work import tools, writer_call


def figure(page=2):
    return {'kind':'figure', 'body':{'source_id':'fig','caption':'Second physical page','page':page},
            'qualifiers':{}, 'claim_kind':'fact'}


def test_received_chinese_page_label_is_rejected_before_adoption():
    with pytest.raises(ValidationError, match='POSITIVE_INTEGER_PHYSICAL_PAGE'):
        ContentNode.model_validate(figure('物理页101'))


@pytest.mark.parametrize('bad', [True, 2.0, '2', 0, -1, None])
def test_strict_renderer_page_contract(bad):
    with pytest.raises(ValidationError, match='POSITIVE_INTEGER_PHYSICAL_PAGE'):
        ContentNode.model_validate(figure(bad))


def test_output_and_registered_adoption_expose_page(ws):
    schemas = [ContentNode.model_json_schema(), NodeInput.model_json_schema(), output_contract(ContentNode,1)]
    with delegated_task(ws, 'coordinator', writer_call()):
        schema = convert_to_openai_tool(StructuredTool.from_function(tools(ws,'writer', Model())['commit_objects']))
    # The provider adapter dereferences and removes titles; inspect its actual shape.
    adoption = []
    def locate(value):
        if isinstance(value,dict):
            if {'kind','body','qualifiers','claim_kind'} <= value.get('properties',{}).keys():
                adoption.append(value)
            for child in value.values(): locate(child)
        elif isinstance(value,list):
            for child in value: locate(child)
    locate(schema['function']['parameters'])
    assert adoption, 'Actual registered model-facing adoption payload missing'
    schemas.extend(adoption)
    for schema in schemas:
        jsonschema.validate(figure(2), schema)
        for bad in [True, '2', '物理页101', 0, -1, None]:
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(figure(bad), schema)
        missing = figure(); del missing['body']['page']
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(missing, schema)
    with pytest.raises(ValidationError, match='POSITIVE_INTEGER_PHYSICAL_PAGE'):
        ContentNode.model_validate(missing)


async def test_native_bad_figure_is_received_failure_not_unexecuted(ws):
    raw = json.dumps(figure('物理页101'), ensure_ascii=False)
    seen = []
    def inspect(messages):
        error = observation(messages,'process_report_content')
        seen.append(error)
        assert error['code'] == 'TEXT_WORK_OUTPUT_CONTRACT_INVALID'
        assert error.get('execution_state') != 'not_executed'
        return AIMessage(content='Known received invalid output preserved; no adoption.')
    driver = Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage(content='Recorded.')],
        writer=[invoke('process_report_content',operation_id='figure-invalid-page',
             objective='Include the selected physical source page as a figure.',object_type='ContentNode',
             source_selections=[{'source_id':'s'}]),inspect],
        text_tool=[AIMessage(content=raw)])
    await run_report(ws,driver)
    assert seen and sum(r=='text_tool' for r,_,_ in driver.calls)==1
    assert not ContentStore(ws.store).list_objects('ContentNode')
    actual = next(e['data']['input']['output_schema'] for e in ws.store.events() if e['kind']=='evidence_analysis_input')
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(json.loads(raw),actual)
    with ws.store.connect() as db:
        received = [json.loads(v) for v, in db.execute("SELECT value FROM state WHERE key LIKE 'text_work:%:figure-invalid-page'")]
    assert len(received)==1 and received[0]['state']=='known_failed'
    assert received[0]['raw_response_received'] is True
    assert ws.store.analysis(received[0]['operation'])['analysis']==raw


async def test_registered_produce_adopt_export_embeds_exact_second_page(tmp_path):
    pdf=PdfWriter()
    pdf.add_blank_page(width=100,height=100)
    pdf.add_blank_page(width=200,height=80)
    buffer=BytesIO();pdf.write(buffer);original=buffer.getvalue()
    root=tmp_path/'case';(root/'sources').mkdir(parents=True)
    (root/'sources/two-pages.pdf').write_bytes(original)
    store=Store(root)
    store.initialize({'goal':'Include the selected physical source page.',
        'content_contract':'hierarchical-review-v1','review_entrypoint':'delegated-reviewer-v1',
        'sources':[{'id':'fig','title':'Two different pages','filename':'two-pages.pdf',
            'content':'Two physical pages with different dimensions.','coverage':'complete',
            'copied_path':'sources/two-pages.pdf','sha256':hashlib.sha256(original).hexdigest()}]})
    workspace=Workspace(store);cs=ContentStore(store);model=Model(json.dumps(figure(2)))
    with delegated_task(workspace,'coordinator',writer_call()) as (_,actor):
        funcs=tools(workspace,'writer',model)
        sources=cs.capture_sources(actor,'sources',['fig'])['result']['source_refs']
        work=await funcs['process_report_content']('figure','Include selected page2.','ContentNode',sources)
        ref=funcs['save_text_node']('adopt',work['text_work_id'])['result']['refs']['text']
        snap=cs.freeze(actor,'snapshot',ref,[ref,*sources])['result']['snapshot_ref']
        result=export_snapshot(cs,actor,'export',snap)['result']
    expected,_=vision_source_image(workspace,'fig',2,None)
    first,_=vision_source_image(workspace,'fig',1,None)
    assert expected != first
    with ZipFile(root/result['file_ref']) as z:
        embedded=[z.read(n) for n in z.namelist() if n.startswith('word/media/')]
    assert embedded == [expected]
    assert len(model.calls)==1
    assert cs.read(ref)['payload']==figure(2)
    assert (root/'sources/two-pages.pdf').read_bytes()==original
