"""Source stamps follow the tool and guard used by an action."""

import pytest

from agent_actions.workflow.config_pipeline import _udf_source_hash
from agent_actions.workflow.executor import _edits_since, edited_since_its_work_began


def test_only_referenced_files_affect_the_digest(tmp_path, monkeypatch):
    tool = tmp_path / "tool.py"
    guard = tmp_path / "guard.py"
    other = tmp_path / "other.py"
    for path in (tool, guard, other):
        path.write_text("original")
    files = {"tool": tool, "guard": guard}
    monkeypatch.setattr(
        "agent_actions.workflow.config_pipeline.get_udf_metadata",
        lambda name: {"file": str(files[name])},
    )
    config = {"model_vendor": "tool", "model_name": "tool", "conditional_clause": "guard"}
    initial = _udf_source_hash(config)
    other.write_text("changed")
    assert _udf_source_hash(config) == initial
    guard.write_text("changed")
    after_guard = _udf_source_hash(config)
    assert after_guard != initial
    tool.write_text("changed")
    assert _udf_source_hash(config) != after_guard


def test_missing_source_is_not_silently_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent_actions.workflow.config_pipeline.get_udf_metadata",
        lambda name: {"file": str(tmp_path / "missing.py")},
    )
    with pytest.raises(OSError):
        _udf_source_hash({"model_vendor": "tool", "model_name": "tool"})


def test_loaded_source_snapshot_survives_a_mid_run_edit(tmp_path, monkeypatch):
    source = tmp_path / "tool.py"
    source.write_text("old")
    metadata = {"file": str(source), "source_hash": "loaded-old"}
    monkeypatch.setattr(
        "agent_actions.workflow.config_pipeline.get_udf_metadata", lambda name: metadata
    )
    config = {"model_vendor": "tool", "model_name": "tool"}
    initial = _udf_source_hash(config)
    source.write_text("new")
    assert _udf_source_hash(config) == initial
    metadata["source_hash"] = "loaded-new"
    assert _udf_source_hash(config) != initial


def test_old_stamps_and_interrupted_work():
    old = {"config_hash": "old"}
    config = {"_udf_source_hash": "new"}
    assert "tool source" in _edits_since(old, config)
    assert "tool source" not in _edits_since(old, {})
    assert edited_since_its_work_began({"answered_under": old}, config) is True
    current = {"config_hash": "old", "udf_source_hash": "old"}
    assert "tool source" in _edits_since(current, config)
    assert edited_since_its_work_began({"answered_under": current}, config) is True
