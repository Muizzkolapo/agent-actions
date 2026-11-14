"""`PromptLoader.record_loads` lists the prompt files `load_prompt` reads in its block, once."""

from pathlib import Path

import pytest

from agent_actions.prompt import handler
from agent_actions.prompt.handler import PromptLoader


@pytest.fixture
def project(tmp_path: Path) -> Path:
    store = tmp_path / "prompt_store"
    (store / "sub").mkdir(parents=True)
    (store / "outer.md").write_text(
        '{prompt Main}\n{{ load_prompt("inner.Header") }}\nBody.\n{end_prompt}\n'
        "{prompt Other}\nOther.\n{end_prompt}\n"
    )
    (store / "sub" / "inner.md").write_text("{prompt Header}\nHeader.\n{end_prompt}\n")
    (store / "unused.md").write_text("{prompt Unused}\nUnused.\n{end_prompt}\n")
    return tmp_path


def test_a_load_outside_a_block_records_nothing(project):
    assert PromptLoader.load_prompt("outer.Other", project_root=project) == "Other."
    assert handler._load_record.get() is None


def test_a_block_records_each_file_read_once_with_nested_loads(project):
    with PromptLoader.record_loads() as files:
        text = PromptLoader.load_prompt_expanded("outer.Main", project_root=project)
        PromptLoader.load_prompt("outer.Other", project_root=project)

    assert text == "Header.\nBody."
    assert files == [project / "prompt_store/outer.md", project / "prompt_store/sub/inner.md"]


def test_a_load_after_the_block_exits_is_not_recorded(project):
    with PromptLoader.record_loads() as files:
        PromptLoader.load_prompt("outer.Other", project_root=project)
    PromptLoader.load_prompt("unused.Unused", project_root=project)

    assert files == [project / "prompt_store/outer.md"]
    assert handler._load_record.get() is None


def test_a_second_block_holds_only_its_own_files(project):
    with PromptLoader.record_loads() as first:
        PromptLoader.load_prompt("outer.Other", project_root=project)
    with PromptLoader.record_loads() as second:
        PromptLoader.load_prompt("unused.Unused", project_root=project)

    assert first == [project / "prompt_store/outer.md"]
    assert second == [project / "prompt_store/unused.md"]
