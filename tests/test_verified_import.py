import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from report_agent.catalog import Catalog
from report_agent.store import Store


spec = importlib.util.spec_from_file_location(
    "verified_import", Path(__file__).parents[1] / "scripts/import_verified_sources.py")
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def inputs(tmp_path):
    root = tmp_path / "originals"
    root.mkdir()
    original = b"synthetic original, never parsed or sent to a model"
    (root / "source.pdf").write_bytes(original)
    scope = "Synthetic commissioning instruction\n"
    (root / importer.SCOPE_FILENAME).write_text(scope, encoding="utf-8")
    text = "[\u7b2c 1 \u9875\uff1bqwen\uff1bready]\n" + "x" * 9100 + "\n"
    text += "[\u7b2c 2 \u9875\uff1bnative\uff1bready]\nEND-OF-SOURCE\n"
    source = {"id": "source-1", "filename": "source.pdf", "text": text,
              "sha256": hashlib.sha256(original).hexdigest(), "parse_id": "parse-1",
              "warning": "\u51712\u9875; verify units"}
    frozen = {k: v for k, v in source.items() if k != "text"}
    frozen["text_sha256"] = importer.text_hash(text)
    publication, preflight = tmp_path / "publication.json", tmp_path / "preflight.json"
    publication.write_text(json.dumps([
        ["publish_knowledge", {"content": "DO-NOT-IMPORT-DERIVED"}],
        ["publish_plan", ["old-project", "old-task", "old-plan", ["DO-NOT-IMPORT-DERIVED"],
                          ["DO-NOT-IMPORT-DERIVED"], [source]]],
        ["publish_structure", {"content": "DO-NOT-IMPORT-DERIVED"}]]), encoding="utf-8")
    preflight.write_text(json.dumps({"sources": [frozen], "scope_text": scope,
                                    "scope_sha256": importer.text_hash(scope)}), encoding="utf-8")
    return publication, preflight, root, tmp_path / "project"


def test_original_hash_mismatch_leaves_no_project(tmp_path):
    args = inputs(tmp_path)
    (args[2] / "source.pdf").write_bytes(b"changed")
    with pytest.raises(ValueError, match="ORIGINAL_HASH_MISMATCH"):
        importer.import_verified_sources(*args)
    assert not args[3].exists()


def test_only_sources_and_scope_are_imported_with_complete_located_blocks(tmp_path):
    args = inputs(tmp_path)
    receipt = importer.import_verified_sources(*args)
    store = Store(args[3])
    manifest = store.manifest
    assert receipt["source_count"] == receipt["scope_count"] == 1
    assert receipt["blocks"] == 4
    assert not store.artifacts()
    assert "DO-NOT-IMPORT-DERIVED" not in json.dumps(manifest)
    assert "old-task" not in json.dumps(manifest)
    assert manifest["goal"] == "Synthetic commissioning instruction\n\n\n" + importer.COMPILATION_NOTE
    assert "source_issue_policy" not in manifest
    result = Catalog(store).read("source-1")
    assert "".join(b["text"] for b in result["blocks"]) == manifest["sources"][0]["content"]
    assert "END-OF-SOURCE" in result["blocks"][-1]["text"]
    locator = result["blocks"][0]["locator"].split("; chars", 1)[0]
    assert json.loads(locator) == {"page": 1, "method": "qwen", "status": "ready",
                                   "warning": "\u51712\u9875; verify units", "parse_id": "parse-1"}
    assert {p.name for p in (args[3] / "sources").iterdir()} == {"source.pdf", importer.SCOPE_FILENAME}


def test_reentry_checks_receipt_without_duplicates_or_writes(tmp_path):
    args = inputs(tmp_path)
    first = importer.import_verified_sources(*args)
    before = {str(p): (p.stat().st_mtime_ns, importer.file_hash(p))
              for p in args[3].rglob("*") if p.is_file()}
    second = importer.import_verified_sources(*args)
    after = {str(p): (p.stat().st_mtime_ns, importer.file_hash(p))
             for p in args[3].rglob("*") if p.is_file()}
    assert second == {**first, "reused": True}
    assert before == after
    store = Store(args[3])
    with store.connect() as db:
        db.execute("UPDATE source_blocks SET text='tampered' WHERE ordinal=0")
    with pytest.raises(ValueError, match="IMPORT_BLOCKS_MISMATCH"):
        importer.import_verified_sources(*args)


@pytest.mark.parametrize("filename", ["../source.pdf", "C:source.pdf", "nested\\source.pdf"])
def test_basename_required(tmp_path, filename):
    args = inputs(tmp_path)
    for path in args[:2]:
        value = json.loads(path.read_text())
        source = value[1][1][5][0] if isinstance(value, list) else value["sources"][0]
        source["filename"] = filename
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="FILENAME_MUST_BE_BASENAME"):
        importer.import_verified_sources(*args)
    assert not args[3].exists()
