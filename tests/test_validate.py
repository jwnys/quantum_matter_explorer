"""The validate tool must check whole files, in both languages.

The Julia path once parsed only the first expression, so a syntax error on any
later line slipped through. These tests pin the whole-file contract. The Julia
cases need a julia binary (QME_JULIA_EXE or `julia` on PATH) and are skipped
when none is available, so the suite still runs on machines without Julia.
"""
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qme.tools.helpers import validate

_validate = validate.func


def _julia_available() -> bool:
    exe = os.environ.get("QME_JULIA_EXE", "julia")
    return shutil.which(exe) is not None or Path(exe).is_file()


def test_python_valid_passes():
    assert "OK" in _validate("def f(x):\n    return x * x\n", language="python")


def test_python_syntax_error_fails():
    out = _validate("def f(x: return\n", language="python")
    assert "OK" not in out and "SyntaxError" in out


needs_julia = pytest.mark.skipif(not _julia_available(), reason="no julia binary available")


@needs_julia
def test_julia_valid_single_expression():
    assert "OK" in _validate("f(x) = x^2", language="julia")


@needs_julia
def test_julia_valid_multi_statement():
    assert "OK" in _validate("a = 1\nb = 2\nf(x) = x + a + b\n", language="julia")


@needs_julia
def test_julia_incomplete_expression_fails():
    assert "OK" not in _validate("f(x) = (x^2", language="julia")


@needs_julia
def test_julia_error_after_first_statement_fails():
    # The old first-expression-only parse passed this; the whole-file parse must not.
    assert "OK" not in _validate("a = 1\nf(x) = ((x\nb = 2\n", language="julia")


if __name__ == "__main__":
    test_python_valid_passes()
    test_python_syntax_error_fails()
    if _julia_available():
        test_julia_valid_single_expression()
        test_julia_valid_multi_statement()
        test_julia_incomplete_expression_fails()
        test_julia_error_after_first_statement_fails()
    print("validate contract checks passed")
