"""Local document parsing and image-only registration with explicit coverage limits."""

from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from PIL import Image, ImageOps


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ZIP_ENTRIES = 2048
MAX_ZIP_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_TEXT_CHARS = 8 * 1024 * 1024
MAX_BLOCKS = 100_000
MAX_NESTING = 32
MAX_PDF_PAGES = 500
MAX_PDF_PAGE_CONTENT_BYTES = 8 * 1024 * 1024
MAX_PDF_TOTAL_CONTENT_BYTES = 64 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_EDGE = 16_384
_IMAGE_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}


class _ParseError(ValueError):
    """Distinguish our public errors from exceptions inside format libraries."""


def _fail(code: str, detail: str):
    raise _ParseError(f"{code}: {detail}")


class _Output:
    def __init__(self):
        self.blocks = []
        self.limitations = []
        self._notes = set()
        self.chars = 0

    def add(self, locator: str, text: str):
        self.chars += len(text)
        if self.chars > MAX_TEXT_CHARS or len(self.blocks) >= MAX_BLOCKS:
            _fail("RESOURCE_LIMIT", "Extracted text/block limit exceeded; nothing imported.")
        self.blocks.append({"locator": locator, "text": text})

    def note(self, text: str):
        if text not in self._notes:
            self._notes.add(text)
            self.limitations.append(text)


def _text(data: bytes, out: _Output):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        _fail("INVALID_UTF8", "TXT/MD must contain UTF-8 text.")
    if not text.strip():
        _fail("EMPTY_DOCUMENT", "No non-whitespace text.")
    if "\x00" in text:
        _fail("CORRUPT_DOCUMENT", "NUL bytes are not supported in text documents.")
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        out.add(f"line {number}", line)


def _check_docx_zip(data: bytes, out: _Output):
    # Check sizes before python-docx expands the package, including unused members.
    with ZipFile(BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            _fail("RESOURCE_LIMIT", f"DOCX exceeds {MAX_ZIP_ENTRIES} ZIP entries.")
        if len({e.filename for e in entries}) != len(entries):
            _fail("CORRUPT_DOCUMENT", "DOCX has duplicate ZIP member names.")
        if any(e.flag_bits & 1 for e in entries):
            _fail("ENCRYPTED_DOCUMENT", "Encrypted DOCX ZIP members are unsupported.")
        if any(e.file_size > MAX_ZIP_MEMBER_BYTES for e in entries):
            _fail("RESOURCE_LIMIT", "DOCX ZIP member exceeds decompressed size limit.")
        if sum(e.file_size for e in entries) > MAX_ZIP_UNCOMPRESSED_BYTES:
            _fail("RESOURCE_LIMIT", "DOCX exceeds total decompressed size limit.")
        if not {"[Content_Types].xml", "word/document.xml"}.issubset(archive.namelist()):
            _fail("CORRUPT_DOCUMENT", "ZIP is not a supported DOCX package.")
        for entry in entries:
            # Streaming verification also checks CRCs on non-body/unused members.
            actual = 0
            with archive.open(entry) as member:
                while chunk := member.read(64 * 1024):
                    actual += len(chunk)
                    if actual > MAX_ZIP_MEMBER_BYTES:
                        _fail("RESOURCE_LIMIT", "DOCX decompressed member limit exceeded.")
            if actual != entry.file_size:
                _fail("CORRUPT_DOCUMENT", "DOCX ZIP size mismatch.")
            name = entry.filename
            if name.startswith(("word/media/", "word/embeddings/", "word/charts/")):
                out.note(f"{name}: image/chart/embedded content is not extracted; no OCR.")
            elif name.startswith(("word/header", "word/footer", "word/footnotes", "word/endnotes", "word/comments")):
                out.note(f"{name}: supplementary content is not extracted.")


def _docx_container(element, parent, prefix: str, out: _Output, depth=0):
    if depth > MAX_NESTING:
        _fail("RESOURCE_LIMIT", "DOCX nested table depth exceeded.")
    paragraphs = tables = 0
    for child in element:
        if child.tag == qn("w:p"):
            paragraphs += 1
            locator = f"{prefix}/paragraph {paragraphs}"
            out.add(locator, Paragraph(child, parent).text)
            unsupported = {"drawing", "pict", "object", "oMath", "oMathPara", "sdt", "ins", "del", "fldChar", "fldSimple", "footnoteReference", "endnoteReference"}
            features = sorted({node.tag.rsplit("}", 1)[-1] for node in child.iter()} & unsupported)
            if features:
                out.note(f"{locator}: unsupported or unevaluated content ({', '.join(features)}); images are not OCRed.")
        elif child.tag == qn("w:tbl"):
            tables += 1
            table = Table(child, parent)
            # Physical XML cells avoid duplicating merged cells from row.cells.
            for row_number, row in enumerate(child.findall(qn("w:tr")), 1):
                for cell_number, cell in enumerate(row.findall(qn("w:tc")), 1):
                    _docx_container(cell, _Cell(cell, table),
                                    f"{prefix}/table {tables}/row {row_number}/cell {cell_number}",
                                    out, depth + 1)
                for item in row:
                    if item.tag not in {qn("w:tc"), qn("w:trPr"), qn("w:tblPrEx")}:
                        out.note(f"{prefix}/table {tables}/row {row_number}: unsupported {item.tag.rsplit('}', 1)[-1]} content is not extracted.")
            for item in child:
                if item.tag not in {qn("w:tr"), qn("w:tblPr"), qn("w:tblGrid")}:
                    out.note(f"{prefix}/table {tables}: unsupported {item.tag.rsplit('}', 1)[-1]} content is not extracted.")
        elif child.tag not in {qn("w:sectPr"), qn("w:tcPr")}:
            out.note(f"{prefix}: unsupported {child.tag.rsplit('}', 1)[-1]} content is not extracted.")


def _docx(data: bytes, out: _Output):
    if data.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        _fail("ENCRYPTED_OR_UNSUPPORTED_DOCUMENT", "OLE container: encrypted DOCX or legacy Word format is unsupported.")
    _check_docx_zip(data, out)
    document = Document(BytesIO(data))
    _docx_container(document.element.body, document, "body", out)
    if not any(b["text"].strip() for b in out.blocks) and not out.limitations:
        _fail("EMPTY_DOCUMENT", "DOCX has no text or detected unsupported content.")
    out.note("DOCX extraction covers body paragraphs and table cells in XML order only. "
             "Layout, pagination, numbering, formatting, image/chart meaning, fields, revisions "
             "and supplementary parts are not fully represented; no OCR or external resources are fetched.")


def _pdf(data: bytes, out: _Output):
    try:
        from pypdf import PdfReader
    except ImportError:
        _fail("PARSER_UNAVAILABLE", "PDF parsing requires pypdf.")
    if not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF"):
        _fail("CORRUPT_DOCUMENT", "PDF header or end marker is missing.")
    reader = PdfReader(BytesIO(data), strict=True)
    if reader.is_encrypted:
        _fail("ENCRYPTED_DOCUMENT", "Encrypted PDFs are unsupported, including empty-password encryption.")
    count = len(reader.pages)
    if not count:
        _fail("EMPTY_DOCUMENT", "PDF contains no pages.")
    if count > MAX_PDF_PAGES:
        _fail("RESOURCE_LIMIT", f"PDF exceeds {MAX_PDF_PAGES} pages.")
    out.note("PDF text extraction only: reading order, layout and tables may be incomplete; "
             "images, vector graphics, annotations, forms and attachments are not extracted or interpreted. "
             "No OCR or external resources are fetched.")
    total_content = 0
    has_content = False
    for number, page in enumerate(reader.pages, 1):
        locator = f"page {number}"
        content = page.get_contents()
        decoded = content.get_data() if content is not None else b""
        size = len(decoded)
        total_content += size
        if size > MAX_PDF_PAGE_CONTENT_BYTES or total_content > MAX_PDF_TOTAL_CONTENT_BYTES:
            _fail("RESOURCE_LIMIT", "PDF decoded page content exceeds extraction limits.")
        has_content |= bool(size or page.get("/Annots"))
        text = page.extract_text() or ""
        out.add(locator, text)
        if not text.strip():
            out.note(f"{locator}: no extractable text; may be blank, scanned or unsupported graphics. No OCR performed.")
        # Do not decode raster data just to enumerate images. Forms may contain images too.
        resources = page.get("/Resources")
        resources = resources.get_object() if resources else {}
        if resources.get("/XObject") or b"BI" in decoded:
            out.note(f"{locator}: image/form resources or inline images may contain unextracted visual content; no OCR.")
    if not has_content and not any(b["text"].strip() for b in out.blocks):
        _fail("EMPTY_DOCUMENT", "PDF contains only empty pages.")


def _decode_image(data: bytes, expected_format=None):
    """Return an owned, EXIF-oriented RGB/RGBA image and structural metadata.

    Shared by import validation and project-bound image access, never performs OCR.
    Limits are checked before pixel decompression; callers must close the result.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        _fail("RESOURCE_LIMIT", f"Image exceeds {MAX_UPLOAD_BYTES} encoded bytes.")
    try:
        with Image.open(BytesIO(data), formats=list(set(_IMAGE_FORMATS.values()))) as image:
            image_format = image.format
            if expected_format is not None and image_format != expected_format:
                _fail("IMAGE_FORMAT_MISMATCH", "Image content does not match its filename extension.")
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS or max(width, height) > MAX_IMAGE_EDGE:
                _fail("RESOURCE_LIMIT", f"Image exceeds {MAX_IMAGE_PIXELS} pixels or {MAX_IMAGE_EDGE}-pixel edge.")
            if getattr(image, "n_frames", 1) != 1:
                _fail("IMAGE_MULTIFRAME_UNSUPPORTED", "Only a single image frame is supported; no frames imported.")
            image.verify()
        with Image.open(BytesIO(data), formats=list(set(_IMAGE_FORMATS.values()))) as image:
            image.load()
            with ImageOps.exif_transpose(image) as oriented:
                decoded = oriented.convert("RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB")
                decoded.info.clear()
        return decoded, {"format": image_format, "width": decoded.width, "height": decoded.height,
                         "encoded_width": width, "encoded_height": height, "frames": 1,
                         "orientation": "EXIF orientation applied"}
    except _ParseError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        _fail("RESOURCE_LIMIT", "Image decompression dimensions exceed safe limits.")
    except Exception:
        raise _ParseError("CORRUPT_DOCUMENT: Cannot decode supported single-frame image.") from None


def parse_document(filename: str, data: bytes) -> dict:
    """Return located text, or ValueError with a stable CODE: detail prefix.

    Limits reject the whole import; they never truncate. These in-process limits
    are not a hard CPU/memory sandbox for hostile third-party parser input.
    """
    if not isinstance(filename, str) or not filename.strip() or "\x00" in filename:
        _fail("INVALID_FILENAME", "A nonempty filename without NUL is required.")
    if not isinstance(data, bytes):
        _fail("INVALID_DATA", "Document data must be bytes.")
    if not data:
        _fail("EMPTY_DOCUMENT", "Upload is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        _fail("RESOURCE_LIMIT", f"Upload exceeds {MAX_UPLOAD_BYTES} bytes.")
    name = PurePosixPath(filename.replace("\\", "/")).name
    suffix = PurePosixPath(name).suffix.lower()
    parsers = {".txt": _text, ".md": _text, ".docx": _docx, ".pdf": _pdf}
    if suffix not in parsers and suffix not in _IMAGE_FORMATS:
        _fail("UNSUPPORTED_FORMAT", "Supported extensions: .txt, .md, .docx, .pdf, .png, .jpg, .jpeg, .webp.")
    out = _Output()
    image_info = None
    try:
        if suffix in _IMAGE_FORMATS:
            image, image_info = _decode_image(data, _IMAGE_FORMATS[suffix])
            image.close()
            out.note("Image-only source: no text extracted and no OCR performed. "
                     "Visual content remains unobserved; optional single-image inspection is separate.")
        else:
            parsers[suffix](data, out)
    except _ParseError:
        raise
    except Exception as exc:
        # Never leak parser internals or return a successfully parsed prefix as a document.
        raise _ParseError(f"CORRUPT_DOCUMENT: Cannot parse {suffix} document ({type(exc).__name__}).") from exc
    result = {"title": PurePosixPath(name).stem, "coverage": "complete" if suffix in {".txt", ".md"} else "partial",
              "limitations": out.limitations, "blocks": out.blocks}
    if image_info is not None:
        result["image"] = image_info
    return result
