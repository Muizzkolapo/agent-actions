"""Regression tests for package console-script metadata."""

import tomllib
from pathlib import Path


def _load_pyproject() -> dict:
    root = Path(__file__).resolve().parents[2]
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def test_agac_lsp_entrypoint_points_to_tooling_server() -> None:
    config = _load_pyproject()
    scripts = config["project"]["scripts"]
    assert scripts["agac-lsp"] == "agent_actions.tooling.lsp.server:main"


def test_docs_site_is_force_included_in_wheel() -> None:
    config = _load_pyproject()
    force_include = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert "agent_actions/tooling/docs/docs_site" in force_include
