"""Regression test: validate-udfs must exit non-zero on any validation
failure (FunctionNotFoundError, UDFLoadError, DuplicateFunctionError)."""

from __future__ import annotations

from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from agent_actions.errors import (
    DuplicateFunctionError,
    FunctionNotFoundError,
    UDFLoadError,
)
from agent_actions.validation.validate_udfs import (
    ValidateUDFsCommand,
    validate_udfs_cmd,
)


def _run_cli(monkeypatch, tmp_path: Path, validate_return: dict) -> click.testing.Result:
    """Invoke the Click command with validate() stubbed on the real class.

    Stubs only validate() so execute()'s formatter dispatch and exit-code
    behavior are exercised end-to-end. CliRunner translates
    click.exceptions.Exit into result.exit_code.
    """
    monkeypatch.setattr(ValidateUDFsCommand, "validate", lambda self: validate_return)
    return CliRunner().invoke(validate_udfs_cmd, ["-a", "wf", "-u", str(tmp_path)])


@pytest.mark.parametrize(
    ("error", "error_type"),
    [
        (
            FunctionNotFoundError(
                "Function 'nonexistent_fn' not found",
                context={"function_name": "nonexistent_fn", "available_functions": []},
            ),
            "not_found",
        ),
        (UDFLoadError(module="bad_module", file="bad.py", error="SyntaxError"), "load_error"),
        (
            DuplicateFunctionError(
                function_name="dup_func",
                existing_location="a",
                existing_file="a.py",
                new_location="b",
                new_file="b.py",
            ),
            "duplicate",
        ),
    ],
    ids=["not_found", "load_error", "duplicate"],
)
def test_validation_failure_exits_non_zero(monkeypatch, tmp_path, error, error_type):
    result = _run_cli(
        monkeypatch, tmp_path, {"valid": False, "error": error, "error_type": error_type}
    )
    assert result.exit_code == 1, result.output


def test_valid_result_exits_zero(monkeypatch, tmp_path):
    """Baseline — success must still exit 0 (guards against an unconditional exit-1 fix)."""
    result = _run_cli(
        monkeypatch,
        tmp_path,
        {
            "valid": True,
            "registry": {"fn": {}},
            "impl_refs": {"fn"},
            "guard_udf_refs": set(),
            "loop_params": set(),
            "action_names": set(),
        },
    )
    assert result.exit_code == 0, result.output
