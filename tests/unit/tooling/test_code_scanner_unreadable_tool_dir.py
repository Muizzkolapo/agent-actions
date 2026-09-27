"""A tool directory the scan cannot list is reported, and costs only its own tools.

``Path.rglob`` drops the subtree beneath a directory it cannot open and raises
nothing, so the tools under it were simply absent from the catalog. This catalog
feeds schema inference and the docs rather than the runtime registry, so the cost
of silence is a tool whose schema is unknowably missing rather than a failed run.
"""

import ast
import logging
import os
from pathlib import Path

import pytest

from agent_actions.tooling.code_scanner import scan_tool_functions

TOOL = '''from agent_actions import udf_tool


@udf_tool
def {name}(data: dict) -> dict:
    """{doc}"""
    return data
'''

pytestmark = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root reads a mode-000 directory, so the loss cannot be staged",
)


@pytest.fixture
def locked_dirs():
    """chmod 000 for the body of a test, restored so tmp_path teardown can run."""
    made: list = []

    def _lock(path):
        path.chmod(0o000)
        made.append(path)
        return path

    yield _lock
    for path in made:
        path.chmod(0o755)


def _project(tmp_path):
    """Two tool directories, so losing one can be told from losing the scan."""
    tools = tmp_path / "tools"
    for workflow, name in (("wf_open", "open_tool"), ("wf_shut", "shut_tool")):
        directory = tools / workflow
        directory.mkdir(parents=True)
        (directory / f"{name}.py").write_text(TOOL.format(name=name, doc=name))
    return tmp_path


class TestADirectoryTheScanCannotList:
    def test_it_is_reported(self, tmp_path, locked_dirs, caplog):
        root = _project(tmp_path)
        locked_dirs(root / "tools" / "wf_shut")

        with caplog.at_level(logging.WARNING):
            scan_tool_functions(root)

        assert any("Cannot list tool directory" in r.message for r in caplog.records)

    def test_only_its_own_tools_are_lost(self, tmp_path, locked_dirs):
        """The scan carries on: one unreadable directory must not cost the catalog
        the tools it could read, which is what the whole-directory ``continue`` the
        old handler would have done — had it ever been able to fire."""
        root = _project(tmp_path)
        locked_dirs(root / "tools" / "wf_shut")

        found = scan_tool_functions(root)

        assert sorted(found) == ["open_tool"]

    def test_a_readable_tree_reports_nothing(self, tmp_path, caplog):
        root = _project(tmp_path)

        with caplog.at_level(logging.WARNING):
            found = scan_tool_functions(root)

        assert sorted(found) == ["open_tool", "shut_tool"]
        assert not [r for r in caplog.records if "Cannot list" in r.message]


class TestTheCatalogIsKeyedOnFunctionName:
    """Two files defining one name collide in the returned dict, so which file wins
    was decided by filesystem order. Sorting makes the winner the same every run."""

    def test_the_last_path_in_sorted_order_wins(self, tmp_path):
        tools = tmp_path / "tools"
        for workflow in ("a_first", "z_last"):
            directory = tools / workflow
            directory.mkdir(parents=True)
            (directory / "dup.py").write_text(TOOL.format(name="dup", doc=workflow))

        found = scan_tool_functions(tmp_path)

        assert found["dup"]["file_path"] == "tools/z_last/dup.py"

    def test_repeated_scans_agree(self, tmp_path):
        tools = tmp_path / "tools"
        for workflow in ("a_first", "z_last"):
            directory = tools / workflow
            directory.mkdir(parents=True)
            (directory / "dup.py").write_text(TOOL.format(name="dup", doc=workflow))

        first, second = scan_tool_functions(tmp_path), scan_tool_functions(tmp_path)

        assert first["dup"]["file_path"] == second["dup"]["file_path"]


class TestTheScannerStaysImportLight:
    """`code_scanner` sits at the top of `tooling` to break an import cycle (its own
    docstring says so), so what it imports at module level has to stay cheap.
    `file_handler` is now one of those imports."""

    def test_file_handler_imports_nothing_from_agent_actions_at_module_level(self):
        import agent_actions.utils.file_handler as module

        tree = ast.parse(Path(module.__file__).read_text())
        top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        names = [n.module or "" for n in top_level if isinstance(n, ast.ImportFrom)] + [
            a.name for n in top_level if isinstance(n, ast.Import) for a in n.names
        ]

        assert [n for n in names if n.startswith("agent_actions")] == []
