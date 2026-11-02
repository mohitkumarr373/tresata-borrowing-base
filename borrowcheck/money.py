"""Exact boundary parsing. All internal monetary amounts are integer cents."""

import re

MONEY = re.compile(r"(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,2})?\Z")


def cents(value: str) -> int:
    if not isinstance(value, str) or not MONEY.fullmatch(value):
        raise ValueError("Money must be a non-negative decimal string with at most two decimals")
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0") or "0")


def money(value: int) -> str:
    if type(value) is not int:
        raise TypeError("Expected integer cents")
    sign = "-" if value < 0 else ""
    value = abs(value)
    return f"{sign}{value // 100}.{value % 100:02d}"


def floor_rate(value: int, basis_points: int) -> int:
    if type(value) is not int or value < 0 or type(basis_points) is not int:
        raise ValueError("Expected non-negative cents and integer basis points")
    if not 0 <= basis_points <= 10000:
        raise ValueError("Rate outside [0, 10000] basis points")
    return value * basis_points // 10000
