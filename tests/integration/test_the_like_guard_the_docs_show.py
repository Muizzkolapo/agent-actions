"""The `LIKE` guard the guards page shows keeps the names it describes (1364).

The page's `LIKE` row is taken as written and run by `agac run`, online and batch: a
pattern written with a glob `*` is read literally and rejects every record it was meant
to keep, and the run exits 0.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest
import yaml

from tests._support.agac_cli import REPO, run_agac

PAGE = REPO / "docs.agent-actions" / "docs" / "reference" / "execution" / "guards.md"
WORKFLOW = "like_guard"
NAMES = ["prod_east", "PROD_WEST", "staging", "dev_prod"]

TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool()
def lookup(data: dict[str, Any]) -> dict[str, Any]:
    return {"name": data["source"]["name"]}
"""


def _shown_condition() -> str:
    (row,) = re.findall(r"^\| `LIKE` \| `(.*)` \|$", PAGE.read_text(encoding="utf-8"), re.M)
    return row


def _config(run_mode: str, condition: str) -> str:
    return yaml.safe_dump(
        {
            "name": WORKFLOW,
            "description": "The LIKE guard the docs show",
            "version": "1.0.0",
            "defaults": {
                "json_mode": True,
                "granularity": "Record",
                "run_mode": run_mode,
                "model_vendor": "agac-provider",
                "model_name": "gpt-4o-mini",
                "api_key": "OPENAI_API_KEY",
                "data_source": {"type": "local", "folder": "./staging", "file_type": ["json"]},
            },
            "actions": [
                {
                    "name": "lookup",
                    "kind": "tool",
                    "impl": "lookup",
                    "intent": "Look up",
                    "schema": {"name": "string"},
                    "context_scope": {"observe": ["source.name"]},
                },
                {
                    "name": "publish",
                    "dependencies": ["lookup"],
                    "intent": "Publish",
                    "prompt": "publish {{ lookup.name }}",
                    "schema": {"result": "string"},
                    "context_scope": {"observe": ["lookup.name"]},
                    "guard": {"condition": condition, "on_false": "filter"},
                },
            ],
        },
        sort_keys=False,
    )


def _sent(run_mode: str, condition: str, base: Path) -> list[str]:
    root = base / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\ntool_path: tools\n"
    )
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_config(run_mode, condition))
    (workflow / "agent_io" / "staging" / "names.json").write_text(
        json.dumps([{"name": name} for name in NAMES])
    )
    (root / "tools" / "lookup.py").write_text(TOOL)
    args = ["run", "-a", WORKFLOW, "--fresh"]
    env = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", "OPENAI_API_KEY": "sk-not-used"}
    for _ in range(6):
        result = run_agac(root, *args, env=env)
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        if "run again" not in output:
            break
        args = ["run", "-a", WORKFLOW]
    (db,) = (workflow / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select compiled_prompt from prompt_trace where action_name = 'publish'"
        ).fetchall()
    finally:
        con.close()
    return sorted(" ".join(prompt.split()).removeprefix("publish ") for (prompt,) in rows)


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_the_pattern_the_page_shows_keeps_the_names_it_starts_with(tmp_path, run_mode):
    kept = _sent(run_mode, _shown_condition(), tmp_path)

    assert kept == ["PROD_WEST", "prod_east"]


def test_a_glob_star_is_read_literally(tmp_path):
    """The form the page used to show: `*` matches only a literal `*`."""
    assert _sent("online", 'lookup.name LIKE "prod_*"', tmp_path) == []
