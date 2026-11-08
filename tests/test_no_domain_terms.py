from pathlib import Path
import re


def test_assertion_contract_has_no_embedded_domain_rules():
    package = Path(__file__).parents[1] / "src/report_agent/assertions"
    domain_term = re.compile(r"\b(?:slope|borehole|rainfall|rockfall|indicator|fake0[34]|X[1-5][1-3])\b|边坡|钻孔", re.I)
    for path in package.rglob("*"):
        if path.suffix in {".py", ".json", ".sql"}:
            assert not domain_term.search(path.read_text()), path
