"""``agac validate-udfs`` must be a complete preflight, not half of one.

It is the only one of the four preflight surfaces with "validate" in its name,
so it is the one a CI job reaches for — but it and ``inspect``/``schema``/``run``
check disjoint things. Measured live by exit code on a real project:

    broken impl:            validate-udfs 1   inspect 0
    missing context_scope:  validate-udfs 0   inspect 1

So a team running only ``validate-udfs`` ships a config the runtime will reject,
and a team running only ``inspect`` ships a broken ``impl:`` that surfaces at
execution.

These drive the real command against a copy of ``examples/review_analyzer``,
because the structural checks read the *expanded* action config and
``ValidateUDFsCommand`` runs only two of the config pipeline's seven stages —
asserting against a hand-built raw dict would test the wrong shape.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from agent_actions.validation.validate_udfs import validate_udfs_cmd

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "review_analyzer"
WORKFLOW = "review_analyzer"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A real, working project on disk — the only shape these checks can read.

    discover_udfs imports tools under an ``agent_actions._udfs.*`` prefix that
    clear_registry does not evict, so a prior test's copy of a same-named tool
    is reused and validation reads the wrong module.
    """
    # Deliberately not skip: this example is committed to the repo, so its
    # absence is a defect. A skip here would delete every check in this file
    # with no failure signal.
    assert EXAMPLE.is_dir(), f"fixture workflow missing: {EXAMPLE}"
    for name in [k for k in sys.modules if k.startswith("agent_actions._udfs.")]:
        del sys.modules[name]
    root = tmp_path / "proj"
    shutil.copytree(EXAMPLE, root)
    monkeypatch.chdir(root)
    return root


def _config_path(root: Path) -> Path:
    return root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"


def _edit_config(root: Path, mutate) -> None:
    path = _config_path(root)
    data = yaml.safe_load(path.read_text())
    mutate(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _run(root: Path):
    return CliRunner().invoke(validate_udfs_cmd, ["-a", WORKFLOW, "-u", str(root / "tools")])


def _drop_context_scope(data: dict) -> None:
    """Remove every context_scope — the breakage `inspect` catches and this does not."""
    data.get("defaults", {}).pop("context_scope", None)
    for action in data.get("actions", []):
        action.pop("context_scope", None)


class TestItCatchesWhatOnlyTheOtherCommandsCaught:
    def test_a_missing_context_scope_fails(self, project):
        _edit_config(project, _drop_context_scope)

        result = _run(project)

        assert result.exit_code != 0, result.output
        # Pin the real preflight, not a bespoke "is context_scope present" check.
        assert "context_scope" in result.output, result.output

    def test_a_dangling_observe_reference_fails(self, project):
        """A structural fault that is not "context_scope is absent".

        Without this, a bespoke "does every action declare context_scope"
        check would pass the whole file while catching none of the analysis
        the other commands actually run.
        """

        def dangle(data: dict) -> None:
            for action in data.get("actions", []):
                scope = action.get("context_scope")
                if isinstance(scope, dict) and scope.get("observe"):
                    scope["observe"] = ["no_such_action.no_such_field"]
                    return
            raise AssertionError("fixture no longer has an observe reference to dangle")

        _edit_config(project, dangle)

        result = _run(project)

        assert result.exit_code != 0, result.output


class TestItStillCatchesWhatItAlreadyDid:
    def test_a_broken_impl_reference_fails(self, project):
        def break_impl(data: dict) -> None:
            for action in data.get("actions", []):
                if "impl" in action:
                    action["impl"] = "no_such_function_anywhere"
                    return
            raise AssertionError("fixture no longer has a tool action to break")

        _edit_config(project, break_impl)

        result = _run(project)

        assert result.exit_code != 0, result.output
        assert "no_such_function_anywhere" in result.output, result.output


class TestACleanProjectStillPasses:
    """The control that matters: a working project must not start failing CI."""

    def test_the_unmodified_example_passes(self, project):
        result = _run(project)

        assert result.exit_code == 0, result.output
