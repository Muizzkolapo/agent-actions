"""A workflow whose prompts hold `{% cache_point %}` loads, runs and stores the answers of the same
workflow without the tag."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.cli.exit_codes import EXIT_PAUSED
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

PAGES = [
    {"page_id": "p1", "page_content": "alpha text"},
    {"page_id": "p2", "page_content": "beta text"},
]
_BATCH_NOW = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
"""

_WORKFLOW = """\
name: w
description: "Prompts with a cache point"
version: "0.1.0"
defaults:
  json_mode: false
  run_mode: RUN_MODE
  model_vendor: VENDOR
  model_name: mock
  api_key: OLLAMA_API_KEY
  enable_prompt_caching: true
  prompt_debug: true
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: summarize
    intent: "Summarize the page"
    prompt: |
      ## PAGE
      {{ source.page_content }}
      TAG_LINE## ID
      {{ source.page_id }}
    context_scope: { observe: [source.page_id, source.page_content] }
  - name: label_page
    intent: "Label the page"
    prompt: $w.Label
    context_scope: { observe: [source.page_id, source.page_content] }
"""

_STORE = """\
{prompt Label}
Label the page.
{{ source.page_content }}
TAG_LINEIts id: {{ source.page_id }}
{end_prompt}
"""
_TAG_LINE = "{% cache_point %}\n"


def _project(tmp_path: Path, *, tag: str = _TAG_LINE, run_mode: str = "online") -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(
        _WORKFLOW.replace("RUN_MODE", run_mode)
        .replace("VENDOR", "agac-provider")
        .replace("TAG_LINE", tag + "      " if tag else "")
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / "w.md").write_text(_STORE.replace("TAG_LINE", tag))
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run_to_the_end(root: Path, env: dict[str, str] | None = None) -> str:
    printed = ""
    for args in (("--fresh",), (), (), (), (), ()):
        result = run_agac(root, "run", "-a", "w", *args, env=env)
        output = result.stdout + result.stderr
        printed += output
        if result.returncode == EXIT_PAUSED:
            assert "run again" in output, output
            continue
        assert result.returncode == 0, output
        assert "run again" not in output, output
        return printed
    raise AssertionError(printed)


def _prompts_printed(output: str) -> list[str]:
    """The prompts `prompt_debug` printed, in order."""
    opening = "DEBUG MODE: Prompt being sent to the agent"
    return [
        chunk.split("[Context Data Preview]")[0].split("=" * 50)[1].strip()
        for chunk in output.split(opening)[1:]
    ]


def _stored_records(root: Path) -> int:
    backend = get_storage_backend(str(root / "agent_workflow" / "w"), "w")
    backend.initialize()
    try:
        return sum(
            len(backend.read_target("label_page", path))
            for path in backend.list_target_files("label_page")
        )
    finally:
        backend.close()


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_the_workflow_runs_and_sends_the_prompts_it_sends_without_the_tag(tmp_path, run_mode):
    env = _BATCH_NOW if run_mode == "batch" else None
    marked = _run_to_the_end(_project(tmp_path / "marked", run_mode=run_mode), env)
    plain = _run_to_the_end(_project(tmp_path / "plain", tag="", run_mode=run_mode), env)

    assert _stored_records(tmp_path / "marked" / "project") == len(PAGES)
    prompts = _prompts_printed(marked)
    assert len(prompts) == 2 * len(PAGES)
    assert sorted(prompts) == sorted(_prompts_printed(plain))
    assert "## PAGE\nalpha text\n## ID\np1" in prompts
    assert "cache_point" not in "".join(prompts)


def test_the_load_says_the_vendor_is_sent_no_cache_point(tmp_path):
    root = _project(tmp_path)

    result = run_agac(root, "inspect", "-a", "w")
    output = " ".join((result.stdout + result.stderr).split())

    assert result.returncode == 0, output
    assert "its prompt holds a cache point" in output, output


def test_the_load_refuses_a_fourth_cache_point_on_an_anthropic_action(tmp_path):
    root = _project(tmp_path)
    config = root / "agent_workflow" / "w" / "agent_config" / "w.yml"
    points = "".join(f"      part {n}\n      {{% cache_point %}}\n" for n in range(3))
    config.write_text(
        config.read_text()
        .replace("agac-provider", "anthropic")
        .replace("      ## PAGE\n", points + "      ## PAGE\n")
    )

    result = run_agac(root, "run", "-a", "w", "--fresh", env={"OLLAMA_API_KEY": "not-used"})
    output = " ".join((result.stdout + result.stderr).split())

    assert result.returncode != 0, output
    assert "cache points" in output, output
    assert "at most 3" in output, output
