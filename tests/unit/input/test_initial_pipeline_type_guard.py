"""Regression tests for type guards in _should_save_source_items().

json.load() can return any JSON type (dict, string, number, list).
Without guards, accessing existing_items[0].keys() crashes with
AttributeError when the JSON is not a list of dicts.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.input.preprocessing.staging.initial_pipeline import (
    _should_save_source_items,
)


@pytest.fixture
def source_env(tmp_path):
    """Create base/output dirs and a dummy input file inside base.

    Returns (base_dir, output_dir, input_file_path, source_json_path).
    The source_json_path is where _should_save_source_items will look for
    existing source data.
    """
    base = tmp_path / "base"
    output = tmp_path / "output"
    base.mkdir()
    output.mkdir()

    input_file = base / "sample.json"
    input_file.write_text("[]")

    # _should_save_source_items resolves source_file via:
    #   workflow_root / "agent_io" / "source" / "<relative_stem>.json"
    # We patch _derive_workflow_root to return output so we can control it.
    source_dir = output / "agent_io" / "source"
    source_dir.mkdir(parents=True)
    source_json = source_dir / "sample.json"

    return str(base), str(output), str(input_file), source_json


NEW_ITEMS = [{"field_a": 1, "field_b": 2}]


class TestNonListJsonReturnsTrue:
    """When existing source file contains non-list JSON (dict, string, number),
    _should_save_source_items must return True instead of crashing."""

    @pytest.mark.parametrize(
        "json_content",
        [
            {"key": "value"},
            "just a string",
            42,
            3.14,
            True,
            None,
        ],
        ids=["dict", "string", "int", "float", "bool", "null"],
    )
    def test_non_list_json_returns_true(self, source_env, json_content):
        base, output, input_file, source_json = source_env
        source_json.write_text(json.dumps(json_content))

        with patch(
            "agent_actions.input.preprocessing.staging.initial_pipeline._derive_workflow_root",
            return_value=Path(output),
        ):
            result = _should_save_source_items(NEW_ITEMS, input_file, base, output)

        assert result is True


class TestListOfNonDictsReturnsTrue:
    """When existing source file is a list but items are not dicts,
    _should_save_source_items must return True instead of crashing."""

    @pytest.mark.parametrize(
        "json_content",
        [
            ["a", "b"],
            [1, 2, 3],
            [None, None],
            [True, False],
            [["nested", "list"]],
        ],
        ids=["strings", "ints", "nulls", "bools", "nested_lists"],
    )
    def test_list_of_non_dicts_returns_true(self, source_env, json_content):
        base, output, input_file, source_json = source_env
        source_json.write_text(json.dumps(json_content))

        with patch(
            "agent_actions.input.preprocessing.staging.initial_pipeline._derive_workflow_root",
            return_value=Path(output),
        ):
            result = _should_save_source_items(NEW_ITEMS, input_file, base, output)

        assert result is True


class TestEmptyListReturnsTrue:
    """When existing source file is an empty list, return True (save new data)."""

    def test_empty_list_returns_true(self, source_env):
        base, output, input_file, source_json = source_env
        source_json.write_text(json.dumps([]))

        with patch(
            "agent_actions.input.preprocessing.staging.initial_pipeline._derive_workflow_root",
            return_value=Path(output),
        ):
            result = _should_save_source_items(NEW_ITEMS, input_file, base, output)

        assert result is True


class TestHappyPathStillWorks:
    """Existing behaviour for valid list-of-dicts JSON is preserved."""

    def test_richer_new_data_returns_true(self, source_env):
        """New items have more fields than existing -> save."""
        base, output, input_file, source_json = source_env
        source_json.write_text(json.dumps([{"only_one_field": 1}]))
        new_items = [{"a": 1, "b": 2, "c": 3}]

        with patch(
            "agent_actions.input.preprocessing.staging.initial_pipeline._derive_workflow_root",
            return_value=Path(output),
        ):
            result = _should_save_source_items(new_items, input_file, base, output)

        assert result is True

    def test_existing_richer_returns_false(self, source_env):
        """Existing items have more fields than new -> skip."""
        base, output, input_file, source_json = source_env
        source_json.write_text(json.dumps([{"a": 1, "b": 2, "c": 3}]))
        new_items = [{"only_one_field": 1}]

        with patch(
            "agent_actions.input.preprocessing.staging.initial_pipeline._derive_workflow_root",
            return_value=Path(output),
        ):
            result = _should_save_source_items(new_items, input_file, base, output)

        assert result is False
