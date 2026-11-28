from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_actions.knowledge.api import INDEX_FOR_METHOD, ensure_indexes, retrieve
from agent_actions.knowledge.search import forget_warnings


@pytest.fixture(autouse=True)
def _fresh_warnings():
    forget_warnings()
    yield
    forget_warnings()


def make_project(root: Path, files: dict[str, str], knowledge: dict[str, Any]) -> Path:
    """A project with *files* and a ``knowledge:`` section in its agent_actions.yml."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "agent_actions.yml").write_text(
        yaml.safe_dump({"project_name": "kb", "knowledge": knowledge}), encoding="utf-8"
    )
    for relpath, text in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def find(root: Path, base: str, methods: dict[str, float], text: str, **limits: Any) -> dict:
    """``api.retrieve`` of *text* over the indexes *methods* read, built first."""
    digest = ensure_indexes(root, base, {INDEX_FOR_METHOD[m] for m in methods}, sandbox=False)
    settings: dict[str, Any] = {
        "top_k": 5,
        "candidates": 20,
        "max_context_tokens": None,
        "max_per_origin": None,
        "where": {},
        **limits,
    }
    return retrieve(root, base=base, digest=digest, methods=methods, query_text=text, **settings)
