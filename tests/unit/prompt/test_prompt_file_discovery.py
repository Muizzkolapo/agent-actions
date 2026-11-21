"""PromptLoader finds the prompt files in a project's prompt store."""

import pytest


# ---------------------------------------------------------------------------
# discover_prompt_files
# ---------------------------------------------------------------------------
class TestDiscoverPromptFiles:
    def test_finds_prompts_in_subdirectories(self, tmp_path):
        """Recursive rglob finds .md files in nested folders."""
        from agent_actions.prompt.handler import PromptLoader

        prompt_dir = tmp_path / "prompt_store" / "sub"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "nested.md").write_text("{prompt test}\ncontent\n{end_prompt}")
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")

        result = PromptLoader.discover_prompt_files(tmp_path)
        assert len(result) == 1
        assert result[0].name == "nested.md"

    def test_returns_empty_when_no_prompt_store(self, tmp_path):
        """Returns empty list when prompt_store/ doesn't exist."""
        from agent_actions.prompt.handler import PromptLoader

        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
        result = PromptLoader.discover_prompt_files(tmp_path)
        assert result == []

    def test_finds_flat_and_nested(self, tmp_path):
        """Finds both top-level and nested .md files."""
        from agent_actions.prompt.handler import PromptLoader

        ps = tmp_path / "prompt_store"
        ps.mkdir()
        (ps / "top.md").write_text("{prompt a}\ncontent\n{end_prompt}")
        sub = ps / "sub"
        sub.mkdir()
        (sub / "deep.md").write_text("{prompt b}\ncontent\n{end_prompt}")
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")

        result = PromptLoader.discover_prompt_files(tmp_path)
        names = [p.name for p in result]
        assert "top.md" in names
        assert "deep.md" in names

    def test_a_workflow_folder_linked_to_the_shared_one_lists_each_file_once(self, tmp_path):
        from agent_actions.prompt.handler import PromptLoader

        shared = tmp_path / "prompt_store"
        shared.mkdir()
        (shared / "x.md").write_text("{prompt Main}\nshared\n{end_prompt}")
        linked = tmp_path / "agent_workflow" / "wf"
        linked.mkdir(parents=True)
        (linked / "prompt_store").symlink_to(shared, target_is_directory=True)

        assert PromptLoader.discover_prompt_files(tmp_path) == [shared / "x.md"]
        assert PromptLoader.load_prompt("x.Main", tmp_path) == "shared"

        other = tmp_path / "agent_workflow" / "other" / "prompt_store"
        other.mkdir(parents=True)
        (other / "x.md").write_text("{prompt Main}\ncopy\n{end_prompt}")
        with pytest.raises(ValueError, match="is in 2 places"):
            PromptLoader.load_prompt("x.Main", tmp_path)


def _prompt(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{{prompt Main}}\n{body}\n{{end_prompt}}\n", encoding="utf-8")
    return path


class TestALinkUnderAnotherNameIsItsOwnPromptFile:
    def test_an_alias_in_the_same_folder_loads_by_both_names(self, tmp_path):
        from agent_actions.prompt.handler import PromptLoader

        real = _prompt(tmp_path / "prompt_store" / "b.md", "real")
        (tmp_path / "prompt_store" / "a.md").symlink_to(real)

        assert PromptLoader.load_prompt("b.Main", tmp_path) == "real"
        assert PromptLoader.load_prompt("a.Main", tmp_path) == "real"

    def test_an_alias_in_a_workflow_folder_loads_by_both_names(self, tmp_path):
        from agent_actions.prompt.handler import PromptLoader

        real = _prompt(tmp_path / "prompt_store" / "zz.md", "real")
        alias = tmp_path / "agent_workflow" / "wf" / "prompt_store" / "aa.md"
        alias.parent.mkdir(parents=True)
        alias.symlink_to(real)

        assert PromptLoader.discover_prompt_files(tmp_path) == [real, alias]
        assert PromptLoader.load_prompt("zz.Main", tmp_path) == "real"
        assert PromptLoader.load_prompt("aa.Main", tmp_path) == "real"


class TestLoadPromptSearchesOnlyThePromptFolders:
    @pytest.mark.parametrize(
        "stray", ["x.md", "docs/x.md", "agent_workflow/wf/notes/x.md"], ids=str
    )
    def test_a_copy_outside_the_prompt_folders_is_not_found(self, tmp_path, stray):
        from agent_actions.prompt.handler import PromptLoader

        _prompt(tmp_path / stray, "stray")
        (tmp_path / "agent_workflow" / "wf").mkdir(parents=True, exist_ok=True)

        with pytest.raises(ValueError, match="Prompt file 'x.md' not found"):
            PromptLoader.load_prompt("x.Main", tmp_path)

        _prompt(tmp_path / "prompt_store" / "x.md", "live")
        assert PromptLoader.load_prompt("x.Main", tmp_path) == "live"

    def test_two_copies_in_the_shared_and_a_workflow_folder_are_refused_naming_both(self, tmp_path):
        from agent_actions.prompt.handler import PromptLoader

        shared = _prompt(tmp_path / "prompt_store" / "x.md", "shared")
        own = _prompt(tmp_path / "agent_workflow" / "wf" / "prompt_store" / "x.md", "own")

        with pytest.raises(ValueError) as excinfo:
            PromptLoader.load_prompt("x.Main", tmp_path)
        message = str(excinfo.value)
        assert "is in 2 places" in message
        assert {str(shared), str(own)} <= set(message.split()), message

        own.unlink()
        assert PromptLoader.load_prompt("x.Main", tmp_path) == "shared"
