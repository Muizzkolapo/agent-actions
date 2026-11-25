"""`agac sandbox check`: run a workflow in the sandbox and compare the result with a file.

The expected outcomes are in ``sandbox_expected.<workflow>.yml`` or ``sandbox_expected.yml``
at the project root. The run is ``agac run --sandbox --fresh --wait``, so it clears and
writes the sandbox output only, never the output of a real run.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import click
import yaml

from agent_actions.cli.cli_decorators import (
    SCENARIO_HELP,
    handles_user_errors,
    requires_project,
    scenario_option,
    workflow_option,
)
from agent_actions.config import sandbox as sandbox_state

EXPECTED_FILE = "sandbox_expected.yml"
EXIT_PASSED = 0
EXIT_MISMATCH = 1
EXIT_BAD_EXPECTATIONS = 2

SCENARIO_KEYS = {
    "errors": "errors",
    "rules_broken": "rules_broken",
    "batch_results_dropped": "dropped",
}
ACTION_STATUSES = (
    "completed",
    "completed_with_failures",
    "failed",
    "skipped",
    "pending",
    "batch_submitted",
)
# Counts of `agac dispositions --json`, and what the store holds for the action.
COUNT_KEYS = (
    "records",
    "total",
    "sent_elsewhere",
    "success",
    "failed_checks",
    "failed",
    "exhausted",
    "guard_skipped",
    "unprocessed",
    "passthrough",
    "filtered",
    "skipped",
    "deferred",
)
ACTION_KEYS = ("status", *COUNT_KEYS)


class ExpectationsError(Exception):
    """The expectations file is missing, does not parse, or holds a key the check refuses."""


@dataclass(frozen=True)
class Expected:
    exit_code: int | None
    scenario: dict[str, int]
    actions: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class Actual:
    exit_code: int
    # None when the run printed no scenario line: it stopped before the mock answered.
    scenario: dict[str, int] | None
    statuses: dict[str, str]
    counts: dict[str, dict[str, int | None]]


@dataclass(frozen=True)
class Row:
    what: str
    expected: Any
    actual: Any

    @property
    def holds(self) -> bool:
        return bool(self.expected == self.actual)


def expectations_path(project_root: Path, workflow: str, given: str | None) -> Path:
    if given is not None:
        return Path(given) if Path(given).is_absolute() else project_root / given
    own = project_root / f"sandbox_expected.{workflow}.yml"
    return own if own.exists() else project_root / EXPECTED_FILE


def load_expected(path: Path) -> Expected:
    if not path.is_file():
        raise ExpectationsError(f"{path.name}: no such file at {path.parent}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ExpectationsError(f"{path.name}: not valid YAML: {error}") from error
    return parse_expected(data, path.name)


def parse_expected(data: Any, name: str) -> Expected:
    """Check the file's shape; every key it does not know is refused by name."""
    if not isinstance(data, dict):
        raise ExpectationsError(f"{name}: the file must be a mapping")
    _refuse_unknown(data, ("exit_code", "scenario", "actions"), name)
    exit_code = data.get("exit_code")
    if exit_code is not None:
        exit_code = _count(exit_code, f"{name}: exit_code")
    scenario = _mapping(data.get("scenario"), f"{name}: scenario")
    _refuse_unknown(scenario, tuple(SCENARIO_KEYS), f"{name}: scenario")
    actions: dict[str, dict[str, Any]] = {}
    for action, keys in _mapping(data.get("actions"), f"{name}: actions").items():
        where = f"{name}: actions.{action}"
        keys = _mapping(keys, where)
        _refuse_unknown(keys, ACTION_KEYS, where)
        checked: dict[str, Any] = {}
        for key, value in keys.items():
            if key == "status":
                if value not in ACTION_STATUSES:
                    raise ExpectationsError(
                        f"{where}.status: {value!r} is not one of {', '.join(ACTION_STATUSES)}"
                    )
                checked[key] = value
            else:
                checked[key] = _count(value, f"{where}.{key}")
        actions[str(action)] = checked
    expected = Expected(
        exit_code=exit_code,
        scenario={
            key: _count(value, f"{name}: scenario.{key}") for key, value in scenario.items()
        },
        actions=actions,
    )
    if expected.exit_code is None and not expected.scenario and not expected.actions:
        raise ExpectationsError(f"{name}: the file states no expectation")
    return expected


def _refuse_unknown(data: Mapping[str, Any], known: tuple[str, ...], where: str) -> None:
    unknown = [str(key) for key in data if key not in known]
    if unknown:
        raise ExpectationsError(
            f"{where}: unknown key {', '.join(repr(k) for k in unknown)}. "
            f"Known keys: {', '.join(known)}"
        )


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ExpectationsError(f"{where}: must be a mapping")
    return value


def _count(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExpectationsError(f"{where}: {value!r} is not a whole number 0 or more")
    return int(value)


def compare(expected: Expected, actual: Actual, workflow_actions: list[str]) -> list[Row]:
    """One row for each value the file states, in the file's order."""
    unknown = [action for action in expected.actions if action not in workflow_actions]
    # With no action status, the run stopped before the workflow loaded: nothing to name.
    if unknown and workflow_actions:
        raise ExpectationsError(
            f"actions: {', '.join(unknown)} is not an action of the workflow. "
            f"Its actions: {', '.join(workflow_actions)}"
        )
    rows: list[Row] = []
    if expected.exit_code is not None:
        rows.append(Row("exit code", expected.exit_code, actual.exit_code))
    for key, value in expected.scenario.items():
        counted = None if actual.scenario is None else actual.scenario.get(SCENARIO_KEYS[key])
        rows.append(Row(f"scenario {key}", value, counted))
    for action, keys in expected.actions.items():
        for key, value in keys.items():
            got: Any = (
                actual.statuses.get(action)
                if key == "status"
                else actual.counts.get(action, {}).get(key)
            )
            rows.append(Row(f"{action} {key}", value, got))
    return rows


def report(rows: list[Row], workflow: str, source: str) -> int:
    click.echo(f"\nSandbox check of {workflow} against {source}:")
    width = max(len(row.what) for row in rows)
    for row in rows:
        mark = "✓" if row.holds else "✗"
        shown = row.actual if row.holds else f"expected {row.expected}, got {row.actual}"
        click.echo(f"  {mark} {row.what:<{width}}  {shown}")
    failed = [row for row in rows if not row.holds]
    if not failed:
        click.echo(f"PASS: all {len(rows)} expectations hold.")
        return EXIT_PASSED
    click.echo(f"FAIL: {len(failed)} of {len(rows)} expectations do not hold:")
    for row in failed:
        click.echo(f"  {row.what}: expected {row.expected}, got {row.actual}")
    return EXIT_MISMATCH


def run_in_sandbox(
    workflow: str, project_root: Path, user_code: str | None, execution_mode: str
) -> int:
    """`agac run --sandbox --fresh --wait` in this process; its exit code."""
    from agent_actions.cli.args import RunCommandArgs
    from agent_actions.cli.exit_codes import EXIT_FAILED, EXIT_SUCCESS
    from agent_actions.cli.run import RunCommand
    from agent_actions.errors import AgentActionsError
    from agent_actions.logging.errors import format_user_error

    args = RunCommandArgs(
        agent=workflow,
        user_code=Path(user_code) if user_code else None,
        use_tools=False,
        execution_mode=cast(Literal["auto", "parallel", "sequential"], execution_mode),
        concurrency_limit=5,
        record_limit=None,
        file_limit=None,
        fresh=True,
        refresh_input=False,
        rerun=(),
        verify_keys=False,
        wait=True,
        poll=None,
        wait_timeout=None,
    )
    try:
        RunCommand(args).execute(project_root=project_root)
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else EXIT_FAILED
    except AgentActionsError as error:
        if not getattr(error, "_already_displayed", False):
            message = format_user_error(error, {"command": "sandbox check"})
            click.echo(f"Error: {message}", err=True)
        return EXIT_FAILED
    except click.ClickException as error:
        error.show()
        return EXIT_FAILED
    return EXIT_SUCCESS


def read_result(workflow: str, project_root: Path, exit_code: int) -> tuple[Actual, list[str]]:
    """What the sandbox run left: action statuses, record counts, the scenario counts."""
    from agent_actions.cli.dispositions import dispositions_report
    from agent_actions.config.project_paths import ProjectPathsFactory
    from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

    paths = ProjectPathsFactory.create_project_paths(
        workflow, workflow, auto_create=False, project_root=project_root
    )
    try:
        held = json.loads(sandbox_state.status_file(paths.io_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        held = {}
    statuses = {
        name: str(entry.get("status"))
        for name, entry in (held.items() if isinstance(held, dict) else [])
        if isinstance(entry, dict)
    }
    actions = list(statuses)
    counts: dict[str, dict[str, int | None]] = {}
    store = sandbox_state.store_file(paths.io_dir, workflow)
    if store.exists() and actions:
        backend = SQLiteBackend.create_readonly(store)
        try:
            for entry in dispositions_report(backend, workflow, actions)["actions"]:
                counts[entry["name"]] = {
                    **entry["counts"],
                    "total": entry["total"],
                    "sent_elsewhere": entry["sent_elsewhere"],
                    "records": entry["records"],
                }
        finally:
            backend.close()
    actual = Actual(
        exit_code=exit_code,
        scenario=sandbox_state.reported_counts(),
        statuses=statuses,
        counts=counts,
    )
    return actual, actions


def _in_sandbox(func: Callable) -> Callable:
    """Run the command in sandbox mode, as ``--sandbox`` does, and say so on stderr."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        click.get_current_context().with_resource(sandbox_state.sandbox_mode(True))
        click.echo(
            f"{click.style('SANDBOX', fg='yellow', bold=True)}: the offline mock answers every "
            "LLM action. The run clears and writes the sandbox output only",
            err=True,
        )
        return func(*args, **kwargs)

    return wrapper


@click.group()
def sandbox() -> None:
    """Test a workflow with sandbox runs."""


@sandbox.command("check")
@workflow_option()
@click.option(
    "--expected",
    metavar="PATH",
    default=None,
    help=(
        "The expected outcomes. Default: sandbox_expected.<workflow>.yml at the project "
        "root, else sandbox_expected.yml"
    ),
)
@_in_sandbox
@scenario_option(help=SCENARIO_HELP)
@click.option(
    "-u",
    "--user-code",
    required=False,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to the user's code folder containing UDFs",
)
@click.option(
    "--execution-mode",
    "-e",
    type=click.Choice(["auto", "parallel", "sequential"], case_sensitive=False),
    default="auto",
    help="Execution mode of the run: 'auto', 'parallel' or 'sequential'",
)
@handles_user_errors("sandbox check")
@requires_project
def check(
    agent: str,
    expected: str | None = None,
    user_code: str | None = None,
    execution_mode: str = "auto",
    project_root: Path | None = None,
) -> None:
    """Run a workflow in the sandbox and check the result against the expected outcomes.

    The run is agac run --sandbox --fresh --wait: it clears and writes the sandbox
    output only. Read that output after the check with --sandbox.

    \b
    Exit codes: 0 every expectation holds, 1 one or more do not hold,
    2 the expectations file is missing or not valid.

    \b
    Examples:
        agac sandbox check -w support_desk
        agac sandbox check -w support_desk --scenario chaos --expected chaos_expected.yml
    """
    assert project_root is not None
    workflow = Path(agent).stem
    path = expectations_path(project_root, workflow, expected)
    try:
        wanted = load_expected(path)
    except ExpectationsError as error:
        click.echo(f"Error: {error}", err=True)
        raise SystemExit(EXIT_BAD_EXPECTATIONS) from None
    exit_code = run_in_sandbox(workflow, project_root, user_code, execution_mode)
    actual, actions = read_result(workflow, project_root, exit_code)
    try:
        rows = compare(wanted, actual, actions)
    except ExpectationsError as error:
        click.echo(f"Error: {path.name}: {error}", err=True)
        raise SystemExit(EXIT_BAD_EXPECTATIONS) from None
    code = report(rows, workflow, path.name)
    if code != EXIT_PASSED:
        raise SystemExit(code)
