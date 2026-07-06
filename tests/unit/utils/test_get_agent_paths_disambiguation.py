"""Duplicate agent base names must raise instead of silently resolving the first."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.errors.validation import AmbiguousAgentName, ValidationError
from agent_actions.utils.file_handler import FileHandler


def _make_agent(base: Path, workflow: str, agent: str) -> None:
    (base / workflow / agent / "agent_config").mkdir(parents=True)
    (base / workflow / agent / "agent_io").mkdir(parents=True)


def test_ambiguous_name_raises_naming_every_candidate(tmp_path):
    proj = tmp_path / "proj"
    _make_agent(proj, "team_a", "resume_review")
    _make_agent(proj, "team_b", "resume_review")
    with pytest.raises(AmbiguousAgentName) as excinfo:
        FileHandler.get_agent_paths("resume_review", project_root=proj)
    msg = str(excinfo.value)
    assert "team_a" in msg and "team_b" in msg
    assert set(excinfo.value.candidates) == {
        str(proj / "team_a" / "resume_review" / "agent_config"),
        str(proj / "team_b" / "resume_review" / "agent_config"),
    }


def test_factory_surfaces_candidate_list_without_generic_rewrap(tmp_path):
    proj = tmp_path / "proj"
    _make_agent(proj, "team_a", "resume_review")
    _make_agent(proj, "team_b", "resume_review")
    with pytest.raises(AmbiguousAgentName) as excinfo:
        ProjectPathsFactory.get_agent_paths("resume_review", project_root=proj)
    msg = str(excinfo.value)
    assert "team_a" in msg and "team_b" in msg
    assert "Failed to get agent paths" not in msg


def test_ambiguous_name_is_a_validation_error():
    exc = AmbiguousAgentName("resume_review", ["/a/resume_review/agent_config"])
    assert isinstance(exc, ValidationError)


def test_single_match_returns_the_only_candidate(tmp_path):
    proj = tmp_path / "proj"
    _make_agent(proj, "team_a", "resume_review")
    cfg, io = FileHandler.get_agent_paths("resume_review", project_root=proj)
    assert cfg is not None and cfg.endswith(str(Path("team_a") / "resume_review" / "agent_config"))
    assert io is not None and io.endswith(str(Path("team_a") / "resume_review" / "agent_io"))


def test_zero_match_returns_none(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg, io = FileHandler.get_agent_paths("nope", project_root=proj)
    assert cfg is None and io is None
