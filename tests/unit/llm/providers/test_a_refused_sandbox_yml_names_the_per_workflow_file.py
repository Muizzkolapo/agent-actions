"""Each refusal of ``sandbox.yml`` in a project of several workflows names the per-workflow file.

That holds for a file that cannot be read, one that is not a mapping, and one with a key
the scenario models refuse, with and without a preset. A ``sandbox.<workflow>.yml``, or a
project of one workflow, gets no such line.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.agac import scenario as sc

ACTIONS = {"extract": None}
HINT = "put a scenario for one workflow in sandbox.<workflow>.yml (sandbox.alpha.yml for alpha)"
UNREADABLE = "actions: [extract\n"
NOT_A_MAPPING = "- extract\n"
UNKNOWN_KEY = "sed: 3\n"


def _project(tmp_path: Path, workflows: tuple[str, ...], files: dict[str, str]) -> Path:
    for workflow in workflows:
        (tmp_path / "agent_workflow" / workflow / "agent_config").mkdir(parents=True)
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def _refused(root: Path, source: str | None = None) -> str:
    with pytest.raises(ConfigurationError) as caught:
        sc.load(source, root, ACTIONS, workflow="alpha")
    return str(caught.value)


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (UNREADABLE, "Scenario sandbox.yml cannot be read"),
        (NOT_A_MAPPING, "(file): must be a mapping, got list"),
        (UNKNOWN_KEY, "- sed: unknown key"),
    ],
    ids=["unreadable", "not-a-mapping", "validation-error"],
)
def test_a_refused_sandbox_yml_names_the_per_workflow_file(tmp_path, text, said):
    root = _project(tmp_path, ("alpha", "beta"), {"sandbox.yml": text})

    message = _refused(root)

    assert said in message, message
    assert HINT in message, message


@pytest.mark.parametrize("text", [UNREADABLE, NOT_A_MAPPING], ids=["unreadable", "not-a-mapping"])
def test_under_a_preset_the_refusal_names_the_preset_and_the_per_workflow_file(tmp_path, text):
    root = _project(tmp_path, ("alpha", "beta"), {"sandbox.yml": text})

    message = _refused(root, "chaos")

    assert "Scenario preset chaos with the stubs of sandbox.yml" in message, message
    assert HINT in message, message


@pytest.mark.parametrize("text", [UNREADABLE, NOT_A_MAPPING], ids=["unreadable", "not-a-mapping"])
@pytest.mark.parametrize(
    ("workflows", "name"),
    [(("alpha",), "sandbox.yml"), (("alpha", "beta"), "sandbox.alpha.yml")],
    ids=["one-workflow", "own-file"],
)
def test_no_per_workflow_line_otherwise(tmp_path, text, workflows, name):
    root = _project(tmp_path, workflows, {name: text})

    message = _refused(root)

    assert name in message, message
    assert "sandbox.<workflow>.yml" not in message, message
