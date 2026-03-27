"""Tests for scanner.scan_tool_functions() tool_paths parameter."""

from pathlib import Path

from agent_actions.tooling.docs.scanner import scan_tool_functions


def _write_udf_file(tool_dir: Path) -> None:
    """Write a minimal Python file with a @udf_tool decorated function."""
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "my_tool.py").write_text(
        "from agent_actions.udf import udf_tool\n\n"
        "@udf_tool\n"
        "def hello(text: str) -> str:\n"
        '    """Say hello."""\n'
        "    return text\n"
    )


def test_default_scans_tools_dir(tmp_path: Path):
    """When tool_paths is None, scan_tool_functions defaults to 'tools/'."""
    _write_udf_file(tmp_path / "tools")
    result = scan_tool_functions(tmp_path)
    assert "hello" in result


def test_custom_tool_path(tmp_path: Path):
    """Respects a custom tool_paths list."""
    _write_udf_file(tmp_path / "my_udfs")
    result = scan_tool_functions(tmp_path, tool_paths=["my_udfs"])
    assert "hello" in result


def test_custom_path_ignores_default(tmp_path: Path):
    """Custom tool_paths does NOT scan the default 'tools/' dir."""
    _write_udf_file(tmp_path / "tools")
    result = scan_tool_functions(tmp_path, tool_paths=["other"])
    assert "hello" not in result


def test_empty_list_scans_nothing(tmp_path: Path):
    """An explicit empty list means scan no directories."""
    _write_udf_file(tmp_path / "tools")
    result = scan_tool_functions(tmp_path, tool_paths=[])
    assert result == {}


def test_multiple_tool_paths(tmp_path: Path):
    """Multiple paths are all scanned."""
    _write_udf_file(tmp_path / "tools_a")
    (tmp_path / "tools_b").mkdir()
    (tmp_path / "tools_b" / "other.py").write_text(
        'def greet(name: str) -> str:\n    """Greet."""\n    return name\n'
    )
    result = scan_tool_functions(tmp_path, tool_paths=["tools_a", "tools_b"])
    assert "hello" in result
    assert "greet" in result


def test_nonexistent_path_skipped(tmp_path: Path):
    """Non-existent paths are silently skipped."""
    result = scan_tool_functions(tmp_path, tool_paths=["does_not_exist"])
    assert result == {}
