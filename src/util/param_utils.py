"""
src/util/param_utils.py

Helpers that keep Hamiltonian parameters concrete and numeric.

A plan can emit a scanned coupling as a placeholder string (e.g.
``{"J2": "variable"}``). If that string ever reaches a Julia script, the
``get(params, "J2", 0.0)`` idiom silently collapses it to ``0.0``, so a "scan"
run quietly becomes J2=0. These helpers let callers detect placeholders before
any script runs:

- ``is_numeric(v)``: True if ``v`` is (or parses as) a real number.
- ``_PLACEHOLDER_TOKENS``: the strings a plan might use to mean "this value is
  scanned" rather than a concrete number.
"""

from __future__ import annotations

from typing import Any

# Tokens a plan might use to mean "this value is scanned".
_PLACEHOLDER_TOKENS = {
    "", "variable", "var", "scan", "scanned", "range", "varies", "tbd", "alpha",
}


def is_numeric(v: Any) -> bool:
    """True if ``v`` is a real number or a string that parses as one.

    ``bool`` is intentionally excluded (it is an ``int`` subclass but is never
    a meaningful coupling value)."""
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v.strip())
            return True
        except (ValueError, AttributeError):
            return False
    return False
