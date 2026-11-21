"""A prompt loads from the project's prompt_store or a workflow's, and from nowhere else."""

from pathlib import Path

import pytest

from agent_actions.prompt.handler import PromptLoader


def _prompt(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Prompts\n\n{{prompt Main}}\n{body}\n{{end_prompt}}\n", encoding="utf-8")
    return path


def test_a_copy_outside_the_prompt_folders_does_not_shadow_the_live_prompt(tmp_path):
    _prompt(tmp_path / "archive" / "prompt_store" / "x.md", "archived")
    _prompt(tmp_path / "archive" / "agent_workflow" / "old" / "prompt_store" / "x.md", "archived")
    _prompt(tmp_path / "prompt_store" / "x.md", "live")

    assert PromptLoader.load_prompt("x.Main", tmp_path) == "live"


def test_a_workflow_prompt_loads(tmp_path):
    _prompt(tmp_path / "agent_workflow" / "wf" / "prompt_store" / "sub" / "x.md", "workflow")

    assert PromptLoader.load_prompt("x.Main", tmp_path) == "workflow"


def test_a_name_in_both_prompt_folders_is_refused_naming_every_copy(tmp_path):
    shared = _prompt(tmp_path / "prompt_store" / "x.md", "shared")
    own = _prompt(tmp_path / "agent_workflow" / "wf" / "prompt_store" / "x.md", "own")
    nested = _prompt(tmp_path / "prompt_store" / "old" / "x.md", "nested")

    with pytest.raises(ValueError) as excinfo:
        PromptLoader.load_prompt("x.Main", tmp_path)

    message = str(excinfo.value)
    assert {str(shared), str(own), str(nested)} <= set(message.split()), message

    own.unlink()
    nested.unlink()
    assert PromptLoader.load_prompt("x.Main", tmp_path) == "shared"


def test_a_prompt_only_in_an_undocumented_folder_does_not_load(tmp_path):
    stray = _prompt(tmp_path / "archive" / "prompt_store" / "x.md", "archived")

    with pytest.raises(ValueError) as excinfo:
        PromptLoader.load_prompt("x.Main", tmp_path)

    message = str(excinfo.value)
    assert str(tmp_path / "prompt_store") in message
    assert str(tmp_path / "agent_workflow" / "*" / "prompt_store") in message
    assert "anywhere in your project tree" not in message
    assert str(stray) not in message

    _prompt(tmp_path / "prompt_store" / "x.md", "live")
    assert PromptLoader.load_prompt("x.Main", tmp_path) == "live"


def test_discovery_covers_both_prompt_folders_and_nothing_else(tmp_path):
    shared = _prompt(tmp_path / "prompt_store" / "a.md", "a")
    own = _prompt(tmp_path / "agent_workflow" / "wf" / "prompt_store" / "deep" / "b.md", "b")
    _prompt(tmp_path / "archive" / "prompt_store" / "c.md", "c")
    _prompt(tmp_path / "agent_workflow" / "wf" / "notes" / "d.md", "d")

    assert PromptLoader.discover_prompt_files(tmp_path) == [shared, own]
