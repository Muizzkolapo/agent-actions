"""Tests for schema validation conditional on json_mode.

Non-JSON-mode workflows (json_mode: false in defaults, no action override)
should skip schema directory validation entirely.
"""

from __future__ import annotations

import pytest

from agent_actions.prompt.renderer import ConfigRenderingService


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        # no json_mode in defaults: defaults to True at runtime
        pytest.param({"defaults": {"model_name": "gpt-4"}, "actions": []}, True, id="unset"),
        pytest.param({"defaults": {"json_mode": True}, "actions": []}, True, id="true"),
        pytest.param(
            {"defaults": {"json_mode": False}, "actions": [{"name": "step1"}]},
            False,
            id="false",
        ),
        pytest.param(
            {
                "defaults": {"json_mode": False},
                "actions": [{"name": "step1"}, {"name": "step2", "json_mode": True}],
            },
            True,
            id="action_override",
        ),
        pytest.param(
            {
                "defaults": {"json_mode": False},
                "actions": [{"name": "step1", "json_mode": False}, {"name": "step2"}],
            },
            False,
            id="all_false",
        ),
        pytest.param({"actions": [{"name": "step1"}]}, True, id="no_defaults"),
        pytest.param({"defaults": None, "actions": []}, True, id="defaults_none"),
    ],
)
def test_workflow_needs_schema(config, expected):
    assert ConfigRenderingService._workflow_needs_schema(config) is expected
