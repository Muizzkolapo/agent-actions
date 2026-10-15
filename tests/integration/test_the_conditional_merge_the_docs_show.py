"""The Conditional Merge the data-lineage page shows answers each record from its own branch (1378).

The page's two guarded branches and its merge template are taken as written and run by
`agac run`, online and batch: one record per branch, and `combine` is sent each record
with the result of the branch that kept it. Only what the page leaves out is added: the
classifying tool, the branches' prompts and schemas, and what each action observes.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest
import yaml

from tests._support.agac_cli import REPO, run_agac

PAGE = REPO / "docs.agent-actions" / "docs" / "reference" / "data-io" / "data-lineage.md"
WORKFLOW = "conditional_merge"
_FENCE = re.compile(r"^```yaml\n(.*?)^```", re.S | re.M)

TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool()
def classify(data: dict[str, Any]) -> dict[str, Any]:
    kind = data["source"]["page_content"]
    return {"complexity": "low" if kind == "urgent" else "high"}
"""

_SECTION = re.compile(r"^## Conditional Merge\n(.*?)^## ", re.S | re.M)


def _shown() -> dict[str, dict]:
    """The actions of the page's Conditional Merge section, by name, as written."""
    (section,) = _SECTION.findall(PAGE.read_text(encoding="utf-8"))
    actions: dict[str, dict] = {}
    for block in _FENCE.findall(section):
        loaded = yaml.safe_load(block)
        for action in loaded["actions"] if isinstance(loaded, dict) else loaded:
            actions[action["name"]] = action
    return actions


def _config(run_mode: str, on_false: str | None = None) -> str:
    shown = _shown()
    if on_false:
        for name in ("fast_path", "slow_path"):
            shown[name]["guard"]["on_false"] = on_false
    classify = {
        **shown["classify"],
        "kind": "tool",
        "impl": "classify",
        "intent": "Classify",
        "schema": {"complexity": "string"},
        "context_scope": {"observe": ["source.page_content"]},
    }
    branches = [
        {
            **shown[name],
            "intent": name,
            "prompt": f"{name} {{{{ classify.complexity }}}}",
            "schema": {"result": "string"},
            "context_scope": {"observe": ["classify.complexity"]},
        }
        for name in ("fast_path", "slow_path")
    ]
    combine = {
        **shown["combine"],
        "intent": "Combine",
        "schema": {"merged": "string"},
        "context_scope": {"observe": ["fast_path.result", "slow_path.result"]},
    }
    return yaml.safe_dump(
        {
            "name": WORKFLOW,
            "description": "The Conditional Merge the docs show",
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
            "actions": [classify, *branches, combine],
        },
        sort_keys=False,
    )


class Project:
    def __init__(self, base: Path, run_mode: str, config: str | None = None) -> None:
        self.root = base / "project"
        workflow = self.root / "agent_workflow" / WORKFLOW
        (workflow / "agent_config").mkdir(parents=True)
        (workflow / "agent_io" / "staging").mkdir(parents=True)
        (self.root / "tools").mkdir()
        (self.root / "agent_actions.yml").write_text(
            "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\ntool_path: tools\n"
        )
        (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(config or _config(run_mode))
        (workflow / "agent_io" / "staging" / "pages.json").write_text(
            json.dumps(
                [
                    {"page_id": "p0", "page_content": "urgent"},
                    {"page_id": "p1", "page_content": "routine"},
                ]
            )
        )
        (self.root / "tools" / "classify.py").write_text(TOOL)

    def run_to_the_end(self) -> str:
        args = ["run", "-a", WORKFLOW, "--fresh"]
        env = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", "OPENAI_API_KEY": "sk-not-used"}
        transcript = ""
        for _ in range(6):
            result = run_agac(self.root, *args, env=env)
            output = result.stdout + result.stderr
            transcript += output
            assert result.returncode == 0, output
            if "run again" not in output:
                return transcript
            args = ["run", "-a", WORKFLOW]
        pytest.fail(f"the workflow never stopped asking to be run again:\n{transcript}")

    def sent(self, action: str) -> list[str]:
        (db,) = (self.root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "select compiled_prompt from prompt_trace where action_name = ?", (action,)
            ).fetchall()
        finally:
            con.close()
        return sorted(" ".join(prompt.split()) for (prompt,) in rows)


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_combine_answers_each_record_with_the_result_of_the_branch_that_kept_it(tmp_path, run_mode):
    project = Project(tmp_path, run_mode)

    transcript = project.run_to_the_end()

    sent = project.sent("combine")
    assert len(sent) == 2, transcript
    assert sum("Fast result:" in p and "Slow result:" not in p for p in sent) == 1, sent
    assert sum("Slow result:" in p and "Fast result:" not in p for p in sent) == 1, sent
    assert "filtered by an upstream guard" not in transcript


def test_under_the_default_filter_combine_is_sent_nothing(tmp_path):
    """What the page's example did before it set `on_false`: each record is filtered by
    the branch it did not take, so the merge holds none."""
    project = Project(tmp_path, "online", _config("online", on_false="filter"))

    transcript = project.run_to_the_end()

    assert project.sent("combine") == []
    assert "dropped 2 record(s) filtered by an upstream guard" in transcript
