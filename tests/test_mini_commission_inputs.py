from pathlib import Path

from report_agent.ingestion import parse_document


def test_native_import_distinguishes_readable_evidence_and_drawing_only_page():
    inputs = Path(__file__).parent / "fake_data" / "mini_commission" / "inputs"
    pages = {}
    for path in inputs.iterdir():
        parsed = parse_document(path.name, path.read_bytes())
        pages[path.stem] = {b["locator"]: b["text"] for b in parsed["blocks"]}

    assert "坡高 18 米" in pages["01_initial"]["page 1"]
    assert "未提供地下水调查记录" in pages["01_initial"]["page 2"]
    assert "2026-03-01 改为 2026-04-15" in pages["02_revision"]["page 1"]
    assert "1:0.75" in pages["04_design"]["page 1"]
    assert "1:1.0" in pages["05_survey"]["page 1"]
    assert pages["06_drawing"] == {"page 1": ""}
    assert "720 mm" in pages["07_region"]["page 1"]
    assert "本报告仅用于青禾路堑工程模拟委托的验证。" in pages["08_template"].values()
