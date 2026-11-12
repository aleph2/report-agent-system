"""Read-time bounded geometry, not scan-origin or OCR-quality inference."""
from io import BytesIO
import json

from PIL import Image
from pypdf import PdfWriter, PdfReader
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject
import pytest

from test_document_tools import workspace, snapshot
from test_ingestion import pdf_bytes
from report_agent.document_tools import source_page_info, vision_source_image


def graphic_pdf(*, image=False, text=False, vector=False, rotation=0, crop=False):
    writer=PdfWriter();page=writer.add_blank_page(width=200,height=100)
    resources=DictionaryObject();parts=[]
    if image:
        obj=DecodedStreamObject();obj.set_data(b'\xff\xff\xff')
        obj.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),
            NameObject('/Width'):NumberObject(1),NameObject('/Height'):NumberObject(1),
            NameObject('/ColorSpace'):NameObject('/DeviceRGB'),NameObject('/BitsPerComponent'):NumberObject(8)})
        resources[NameObject('/XObject')]=DictionaryObject({NameObject('/Im'):writer._add_object(obj)})
        parts.append('q 200 0 0 100 0 0 cm /Im Do Q')
    if text:
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        resources[NameObject('/Font')]=DictionaryObject({NameObject('/F1'):writer._add_object(font)})
        parts.append('BT /F1 10 Tf 10 10 Td (Native text) Tj ET')
    if vector:parts.extend(['0 0 100 100 re f']*10000)
    page[NameObject('/Resources')]=resources
    stream=DecodedStreamObject();stream.set_data('\n'.join(parts).encode());page[NameObject('/Contents')]=writer._add_object(stream)
    if rotation:page.rotate(rotation)
    if crop:page.cropbox.lower_left=(0,0);page.cropbox.upper_right=(100,100)
    out=BytesIO();writer.write(out);return out.getvalue()


@pytest.mark.parametrize('kind', ['text','image','mixed','vector'])
def test_reader_page_facts_and_no_source_or_database_write(tmp_path,kind):
    data=graphic_pdf(image=kind in ['image','mixed'],text=kind in ['text','mixed'],vector=kind=='vector')
    ws=workspace(tmp_path,data);before=snapshot(ws)
    one=source_page_info(ws,'original',1);two=source_page_info(ws,'original',1)
    facts=one['page_facts'];assert facts==two['page_facts'] and facts['status']=='observed'
    assert facts['graphics_grid']==[200,200]
    assert facts['scan_like']==(kind=='image')
    assert facts['graphics_coverage']==pytest.approx({'text':0,'image':1,'mixed':1,'vector':.5}[kind])
    assert facts['native_character_count']>0 if kind in ['text','mixed'] else facts['native_character_count']==0
    assert 'ocr_quality' not in facts
    assert snapshot(ws)==before and (tmp_path/'sources/original.pdf').read_bytes()==data


@pytest.mark.parametrize('options',[{'rotation':90},{'crop':True}])
def test_one_rotated_and_one_cropped_page(tmp_path,options):
    facts=source_page_info(workspace(tmp_path,graphic_pdf(image=True,**options)),'original',1)['page_facts']
    assert facts['scan_like'] and facts['graphics_coverage']==1


def test_geometry_parse_failure_is_unknown(tmp_path,monkeypatch):
    monkeypatch.setattr('report_agent.source_tables.pdfplumber.open',lambda *a,**k: (_ for _ in ()).throw(ValueError('private details')))
    value=source_page_info(workspace(tmp_path),'original',1)
    assert value['page_facts']['status']=='unavailable'
    assert value['page_facts']['graphics_coverage'] is None and value['page_facts']['scan_like'] is None
    assert 'private details' not in json.dumps(value)


def test_vision_host_size_limit_is_distinct_from_report_rendition(tmp_path):
    ws=workspace(tmp_path,graphic_pdf(image=True))
    png,provenance=vision_source_image(ws,'original',max_edge=128)
    with Image.open(BytesIO(png)) as image:assert max(image.size)<=128
    assert provenance['render_limits']['max_output_edge']==128


def test_default_block_reader_exposes_image_only_page_without_inventing_block_offset(tmp_path):
    from report_agent.catalog import Catalog
    from report_agent.source_tables import present_source_tables
    ws=workspace(tmp_path)
    catalog=Catalog(ws.store)
    source_id=catalog.import_file('drawing.pdf',graphic_pdf(image=True))['source']['id']
    before=catalog.read(source_id)
    assert before['blocks']==[]
    result=present_source_tables(ws,before)
    assert result['blocks']==before['blocks'] and result['next_offset']==before['next_offset']
    assert result['source_table_views'][0]['page']==1
    assert result['source_table_views'][0]['page_facts']['scan_like']
