"""Manual state-mirror repro for the batch CLI multi-workflow bugs.

Run: ``python -m tests.manual.repro_viol_0042_batch_cli_state_mirror``

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
from agent_actions.llm.batch.batch_cli import _discover_workflow_name
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage import get_storage_backend

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _make_multi_workflow_project(root: Path) -> None:
    """Two workflows under one project, each with one batch action, each
    seeded with a `batch_registry:{action}` row in its own DB."""
    (root / "agent_actions.yml").write_text("name: multi\n")
    for wf, action in (("alpha", "alpha_action"), ("beta", "beta_action")):
        wf_root = root / "agent_workflow" / wf
        (wf_root / "agent_io" / "store").mkdir(parents=True)
        (wf_root / f"{wf}.yml").write_text(f"name: {wf}\n")

        backend = get_storage_backend(workflow_path=str(wf_root), workflow_name=wf)
        backend.initialize()
        registry = BatchRegistryManager(storage_backend=backend, action_name=action)
        registry.save_batch_job(
            file_name=f"{action}_chunk_0.jsonl",
            entry=BatchJobEntry(
                batch_id=f"fake_{wf}_batch",
                status=BatchStatus.COMPLETED,
                timestamp="2026-06-28T00:00:00Z",
                provider="ollama",
                file_name=f"{action}_chunk_0.jsonl",
            ),
        )


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
    # Current-state check: legacy helper fails to discover.
    import click as _click

    current_passes = False
    try:
        _discover_workflow_name(project_root)
    except _click.UsageError:
        current_passes = True  # Bug confirmed — discovery blows up.
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
        name="Workflow path discovery (VIOL-0067 path)",
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
        name="action_name routing (VIOL-0067 key)",
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
        name="CLI flag surface (VIOL-0042)",
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
    print("VIOL-0042 / VIOL-0067 state mirror — batch CLI multi-workflow bugs")
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
