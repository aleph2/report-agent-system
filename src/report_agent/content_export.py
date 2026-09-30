"""Snapshot-only export and rendering. Neither operation confers acceptance."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from docx import Document

from .content_models import Ref
from .errors import ActionForbidden, ActionRejected
from .store import digest


def _asset(store, name, data):
    root = store.root / "content-assets"
    root.mkdir(exist_ok=True)
    path = root / name
    if path.exists() and path.read_bytes() != data:
        raise ActionRejected("ASSET_IDENTITY_CONFLICT")
    path.write_bytes(data)
    return path.relative_to(store.root).as_posix()


def _bytes(store, asset, expected):
    path = (store.root / asset).resolve()
    if not path.is_relative_to((store.root / "content-assets").resolve()):
        raise ActionForbidden("ASSET_OUTSIDE_PROJECT")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ActionRejected("ASSET_DIGEST_MISMATCH")
    return data


def export_snapshot(contents, actor, operation_id, snapshot_ref):
    def execute(db):
        if actor.role not in {"coordinator", "writer"}:
            raise ActionForbidden("FORBIDDEN: export producer")
        snapshot = contents._read(db, snapshot_ref)
        if snapshot_ref["type"] != "DocumentSnapshot" or snapshot["owner_id"] != actor.id:
            raise ActionForbidden("FORBIDDEN: snapshot owner")
        records = {Ref.model_validate(r).key(): contents._read(db, r) for r in snapshot["payload"]["refs"]}
        edges = {}
        for record in records.values():
            p = record["payload"]
            if record["ref"]["type"] == "Relation" and p["predicate"] == "contains":
                edges.setdefault(Ref.model_validate(p["subject_ref"]).key(), []).append((p["position"], p["object_ref"]))
        doc, mappings = Document(), []
        from .exporting import _source_images
        from types import SimpleNamespace
        adopted_sources = {r["payload"]["source_id"] for r in records.values() if r["ref"]["type"] == "SourceArtifact"}
        used_images = set()
        source_workspace = SimpleNamespace(store=contents.store)
        image_renderer = _source_images(source_workspace, doc, used_images)
        from docx.shared import RGBColor
        for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
            doc.styles[name].font.color.rgb = RGBColor(0, 0, 0)
            from docx.oxml.ns import qn
            for border in doc.styles[name].element.iter(qn("w:pBdr")):
                border.getparent().remove(border)
        def emit(ref, depth):
            node = records[Ref.model_validate(ref).key()]["payload"]
            body, kind = node["body"], node["kind"]
            start = len(list(doc.element.body)) - 1
            if kind == "table":
                table = doc.add_table(rows=1, cols=len(body["columns"]), style="Table Grid")
                for cell, value in zip(table.rows[0].cells, body["columns"]):
                    cell.text = str(value)
                for values in body["rows"]:
                    for cell, value in zip(table.add_row().cells, values):
                        cell.text = str(value)
            elif kind == "figure":
                from .document_tools import vision_source_image
                png, _ = vision_source_image(source_workspace, body["source_id"], body.get("page", 1), None)
                from docx.shared import Inches
                doc.add_picture(BytesIO(png), width=Inches(6))
                doc.add_paragraph(body["caption"])
            elif kind in {"report", "chapter"}:
                doc.add_heading(body["text"], 0 if kind == "report" else min(depth, 9))
            else:
                # Preserve full actual text and its explicit qualifiers; no model summarization.
                from .exporting import _add_markdown
                _add_markdown(doc, body["text"], image_renderer)
            if node["qualifiers"]:
                doc.add_paragraph("；".join(f"{key}：{value}" for key, value in node["qualifiers"].items()))
            mappings.append({"node_ref": ref, "block_start": start,
                "block_stop": len(list(doc.element.body)) - 1, "content_digest": digest(body),
                "qualifiers": node["qualifiers"]})
            for _, child in sorted(edges.get(Ref.model_validate(ref).key(), []), key=lambda p: p[0]):
                emit(child, depth + 1)
        emit(snapshot["payload"]["root_ref"], 0)
        if not used_images <= adopted_sources:
            raise ActionRejected("IMAGE_SOURCE_OUTSIDE_SNAPSHOT")
        anchors = {Ref.model_validate(m["node_ref"]).key(): m for m in mappings}
        for record in records.values():
            p = record["payload"]
            if record["ref"]["type"] == "Relation" and p["predicate"] in {"expresses", "references"}:
                subject = Ref.model_validate(p["subject_ref"]).key()
                if subject in anchors and p["object_ref"]["type"] == "ContentNode":
                    mappings.append({**anchors[subject], "node_ref": p["object_ref"], "via_relation": record["ref"]})
        mapped = {Ref.model_validate(m["node_ref"]).key() for m in mappings}
        unrendered = [r["ref"] for key, r in records.items() if key[0] == "ContentNode" and key not in mapped]
        buffer = BytesIO()
        doc.save(buffer)
        data = buffer.getvalue()
        checksum = hashlib.sha256(data).hexdigest()
        asset = _asset(contents.store, checksum + ".docx", data)
        export_ref = contents._insert(db, actor, "ExportArtifact", {"snapshot_ref": snapshot_ref,
            "file_ref": asset, "file_digest": checksum, "template_ref": "snapshot-basic-v1",
            "export_config": {"exporter_digest": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}})
        mapping_ref = contents._insert(db, actor, "MappingArtifact", {"snapshot_ref": snapshot_ref,
            "export_ref": export_ref, "anchor_records": mappings, "unrendered_dependency_nodes": unrendered,
            "limitation": "OOXML block indices bind only this export; page coordinates require a render."})
        return {"export_ref": export_ref, "mapping_ref": mapping_ref, "file_ref": asset, "file_digest": checksum}
    return contents.operation(actor, operation_id, {"export": snapshot_ref}, execute)


def read_export(contents, actor, export_ref):
    record = contents.read(export_ref)
    if export_ref["type"] != "ExportArtifact":
        raise ActionRejected("EXPORT_REQUIRED")
    data = _bytes(contents.store, record["payload"]["file_ref"], record["payload"]["file_digest"])
    from .report_preview import _structure
    structure, text = _structure(data)
    return contents.observe(actor, {"export_ref": export_ref, "file_digest": record["payload"]["file_digest"],
        "structure": structure, "text": text, "limitation": "Actual OOXML content; not visual observation."})


def render_export(contents, actor, operation_id, export_ref):
    def execute(db):
        export = contents._read(db, export_ref)
        if export_ref["type"] != "ExportArtifact":
            raise ActionRejected("EXPORT_REQUIRED")
        data = _bytes(contents.store, export["payload"]["file_ref"], export["payload"]["file_digest"])
        executable = shutil.which("libreoffice") or shutil.which("soffice")
        if not executable:
            candidate = Path("C:/Program Files/LibreOffice/program/soffice.com")
            executable = str(candidate) if candidate.exists() else None
        windows_bridge = False
        if not executable:
            candidate = Path("/mnt/c/Program Files/LibreOffice/program/soffice.com")
            if candidate.exists() and shutil.which("wslpath"):
                executable, windows_bridge = str(candidate), True
        if not executable:
            return {"execution_state": "blocked", "verdict": None, "code": "RENDER_UNAVAILABLE",
                    "export_ref": export_ref, "coverage": {"checked": [], "blocked": ["all rendered pages"]}}
        import pypdfium2 as pdfium
        with tempfile.TemporaryDirectory(prefix="report-render-", dir=contents.store.root if windows_bridge else None) as tmp:
            folder = Path(tmp)
            (folder / "input.docx").write_bytes(data)
            version = {"executable": Path(executable).name, "binary_digest": hashlib.sha256(Path(executable).read_bytes()).hexdigest()}
            def external_path(path):
                return subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, check=True).stdout.strip() if windows_bridge else str(path)
            if windows_bridge:
                from urllib.parse import quote
                profile = "file:///" + quote(external_path(folder / "profile").replace("\\", "/"), safe=":/")
            else:
                profile = (folder / "profile").as_uri()
            command = [executable, "-env:UserInstallation=" + profile,
                       "--headless", "--convert-to", "pdf", "--outdir", external_path(folder), external_path(folder / "input.docx")]
            try:
                subprocess.run(command, capture_output=True, check=True, timeout=120,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                pdf = (folder / "input.pdf").read_bytes()
            except (subprocess.SubprocessError, OSError):
                return {"execution_state": "blocked", "verdict": None, "code": "RENDER_UNAVAILABLE", "export_ref": export_ref}
            pages = []
            with pdfium.PdfDocument(pdf) as document:
                for index in range(len(document)):
                    page = document[index]
                    bitmap = page.render(scale=1.5)
                    output = BytesIO()
                    bitmap.to_pil().save(output, format="PNG")
                    png = output.getvalue()
                    sha = hashlib.sha256(png).hexdigest()
                    pages.append({"page": index + 1, "asset_ref": _asset(contents.store, sha + ".png", png), "sha256": sha})
                    bitmap.close()
                    page.close()
        pdf_sha = hashlib.sha256(pdf).hexdigest()
        payload = {"snapshot_ref": export["payload"]["snapshot_ref"], "export_ref": export_ref,
            "export_digest": export["payload"]["file_digest"], "renderer_identity": version,
            "config": {"scale": 1.5}, "pdf_ref": _asset(contents.store, pdf_sha + ".pdf", pdf),
            "pdf_digest": pdf_sha, "page_assets": pages}
        ref = contents._insert(db, actor, "RenderArtifact", payload)
        return {"render_ref": ref, "pages": pages, "execution_state": "completed", "verdict": None}
    return contents.operation(actor, operation_id, {"render": export_ref}, execute)


async def inspect_render(contents, actor, render_ref, page, question, client=None):
    record = contents.read(render_ref)
    if render_ref["type"] != "RenderArtifact" or not question.strip():
        raise ActionRejected("RENDER_AND_QUESTION_REQUIRED")
    pages = record["payload"]["page_assets"]
    if not 1 <= page <= len(pages):
        raise ActionRejected("PAGE_OUT_OF_RANGE")
    asset = pages[page - 1]
    png = _bytes(contents.store, asset["asset_ref"], asset["sha256"])
    from .deep_models import configured_vision_client
    from .vision import _observe
    owns = client is None
    client = client or configured_vision_client()
    try:
        result = await _observe(contents.store, png, {"source_id": render_ref["id"],
            "render_ref": render_ref, "export_ref": record["payload"]["export_ref"], "page": page}, question, client)
        return contents.observe(actor, result)
    finally:
        if owns:
            await client.close()
