"""Mechanical, read-only PDF table observations, separate from frozen source text.

No OCR, model invocation, source indexing, semantic header filling, or cached writes.
Only pages selected by explicit locators in a caller's actual retrieval are added.
"""
from io import BytesIO

import pdfplumber

from .document_tools import _pdf_page, physical_page_number
from .errors import ActionRejected
from .ingestion import MAX_PDF_PAGE_CONTENT_BYTES


SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
LIMITATIONS = [
    "Derived PDF line/cell geometry, not verified facts or complete visual coverage; no new OCR.",
    "Rows retain geometric column positions. null means no separate cell (often merged); empty text is not zero. No header meaning or value is filled in.",
    "Detected tables are geometric candidates: drawing frames or empty grids can be false candidates. Detection can miss unruled/scanned tables or misread lines, text, merged cells and rotations. No detected table does not establish absent information.",
    "Whole-page table supplements may contain text outside the returned text blocks or literal search matches. Frozen text and pagination are unchanged.",
]


def source_tables(workspace, source_id, pages):
    """Batch requested 1-based PDF pages, verifying original membership/hash each call."""
    pages = list(dict.fromkeys(pages))
    if not pages:
        return []
    if any(type(p) is not int or p < 1 for p in pages):
        raise ActionRejected("SOURCE_PAGE_REQUIRES_POSITIVE_INTEGER")
    base = {"source_id": source_id, "derived": True,
            "extractor": {"name": "pdfplumber", "version": pdfplumber.__version__,
                          "settings": dict(SETTINGS), "text_settings": "library defaults"},
            "coordinate_system": "PDF points (x0, top, x1, bottom), origin as in page_bbox; row/column indices are 1-based",
            "limitations": list(LIMITATIONS)}
    try:
        source, data, reader, count = _pdf_page(workspace, source_id, 1)
    except ActionRejected as exc:
        return [{**base, "page": p, "status": "unavailable", "error": str(exc)} for p in pages]
    base.update(source_sha256=source["sha256"].lower(), page_count=count)
    views = {}
    selected = []
    for p in pages:
        item = {**base, "page": p, "locator": f"PDF physical page {p}"}
        views[p] = item
        if p > count:
            item.update(status="unavailable", error="SOURCE_PAGE_OUT_OF_RANGE")
            continue
        try:
            content = reader.pages[p - 1].get_contents()
            if content is not None and len(content.get_data()) > MAX_PDF_PAGE_CONTENT_BYTES:
                item.update(status="unavailable", error="SOURCE_TABLE_PAGE_CONTENT_LIMIT",
                            max_page_content_bytes=MAX_PDF_PAGE_CONTENT_BYTES)
                continue
        except Exception:
            item.update(status="unavailable", error="SOURCE_TABLE_PAGE_UNREADABLE")
            continue
        selected.append(p)
    if selected:
        try:
            with pdfplumber.open(BytesIO(data), pages=selected) as document:
                for page in document.pages:
                    item = views[page.page_number]
                    try:
                        tables = []
                        for index, table in enumerate(page.find_tables(SETTINGS), 1):
                            rows = table.extract()
                            # Sparse bounds only omit cells with no extracted text;
                            # every empty/null position remains present in rows.
                            bounds = [{"row": r + 1, "column": c + 1, "bbox": cell}
                                      for r, row in enumerate(table.rows)
                                      for c, cell in enumerate(row.cells)
                                      if cell is not None and rows[r][c]]
                            tables.append({"table": index, "bbox": table.bbox,
                                           "rows": rows, "nonempty_cell_bounds": bounds})
                        item.update(status="extracted" if tables else "no_tables_detected",
                                    page_bbox=page.bbox, tables=tables,
                                    native_character_count=len(page.chars))
                    except Exception:
                        item.update(status="unavailable", error="SOURCE_TABLE_EXTRACTION_FAILED")
                    finally:
                        page.close()
        except Exception:
            for p in selected:
                if "status" not in views[p]:
                    views[p].update(status="unavailable", error="SOURCE_TABLE_PDF_UNREADABLE")
        for p in selected:
            if "status" not in views[p]:
                views[p].update(status="unavailable", error="SOURCE_TABLE_PAGE_UNREADABLE")
    return [views[p] for p in pages]


def with_source_tables(workspace, result):
    """Add deduplicated page supplements; retain retrieval text/order/count/offsets."""
    located = {}
    unresolved = []
    blocks = result.get("matches")
    if blocks is None:
        blocks = [{**block, "source_id": result["source"]["id"]} for block in result["blocks"]]
    for block in blocks:
        source_id = block["source_id"]
        for locator in block.get("locators", [block["locator"]]):
            page = physical_page_number(locator)
            if page is None:
                entry = {"source_id": source_id, "locator": locator,
                         "status": "physical_page_not_located"}
                if entry not in unresolved:
                    unresolved.append(entry)
            else:
                located.setdefault(source_id, {})[page] = None
    views = [view for source_id, pages in located.items()
             for view in source_tables(workspace, source_id, pages)]
    return {**result, "source_table_views": views, "table_view_unlocated": unresolved}
