"""The line naming the stubbed tools is given once per command, and again in the next one.

A command (one ``scenario_choice`` block) loads the workflow once per ``--wait`` pass or
``retry --all`` pass; each load reads the scenario again.
"""

from __future__ import annotations

from agent_actions.config import sandbox
from agent_actions.llm.providers.agac.scenario import Tool

NOTICE = "the scenario stubs these tool actions, so their code does not run: search"


def _load(tmp_path) -> None:
    sandbox.load_scenario(tmp_path, {}, {"search": Tool(), "lookup": Tool()}, "catalog")


def test_each_command_gets_the_notice_once_over_its_loads(tmp_path):
    (tmp_path / "sandbox.yml").write_text("actions:\n  search: {stub: true}\n")

    with sandbox.sandbox_mode(True):
        for _command in range(2):
            with sandbox.scenario_choice(None):
                _load(tmp_path)
                assert sandbox.stub_notice() == NOTICE
                _load(tmp_path)
                assert sandbox.stub_notice() is None


def test_a_block_entered_inside_another_starts_its_own_count(tmp_path):
    """As it starts its own tally: the state of the open block does not carry in."""
    (tmp_path / "sandbox.yml").write_text("actions:\n  search: {stub: true}\n")

    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        _load(tmp_path)
        assert sandbox.stub_notice() == NOTICE
        with sandbox.scenario_choice(None):
            _load(tmp_path)
            assert sandbox.stub_notice() == NOTICE
        assert sandbox.stub_notice() is None


def test_a_command_that_stubs_nothing_gets_no_notice(tmp_path):
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        _load(tmp_path)
        assert sandbox.stub_notice() is None


def test_under_a_preset_the_notice_names_the_file_of_the_stubs(tmp_path):
    (tmp_path / "sandbox.catalog.yml").write_text("actions:\n  search: {stub: true}\n")

    with sandbox.sandbox_mode(True), sandbox.scenario_choice("chaos"):
        _load(tmp_path)
        assert sandbox.stub_notice() == (
            f"{NOTICE} (the stubs come from sandbox.catalog.yml, the rest from preset chaos)"
        )
