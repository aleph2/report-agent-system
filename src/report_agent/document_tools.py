"""Read-only pages and images from project-bound, hash-verified originals.

DOCX has no stable physical pages without a separate layout renderer. These tools
do not run OCR, interpret figures, or imply a model has received an image.
"""

from contextlib import closing
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path, PureWindowsPath
import re
import sqlite3
from threading import Lock
from urllib.parse import quote, unquote

from markdown_it import MarkdownIt
from pypdf import PdfReader

from .errors import ActionRejected


_PDFIUM_LOCK = Lock()
_MAX_IMAGE_EDGE = 4096


def markdown_source_ids(body: str) -> list[str]:
    """Collect source IDs from Markdown image tokens, including table cells.

    Uses the exporter's Markdown dialect and canonical source-page URL contract.
    Text, links, code and HTML are not image tokens. Does not resolve membership,
    freshness, originals or physical page bounds; the bound caller checks those.
    """
    ids = []
    seen = set()
    for token in MarkdownIt("commonmark").enable("table").parse(body):
        if token.type != "inline":
            continue
        for child in token.children or []:
            if child.type != "image":
                continue
            match = re.fullmatch(r"source-page://([^/?#]+)/([1-9][0-9]*)", child.attrGet("src") or "")
            if not match:
                raise ActionRejected("EXPORT_IMAGE_REQUIRES_SOURCE_PAGE_REFERENCE")
            try:
                source_id = unquote(match[1], errors="strict")
            except UnicodeDecodeError:
                raise ActionRejected("EXPORT_IMAGE_REQUIRES_SOURCE_PAGE_REFERENCE") from None
            if source_id in (".", "..") or quote(source_id, safe="") != match[1]:
                raise ActionRejected("EXPORT_IMAGE_REQUIRES_SOURCE_PAGE_REFERENCE")
            if source_id not in seen:
                seen.add(source_id)
                ids.append(source_id)
    return ids


def _original(workspace, source_id):
    if not isinstance(source_id, str) or not source_id:
        raise ActionRejected("SOURCE_NOT_IN_PROJECT")
    store = workspace.store
    source = next((s for s in store.manifest["sources"] if s["id"] == source_id), None)
    data = None
    if source is None:
        row = store.source_original(source_id)
        if row is None:
            raise ActionRejected("SOURCE_NOT_IN_PROJECT")
        source, data = row
        if source.get("id") != source_id:
            raise ActionRejected("SOURCE_METADATA_MISMATCH")

    # A text-only source is not an original, even if a filename was recorded.
    value = source.get("copied_path") or source.get("original_path")
    if data is None and not value:
        raise ActionRejected("SOURCE_ORIGINAL_UNAVAILABLE")
    expected = source.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ActionRejected("SOURCE_ORIGINAL_SHA256_REQUIRED")
    if data is None:
        # copied_path wins: original_path often refers to a legacy external file.
        if not isinstance(value, str) or "://" in value or "\x00" in value:
            raise ActionRejected("SOURCE_ORIGINAL_OUTSIDE_PROJECT")
        path = Path(value)
        if not path.is_absolute() and PureWindowsPath(value).drive:
            raise ActionRejected("SOURCE_ORIGINAL_OUTSIDE_PROJECT")
        root = store.root.resolve()
        try:
            sources = root / "sources"
            path = (path if path.is_absolute() else root / path).resolve()
            if not path.is_relative_to(sources):
                raise ActionRejected("SOURCE_ORIGINAL_OUTSIDE_PROJECT")
            if not path.is_file():
                raise ActionRejected("SOURCE_ORIGINAL_UNAVAILABLE")
            data = path.read_bytes()
        except ActionRejected:
            raise
        except (OSError, RuntimeError, ValueError):
            raise ActionRejected("SOURCE_ORIGINAL_UNAVAILABLE") from None
    if not data:
        raise ActionRejected("SOURCE_ORIGINAL_UNAVAILABLE")
    if hashlib.sha256(data).hexdigest() != expected.lower():
        raise ActionRejected("SOURCE_ORIGINAL_SHA256_MISMATCH")
    return source, data


def _pdf_page(workspace, source_id, page):
    if type(page) is not int or page < 1:
        raise ActionRejected("SOURCE_PAGE_REQUIRES_POSITIVE_INTEGER")
    source, data = _original(workspace, source_id)
    filename = source.get("filename", source.get("title", ""))
    if str(filename).lower().endswith(".docx"):
        raise ActionRejected("DOCX_PHYSICAL_PAGES_UNAVAILABLE")
    if b"%PDF-" not in data[:1024]:
        raise ActionRejected("SOURCE_FORMAT_REQUIRES_PDF")
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ActionRejected("SOURCE_PDF_ENCRYPTED")
        count = len(reader.pages)
        if page > count:
            raise ActionRejected("SOURCE_PAGE_OUT_OF_RANGE")
    except ActionRejected:
        raise
    except Exception:
        raise ActionRejected("SOURCE_PDF_UNREADABLE") from None
    return source, data, reader, count


def physical_page_number(locator):
    """Read an explicit importer locator; block ordinals are never page numbers."""
    if not isinstance(locator, str):
        return None
    if locator.startswith("{"):
        try:
            location, end = json.JSONDecoder().raw_decode(locator)
        except ValueError:
            return None
        if not isinstance(location, dict) or not re.fullmatch(r"(?:; chars [1-9][0-9]*-[1-9][0-9]*)?", locator[end:]):
            return None
        page = location.get("page")
        return page if type(page) is int and page > 0 else None
    match = re.fullmatch(r"page ([1-9][0-9]*)(?:; chars [1-9][0-9]*-[1-9][0-9]*)?", locator)
    return int(match[1]) if match else None


def _frozen_page_blocks(workspace, source_id, page):
    """Match only explicit imported physical-page locators."""
    return workspace.store.source_page_blocks(source_id, page)


def source_page_info(workspace, source_id: str, page: int) -> dict:
    """Return one 1-based physical PDF page's native text and image reference.

    Text is the native text layer, not a new OCR result or figure interpretation.
    Printed page labels may differ from the physical index. No text is truncated.
    """
    from .source_tables import source_tables

    source, _, reader, count = _pdf_page(workspace, source_id, page)
    try:
        text = reader.pages[page - 1].extract_text() or ""
    except Exception:
        raise ActionRejected("SOURCE_PAGE_TEXT_EXTRACTION_FAILED") from None
    limitations = [
        "Physical PDF page index (1-based), not the printed page label.",
        "native_text is only the PDF text layer; no new OCR, figure interpretation, or complete visual coverage claim.",
        "An image reference does not mean the model has viewed the image.",
        "PNG rendition: up to 144 DPI, reduced to a maximum 4096-pixel edge for large pages.",
    ]
    if not text.strip():
        limitations.append("No native text on this page; this does not establish missing information. Existing OCR is unchanged.")
    return {
        "source_id": source_id,
        "sha256": source["sha256"].lower(),
        "page": page,
        "page_count": count,
        "locator": f"PDF physical page {page} of {count}",
        "native_text": text,
        "table_view": source_tables(workspace, source_id, [page])[0],
        "frozen_text_blocks": _frozen_page_blocks(workspace, source_id, page),
        "frozen_text_note": "Existing stored extraction/OCR matched by explicit physical-page locator, not block ordinal. No OCR rerun; no match does not establish absent OCR.",
        "image_ref": f"source-page://{quote(source_id, safe='')}/{page}",
        "limitations": limitations,
    }


def source_page_png(workspace, source_id: str, page: int) -> bytes:
    """Render a verified project PDF page as PNG; never accept a path or URL.

    Returns only image bytes. Callers must bind the workspace and resolve source
    IDs themselves, including when embedding source-page references into reports.
    """
    _, data, _, count = _pdf_page(workspace, source_id, page)
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise ActionRejected("SOURCE_PAGE_RENDERER_UNAVAILABLE") from None
    # PDFium calls, including object destruction, cannot run concurrently in threads.
    with _PDFIUM_LOCK:
        try:
            with pdfium.PdfDocument(data) as document:
                if len(document) != count:
                    raise ActionRejected("SOURCE_PDF_PAGE_COUNT_MISMATCH")
                with closing(document[page - 1]) as pdf_page:
                    width, height = pdf_page.get_size()
                    if not all(math.isfinite(n) and n > 0 for n in (width, height)):
                        raise ActionRejected("SOURCE_PAGE_INVALID_DIMENSIONS")
                    scale = min(2.0, _MAX_IMAGE_EDGE / max(width, height))
                    with closing(pdf_page.render(scale=scale)) as bitmap:
                        with bitmap.to_pil() as image:
                            output = BytesIO()
                            image.save(output, format="PNG")
                            return output.getvalue()
        except ActionRejected:
            raise
        except Exception:
            raise ActionRejected("SOURCE_PAGE_RENDER_FAILED") from None


def vision_source_image(workspace, source_id: str, page: int = 1, crop=None) -> tuple[bytes, dict]:
    """Return one bounded PNG plus provenance, without OCR or a model invocation.

    crop is None or [x0, y0, x1, y1] in normalized top-left coordinates on the
    EXIF-oriented image / rendered PDF page. Pixel bounds round outwards. Raster
    crops precede downscaling; PDF crops use the existing bounded page rendition.
    """
    from PIL import Image
    from .ingestion import _decode_image, _ParseError, MAX_IMAGE_EDGE, MAX_IMAGE_PIXELS, MAX_UPLOAD_BYTES

    if type(page) is not int or page < 1:
        raise ActionRejected("SOURCE_PAGE_REQUIRES_POSITIVE_INTEGER")
    if crop is not None:
        if not isinstance(crop, list) or len(crop) != 4 or any(type(n) not in (int, float) for n in crop):
            raise ActionRejected("SOURCE_IMAGE_INVALID_CROP")
        try:
            crop = [float(n) for n in crop]
        except (ValueError, OverflowError):
            raise ActionRejected("SOURCE_IMAGE_INVALID_CROP") from None
        if not all(math.isfinite(n) for n in crop) or not (0 <= crop[0] < crop[2] <= 1 and 0 <= crop[1] < crop[3] <= 1):
            raise ActionRejected("SOURCE_IMAGE_INVALID_CROP")

    source, data = _original(workspace, source_id)
    is_pdf = data.startswith(b"%PDF-")
    limitations = ["Image access only: no OCR or semantic interpretation performed; existing text/OCR is unchanged.",
                   "One image does not establish whole-document coverage or complete text recognition."]
    if is_pdf:
        png = source_page_png(workspace, source_id, page)
        with Image.open(BytesIO(png)) as rendered:
            image = rendered.convert("RGB")
        source_format = "PDF"
        limitations.append("PDF uses the existing page rendition, up to 144 DPI and a 4096-pixel edge; crop does not add resolution.")
    else:
        if page != 1:
            raise ActionRejected("SOURCE_PAGE_OUT_OF_RANGE")
        try:
            image, metadata = _decode_image(data)
        except _ParseError as exc:
            code = str(exc).split(":", 1)[0]
            raise ActionRejected("SOURCE_IMAGE_" + code) from None
        source_format = metadata["format"]
        limitations.append("Single-frame raster; EXIF orientation applied. Crop coordinates refer to this oriented image.")

    try:
        base_width, base_height = image.size
        pixel_crop = None
        if crop is not None:
            pixel_crop = [math.floor(crop[0] * base_width), math.floor(crop[1] * base_height),
                          math.ceil(crop[2] * base_width), math.ceil(crop[3] * base_height)]
            region = image.crop(tuple(pixel_crop))
            image.close()
            image = region
            limitations.append("Region coverage only, never full-page OCR; pixel bounds round outwards from the requested crop.")
        if image.mode == "RGBA":
            opaque = Image.new("RGB", image.size, "white")
            with image.getchannel("A") as alpha:
                opaque.paste(image, mask=alpha)
            image.close()
            image = opaque
            limitations.append("Transparency composited onto white for the returned image.")
        selected_size = image.size
        image.thumbnail((_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
        # Strip source metadata from the generated rendition, retaining provenance below.
        image.info.clear()
        output = BytesIO()
        image.save(output, format="PNG")
        png = output.getvalue()
        provenance = {
            "source_id": source_id, "source_sha256": source["sha256"].lower(),
            "source_format": source_format, "page": page, "crop": crop,
            "crop_pixels": pixel_crop, "base_width": base_width, "base_height": base_height,
            "width": image.width, "height": image.height,
            "image_sha256": hashlib.sha256(png).hexdigest(), "mime_type": "image/png",
            "coverage": "region_only" if crop is not None else "full_page_image" if is_pdf else "full_image",
            "locator": f"PDF physical page {page}" if is_pdf else "single image 1",
            "render_limits": {"max_output_edge": _MAX_IMAGE_EDGE, "pdf_max_dpi": 144,
                              "max_raster_input_pixels": MAX_IMAGE_PIXELS, "max_raster_input_edge": MAX_IMAGE_EDGE,
                              "max_raster_input_bytes": MAX_UPLOAD_BYTES, "raster_upscale": False},
            "limitations": limitations,
        }
        if crop is not None:
            provenance["locator"] += "; normalized crop " + json.dumps(crop)
        if image.size != selected_size:
            limitations.append("Selected image/region downscaled to the output edge limit; fine detail may be lost.")
        return png, provenance
    finally:
        image.close()
