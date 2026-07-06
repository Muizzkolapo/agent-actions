"""Cover validate-udfs enforcing the workflow name matches its filename stem."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from agent_actions.validation.validate_udfs import validate_udfs_cmd


def _project(root: Path, agent_stem: str, name_value: str) -> Path:
    (root / "agent_actions.yml").write_text("name: proj\n")
    cfg = root / agent_stem / "agent_config"
    cfg.mkdir(parents=True)
    (root / agent_stem / "agent_io").mkdir(parents=True)
    (cfg / f"{agent_stem}.yml").write_text(
        f"name: {name_value}\nactions:\n  - name: step_one\n    prompt: hi\n"
    )
    udf = root / "user_code"
    udf.mkdir()
    return udf


def test_validate_udfs_rejects_name_filename_mismatch(tmp_path, monkeypatch):
    udf = _project(tmp_path, "wrong", "real_name")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(validate_udfs_cmd, ["-a", "wrong", "-u", str(udf)])
    assert result.exit_code == 1, result.output
    assert "real_name" in result.output, result.output
    assert "wrong" in result.output, result.output


def test_validate_udfs_accepts_matching_name(tmp_path, monkeypatch):
    udf = _project(tmp_path, "good", "good")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(validate_udfs_cmd, ["-a", "good", "-u", str(udf)])
    assert "does not match" not in result.output, result.output
    assert result.exit_code == 0, result.output


def test_validate_udfs_unnamed_config_is_not_reported_as_mismatch(tmp_path, monkeypatch):
    udf = _project(tmp_path, "blank", "blank")
    (tmp_path / "blank" / "agent_config" / "blank.yml").write_text("{}\n")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(validate_udfs_cmd, ["-a", "blank", "-u", str(udf)])
    assert result.exit_code == 1, result.output
    assert "does not match" not in result.output, result.output
