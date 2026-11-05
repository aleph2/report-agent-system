from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document
from docx.oxml import OxmlElement
from pydantic import ValidationError

from report_agent.errors import ActionRejected
from report_agent.position_anchors import ParagraphAnchor, comment_position, comment_range

NODE = {"type": "ContentNode", "id": "own-node", "version": 4}

def issue(**position):
    return SimpleNamespace(id="MI-3-2-01", anchor=ParagraphAnchor(**position),
                           comment=lambda: "Original issue explanation")

def selected_text(paragraph):
    children = list(paragraph._p)
    start = next(i for i, node in enumerate(children) if node.tag.endswith('commentRangeStart'))
    end = next(i for i, node in enumerate(children) if node.tag.endswith('commentRangeEnd'))
    return ''.join(node.text or '' for child in children[start+1:end] for node in child.xpath('.//w:t'))

def test_position_targets_own_node_even_when_all_paragraph_text_is_identical():
    doc = Document()
    elsewhere = doc.add_paragraph('same text')
    own = [doc.add_paragraph('same text'), doc.add_paragraph('same text')]
    comment_position(doc, own, issue(paragraph_index=1), NODE)
    assert not elsewhere._p.xpath('.//w:commentRangeStart')
    assert not own[0]._p.xpath('.//w:commentRangeStart')
    assert selected_text(own[1]) == 'same text'
    data = BytesIO(); doc.save(data)
    reopened = Document(BytesIO(data.getvalue()))
    assert len(reopened.comments) == 1
    assert reopened.comments.get(0).text == 'Original issue explanation'

def test_partial_range_crosses_runs_and_preserves_formatting():
    doc = Document(); paragraph = doc.add_paragraph()
    paragraph.add_run('abc').bold = True
    paragraph.add_run('def').italic = True
    comment_range(doc, paragraph, 1, 5, issue(paragraph_index=0), NODE)
    assert paragraph.text == 'abcdef'
    assert selected_text(paragraph) == 'bcde'
    assert [(r.text, r.bold, r.italic) for r in paragraph.runs if r.text] == [
        ('a', True, None), ('bc', True, None), ('de', None, True), ('f', None, True)]

def test_unicode_offsets_and_default_end():
    doc = Document(); paragraph = doc.add_paragraph('前文边坡14m尾')
    comment_position(doc, [paragraph], issue(paragraph_index=0, start=2), NODE)
    assert selected_text(paragraph) == '边坡14m尾'

@pytest.mark.parametrize('paragraphs, position', [
    ([], dict(paragraph_index=0)),
    (['text'], dict(paragraph_index=1)),
    ([''], dict(paragraph_index=0)),
    (['text'], dict(paragraph_index=0, start=4)),
    (['text'], dict(paragraph_index=0, end=5)),
])
def test_invalid_position_refuses_before_mutating_document(paragraphs, position):
    doc = Document(); own = [doc.add_paragraph(text) for text in paragraphs]
    before = doc.element.xml
    with pytest.raises(ActionRejected) as caught:
        comment_position(doc, own, issue(**position), NODE)
    assert 'MI-3-2-01' in str(caught.value) and 'own-node' in str(caught.value)
    assert doc.element.xml == before and len(doc.comments) == 0

@pytest.mark.parametrize('start,end', [(-1, 2), (0, 0), (2, 1), (0, 5), (True, 2), (0, 1.5)])
def test_direct_range_validates_numeric_bounds(start, end):
    doc = Document(); paragraph = doc.add_paragraph('text'); before = paragraph._p.xml
    with pytest.raises(ActionRejected) as caught:
        comment_range(doc, paragraph, start, end, issue(paragraph_index=0), NODE)
    assert 'MI-3-2-01' in str(caught.value) and 'own-node' in str(caught.value)
    assert paragraph._p.xml == before

@pytest.mark.parametrize('payload', [dict(paragraph_index=-1), dict(paragraph_index='0'),
    dict(paragraph_index=True), dict(paragraph_index=0, start=-1), dict(paragraph_index=0, end=0),
    dict(paragraph_index=0, start=3, end=2), dict(paragraph_index=0, unexpected=1)])
def test_anchor_contract_is_strict(payload):
    with pytest.raises(ValidationError): ParagraphAnchor.model_validate(payload)

@pytest.mark.parametrize('tag', ['drawing', 'fldChar', 'instrText'])
def test_unsupported_run_content_is_not_lost_on_refusal(tag):
    doc = Document(); paragraph = doc.add_paragraph('text')
    paragraph.runs[0]._r.append(OxmlElement('w:' + tag)); before = paragraph._p.xml
    with pytest.raises(ActionRejected, match='MATERIAL_ISSUE_RENDERED_RUNS_UNSUPPORTED') as caught:
        comment_position(doc, [paragraph], issue(paragraph_index=0), NODE)
    assert 'MI-3-2-01' in str(caught.value) and 'own-node' in str(caught.value)
    assert paragraph._p.xml == before

def test_non_direct_text_is_rejected_before_mutation():
    doc = Document(); paragraph = doc.add_paragraph('prefix')
    link = OxmlElement('w:hyperlink'); run = OxmlElement('w:r'); text = OxmlElement('w:t')
    text.text = 'linked'; run.append(text); link.append(run); paragraph._p.append(link)
    before = paragraph._p.xml
    with pytest.raises(ActionRejected, match='MATERIAL_ISSUE_RENDERED_RUNS_UNSUPPORTED'):
        comment_position(doc, [paragraph], issue(paragraph_index=0), NODE)
    assert paragraph._p.xml == before

def test_existing_comment_and_unselected_drawing_are_preserved():
    doc = Document(); paragraph = doc.add_paragraph('abcdefgh')
    drawing = paragraph.add_run(); drawing._r.append(OxmlElement('w:drawing'))
    comment_position(doc, [paragraph], issue(paragraph_index=0, start=0, end=2), NODE)
    comment_position(doc, [paragraph], issue(paragraph_index=0, start=4, end=6), NODE)
    assert paragraph.text == 'abcdefgh' and len(doc.comments) == 2
    assert len(paragraph._p.xpath('.//w:drawing')) == 1
