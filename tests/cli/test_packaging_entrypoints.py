"""Regression tests for package console-script metadata and build config."""

import tomllib
from pathlib import Path


def _load_pyproject() -> dict:
    root = Path(__file__).resolve().parents[2]
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def test_agac_lsp_entrypoint_points_to_tooling_server() -> None:
    config = _load_pyproject()
    scripts = config["project"]["scripts"]
    assert scripts["agac-lsp"] == "agent_actions.tooling.lsp.server:main"


def test_docs_site_exists_in_package() -> None:
    """The static docs site must ship inside the wheel (used by ``agac docs serve``)."""
    root = Path(__file__).resolve().parents[2]
    docs_site = root / "agent_actions" / "tooling" / "docs" / "docs_site"
    assert docs_site.is_dir(), "docs_site directory missing from package tree"
    assert (docs_site / "index.html").exists(), "docs_site/index.html missing"


def test_hatch_build_ignores_vcs() -> None:
    """ignore-vcs must be true so .gitignore cannot silently exclude package modules.

    Regression: .gitignore `batch/` matched agent_actions/llm/batch/ at any depth,
    causing hatchling to silently drop it from wheels and sdists.
    """
    config = _load_pyproject()
    assert config["tool"]["hatch"]["build"]["ignore-vcs"] is True


def test_batch_module_importable() -> None:
    """Regression: agent_actions.llm.batch must ship in the package."""
    import agent_actions.llm.batch  # noqa: F401
    import agent_actions.llm.batch.batch_cli  # noqa: F401
