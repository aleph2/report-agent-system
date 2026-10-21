"""Actual image/provenance boundaries; no simulated model-quality claim."""
from io import BytesIO
from types import SimpleNamespace
from PIL import Image
import pytest
from report_agent.content_export import inspect_render
from report_agent.errors import ActionRejected
from report_agent.store import Store
from report_agent.hierarchical_tools import actor_for

RENDER={'type':'RenderArtifact','id':'render','version':1}
EXPORT={'type':'ExportArtifact','id':'word','version':1}

def png(color):
    data=BytesIO()
    with Image.new('RGB',(100,200),color) as im:im.save(data,format='PNG')
    return data.getvalue()

class Contents:
    store=object()
    def __init__(self,suffix='docx'):self.suffix=suffix
    def read(self,ref):
        if ref==RENDER:return {'payload':{'page_assets':[{'asset_ref':'image.png','sha256':'digest'}],'export_ref':EXPORT}}
        assert ref==EXPORT
        return {'payload':{'file_ref':'actual.'+self.suffix}}
    def observe(self,actor,result):return {'result':result}

@pytest.fixture(autouse=True)
def initialized_project(tmp_path, monkeypatch):
    # Explicit unit-fixture migration: real Store/Actor protocol, no new grant.
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic paired image boundary', 'sources': [
        {'id': 'reference', 'title': 'Synthetic reference', 'content': 'Synthetic reference image only', 'coverage': 'complete'}]})
    monkeypatch.setattr(Contents, 'store', store)

@pytest.fixture
def capture(monkeypatch):
    import report_agent.content_export as exporting
    import report_agent.document_tools as docs
    import report_agent.vision as vision
    calls=[]
    monkeypatch.setattr(exporting,'_bytes',lambda *args:png('blue'))
    def reference(workspace,source,page,crop):
        if source!='reference':raise ActionRejected('SOURCE_NOT_IN_PROJECT')
        return png('green'),{'source_id':source,'page':page,'coverage':'region_only' if crop else 'full_page_image','crop':crop}
    monkeypatch.setattr(docs,'vision_source_image',reference)
    async def observation(store,data,provenance,question,client,actor=None):
        calls.append((data,provenance,question))
        return {'status':'observed','source':provenance,'observation':'Fixture observation'}
    monkeypatch.setattr(vision,'_observe',observation)
    return calls

async def test_single_page_compatibility_and_exact_scope(capture):
    result=await inspect_render(Contents(),actor_for("coordinator"),RENDER,1,'Question',client=object())
    assert capture[0][0]==png('blue') and capture[0][2]=='Question'
    assert result['result']['source']['coverage']=='full_page_image'

async def test_paired_reference_is_in_same_fresh_request(capture):
    result=await inspect_render(Contents(),actor_for("coordinator"),RENDER,1,'Compare visible style',client=object(),
        reference_source_id='reference',reference_page=44)
    with Image.open(BytesIO(capture[0][0])) as image:
        assert image.getpixel((50,100))==(0,128,0)
        assert image.getpixel((175,100))==(0,0,255)
    source=result['result']['source']
    assert source['render_ref']==RENDER and source['page']==1
    assert source['presentation_reference']['page']==44
    assert 'CUSTOMER' in capture[0][2] and 'GENERATED' in capture[0][2]

async def test_close_region_cannot_claim_full_page(capture):
    result=await inspect_render(Contents(),actor_for("coordinator"),RENDER,1,'Inspect top text',client=object(),crop=[0,0,1,.2])
    assert result['result']['source']['coverage']=='region_only'
    with Image.open(BytesIO(capture[0][0])) as image:assert image.size==(100,40)
    assert 'not a full-page' in capture[0][2]

@pytest.mark.parametrize('crop',[[-.1,0,1,1],[0,0,1,float('nan')],[0,0,0,1],[True,0,1,1]])
async def test_invalid_region_does_not_call_model(capture,crop):
    with pytest.raises(ActionRejected,match='INVALID_CROP'):
        await inspect_render(Contents(),actor_for("coordinator"),RENDER,1,'Question',client=object(),crop=crop)
    assert not capture

async def test_foreign_reference_does_not_call_model(capture):
    with pytest.raises(ActionRejected,match='NOT_IN_PROJECT'):
        await inspect_render(Contents(),actor_for("coordinator"),RENDER,1,'Question',client=object(),reference_source_id='foreign')
    assert not capture

async def test_excel_is_not_visually_checked(capture):
    with pytest.raises(ActionRejected,match='NO_EXCEL_LAYOUT'):
        await inspect_render(Contents('xlsx'),actor_for("coordinator"),RENDER,1,'Question',client=object())
    assert not capture
