"""Deterministic decimal arithmetic, without domain rules or code execution."""
from decimal import Decimal, DecimalException, Inexact, localcontext

from .errors import ActionRejected


def sum_products(terms: list[list[str]]) -> dict:
    """Multiply each row's factors and add the products; inputs stay explicit."""
    if not terms or len(terms) > 1000:
        raise ActionRejected("CALCULATION_REQUIRES_1_TO_1000_TERMS")
    try:
        with localcontext() as context:
            context.prec = 50
            context.Emax = 1000
            context.Emin = -1000
            products = []
            for factors in terms:
                if not factors or len(factors) > 20:
                    raise ActionRejected("CALCULATION_REQUIRES_1_TO_20_FACTORS")
                product = Decimal(1)
                for value in factors:
                    if not isinstance(value, str) or len(value) > 80:
                        raise ActionRejected("CALCULATION_REQUIRES_DECIMAL_STRINGS")
                    number = Decimal(value)
                    if not number.is_finite() or abs(number.adjusted()) > 100:
                        raise ActionRejected("CALCULATION_NUMBER_OUT_OF_RANGE")
                    product *= number
                products.append(product)
            total = sum(products, Decimal(0))
            if not total.is_finite():
                raise ActionRejected("CALCULATION_NUMBER_OUT_OF_RANGE")
            return {"terms": terms, "products": [str(p) for p in products],
                    "total": str(total), "precision": context.prec,
                    "rounded": context.flags.get(Inexact, False),
                    "limitation": "Arithmetic only. Input selection, units and applicable rules are not verified."}
    except (DecimalException, ValueError, TypeError):
        raise ActionRejected("INVALID_DECIMAL_CALCULATION") from None
