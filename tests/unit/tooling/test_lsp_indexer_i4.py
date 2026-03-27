"""Regression test for I-4: LSP indexer context_scope list exit on non-list-item sibling."""

from __future__ import annotations

from pathlib import Path

from agent_actions.tooling.lsp.indexer import _index_workflow_file
from agent_actions.tooling.lsp.models import ProjectIndex


def _make_index(tmp_path: Path) -> ProjectIndex:
    return ProjectIndex(root=tmp_path)


def _run_indexer(tmp_path: Path, yaml_content: str) -> ProjectIndex:
    """Write YAML to a temp file and index it; return the resulting index."""
    from ruamel.yaml import YAML

    yaml_file = tmp_path / "test_action.yml"
    yaml_file.write_text(yaml_content)
    index = _make_index(tmp_path)
    index.file_actions[yaml_file] = {}
    index.references_by_file[yaml_file] = []
    index.duplicate_actions_by_file[yaml_file] = set()
    _index_workflow_file(index, yaml_file, YAML(typ="safe"))
    return index


class TestLSPIndexerContextScopeExit:
    """I-4: Non-list-item at or before list indent should exit the context_scope list."""

    def test_observe_items_collected_normally(self, tmp_path):
        """Sanity: items under observe: are collected."""
        yaml = """\
actions:
  - name: my_action
    context_scope:
      observe:
        - upstream.field_a
        - upstream.field_b
"""
        index = _run_indexer(tmp_path, yaml)
        yaml_file = tmp_path / "test_action.yml"
        actions = index.file_actions.get(yaml_file, {})
        assert "my_action" in actions
        action = actions["my_action"]
        assert "upstream.field_a" in action.context_observe
        assert "upstream.field_b" in action.context_observe

    def test_non_list_item_exits_context_list(self, tmp_path):
        """I-4 regression: a non-list-item key at list indent terminates list collection.

        Without the fix, 'intent: something' was incorrectly parsed as a list item
        and appended to context_observe.
        """
        yaml = """\
actions:
  - name: my_action
    context_scope:
      observe:
        - upstream.field_a
      intent: should_not_be_in_observe
"""
        index = _run_indexer(tmp_path, yaml)
        yaml_file = tmp_path / "test_action.yml"
        action = index.file_actions.get(yaml_file, {}).get("my_action")
        assert action is not None
        assert "upstream.field_a" in action.context_observe
        # The key 'intent: should_not_be_in_observe' must NOT appear in observe
        assert not any(
            "intent" in v or "should_not_be_in_observe" in v for v in action.context_observe
        )

    def test_new_action_after_context_scope_not_collected(self, tmp_path):
        """Items in a subsequent action should not bleed into the previous action's observe."""
        yaml = """\
actions:
  - name: action_one
    context_scope:
      observe:
        - upstream.field_a
  - name: action_two
    context_scope:
      observe:
        - upstream.field_b
"""
        index = _run_indexer(tmp_path, yaml)
        yaml_file = tmp_path / "test_action.yml"
        actions = index.file_actions.get(yaml_file, {})
        one = actions.get("action_one")
        two = actions.get("action_two")
        assert one is not None and two is not None
        assert "upstream.field_a" in one.context_observe
        assert "upstream.field_b" not in one.context_observe
        assert "upstream.field_b" in two.context_observe
        assert "upstream.field_a" not in two.context_observe
