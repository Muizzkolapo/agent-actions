"""Manual state-mirror test for the batch CLI multi-workflow bugs.

Run: ``python -m tests.manual.batch_cli_state_mirror``

This script mirrors two states of the batch CLI:

    CURRENT state — today, before any fix:
      - ``_discover_workflow_name(project_root)`` looks at
        ``<project_root>/agent_io/store/``, which does not exist in
        multi-workflow layouts.
      - ``batch_cli.status`` / ``retrieve`` pass ``action_name=workflow_name``
        to the services, so registry lookups hit the wrong key whenever an
        action's name differs from its workflow's name.
      - ``agac batch status`` and ``agac batch retrieve`` advertise no
        ``-a/--agent`` or ``--action`` flags.

    FUTURE state — after the planned fix:
      - Workflow path resolves through ``ProjectPathsFactory.get_agent_paths``
        and the ``agent_workflow/<wf>`` layout.
      - ``action_name`` is threaded from the CLI flag into the services so
        the registry lookup hits ``batch_registry:{action_name}``.
      - Both subcommands accept ``-a/--agent`` and ``--action``.

Each scenario emits a verdict:

    CURRENT  — bug is present (current-state check PASSED, future-state FAILED)
    FUTURE   — fix has landed (current-state FAILED, future-state PASSED)
    MIXED    — neither state matches cleanly; investigate

Exit code is 0 when ALL scenarios produce a single coherent verdict
(all CURRENT, or all FUTURE). Mixed verdicts exit non-zero.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests._support.batch_workflows import seed_workflow

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _make_multi_workflow_project(root: Path) -> None:
    """Two workflows under one project, each with one batch action, each
    seeded with a `batch_registry:{action}` row in its own DB."""
    (root / "agent_actions.yml").write_text("name: multi\n")
    seed_workflow(root, "alpha", "alpha_action", "fake_alpha_batch")
    seed_workflow(root, "beta", "beta_action", "fake_beta_batch")


# --------------------------------------------------------------------------
# Scenarios — each returns (current_passes, future_passes)
# --------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    name: str
    current_passes: bool
    future_passes: bool
    detail: str = ""


def scenario_1_workflow_path_discovery(project_root: Path) -> ScenarioResult:
    """`_discover_workflow_name` against a multi-workflow project root.

    CURRENT: raises UsageError because <project_root>/agent_io/store/ is empty.
    FUTURE:  the helper has been replaced with workflow-aware resolution
             keyed off `agent_workflow/<wf>` (probed via the existence of
             a `_resolve_workflow` symbol).
    """
    # Current-state check: legacy helper exists AND blows up on a
    # multi-workflow project. Future state: the helper has been deleted.
    import click as _click

    from agent_actions.llm.batch import batch_cli as _bc

    legacy = getattr(_bc, "_discover_workflow_name", None)
    if legacy is None:
        current_passes = False  # Legacy helper deleted → future state.
    else:
        try:
            legacy(project_root)
            current_passes = False  # Discovery somehow succeeded — neither state.
        except _click.UsageError:
            current_passes = True
        except Exception:  # noqa: BLE001
            current_passes = False

    # Future-state check: replacement helper exists and resolves "alpha".
    future_passes = False
    detail = ""
    try:
        from agent_actions.llm.batch import batch_cli as _bc

        resolver = getattr(_bc, "_resolve_workflow", None)
        if resolver is not None:
            name, wf_root = resolver(project_root, "alpha")
            future_passes = (
                name == "alpha" and Path(wf_root).name == "alpha" and Path(wf_root).is_dir()
            )
            detail = f"_resolve_workflow → ({name!r}, {wf_root})"
        else:
            detail = "_resolve_workflow not yet defined"
    except Exception as e:  # noqa: BLE001
        detail = f"_resolve_workflow raised {type(e).__name__}: {e}"

    return ScenarioResult(
        name="Workflow path discovery",
        current_passes=current_passes,
        future_passes=future_passes,
        detail=detail,
    )


def scenario_2_action_name_routing() -> ScenarioResult:
    """`batch_cli.py` source pin: what does the CLI pass to the services?

    CURRENT: `batch_cli.status` calls `service.check_status(..., action_name=workflow_name)`
             and `batch_cli.retrieve` constructs `BatchRetrievalService(action_name=workflow_name)`.
             The literal `action_name=workflow_name` is present in the file.
    FUTURE:  the literal is gone — both call sites pass a separately-resolved
             `action_name` variable.
    """
    import agent_actions.llm.batch.batch_cli as _bc

    src = Path(_bc.__file__).read_text()
    has_wrong_pin = "action_name=workflow_name" in src

    current_passes = has_wrong_pin
    future_passes = not has_wrong_pin

    return ScenarioResult(
        name="action_name routing",
        current_passes=current_passes,
        future_passes=future_passes,
        detail=f"'action_name=workflow_name' literal in batch_cli.py: {has_wrong_pin}",
    )


def scenario_3_cli_flag_surface() -> ScenarioResult:
    """`agac batch status --help` flag surface.

    CURRENT: no `-a/--agent`, no `--action`.
    FUTURE:  both flags present and documented.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["batch", "status", "--help"])
    help_text = result.output

    has_agent = "--agent" in help_text
    has_action = "--action" in help_text

    current_passes = not has_agent and not has_action
    future_passes = has_agent and has_action

    return ScenarioResult(
        name="CLI flag surface",
        current_passes=current_passes,
        future_passes=future_passes,
        detail=f"--agent: {has_agent}, --action: {has_action}",
    )


# --------------------------------------------------------------------------
# Verdict + main
# --------------------------------------------------------------------------


def _verdict(r: ScenarioResult) -> str:
    if r.current_passes and not r.future_passes:
        return "CURRENT (bug present)"
    if r.future_passes and not r.current_passes:
        return "FUTURE (fix landed)"
    return "MIXED — investigate"


def main() -> int:
    print("=" * 72)
    print("State mirror — batch CLI multi-workflow bugs")
    print("=" * 72)

    with tempfile.TemporaryDirectory() as tmp:
        project_root = Path(tmp)
        _make_multi_workflow_project(project_root)

        scenarios = [
            scenario_1_workflow_path_discovery(project_root),
            scenario_2_action_name_routing(),
            scenario_3_cli_flag_surface(),
        ]

    verdicts = []
    for r in scenarios:
        v = _verdict(r)
        verdicts.append(v)
        print()
        print(f"[{r.name}]")
        print(f"  current-state check passes: {r.current_passes}")
        print(f"  future-state check passes:  {r.future_passes}")
        if r.detail:
            print(f"  detail: {r.detail}")
        print(f"  verdict: {v}")

    print()
    print("-" * 72)
    if all(v.startswith("CURRENT") for v in verdicts):
        print("OVERALL: CURRENT — bugs confirmed. Run the spec.")
        return 0
    if all(v.startswith("FUTURE") for v in verdicts):
        print("OVERALL: FUTURE — fix has landed. Roles are reversed; bug is gone.")
        return 0
    print("OVERALL: MIXED — partial state. Likely mid-fix or unexpected drift.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
