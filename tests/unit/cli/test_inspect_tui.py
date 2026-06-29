"""Pure-logic tests for the interactive ``agac inspect -i`` TUI.

We can't drive a real TTY in CI, so the run-loop itself is tested
manually. Everything pure — step building, version collapsing, key
handling — is unit-tested here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_actions.cli.inspect_tui import (
    InspectTUI,
    Step,
    build_steps,
    collapse_versions,
)


class TestBuildSteps:
    def test_empty_levels(self):
        assert build_steps([]) == []

    def test_single_action_level_becomes_serial_step(self):
        steps = build_steps([["a"]])
        assert steps == [Step("serial", ["a"])]

    def test_consecutive_singletons_collapse_into_one_chain(self):
        steps = build_steps([["a"], ["b"], ["c"]])
        assert steps == [Step("serial", ["a", "b", "c"])]

    def test_parallel_levels_are_standalone(self):
        steps = build_steps([["a"], ["b", "c"], ["d"]])
        assert steps == [
            Step("serial", ["a"]),
            Step("parallel", ["b", "c"]),
            Step("serial", ["d"]),
        ]

    def test_parallel_does_not_swallow_next_serial(self):
        steps = build_steps([["a", "b"], ["c"], ["d"]])
        assert steps == [
            Step("parallel", ["a", "b"]),
            Step("serial", ["c", "d"]),
        ]


class TestCollapseVersions:
    def test_collapses_version_group(self):
        assert collapse_versions(["foo_1", "foo_2", "foo_3"]) == ["foo (×3)"]

    def test_keeps_singleton_full_name(self):
        assert collapse_versions(["foo_1", "bar"]) == ["foo_1", "bar"]

    def test_preserves_first_occurrence_order(self):
        assert collapse_versions(["bar", "foo_1", "baz", "foo_2"]) == [
            "bar",
            "foo (×2)",
            "baz",
        ]

    def test_out_of_order_versions_count_correctly(self):
        assert collapse_versions(["foo_3", "foo_1", "foo_2"]) == ["foo (×3)"]


class TestKeyHandling:
    def _tui(self, num_steps=3, num_actions_in_first_parallel=3):
        inspector = MagicMock()
        inspector.action_configs = {f"a{i}": {} for i in range(10)}
        inspector.execution_order = list(inspector.action_configs)
        tui = InspectTUI(inspector)
        tui.steps = [Step("serial", [f"a{i}"]) for i in range(num_steps)]
        if num_actions_in_first_parallel >= 2:
            tui.steps[0] = Step("parallel", [f"p{i}" for i in range(num_actions_in_first_parallel)])
        return tui

    def test_down_arrow_moves_cursor_down(self):
        tui = self._tui(num_steps=3)
        assert tui.cursor == 0
        tui._handle_key("down")
        assert tui.cursor == 1
        tui._handle_key("j")  # vim
        assert tui.cursor == 2

    def test_down_arrow_clamps_at_last_step(self):
        tui = self._tui(num_steps=3)
        for _ in range(10):
            tui._handle_key("down")
        assert tui.cursor == 2

    def test_up_arrow_clamps_at_zero(self):
        tui = self._tui(num_steps=3)
        for _ in range(10):
            tui._handle_key("up")
        assert tui.cursor == 0

    def test_g_jumps_home_capital_g_jumps_end(self):
        tui = self._tui(num_steps=5)
        tui.cursor = 3
        tui._handle_key("g")
        assert tui.cursor == 0
        tui._handle_key("G")
        assert tui.cursor == 4

    def test_enter_drills_into_first_action_of_step(self):
        tui = self._tui(num_steps=3, num_actions_in_first_parallel=3)
        tui.cursor = 0
        tui._handle_key("enter")
        assert tui.screen == "action"
        assert tui.drill_action == "p0"

    def test_esc_in_action_screen_returns_to_pipeline(self):
        tui = self._tui()
        tui.screen = "action"
        tui.drill_action = "p0"
        result = tui._handle_key("esc")
        assert result is True
        assert tui.screen == "pipeline"
        assert tui.drill_action is None

    def test_esc_in_pipeline_screen_quits(self):
        tui = self._tui()
        result = tui._handle_key("esc")
        assert result is False

    def test_q_quits_from_either_screen(self):
        tui = self._tui()
        assert tui._handle_key("q") is False

        tui.screen = "action"
        tui.drill_action = "p0"
        assert tui._handle_key("q") is False

    def test_ctrl_c_quits(self):
        tui = self._tui()
        assert tui._handle_key("ctrl-c") is False

    def test_horizontal_arrows_cycle_parallel_siblings(self):
        tui = self._tui(num_steps=2, num_actions_in_first_parallel=3)
        tui.cursor = 0
        tui._handle_key("enter")
        assert tui.drill_action == "p0"
        tui._handle_key("right")
        assert tui.drill_action == "p1"
        tui._handle_key("right")
        assert tui.drill_action == "p2"
        tui._handle_key("right")
        assert tui.drill_action == "p0"  # wraps
        tui._handle_key("left")
        assert tui.drill_action == "p2"
        tui._handle_key("h")  # vim
        assert tui.drill_action == "p1"
        tui._handle_key("l")  # vim
        assert tui.drill_action == "p2"


@pytest.mark.parametrize("flag", ["--yaml", "--validate", "--dry-run", "--json"])
def test_interactive_with_conflicting_flag_is_usage_error(flag):
    """The TUI is for the default form only — combining with output
    flags would be ambiguous (the TUI is navigation, not a report).
    """
    from click.testing import CliRunner

    from agent_actions.cli.inspect import inspect

    runner = CliRunner()
    result = runner.invoke(inspect, ["-a", "wf", "-i", flag])
    assert result.exit_code != 0
    assert (
        "interactive" in result.output.lower()
        or "only" in result.output.lower()
        or "drop" in result.output.lower()
    )
