import pytest

from report_agent.calculations import sum_products
from report_agent.errors import ActionRejected


def test_decimal_products_and_total():
    result = sum_products([["50", "0.03"], ["100", "0.06"], ["-0.1"], ["0.2"]])
    assert result["products"] == ["1.50", "6.00", "-0.1", "0.2"]
    assert result["total"] == "7.60"
    assert result["rounded"] is False


@pytest.mark.parametrize("terms", [[], [[]], [["nan"]], [["Infinity"]], [["1e999999"]],
                                  [["__import__('os')"]], [["1/0"]], [[1.0]]])
def test_invalid_or_executable_input_rejected(terms):
    with pytest.raises(ActionRejected):
        sum_products(terms)
