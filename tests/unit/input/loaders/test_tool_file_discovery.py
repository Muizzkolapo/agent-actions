"""discover_tool_files finds a project's tool files."""


# ---------------------------------------------------------------------------
# discover_tool_files
# ---------------------------------------------------------------------------
class TestDiscoverToolFiles:
    def test_nonexistent_dir_returns_empty(self, tmp_path):
        """Non-existent directory returns empty list."""
        from agent_actions.input.loaders.udf import discover_tool_files

        result = discover_tool_files(tmp_path / "nonexistent")
        assert result == []

    def test_file_not_dir_returns_empty(self, tmp_path):
        """Path that is a file (not dir) returns empty list."""
        from agent_actions.input.loaders.udf import discover_tool_files

        f = tmp_path / "not_a_dir.py"
        f.write_text("x = 1")
        result = discover_tool_files(f)
        assert result == []

    def test_filters_private_and_test_files(self, tmp_path):
        """Files starting with _ or test_ are excluded."""
        from agent_actions.input.loaders.udf import discover_tool_files

        tools = tmp_path / "tools"
        tools.mkdir()
        (tools / "good.py").write_text("x = 1")
        (tools / "_private.py").write_text("x = 1")
        (tools / "test_something.py").write_text("x = 1")
        (tools / "__init__.py").write_text("")

        result = discover_tool_files(tools)
        names = [p.name for p in result]
        assert "good.py" in names
        assert "_private.py" not in names
        assert "test_something.py" not in names
        assert "__init__.py" not in names

    def test_finds_files_recursively(self, tmp_path):
        """Files in subdirectories are found."""
        from agent_actions.input.loaders.udf import discover_tool_files

        tools = tmp_path / "tools"
        sub = tools / "sub"
        sub.mkdir(parents=True)
        (sub / "deep.py").write_text("x = 1")

        result = discover_tool_files(tools)
        assert len(result) == 1
        assert result[0].name == "deep.py"
