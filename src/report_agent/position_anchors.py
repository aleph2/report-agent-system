"""Comments anchored by node-local rendered coordinates, never text matching."""
from copy import deepcopy

from docx.oxml.ns import qn
from docx.text.run import Run
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import ActionRejected


class ParagraphAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    paragraph_index: int = Field(ge=0)
    start: int = Field(default=0, ge=0)
    end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def nonempty_range(self):
        if self.end is not None and self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


def comment_position(doc, paragraphs, issue, node_ref, excluded=()):
    """The caller supplies only this node's rendered paragraph range."""
    anchor = issue.anchor
    if not isinstance(anchor, ParagraphAnchor) or anchor.paragraph_index >= len(paragraphs):
        raise ActionRejected(f"MATERIAL_ISSUE_POSITION_INVALID: {issue.id}; node={node_ref}")
    paragraph = paragraphs[anchor.paragraph_index]
    end = len(paragraph.text) if anchor.end is None else anchor.end
    comment_range(doc, paragraph, anchor.start, end, issue, node_ref, excluded)


def comment_range(doc, paragraph, start, end, issue, node_ref, excluded=()):
    """Split touched plain-text runs at numeric offsets; validate before mutation."""
    text = paragraph.text
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise ActionRejected(f"MATERIAL_ISSUE_POSITION_INVALID: {issue.id}; node={node_ref}")
    supported_paragraph = {qn('w:' + tag) for tag in (
        'pPr', 'r', 'bookmarkStart', 'bookmarkEnd', 'commentRangeStart', 'commentRangeEnd',
        'proofErr', 'permStart', 'permEnd')}
    runs = list(paragraph.runs)
    if any(child.tag not in supported_paragraph for child in paragraph._p) or ''.join(r.text for r in runs) != text:
        raise ActionRejected(f"MATERIAL_ISSUE_RENDERED_RUNS_UNSUPPORTED: {issue.id}; node={node_ref}")
    supported_run = {qn('w:' + tag) for tag in ('rPr', 't', 'tab', 'br', 'cr')}
    position, touched = 0, []
    for run in runs:
        stop = position + len(run.text)
        if position < end and stop > start:
            if any(child.tag not in supported_run or child.tag == qn('w:br')
                   and child.get(qn('w:type')) not in (None, 'textWrapping') for child in run._r):
                raise ActionRejected(f"MATERIAL_ISSUE_RENDERED_RUNS_UNSUPPORTED: {issue.id}; node={node_ref}")
            touched.append((run, max(0, start-position), min(len(run.text), end-position)))
        position = stop
    selected = []
    for run, left, right in touched:
        original, template = run.text, deepcopy(run._r)
        parts = [(original[:left], False), (original[left:right], True), (original[right:], False)]
        last = None
        for value, included in parts:
            if not value:
                continue
            if last is None:
                fragment = run
            else:
                element = deepcopy(template)
                last.addnext(element)
                fragment = Run(element, paragraph)
            fragment.text = value
            last = fragment._r
            if included:
                selected.append(fragment)
    doc.add_comment(selected, issue.comment(excluded), author="待核", initials="核")
