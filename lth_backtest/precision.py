from __future__ import annotations

from dataclasses import asdict, is_dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any


ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
MONEY_QUANTUM = Decimal("0.0001")
PRICE_QUANTUM = Decimal("0.000001")
T_QUANTUM = Decimal("0.0000000001")
RATE_QUANTUM = Decimal("0.00000001")


def decimal(value: Decimal | str | int | float | None, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize(value: Decimal, quantum: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 34
        return value.quantize(quantum, rounding=ROUND_HALF_UP)


def round_order_price(value: Decimal) -> Decimal:
    return quantize(value, CENT)


def round_market_price(value: Decimal) -> Decimal:
    return quantize(value, PRICE_QUANTUM)


def round_money(value: Decimal) -> Decimal:
    return quantize(value, MONEY_QUANTUM)


def round_t(value: Decimal) -> Decimal:
    return quantize(value, T_QUANTUM)


def round_rate(value: Decimal) -> Decimal:
    return quantize(value, RATE_QUANTUM)


def floor_int(value: Decimal) -> int:
    if not value.is_finite() or value <= ZERO:
        return 0
    return int(value // ONE)


def mean_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def to_primitive(value: Any) -> Any:
    """Convert result objects to JSON-safe primitives without float math in the engine."""
    if isinstance(value, Decimal):
        return float(value)
    if is_dataclass(value):
        return to_primitive(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_primitive(item) for item in value]
    return value
