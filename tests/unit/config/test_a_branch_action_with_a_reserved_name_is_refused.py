"""A branch action named like a framework namespace is refused, as in a workflow without an include.

A branch action `source` hid the staged `source` namespace of its instance, with no message.
"""

from __future__ import annotations

import pytest

from agent_actions.utils.constants import RESERVED_AGENT_NAMES
from tests.unit.config.test_a_workflow_includes_a_branch_file import A, _names, _refusal, _render
from tests.unit.config.test_an_include_as_gives_each_instance_its_own_names import (
    REVIEW,
    WRITE,
    _round,
    _use,
)

WF = "agent_workflow/wf/agent_config/wf.yml"


@pytest.mark.parametrize("name", sorted(RESERVED_AGENT_NAMES))
def test_a_reserved_name_is_refused_with_the_text_a_workflow_gives(tmp_path, name):
    reserved = {**WRITE, "name": name}
    reader = {**REVIEW, "dependencies": [name], "context_scope": {"observe": [f"{name}.text"]}}
    reader.pop("guard")

    message = _refusal(tmp_path, [A, _use("c")], {"round": _round([reserved, reader])})

    assert message == (
        f"Branch 'round' (branches/round.yml), included in {WF} as 'c', action '{name}': "
        f"Reserved action name '{name}' cannot be used"
    )


def test_the_same_branch_with_another_name_loads(tmp_path):
    assert _names(_render(tmp_path, [A, _use("c")], {"round": _round([WRITE, REVIEW])}))[-1] == (
        "c__review"
    )
