"""PromptLoader finds the prompt files in a project's prompt store."""


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
