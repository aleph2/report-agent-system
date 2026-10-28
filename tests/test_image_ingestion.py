"""Synthetic image import/access: no models, OCR, network, or live projects."""

import hashlib
from io import BytesIO
import math
from unittest.mock import patch

from PIL import Image
import pytest

from report_agent import ingestion
from report_agent.catalog import Catalog
from report_agent.document_tools import source_page_png, vision_source_image
from report_agent.errors import ActionRejected
from report_agent.ingestion import parse_document
from test_document_tools import snapshot, workspace
from test_ingestion import pdf_bytes


def image_bytes(format="PNG", size=(100, 80), **options):
    with Image.new("RGB", size, "white") as image:
        image.paste("red", (0, 0, size[0] // 2, size[1]))
        stream = BytesIO()
        image.save(stream, format=format, **options)
        return stream.getvalue()


@pytest.mark.parametrize("suffix,format", [("png", "PNG"), ("jpg", "JPEG"), ("JPEG", "JPEG"), ("webp", "WEBP")])
def test_image_import_is_partial_without_extracted_text(suffix, format):
    data = image_bytes(format)
    result = parse_document("diagram." + suffix, data)
    assert result["coverage"] == "partial"
    assert result["blocks"] == []
    assert "no OCR performed" in " ".join(result["limitations"])
    assert result["image"]["width"] == 100 and result["image"]["height"] == 80
    assert result["image"]["format"] == format


@pytest.mark.parametrize("suffix", ["png", "jpg", "webp"])
def test_corrupt_images_never_register_text(suffix):
    with pytest.raises(ValueError, match="^CORRUPT_DOCUMENT:"):
        parse_document("bad." + suffix, b"not an image with private data")


def test_extension_mismatch_and_truncated_png():
    with pytest.raises(ValueError, match="^IMAGE_FORMAT_MISMATCH:"):
        parse_document("wrong.jpg", image_bytes("PNG"))
    with pytest.raises(ValueError, match="^CORRUPT_DOCUMENT:"):
        parse_document("truncated.png", image_bytes()[:60])


@pytest.mark.parametrize("limit", ["MAX_UPLOAD_BYTES", "MAX_IMAGE_PIXELS", "MAX_IMAGE_EDGE"])
def test_import_resource_limits_before_decoding(monkeypatch, limit):
    data = image_bytes()
    monkeypatch.setattr(ingestion, limit, 10)
    with patch.object(Image.Image, "load", side_effect=AssertionError("No pixel decompression")):
        with pytest.raises(ValueError, match="^RESOURCE_LIMIT:"):
            parse_document("large.png", data)


@pytest.mark.parametrize("format,suffix", [("PNG", "png"), ("WEBP", "webp")])
def test_multiframe_images_rejected_not_silently_first_frame(format, suffix):
    with Image.new("RGB", (20, 20), "red") as first, Image.new("RGB", (20, 20), "blue") as second:
        stream = BytesIO()
        first.save(stream, format=format, save_all=True, append_images=[second], duration=100)
    with pytest.raises(ValueError, match="^IMAGE_MULTIFRAME_UNSUPPORTED:"):
        parse_document("animated." + suffix, stream.getvalue())


def test_catalog_registers_original_no_fabricated_text_and_vision_is_read_only(tmp_path):
    ws = workspace(tmp_path)
    data = image_bytes()
    cat = Catalog(ws.store)
    imported = cat.import_file("diagram.png", data)
    sid = imported["source"]["id"]
    assert imported["source"]["coverage"] == "partial"
    assert cat.read(sid)["blocks"] == []
    assert ws.store.sources([sid])[0]["content"] == ""
    assert cat.import_file("diagram.png", data)["reused"]
    before = snapshot(ws)
    png, provenance = vision_source_image(ws, sid)
    assert snapshot(ws) == before
    assert provenance["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert provenance["image_sha256"] == hashlib.sha256(png).hexdigest()
    assert provenance["coverage"] == "full_image"
    assert provenance["page"] == 1 and provenance["crop"] is None
    assert provenance["width"] == 100 and provenance["height"] == 80
    assert ws.store.source_original(sid)[1] == data


@pytest.mark.parametrize("format,suffix", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp")])
def test_project_file_image_and_crop_pixels(tmp_path, format, suffix):
    data = image_bytes(format)
    ws = workspace(tmp_path, data, filename="source." + suffix)
    before = snapshot(ws)
    crop = [0.0, 0.0, 0.5, 1.0]
    png, provenance = vision_source_image(ws, "original", crop=crop)
    assert provenance["crop"] == crop and provenance["crop_pixels"] == [0, 0, 50, 80]
    assert provenance["coverage"] == "region_only"
    assert "never full-page OCR" in " ".join(provenance["limitations"])
    assert provenance["source_format"] == format
    with Image.open(BytesIO(png)) as image:
        assert image.size == (50, 80)
        red, green, blue = image.getpixel((10, 10))
        assert red > 240 and green < 10 and blue < 10
    assert (tmp_path / "sources/original.pdf").read_bytes() == data
    assert snapshot(ws) == before


@pytest.mark.parametrize("crop", [[], [0, 0, 1], (0, 0, 1, 1), [0, 0, 0, 1], [0, 0.5, 1, 0.2],
                                  [-0.1, 0, 1, 1], [0, 0, 1.1, 1], [0, 0, math.inf, 1],
                                  [0, 0, math.nan, 1], [False, 0, 1, 1], ["0", 0, 1, 1],
                                  [0, 0, 10 ** 400, 1]])
def test_invalid_crop_is_deterministically_rejected_before_original_read(tmp_path, crop):
    ws = workspace(tmp_path)
    with patch("report_agent.document_tools._original", side_effect=AssertionError("No read")):
        with pytest.raises(ActionRejected, match="SOURCE_IMAGE_INVALID_CROP"):
            vision_source_image(ws, "original", crop=crop)


def test_fractional_pixel_crop_rounds_outwards(tmp_path):
    ws = workspace(tmp_path, image_bytes(size=(10, 10)), filename="a.png")
    png, provenance = vision_source_image(ws, "original", crop=[0.11, 0.21, 0.12, 0.22])
    assert provenance["crop_pixels"] == [1, 2, 2, 3]
    with Image.open(BytesIO(png)) as image:
        assert image.size == (1, 1)


def test_pdf_uses_existing_page_renderer_without_ocr_or_mutation(tmp_path):
    ws = workspace(tmp_path, pdf_bytes(("Page One", "Page Two")))
    before = snapshot(ws)
    existing = source_page_png(ws, "original", 2)
    with patch("report_agent.document_tools.source_page_png", wraps=source_page_png) as renderer:
        full, provenance = vision_source_image(ws, "original", page=2)
        assert renderer.call_args.args == (ws, "original", 2)
    assert full == existing
    assert provenance["source_format"] == "PDF" and provenance["page"] == 2
    assert provenance["coverage"] == "full_page_image"
    cropped, region = vision_source_image(ws, "original", page=2, crop=[0, 0.5, 0.5, 1])
    assert region["crop_pixels"] == [0, 300, 300, 600]
    with Image.open(BytesIO(cropped)) as image:
        assert image.size == (300, 300)
    assert region["image_sha256"] != provenance["image_sha256"]
    assert snapshot(ws) == before


def test_exif_orientation_is_applied_before_crop(tmp_path):
    exif = Image.Exif()
    exif[274] = 6
    data = image_bytes("JPEG", size=(100, 80), exif=exif)
    ws = workspace(tmp_path, data, filename="photo.jpg")
    parsed = parse_document("photo.jpg", data)
    assert (parsed["image"]["width"], parsed["image"]["height"]) == (80, 100)
    png, provenance = vision_source_image(ws, "original", crop=[0, 0, 1, 0.5])
    assert (provenance["base_width"], provenance["base_height"]) == (80, 100)
    assert provenance["crop_pixels"] == [0, 0, 80, 50]
    with Image.open(BytesIO(png)) as image:
        assert image.size == (80, 50)
        assert not image.getexif()
        assert image.getpixel((10, 10))[0] > 240


def test_alpha_compositing_and_metadata_not_forwarded(tmp_path):
    from PIL.PngImagePlugin import PngInfo

    metadata = PngInfo()
    metadata.add_text("private", "Do not forward ancillary metadata")
    with Image.new("RGBA", (30, 20), (0, 0, 0, 0)) as image:
        stream = BytesIO()
        image.save(stream, format="PNG", pnginfo=metadata)
    ws = workspace(tmp_path, stream.getvalue(), filename="diagram.png")
    png, provenance = vision_source_image(ws, "original")
    with Image.open(BytesIO(png)) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)
        assert "private" not in image.info
    assert "onto white" in " ".join(provenance["limitations"])


def test_output_size_bound_crop_before_resize_and_no_upscale(tmp_path):
    ws = workspace(tmp_path, image_bytes(size=(5000, 100)), filename="wide.png")
    _, full = vision_source_image(ws, "original")
    assert full["width"] == 4096 and full["height"] <= 100
    _, region = vision_source_image(ws, "original", crop=[0, 0, 0.2, 1])
    assert region["width"] == 1000 and region["height"] == 100
    assert region["base_width"] == 5000
    assert full["render_limits"]["max_output_edge"] == 4096


@pytest.mark.parametrize("page", [0, True, "1", 1.0, 2])
def test_raster_page_one_only(tmp_path, page):
    ws = workspace(tmp_path, image_bytes(), filename="a.png")
    with pytest.raises(ActionRejected, match="SOURCE_PAGE_"):
        vision_source_image(ws, "original", page=page)


def test_membership_paths_and_hash_are_enforced(tmp_path):
    ws = workspace(tmp_path / "local", image_bytes(), filename="a.png")
    other = workspace(tmp_path / "other")
    sid = Catalog(other.store).import_file("a.png", image_bytes())["source"]["id"]
    for foreign in [sid, "../other/sources/original.pdf", "https://example.test/image.png"]:
        with pytest.raises(ActionRejected, match="SOURCE_NOT_IN_PROJECT"):
            vision_source_image(ws, foreign)
    local = ws.store.root / "sources/original.pdf"
    local.write_bytes(image_bytes(size=(20, 20)))
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_SHA256_MISMATCH"):
        vision_source_image(ws, "original")
    local.unlink()
    local.symlink_to(other.store.root / "sources/original.pdf")
    with pytest.raises(ActionRejected, match="SOURCE_ORIGINAL_OUTSIDE_PROJECT"):
        vision_source_image(ws, "original")


def test_original_image_resource_limits_also_apply_without_catalog_import(tmp_path, monkeypatch):
    ws = workspace(tmp_path, image_bytes(), filename="a.png")
    monkeypatch.setattr(ingestion, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ActionRejected, match="SOURCE_IMAGE_RESOURCE_LIMIT"):
        vision_source_image(ws, "original")


def test_failed_image_import_is_atomic(tmp_path):
    ws = workspace(tmp_path)
    catalog = Catalog(ws.store)
    before = snapshot(ws)
    with pytest.raises(ValueError, match="CORRUPT_DOCUMENT"):
        catalog.import_file("broken.png", image_bytes()[:60])
    assert snapshot(ws) == before


def test_pdf_marker_in_png_metadata_does_not_change_format(tmp_path):
    from PIL.PngImagePlugin import PngInfo

    metadata = PngInfo()
    metadata.add_text("comment", "%PDF-1.7 is not the actual file format")
    data = image_bytes(pnginfo=metadata)
    ws = workspace(tmp_path, data, filename="a.png")
    _, provenance = vision_source_image(ws, "original")
    assert provenance["source_format"] == "PNG"
