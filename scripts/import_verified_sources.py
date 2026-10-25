"""Import only verified original sources and frozen located text; never run OCR/models."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter
from pathlib import Path, PureWindowsPath
from zipfile import ZipFile

from report_agent.catalog import Catalog
from report_agent.store import Store, encode


SCOPE_FILENAME = "\u62a5\u544a\u7f16\u5199\u8303\u56f4\u8bf4\u660e.md"
COMPILATION_NOTE = "\u672c\u62a5\u544a\u662f\u5df2\u6709\u8d44\u6599\u6c47\u7f16\uff0c\u4e0d\u662f\u65b0\u8bbe\u8ba1\uff0c\u4e0d\u4ee3\u66ff\u5de5\u7a0b\u7b7e\u53d1\u3002"
PAGE = re.compile(r"(?m)^\[\u7b2c (\d+) \u9875\uff1b([^\uff1b\]\r\n]+)\uff1b([^\]\r\n]+)\]")
PAGE_COUNT = re.compile(r"\u5171(\d+)\u9875")
FIELDS = ("id", "filename", "sha256", "text", "warning", "parse_id")


def require(condition, code):
    if not condition:
        raise ValueError(code)


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def text_hash(text):
    # The historical receipt hashes a JSON string, including its outer quotes.
    return hashlib.sha256(json.dumps(text, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def source_path(root, filename):
    require(isinstance(filename, str) and bool(filename), "INVALID_FILENAME")
    require(filename not in {".", ".."} and not any(c in filename for c in '/\\:\x00')
            and not any(ord(c) < 32 for c in filename)
            and filename == filename.rstrip(" .") and not PureWindowsPath(filename).is_reserved(),
            "FILENAME_MUST_BE_BASENAME")
    path = root / filename
    require(not path.is_symlink() and path.resolve().parent == root and path.is_file(),
            "ORIGINAL_MUST_BE_LOCAL_FILE")
    return path


def located_blocks(source):
    text, warning = source["text"], source["warning"]
    markers = list(PAGE.finditer(text)) if source["filename"].lower().endswith(".pdf") else []
    if source["filename"].lower().endswith(".pdf"):
        require(bool(markers) and markers[0].start() == 0, "PDF_PAGE_MARKERS_REQUIRED")
        numbers = [int(m[1]) for m in markers]
        require(numbers == list(range(1, len(markers) + 1)), "PDF_PAGE_SEQUENCE_INVALID")
        count = PAGE_COUNT.search(warning)
        require(count is not None and int(count[1]) == len(markers), "PDF_PAGE_COUNT_MISMATCH")
        blocks = [{"locator": encode({"page": int(m[1]), "method": m[2], "status": m[3],
                                      "warning": warning, "parse_id": source["parse_id"]}),
                   "text": text[m.start():markers[i + 1].start() if i + 1 < len(markers) else len(text)]}
                  for i, m in enumerate(markers)]
    else:
        blocks = [{"locator": encode({"location": "document paragraphs and tables",
                    "method": "frozen_text_extraction", "status": "partial", "warning": warning}),
                   "text": text}]
    require("".join(b["text"] for b in blocks) == text, "TEXT_COVERAGE_MISMATCH")
    return blocks


def block_rows(source_id, blocks):
    ordinal = 0
    for block in blocks:
        for start in range(0, len(block["text"]), 4000):
            text = block["text"][start:start + 4000]
            yield (source_id, ordinal,
                   f'{block["locator"]}; chars {start + 1}-{start + len(text)}', text)
            ordinal += 1


def rows_hash(rows):
    value = hashlib.sha256()
    for row in rows:
        value.update((encode(list(row)) + "\n").encode())
    return value.hexdigest()


def prepare(publication, preflight, source_root):
    entries, frozen = load_json(publication), load_json(preflight)
    selected = [entry for entry in entries if isinstance(entry, list) and len(entry) == 2
                and entry[0] == "publish_plan"]
    require(len(selected) == 1 and isinstance(selected[0][1], list)
            and len(selected[0][1]) > 5, "ONE_PUBLISH_PLAN_REQUIRED")
    sources = selected[0][1][5]
    require(isinstance(sources, list) and bool(sources), "SOURCES_REQUIRED")
    expected = frozen["sources"]
    require(len({s["id"] for s in expected}) == len(expected), "DUPLICATE_PREFLIGHT_SOURCE")
    index = {s["id"]: s for s in expected}
    require(len(sources) == len(index) and {s["id"] for s in sources} == set(index),
            "SOURCE_SET_MISMATCH")
    require(len({s["filename"].casefold() for s in sources}) == len(sources), "DUPLICATE_FILENAME")
    catalog, provenance, blocks_by_id, copies = [], [], {}, []
    for raw in sources:
        source = {key: raw[key] for key in FIELDS}
        check = index[source["id"]]
        require(all(source[key] == check[key] for key in FIELDS if key != "text"), "SOURCE_METADATA_MISMATCH")
        require(isinstance(source["text"], str) and bool(source["text"])
                and isinstance(source["warning"], str) and bool(source["id"]), "INVALID_SOURCE")
        require(text_hash(source["text"]) == check["text_sha256"], "TEXT_HASH_MISMATCH")
        path = source_path(source_root, source["filename"])
        require(source["filename"].casefold() != SCOPE_FILENAME.casefold(), "SCOPE_IS_NOT_ENGINEERING_SOURCE")
        require(file_hash(path) == source["sha256"], "ORIGINAL_HASH_MISMATCH")
        blocks = located_blocks(source)
        pages = list(PAGE.finditer(source["text"])) if path.suffix.lower() == ".pdf" else []
        limitations = [source["warning"]] if source["warning"] else []
        media, headers = 0, 0
        if path.suffix.lower() == ".docx":
            with ZipFile(path) as archive:
                media = sum(n.startswith("word/media/") and not n.endswith("/") for n in archive.namelist())
                headers = sum(bool(re.fullmatch(r"word/(header|footer)\d+\.xml", n)) for n in archive.namelist())
            limitations.append(f"Frozen text does not cover images, headers/footers or layout; "
                               f"unparsed media files={media}, header/footer parts={headers}.")
        else:
            limitations.append("Page coverage is not OCR accuracy; verify numbers, units, tables and drawings against originals.")
        metadata = {key: source[key] for key in FIELDS if key != "text"}
        metadata.update({"bytes": path.stat().st_size, "text_sha256": check["text_sha256"],
                         "text_characters": len(source["text"]), "limitations": limitations,
                         "original_path": str(path), "copied_path": "sources/" + path.name,
                         "unparsed_media_files": media, "header_footer_parts": headers,
                         "pages": len(blocks) if path.suffix.lower() == ".pdf" else None,
                         "page_methods": dict(Counter(m[2] for m in pages)),
                         "page_statuses": dict(Counter(m[3] for m in pages)),
                         "blocks": sum(1 for _ in block_rows(source["id"], blocks)),
                         "blocks_sha256": rows_hash(block_rows(source["id"], blocks))})
        catalog.append({**metadata, "title": path.name, "content": source["text"],
                        "coverage": "partial", "origin": "verified_original_and_frozen_parse"})
        provenance.append(metadata)
        blocks_by_id[source["id"]] = blocks
        copies.append((path, source["sha256"]))
    scope_path = source_path(source_root, SCOPE_FILENAME)
    scope = scope_path.read_text(encoding="utf-8-sig")
    require(scope == frozen["scope_text"] and text_hash(scope) == frozen["scope_sha256"], "SCOPE_HASH_MISMATCH")
    scope_meta = {"filename": SCOPE_FILENAME, "sha256": file_hash(scope_path),
                  "text_sha256": text_hash(scope), "characters": len(scope),
                  "bytes": scope_path.stat().st_size, "original_path": str(scope_path),
                  "copied_path": "sources/" + SCOPE_FILENAME, "role": "commissioning_instruction"}
    copies.append((scope_path, scope_meta["sha256"]))
    manifest = {"goal": scope + "\n\n" + COMPILATION_NOTE,
                "scope_instruction": {**scope_meta, "text": scope}, "sources": catalog}
    receipt = {"format": "verified_sources_v1", "source_count": len(catalog), "scope_count": 1,
               "original_bytes": sum(s["bytes"] for s in provenance),
               "text_characters": sum(s["text_characters"] for s in provenance),
               "blocks": sum(s["blocks"] for s in provenance),
               "sources": provenance, "scope": scope_meta,
               "publication": {"path": str(publication), "sha256": file_hash(publication),
                               "selection": "publish_plan.params[5] only"},
               "preflight": {"path": str(preflight), "sha256": file_hash(preflight)},
               "manifest_sha256": hashlib.sha256(encode(manifest).encode()).hexdigest(),
               "new_ocr_calls": 0, "model_calls": 0,
               "source_issue_policy": "unspecified; import does not choose continue or wait"}
    return manifest, receipt, blocks_by_id, copies


def check_existing(project, receipt):
    require(not project.is_symlink() and project.is_dir(), "PROJECT_PATH_INVALID")
    path = project / "provenance.json"
    require(path.is_file() and not path.is_symlink(), "EXISTING_PROJECT_REQUIRES_RECEIPT_REVIEW")
    require(load_json(path) == receipt, "IMPORT_RECEIPT_MISMATCH")
    originals = (project / "sources").resolve()
    require(originals.parent == project and not (project / "sources").is_symlink(), "PROJECT_SOURCES_INVALID")
    for source in receipt["sources"] + [receipt["scope"]]:
        require(file_hash(source_path(originals, source["filename"])) == source["sha256"],
                "IMPORTED_ORIGINAL_HASH_MISMATCH")
    dbpath = project / "state.db"
    require(dbpath.is_file() and not dbpath.is_symlink(), "PROJECT_DATABASE_INVALID")
    with sqlite3.connect(dbpath.as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT value FROM state WHERE key='verified_source_import'").fetchone()
        require(row is not None and json.loads(row[0]) == receipt, "IMPORT_DATABASE_RECEIPT_MISMATCH")
        row = db.execute("SELECT value FROM state WHERE key='manifest'").fetchone()
        require(row is not None and hashlib.sha256(row[0].encode()).hexdigest() == receipt["manifest_sha256"],
                "IMPORT_MANIFEST_MISMATCH")
        for source in receipt["sources"]:
            rows = db.execute("SELECT source_id,ordinal,locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal",
                              (source["id"],)).fetchall()
            require(len(rows) == source["blocks"] and rows_hash(rows) == source["blocks_sha256"],
                    "IMPORT_BLOCKS_MISMATCH")


def import_verified_sources(publication: Path, preflight: Path, source_root: Path, project: Path):
    require(not project.is_symlink(), "PROJECT_PATH_INVALID")
    publication, preflight, source_root, project = (p.resolve() for p in (publication, preflight, source_root, project))
    require(not project.is_relative_to(source_root) and not source_root.is_relative_to(project),
            "PROJECT_MUST_BE_SEPARATE_FROM_ORIGINALS")
    require(not publication.is_relative_to(project) and not preflight.is_relative_to(project),
            "PROJECT_MUST_BE_SEPARATE_FROM_EVIDENCE")
    manifest, receipt, blocks, copies = prepare(publication, preflight, source_root)
    if project.exists():
        check_existing(project, receipt)
        return {**receipt, "reused": True}
    # Exclusive creation prevents concurrent import or overwriting a partially initialized project.
    project.mkdir(parents=True, exist_ok=False)
    destination = project / "sources"
    destination.mkdir()
    for path, expected in copies:
        target = destination / path.name
        with path.open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        require(file_hash(target) == expected, "COPIED_ORIGINAL_HASH_MISMATCH")
    store = Store(project)
    store.initialize(manifest)
    Catalog(store)
    with store.connect() as db:
        for source in receipt["sources"]:
            db.execute("DELETE FROM source_blocks WHERE source_id=?", (source["id"],))
            Catalog._blocks(db, source["id"], blocks[source["id"]])
            rows = db.execute("SELECT source_id,ordinal,locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal",
                              (source["id"],)).fetchall()
            require(rows_hash(rows) == source["blocks_sha256"], "CATALOG_BLOCKS_MISMATCH")
        db.execute("INSERT INTO state VALUES ('verified_source_import', ?)", (encode(receipt),))
    with (project / "provenance.json").open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    check_existing(project, receipt)
    return {**receipt, "reused": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("publication", "preflight", "source-root", "project"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = import_verified_sources(args.publication, args.preflight, args.source_root, args.project)
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        # Do not expose source text, paths embedded in exceptions, or partial JSON payloads.
        code = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r"[A-Z_]+", str(exc)) else type(exc).__name__
        raise SystemExit(f"IMPORT_FAILED {code}: inspect inputs and existing receipt; no automatic overwrite") from None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
