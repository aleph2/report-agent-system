"""Saved-export evidence, not report approval or a substitute for visual inspection."""

from __future__ import annotations

import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
import re
import tempfile
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .errors import ActionRejected
from .exporting import export_docx
from .workspace import Workspace


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
      "v": "urn:schemas-microsoft-com:vml"}
W = "{" + NS["w"] + "}"
MAX_READ = 100
BLOCK_CHARACTERS = 400
SCHEMA = "ooxml-preview-v1"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(element) -> str:
    parts = []
    for node in element.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag == W + "tab":
            parts.append("\t")
        elif node.tag in (W + "br", W + "cr"):
            parts.append("\n")
    return "".join(parts)


def _fields(element) -> list[str]:
    result, stack = [], []
    for node in element.iter():
        if node.tag == W + "fldSimple":
            result.append(node.get(W + "instr", ""))
        elif node.tag == W + "fldChar":
            kind = node.get(W + "fldCharType")
            if kind == "begin":
                stack.append([])
            elif kind == "end" and stack:
                result.append("".join(stack.pop()))
        elif node.tag == W + "instrText" and stack:
            stack[-1].append(node.text or "")
    return [value.strip() for value in result if value.strip()]


def _on(element) -> bool:
    return element is not None and element.get(W + "val", "true") not in ("0", "false", "off")


def _structure(data: bytes) -> tuple[dict, str]:
    with ZipFile(BytesIO(data)) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        body = document.find("w:body", NS)
        styles = ET.fromstring(archive.read("word/styles.xml"))
        style_map = {s.get(W + "styleId"): s for s in styles.findall("w:style", NS)}

        def style_property(style_id, path):
            seen = set()
            while style_id in style_map and style_id not in seen:
                seen.add(style_id)
                style = style_map[style_id]
                found = style.find(path, NS)
                if found is not None:
                    return found.get(W + "val")
                parent = style.find("w:basedOn", NS)
                style_id = parent.get(W + "val") if parent is not None else None
            return None

        paragraphs = list(body.iter(W + "p"))
        headings, titles = [], []
        for index, paragraph in enumerate(paragraphs):
            style = paragraph.find("w:pPr/w:pStyle", NS)
            style_id = style.get(W + "val") if style is not None else None
            outline = paragraph.find("w:pPr/w:outlineLvl", NS)
            level = (outline.get(W + "val") if outline is not None else
                     style_property(style_id, "w:pPr/w:outlineLvl"))
            name = style_property(style_id, "w:name") or ""
            if level is not None and level.isdigit() and int(level) < 9:
                headings.append({"paragraph_index": index, "level": int(level) + 1,
                                 "text": _text(paragraph)[:300]})
            if style_id == "Title" or name.lower() == "title":
                titles.append({"paragraph_index": index, "text": _text(paragraph)[:300]})

        sections = []
        for section in body.iter(W + "sectPr"):
            size = section.find("w:pgSz", NS)
            margins = section.find("w:pgMar", NS)
            sections.append({
                "page_size_twips": {k.removeprefix(W): v for k, v in size.attrib.items()} if size is not None else {},
                "margins_twips": {k.removeprefix(W): v for k, v in margins.attrib.items()} if margins is not None else {},
                "different_first_page": _on(section.find("w:titlePg", NS)),
                "header_references": [dict(e.attrib) for e in section.findall("w:headerReference", NS)],
                "footer_references": [dict(e.attrib) for e in section.findall("w:footerReference", NS)],
            })
        headers, footers = [], []
        for name in sorted(archive.namelist()):
            if re.fullmatch(r"word/(header|footer)\d+\.xml", name):
                part = ET.fromstring(archive.read(name))
                text = "\n".join(_text(p) for p in part.iter(W + "p"))
                fields = _fields(part)
                (headers if "/header" in name else footers).append({
                    "part": name, "text_excerpt": text[:500], "text_characters": len(text),
                    "fields": fields[:20], "field_count": len(fields),
                })
        fields = _fields(body)
        toc = [f for f in fields if re.match(r"^TOC\b", f, re.IGNORECASE)]
        tables = list(body.iter(W + "tbl"))
        text = "\n".join(_text(p) for p in paragraphs)
        return {
            "counts": {"paragraphs": len(paragraphs), "body_paragraphs": len(body.findall("w:p", NS)),
                       "headings": len(headings), "tables": len(tables),
                       "images": len(body.findall(".//pic:pic", NS)) + len(body.findall(".//v:imagedata", NS)),
                       "media_files": sum(n.startswith("word/media/") and not n.endswith("/") for n in archive.namelist())},
            "count_scope": "Paragraphs/headings/tables/images include table descendants in the main document, not headers/footers; media_files counts package assets.",
            "headings": headings[:50], "headings_truncated": len(headings) > 50,
            "cover": {"title_paragraphs": titles[:10], "title_count": len(titles),
                      "separate_cover_page": "unknown_without_rendering"},
            "toc": {"field_count": len(toc), "instructions": toc[:20],
                    "updated_or_paginated": "unknown_without_rendering"},
            "sections": sections, "headers": headers, "footers": footers,
            "pagination_markers": {
                "explicit_page_breaks": sum(e.get(W + "type") == "page" for e in body.iter(W + "br")),
                "paragraph_page_break_before": sum(_on(p.find("w:pPr/w:pageBreakBefore", NS)) for p in paragraphs),
                "cached_rendered_page_breaks": len(body.findall(".//w:lastRenderedPageBreak", NS)),
            },
            "render": {"status": "render_unavailable", "reason": "Rendering is not enabled in this OOXML-only preview; no renderer was launched.",
                       "page_count": None, "visual_verification": "not_performed"},
            "limitations": ["OOXML structure does not prove layout, legibility, TOC freshness, evidence support or engineering correctness.",
                            "Text offsets count blocks of at most 400 Unicode characters, not physical PDF/Word pages; headers and footers are summarized separately.",
                            "No acceptance, delivery selection or review state is changed."],
        }, text


def _checked_draft(workspace, draft_id):
    draft = workspace.result(draft_id)
    if draft["kind"] != "draft":
        raise ActionRejected("PREVIEW_REQUIRES_SAVED_DRAFT")
    return draft


def _blocks(text):
    return [line[start:start + BLOCK_CHARACTERS] for line in text.splitlines(keepends=True)
            for start in range(0, len(line), BLOCK_CHARACTERS)]


def _contained(root: Path, path: Path) -> Path:
    if not path.resolve().is_relative_to(root):
        raise ActionRejected("PREVIEW_PATH_OUTSIDE_PROJECT")
    return path


def _paths(workspace, draft_id):
    root = workspace.store.root.resolve()
    base = _contained(root, root / "previews")
    key = _hash(draft_id.encode("utf-8"))
    return root, base, key


def _write(path: Path, data: bytes):
    # Publish only complete files; concurrent readers never see a partial index.
    fd, temp = tempfile.mkstemp(prefix=".preview-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def preview_saved_report(workspace: Workspace, draft_id: str) -> dict:
    """Export this project's saved draft and return bounded OOXML evidence, never full text.

    Each invocation exports afresh (review/issue state and the exporter may change).
    Snapshots are named by draft identity and actual DOCX hash. No renderer/model runs.
    """
    draft = _checked_draft(workspace, draft_id)
    data = export_docx(workspace, draft_id)
    summary, text = _structure(data)
    root, base, key = _paths(workspace, draft_id)
    version = key + "-" + _hash(data)
    folder = _contained(root, base / version)
    folder.mkdir(parents=True, exist_ok=True)
    text_data = text.encode("utf-8")
    summary.update({"schema": SCHEMA, "draft_id": draft_id, "preview_version": version,
                    "draft_body_sha256": _hash(draft["body"].encode("utf-8")),
                    "docx": {"path": str(folder / "report.docx"), "sha256": _hash(data), "bytes": len(data)},
                    "text": {"sha256": _hash(text_data), "characters": len(text), "blocks": len(_blocks(text)),
                             "unit": "text_blocks", "max_block_characters": BLOCK_CHARACTERS,
                             "max_read_limit": MAX_READ}})
    for name, payload in (("report.docx", data), ("text.txt", text_data),
                          ("summary.json", json.dumps(summary, ensure_ascii=False).encode("utf-8"))):
        _write(_contained(root, folder / name), payload)
    _write(_contained(root, base / (key + ".json")), json.dumps({"version": version}).encode())
    return summary


def read_preview(workspace: Workspace, draft_id: str, offset: int = 0, limit: int = 30,
                 preview_version: str = "") -> dict:
    """Read up to limit text blocks (400 characters each), never physical pages.

    Pin preview_version when paging; empty selects the latest snapshot. A supplied
    version never reads the latest index or falls back to another snapshot.
    Follow next_offset until null. Does not re-export or call a renderer/model.
    """
    _checked_draft(workspace, draft_id)
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= MAX_READ:
        raise ActionRejected("PREVIEW_INVALID_RANGE")
    if not isinstance(preview_version, str):
        raise ActionRejected("PREVIEW_INVALID_VERSION")
    root, base, key = _paths(workspace, draft_id)
    version = preview_version
    if not version:
        index = _contained(root, base / (key + ".json"))
        if not index.exists():
            raise ActionRejected("PREVIEW_NOT_FOUND_CALL_PREVIEW_SAVED_REPORT")
        version = json.loads(index.read_text(encoding="utf-8"))["version"]
    if not isinstance(version, str) or not re.fullmatch(key + r"-[0-9a-f]{64}", version):
        raise ActionRejected("PREVIEW_INVALID_VERSION")
    folder = _contained(root, base / version)
    for name in ("summary.json", "text.txt", "report.docx"):
        if not _contained(root, folder / name).is_file():
            raise ActionRejected("PREVIEW_SNAPSHOT_NOT_FOUND")
    summary = json.loads(_contained(root, folder / "summary.json").read_text(encoding="utf-8"))
    data = _contained(root, folder / "text.txt").read_bytes()
    docx = _contained(root, folder / "report.docx").read_bytes()
    if (summary["draft_id"] != draft_id or summary["preview_version"] != version
            or _hash(docx) != version[-64:] or _hash(data) != summary["text"]["sha256"]):
        raise ActionRejected("PREVIEW_INTEGRITY_MISMATCH")
    text = data.decode("utf-8")
    blocks = _blocks(text)
    if offset > len(blocks):
        raise ActionRejected("PREVIEW_OFFSET_OUT_OF_RANGE")
    end = min(offset + limit, len(blocks))
    return {"draft_id": draft_id, "preview_version": version, "docx_sha256": _hash(docx),
            "text_sha256": _hash(data), "draft_body_sha256": summary["draft_body_sha256"],
            "offset": offset, "limit": limit, "total_characters": len(text),
            "total_blocks": len(blocks), "next_offset": end if end < len(blocks) else None,
            "text": "".join(blocks[offset:end]), "unit": "text_blocks", "physical_page_numbers": None}
