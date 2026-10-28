"""Synthetic original-page checks; no OCR, model, network, or live project data."""

import hashlib
from io import BytesIO
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pytest

from report_agent.catalog import Catalog
from report_agent.document_tools import markdown_source_ids, source_page_info, source_page_png
from report_agent.errors import ActionRejected
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_ingestion import pdf_bytes


def workspace(tmp_path, data=None, **metadata):
    data = pdf_bytes(("First physical page", "Second physical page")) if data is None else data
    store = Store(tmp_path)
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "original.pdf").write_bytes(data)
    source = {"id": "original", "title": "Synthetic original", "filename": "original.pdf",
              "content": "Frozen OCR must not be replaced", "coverage": "partial",
              "sha256": hashlib.sha256(data).hexdigest(), "copied_path": "sources/original.pdf",
              "original_path": "/outside/legacy/original.pdf", **metadata}
    store.initialize({"goal": "Test source pages", "sources": [source]})
    return Workspace(store)


def snapshot(ws):
    with ws.store.connect() as db:
        return list(db.iterdump())


def test_native_page_count_reference_and_no_writes_or_ocr(tmp_path):
    ws = workspace(tmp_path)
    before = snapshot(ws)
    original = (tmp_path / "sources/original.pdf").read_bytes()
    with patch("report_agent.ingestion.parse_document", side_effect=AssertionError("No reparse/OCR")):
        first = source_page_info(ws, "original", 1)
        second = source_page_info(ws, "original", 2)
    assert first["native_text"] == "First physical page"
    assert second["native_text"] == "Second physical page"
    assert first["page_count"] == second["page_count"] == 2
    assert second["page"] == 2
    assert second["image_ref"] == "source-page://original/2"
    assert second["locator"] == "PDF physical page 2 of 2"
    assert second["sha256"] == hashlib.sha256(original).hexdigest()
    assert "model has viewed" in " ".join(second["limitations"])
    assert "Frozen OCR" not in second["native_text"]
    assert snapshot(ws) == before
    assert (tmp_path / "sources/original.pdf").read_bytes() == original


def test_native_empty_page_does_not_claim_absence(tmp_path):
    ws = workspace(tmp_path, pdf_bytes((), image_page=True))
    info = source_page_info(ws, "original", 1)
    assert info["native_text"] == ""
    assert info["page_count"] == 1
    assert "does not establish missing information" in " ".join(info["limitations"])


@pytest.mark.parametrize("page", [0, -1, True, 1.0, "1", None, 3])
@pytest.mark.parametrize("api", [source_page_info, source_page_png])
def test_invalid_physical_page(tmp_path, api, page):
    ws = workspace(tmp_path)
    with pytest.raises(ActionRejected, match="SOURCE_PAGE_"):
        api(ws, "original", page)


@pytest.mark.parametrize("source_id", ["foreign", "../sources/original.pdf", "https://example.test/a.pdf", "' OR 1=1 --", None])
def test_source_ids_are_not_paths_or_queries(tmp_path, source_id):
    ws = workspace(tmp_path)
    with pytest.raises(ActionRejected, match="SOURCE_NOT_IN_PROJECT"):
        source_page_info(ws, source_id, 1)


@pytest.mark.parametrize("copied_path", ["../foreign.pdf", "https://example.test/a.pdf", "file:///tmp/a.pdf", r"C:\outside\original.pdf"])
def test_reject_unbound_paths_without_opening_them(tmp_path, copied_path):
    ws = workspace(tmp_path, copied_path=copied_path)
    with patch.object(Path, "read_bytes", side_effect=AssertionError("Must not open foreign path")):
        with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_OUTSIDE_PROJECT"):
            source_page_info(ws, "original", 1)


def test_cross_project_original_and_symlink_are_rejected(tmp_path):
    foreign = workspace(tmp_path / "foreign")
    ws = workspace(tmp_path / "local", copied_path=str(foreign.store.root / "sources/original.pdf"))
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_OUTSIDE_PROJECT"):
        source_page_info(ws, "original", 1)
    ws = workspace(tmp_path / "symlink")
    path = ws.store.root / "sources/original.pdf"
    path.unlink()
    path.symlink_to(foreign.store.root / "sources/original.pdf")
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_OUTSIDE_PROJECT"):
        source_page_info(ws, "original", 1)


def test_sources_directory_symlink_cannot_escape_project(tmp_path):
    ws = workspace(tmp_path / "project")
    sources = ws.store.root / "sources"
    outside = tmp_path / "outside"
    sources.rename(outside)
    sources.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_OUTSIDE_PROJECT"):
        source_page_info(ws, "original", 1)


def test_project_local_original_path_is_allowed(tmp_path):
    ws = workspace(tmp_path, copied_path="", original_path=str(tmp_path / "sources/original.pdf"))
    assert source_page_info(ws, "original", 2)["native_text"] == "Second physical page"


@pytest.mark.parametrize("sha256", [None, "", "not-a-hash"])
def test_hash_is_required(tmp_path, sha256):
    ws = workspace(tmp_path, sha256=sha256)
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_SHA256_REQUIRED"):
        source_page_info(ws, "original", 1)


@pytest.mark.parametrize("api", [source_page_info, source_page_png])
def test_changed_original_is_rejected(tmp_path, api):
    ws = workspace(tmp_path)
    (tmp_path / "sources/original.pdf").write_bytes(pdf_bytes(("Changed",)))
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_SHA256_MISMATCH"):
        api(ws, "original", 1)


def test_missing_copy_does_not_fall_back_to_external_original(tmp_path):
    ws = workspace(tmp_path)
    (tmp_path / "sources/original.pdf").unlink()
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_UNAVAILABLE"):
        source_page_info(ws, "original", 1)


def test_no_original_metadata(tmp_path):
    ws = workspace(tmp_path, copied_path="", original_path="")
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_UNAVAILABLE"):
        source_page_info(ws, "original", 1)


def test_text_only_manifest_reports_missing_original_not_missing_hash(tmp_path):
    ws = workspace(tmp_path, copied_path="", original_path="", sha256=None)
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_UNAVAILABLE"):
        source_page_info(ws, "original", 1)


@pytest.mark.parametrize("data, metadata, code", [
    (b"Not PDF", {}, "SOURCE_FORMAT_REQUIRES_PDF"),
    (b"%PDF-1.7\nBroken", {}, "SOURCE_PDF_UNREADABLE"),
    (b"DOCX placeholder", {"filename": "original.docx"}, "DOCX_PHYSICAL_PAGES_UNAVAILABLE"),
])
def test_unsupported_or_corrupt_original(tmp_path, data, metadata, code):
    ws = workspace(tmp_path, data, **metadata)
    with pytest.raises(ActionRejected, match=code):
        source_page_info(ws, "original", 1)


def test_encrypted_pdf_is_explicitly_unsupported(tmp_path):
    ws = workspace(tmp_path, pdf_bytes(encrypted=True))
    with pytest.raises(ActionRejected, match="SOURCE_PDF_ENCRYPTED"):
        source_page_info(ws, "original", 1)


def test_catalog_blob_is_bound_to_project_and_old_version_is_readable(tmp_path):
    ws = workspace(tmp_path / "one")
    cat = Catalog(ws.store)
    first = cat.import_file("uploaded.pdf", pdf_bytes(("Old original",)))["source"]["id"]
    second = cat.import_file("uploaded.pdf", pdf_bytes(("New original",)), first)["source"]["id"]
    before = snapshot(ws)
    assert source_page_info(ws, first, 1)["native_text"] == "Old original"
    assert source_page_info(ws, second, 1)["native_text"] == "New original"
    assert snapshot(ws) == before
    other = workspace(tmp_path / "two")
    with pytest.raises(ActionRejected, match="SOURCE_NOT_IN_PROJECT"):
        source_page_info(other, first, 1)
    with ws.store.connect() as db:
        sha = db.execute("SELECT object_sha256 FROM source_originals WHERE source_id=?", (first,)).fetchone()[0]
    (ws.store.root / 'sources' / 'objects' / sha).write_bytes(pdf_bytes(("Tampered",)))
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_SHA256_MISMATCH"):
        source_page_info(ws, first, 1)


def test_render_original_image_page_pixels_and_no_mutation(tmp_path):
    ws = workspace(tmp_path, pdf_bytes((), image_page=True))
    before = snapshot(ws)
    rendered = source_page_png(ws, "original", 1)
    assert rendered.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(rendered)) as image:
        assert image.size == (600, 600)
        assert image.convert("RGB").getpixel((10, 590)) == (0, 0, 0)
        assert image.convert("RGB").getpixel((300, 300)) == (255, 255, 255)
    assert snapshot(ws) == before


def test_render_catalog_blob_and_select_exact_page(tmp_path):
    ws = workspace(tmp_path)
    sid = Catalog(ws.store).import_file("upload.pdf", pdf_bytes(("First", "Second")))["source"]["id"]
    one, two = source_page_png(ws, sid, 1), source_page_png(ws, sid, 2)
    assert one != two
    with Image.open(BytesIO(two)) as image:
        assert image.size == (600, 600)


@pytest.mark.parametrize("crop", [None, [0.1, 0.1, 0.9, 0.9]])
def test_authorized_page_read_ignores_withdrawn_historical_blacklist(tmp_path, crop):
    from report_agent.document_tools import vision_source_image
    ws = workspace(tmp_path)
    ws.store.set("visual_page_exclusions", {"original": [2]})
    before = snapshot(ws)
    png, provenance = vision_source_image(ws, "original", 2, crop)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert provenance["page"] == 2
    assert source_page_png(ws, "original", 2).startswith(b"\x89PNG\r\n\x1a\n")
    assert source_page_info(ws, "original", 2)["native_text"] == "Second physical page"
    with pytest.raises(ActionRejected, match="SOURCE_NOT_IN_PROJECT"):
        vision_source_image(ws, "foreign", 2, crop)
    assert snapshot(ws) == before


def test_frozen_ocr_matches_physical_page_not_block_ordinal(tmp_path):
    ws = workspace(tmp_path)
    Catalog(ws.store)
    first = json.dumps({"page": 1, "method": "ocr", "status": "partial", "parse_id": "frozen-1"})
    second = json.dumps({"page": 2, "method": "ocr", "status": "partial", "parse_id": "frozen-1"})
    with ws.store.connect() as db:
        db.execute("DELETE FROM source_blocks WHERE source_id='original'")
        db.executemany("INSERT INTO source_blocks VALUES (?, ?, ?, ?)", [
            ("original", 0, first + "; chars 1-7", "PageOne"),
            ("original", 2, first + "; chars 8-14", "NotPageTwo"),
            ("original", 17, second + "; chars 1-7", "OCR Two"),
            ("original", 18, second + "; chars 8-14", " continued"),
            ("original", 19, '{"page": "2"}; chars 1-2', "WrongType"),
            ("original", 20, '{"page": 2}; arbitrary suffix', "UnknownLocator"),
            ("original", 21, "paragraph 2; chars 1-2", "NotAPage"),
            ("foreign", 0, second + "; chars 1-7", "Foreign"),
        ])
    before = snapshot(ws)
    info = source_page_info(ws, "original", 2)
    assert [b["ordinal"] for b in info["frozen_text_blocks"]] == [17, 18]
    assert "".join(b["text"] for b in info["frozen_text_blocks"]) == "OCR Two continued"
    assert info["native_text"] == "Second physical page"
    assert snapshot(ws) == before


def test_existing_upload_native_locator_is_explicitly_matched(tmp_path):
    ws = workspace(tmp_path)
    sid = Catalog(ws.store).import_file("upload.pdf", pdf_bytes(("Alpha", "Beta")))["source"]["id"]
    info = source_page_info(ws, sid, 2)
    assert len(info["frozen_text_blocks"]) == 1
    assert info["frozen_text_blocks"][0]["text"] == "Beta"
    assert info["frozen_text_blocks"][0]["locator"].startswith("page 2;")


def test_large_page_render_is_bounded_and_declared(tmp_path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=6000, height=3000)
    stream = BytesIO()
    writer.write(stream)
    ws = workspace(tmp_path, stream.getvalue())
    rendered = source_page_png(ws, "original", 1)
    with Image.open(BytesIO(rendered)) as image:
        assert image.size == (4096, 2048)
    assert "4096-pixel" in " ".join(source_page_info(ws, "original", 1)["limitations"])


def test_missing_renderer_does_not_disable_text(tmp_path):
    ws = workspace(tmp_path)
    with patch.dict("sys.modules", {"pypdfium2": None}):
        assert source_page_info(ws, "original", 1)["native_text"] == "First physical page"
        with pytest.raises(ActionRejected, match="SOURCE_PAGE_RENDERER_UNAVAILABLE"):
            source_page_png(ws, "original", 1)


def test_frozen_ocr_available_even_without_native_text(tmp_path):
    ws = workspace(tmp_path, pdf_bytes((), image_page=True))
    Catalog(ws.store)
    with ws.store.connect() as db:
        db.execute("INSERT INTO source_blocks VALUES (?, ?, ?, ?)",
                   ("original", 7, '{"page": 1, "method": "ocr"}; chars 1-10', "Frozen OCR"))
    info = source_page_info(ws, "original", 1)
    assert info["native_text"] == ""
    assert info["frozen_text_blocks"][0]["text"] == "Frozen OCR"
    assert "No native text" in " ".join(info["limitations"])


def test_source_id_is_percent_encoded_not_treated_as_a_path(tmp_path):
    ws = workspace(tmp_path, id="a/b #")
    assert source_page_info(ws, "a/b #", 1)["image_ref"] == "source-page://a%2Fb%20%23/1"


def test_serialized_native_render_is_safe_for_concurrent_callers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    ws = workspace(tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        images = list(pool.map(lambda _: source_page_png(ws, "original", 1), range(6)))
    assert len(set(images)) == 1


def test_markdown_image_sources_in_inline_table_and_reference_images():
    body = """Before **![first](source-page://alpha/2)** and ![again](source-page://alpha/7).

| Figure | Supporting figure |
| --- | --- |
| ![table](source-page://beta/1) | [![linked](source-page://gamma/4)](https://example.test) |

![reference][figure]

[figure]: source-page://delta/3 "Existing page"
"""
    assert markdown_source_ids(body) == ["alpha", "beta", "gamma", "delta"]


def test_markdown_source_ids_are_pure_and_do_not_validate_project_membership():
    with patch("report_agent.document_tools._original", side_effect=AssertionError("No original read")), \
         patch("report_agent.document_tools.source_page_png", side_effect=AssertionError("No rendering")):
        assert markdown_source_ids("![page](source-page://unknown-but-syntactically-valid/999)") == [
            "unknown-but-syntactically-valid"
        ]


@pytest.mark.parametrize("body", [
    "", "source-page://not-an-image/1", "[ordinary link](source-page://not-an-image/1)",
    "`![code](source-page://not-an-image/1)`",
    "```markdown\n![code](source-page://not-an-image/1)\n```",
    "    ![indented code](source-page://not-an-image/1)",
    r"\![escaped](source-page://not-an-image/1)",
    '<img src="source-page://html-not-markdown/1">',
    '<!-- ![comment](source-page://not-an-image/1) -->',
    "[unused]: source-page://not-an-image/1",
    "[ordinary link](https://example.test)",
])
def test_non_image_text_does_not_adopt_sources(body):
    assert markdown_source_ids(body) == []


@pytest.mark.parametrize("url", [
    "https://example.test/image.png", "relative.png", "source-page://id/0",
    "source-page://id/-1", "source-page://id/01", "source-page://id/1.0",
    "source-page://id/1?query", "source-page://id/1#fragment", "source-page://id/1/extra",
    "source-page:///1", "source-page://./1", "source-page://../1",
    "source-page://a/b/1", "source-page://%61/1", "source-page://a%2fb/1",
    "source-page://%FF/1", "source-page://%2E/1",
    "source-page://user@host/1", "SOURCE-PAGE://id/1",
])
def test_invalid_markdown_image_reference_is_rejected(url):
    with pytest.raises(ActionRejected, match="^EXPORT_IMAGE_REQUIRES_SOURCE_PAGE_REFERENCE$"):
        markdown_source_ids(f"![image]({url})")


def test_markdown_source_id_decoding_is_canonical_and_once_only():
    assert markdown_source_ids(
        "![one](source-page://a%2Fb%20%23/1) "
        "![two](source-page://%E4%B8%AD/2) "
        "![three](source-page://literal%252F/3)"
    ) == ["a/b #", "\u4e2d", "literal%2F"]


def test_url_validation_uses_same_parser_normalization_as_exporter():
    # MarkdownIt turns a literal percent into %25 before either consumer sees it.
    assert markdown_source_ids("![percent](source-page://%/1)") == ["%"]


def test_image_alt_text_is_not_another_adopted_image():
    assert markdown_source_ids(
        "![outer ![inner](source-page://alt-text-only/1)](source-page://rendered/2)"
    ) == ["rendered"]


def test_images_in_lists_and_blockquotes_are_explicit_adoptions():
    assert markdown_source_ids(
        "- ![listed](source-page://list/1)\n\n> ![quoted](source-page://quote/2)"
    ) == ["list", "quote"]
