"""Synthetic, in-memory parser fixtures; no source documents, OCR or network."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement

from report_agent import ingestion
from report_agent.ingestion import parse_document


def docx_bytes(document):
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def pdf_bytes(texts=("First page",), *, image_page=False, encrypted=False):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject

    writer = pypdf.PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            content = DecodedStreamObject()
            content.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(content)
    if image_page:
        page = writer.add_blank_page(width=300, height=300)
        image = DecodedStreamObject()
        image.set_data(b"\x00\x00\x00")
        image.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                      NameObject("/Width"): NumberObject(1), NameObject("/Height"): NumberObject(1),
                      NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8)})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): writer._add_object(image)})})
        content = DecodedStreamObject()
        content.set_data(b"q 10 0 0 10 0 0 cm /Im0 Do Q")
        page[NameObject("/Contents")] = writer._add_object(content)
    if encrypted:
        writer.encrypt("")
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


@pytest.mark.parametrize("filename", ["notes.txt", "NOTES.MD", r"C:\fakepath\notes.txt"])
def test_utf8_is_complete_and_preserves_all_text(filename):
    original = "# Synthetic\r\n\r\n\u6d4b\u8bd5\tline\nlast "
    parsed = parse_document(filename, b"\xef\xbb\xbf" + original.encode())
    assert parsed["coverage"] == "complete"
    assert parsed["limitations"] == []
    assert "".join(b["text"] for b in parsed["blocks"]) == original
    assert [b["locator"] for b in parsed["blocks"]] == ["line 1", "line 2", "line 3", "line 4"]
    assert parsed["title"].lower() == "notes"


@pytest.mark.parametrize(("filename", "data", "code"), [
    ("a.txt", b"", "EMPTY_DOCUMENT"), ("a.md", b" \n\t", "EMPTY_DOCUMENT"),
    ("a.txt", b"\xff", "INVALID_UTF8"), ("a.txt", b"a\x00b", "CORRUPT_DOCUMENT"),
    ("a.exe", b"hello", "UNSUPPORTED_FORMAT"), ("a.docx", b"bad ZIP", "CORRUPT_DOCUMENT"),
    ("", b"hello", "INVALID_FILENAME"), ("a.txt", "hello", "INVALID_DATA"),
    ("a.docx", bytes.fromhex("d0cf11e0a1b11ae1"), "ENCRYPTED_OR_UNSUPPORTED_DOCUMENT"),
])
def test_predictable_rejections(filename, data, code):
    with pytest.raises(ValueError, match=f"^{code}:"):
        parse_document(filename, data)


def test_docx_preserves_body_table_nested_table_and_merged_cell_order():
    doc = Document()
    doc.add_paragraph("before")
    table = doc.add_table(rows=1, cols=2)
    cell = table.cell(0, 0).merge(table.cell(0, 1))
    cell.text = "merged"
    nested = cell.add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "nested"
    cell.add_paragraph("cell after")
    doc.add_paragraph("after")
    parsed = parse_document("ordered.docx", docx_bytes(doc))
    assert [b["text"] for b in parsed["blocks"] if b["text"]] == ["before", "merged", "nested", "cell after", "after"]
    assert len({b["locator"] for b in parsed["blocks"]}) == len(parsed["blocks"])
    assert "table 1/row 1/cell 1/table 1" in parsed["blocks"][2]["locator"]
    assert parsed["coverage"] == "partial" and parsed["limitations"]


def test_docx_reports_unsupported_body_and_header_content():
    doc = Document()
    doc.add_paragraph("visible")
    doc.sections[0].header.paragraphs[0].text = "header not extracted"
    doc.element.body.insert(1, OxmlElement("w:sdt"))
    doc.paragraphs[0]._p.append(OxmlElement("w:drawing"))
    parsed = parse_document("features.docx", docx_bytes(doc))
    notes = "\n".join(parsed["limitations"])
    assert "header" in notes and "sdt" in notes and "drawing" in notes and "OCR" in notes
    assert parsed["coverage"] == "partial"


def test_empty_docx_rejected():
    with pytest.raises(ValueError, match="^EMPTY_DOCUMENT:"):
        parse_document("empty.docx", docx_bytes(Document()))


def test_upload_and_output_limits_reject_instead_of_truncating(monkeypatch):
    monkeypatch.setattr(ingestion, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(ValueError, match="^RESOURCE_LIMIT:"):
        parse_document("a.txt", b"12345")
    assert parse_document("a.txt", b"1234")["blocks"][0]["text"] == "1234"
    monkeypatch.setattr(ingestion, "MAX_TEXT_CHARS", 2)
    with pytest.raises(ValueError, match="^RESOURCE_LIMIT:"):
        parse_document("a.txt", b"123")
    monkeypatch.setattr(ingestion, "MAX_TEXT_CHARS", 20)
    monkeypatch.setattr(ingestion, "MAX_BLOCKS", 1)
    with pytest.raises(ValueError, match="^RESOURCE_LIMIT:"):
        parse_document("a.txt", b"a\nb")


@pytest.mark.parametrize("limit", ["MAX_ZIP_UNCOMPRESSED_BYTES", "MAX_ZIP_MEMBER_BYTES", "MAX_ZIP_ENTRIES"])
def test_docx_zip_limits_checked_before_loading(monkeypatch, limit):
    payload = docx_bytes(Document())
    monkeypatch.setattr(ingestion, limit, 1)
    monkeypatch.setattr(ingestion, "Document", lambda *_: pytest.fail("Must validate ZIP before loading"))
    with pytest.raises(ValueError, match="^RESOURCE_LIMIT:"):
        parse_document("oversized.docx", payload)


def test_docx_invalid_package_and_duplicate_entries():
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("other.txt", "synthetic")
    with pytest.raises(ValueError, match="^CORRUPT_DOCUMENT:"):
        parse_document("wrong.docx", stream.getvalue())
    stream = BytesIO(docx_bytes(Document()))
    with ZipFile(stream, "a") as archive:
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("word/document.xml", "broken")
    with pytest.raises(ValueError, match="^CORRUPT_DOCUMENT:.*duplicate"):
        parse_document("duplicate.docx", stream.getvalue())


def test_pdf_pages_and_scanned_page_are_located_and_partial():
    parsed = parse_document("synthetic.pdf", pdf_bytes(("First", "Second"), image_page=True))
    assert [b["locator"] for b in parsed["blocks"]] == ["page 1", "page 2", "page 3"]
    assert [b["text"].strip() for b in parsed["blocks"]] == ["First", "Second", ""]
    assert parsed["coverage"] == "partial"
    notes = "\n".join(parsed["limitations"])
    assert "page 3: no extractable text" in notes and "page 3: image/form" in notes


def test_image_only_pdf_is_not_misreported_as_empty_or_complete():
    parsed = parse_document("scan.pdf", pdf_bytes((), image_page=True))
    assert parsed["coverage"] == "partial"
    assert parsed["blocks"] == [{"locator": "page 1", "text": ""}]
    assert any("no extractable text" in note for note in parsed["limitations"])


@pytest.mark.parametrize("texts", [(), ("",)])
def test_empty_pdf_rejected(texts):
    with pytest.raises(ValueError, match="^EMPTY_DOCUMENT:"):
        parse_document("empty.pdf", pdf_bytes(texts))


def test_encrypted_and_corrupt_pdf_rejected():
    payload = pdf_bytes(encrypted=True)
    with pytest.raises(ValueError, match="^ENCRYPTED_DOCUMENT:"):
        parse_document("secret.pdf", payload)
    for data in [b"not PDF", b"%PDF-1.7\nbroken\n%%EOF", pdf_bytes()[:-10]]:
        with pytest.raises(ValueError, match="^CORRUPT_DOCUMENT:"):
            parse_document("broken.pdf", data)


@pytest.mark.parametrize("limit", ["MAX_PDF_PAGES", "MAX_PDF_PAGE_CONTENT_BYTES", "MAX_PDF_TOTAL_CONTENT_BYTES"])
def test_pdf_resource_limits(monkeypatch, limit):
    payload = pdf_bytes(("First", "Second"))
    monkeypatch.setattr(ingestion, limit, 1)
    with pytest.raises(ValueError, match="^RESOURCE_LIMIT:"):
        parse_document("large.pdf", payload)


def test_pdf_missing_dependency_is_explicit(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(ValueError, match="^PARSER_UNAVAILABLE:"):
        parse_document("a.pdf", b"%PDF-1.7\n%%EOF")


def test_docx_hyperlink_text_and_nested_depth_limit(monkeypatch):
    doc = Document()
    paragraph = doc.add_paragraph("before ")
    link = OxmlElement("w:hyperlink")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "linked text"
    run.append(text)
    link.append(run)
    paragraph._p.append(link)
    paragraph.add_run(" after")
    assert parse_document("link.docx", docx_bytes(doc))["blocks"][0]["text"] == "before linked text after"
    doc.add_table(rows=1, cols=1).cell(0, 0).add_table(rows=1, cols=1)
    monkeypatch.setattr(ingestion, "MAX_NESTING", 1)
    with pytest.raises(ValueError, match="^RESOURCE_LIMIT:.*depth"):
        parse_document("nested.docx", docx_bytes(doc))


def test_docx_zip_crc_and_encryption_rejected():
    import struct
    from zipfile import ZIP_STORED

    original = ZipFile(BytesIO(docx_bytes(Document())))
    stream = BytesIO()
    with original, ZipFile(stream, "w", ZIP_STORED) as archive:
        for entry in original.infolist():
            archive.writestr(entry.filename, original.read(entry.filename))
    payload = bytearray(stream.getvalue())
    with ZipFile(BytesIO(payload)) as archive:
        entry = archive.getinfo("word/document.xml")
        offset = entry.header_offset
    name_length, extra_length = struct.unpack_from("<HH", payload, offset + 26)
    payload[offset + 30 + name_length + extra_length] ^= 1
    with pytest.raises(ValueError, match="^CORRUPT_DOCUMENT:"):
        parse_document("crc.docx", bytes(payload))
    payload = bytearray(stream.getvalue())
    central = payload.index(b"PK\x01\x02")
    payload[central + 8] |= 1
    with pytest.raises(ValueError, match="^ENCRYPTED_DOCUMENT:"):
        parse_document("encrypted.docx", bytes(payload))


def test_pdf_later_page_failure_never_returns_successful_prefix(monkeypatch):
    pytest.importorskip("pypdf")
    from pypdf import PageObject

    payload = pdf_bytes(("First", "Second"))
    extract = PageObject.extract_text
    calls = 0

    def fail_second(page, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic parse failure")
        return extract(page, *args, **kwargs)

    monkeypatch.setattr(PageObject, "extract_text", fail_second)
    with pytest.raises(ValueError, match="^CORRUPT_DOCUMENT:"):
        parse_document("failed.pdf", payload)
    assert calls == 2
