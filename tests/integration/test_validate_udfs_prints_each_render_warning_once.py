"""`agac validate-udfs` prints each render warning of the workflow once."""

from __future__ import annotations

from tests._support.agac_cli import run_agac
from tests.integration.test_run_warns_on_a_bare_inline_array import _message, _project


def test_validate_udfs_prints_each_bare_array_warning_once(tmp_path):
    project = _project(tmp_path)

    result = run_agac(project, "validate-udfs", "-a", "w", "-u", "tools")
    output = result.stdout + result.stderr
    flat = " ".join(output.split())

    assert result.returncode == 0, output
    for field in ("candidates", "picks"):
        assert _message(field) in flat, output
        assert flat.count(_message(field)) == 1, output
    assert _message("tags") not in flat, output
