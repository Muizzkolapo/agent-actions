"""Sandbox runs: the offline mock answers every LLM action, and the output is kept apart.

A command given ``--sandbox`` sets the mode for the whole process with ``sandbox_mode``.
Each path a run writes or a read command reads is derived here, so a sandbox run never
writes where a real run reads. A command that calls the mock (``run``, ``retry``) also
follows a scenario, loaded once per workflow load and held here for the mock to read.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.utils.constants import DEFAULT_ACTION_KIND, MODEL_VENDOR_KEY

if TYPE_CHECKING:
    from agent_actions.llm.providers.agac.scenario import Scenario, Tally
    from agent_actions.storage.backend import StorageBackend

SANDBOX_VENDOR = "agac-provider"
SANDBOX_DIR = "sandbox"
STATUS_FILE_NAME = ".agent_status.json"
SANDBOX_STORE_SUFFIX = ".sandbox.db"
# Set on a HITL action's config: the review approves every record with no human.
AUTO_APPROVE_KEY = "_sandbox_auto_approve"

_active = False
_follows_scenario = False
# What --scenario named; None is the project's sandbox.yml, else the happy preset.
_scenario_flag: str | None = None
_scenario: Scenario | None = None
# What the scenario did over the whole command, across each load of the workflow.
_tally: Tally | None = None


def is_active() -> bool:
    return _active


@contextmanager
def sandbox_mode(enabled: bool) -> Iterator[None]:
    global _active
    previous = _active
    _active = enabled
    try:
        yield
    finally:
        _active = previous


@contextmanager
def scenario_choice(source: str | None) -> Iterator[None]:
    """Have each workflow load in this block read the scenario *source* names."""
    global _follows_scenario, _scenario_flag, _scenario, _tally
    from agent_actions.llm.providers.agac.scenario import Tally

    previous = (_follows_scenario, _scenario_flag, _scenario, _tally)
    _follows_scenario, _scenario_flag, _scenario, _tally = True, source, None, Tally()
    try:
        yield
    finally:
        _follows_scenario, _scenario_flag, _scenario, _tally = previous


def load_scenario(project_root: Path | None, llm_actions: Mapping[str, str | None]) -> None:
    """Read and check the scenario, before any call; a command that calls no mock reads none.

    *llm_actions* maps each LLM action to its version group's base name, or to None.
    """
    global _scenario
    if not (_active and _follows_scenario):
        return
    from agent_actions.llm.providers.agac.scenario import load

    _scenario = load(_scenario_flag, project_root or Path.cwd(), llm_actions, _tally)


def check_scenario_outputs(schemas: Mapping[str, Any], action_configs: Mapping[str, Any]) -> None:
    """Refuse a scenario ``pin`` or ``break_rules`` an action's output schema cannot take.

    *schemas* are the workflow's ``ActionSchema`` objects by action, as pre-flight reads them.
    """
    followed = scenario()
    if followed is None:
        return
    from agent_actions.models.action_schema import FieldSource

    declared: dict[str, set[str] | None] = {}
    for name, schema in schemas.items():
        config = action_configs.get(name) or {}
        if config.get(MODEL_VENDOR_KEY) != SANDBOX_VENDOR:
            continue
        if schema.is_schemaless or config.get("json_mode") is False:
            declared[name] = None
        elif not schema.is_dynamic:
            declared[name] = {
                field.name for field in schema.output_fields if field.source is FieldSource.SCHEMA
            }
    followed.check_outputs(declared)


def attach_store(store: StorageBackend) -> None:
    """Keep the scenario's attempt counts in the run's sandbox store."""
    if _scenario is not None and _active:
        _scenario.attach(store)


def forget_attempts(
    store: StorageBackend, action: str | None = None, records: Iterable[str] | None = None
) -> None:
    """Clear the scenario attempt counts from *store*: of every action, or of *action*.

    With *records*, only the counts of those records (their ``source_guid``) at *action*.
    """
    if not _active:
        return
    from agent_actions.llm.providers.agac.scenario import ATTEMPTS_KEY_PREFIX, attempts_key

    if action is None:
        store.delete_metadata_prefix(ATTEMPTS_KEY_PREFIX)
    elif records is None:
        store.delete_metadata_prefix(attempts_key(action, ""))
    else:
        for record in records:
            store.delete_metadata(attempts_key(action, record))


def scenario() -> Scenario | None:
    return _scenario if _active else None


def scenario_summary(only_after_calls: bool = False) -> str | None:
    """The line that counts what the scenario did in this command; the count then restarts.

    With *only_after_calls*, None when the mock answered no call.
    """
    if _scenario is None or not _active or _tally is None:
        return None
    if only_after_calls and not _tally.calls:
        return None
    line = _tally.line(_scenario.name)
    _tally.clear()
    return line


def wait_between_passes() -> float:
    """Seconds ``agac run --wait`` waits between two passes when ``--poll`` is not given.

    No time, since the mock answers at once. While the scenario holds each batch for
    ``complete_after_seconds``, that time, at most one second: with no wait the passes
    would repeat without a pause until the time is up.
    """
    held = _scenario.batch.complete_after_seconds if _scenario is not None else 0.0
    return min(1.0, held)


def flag() -> str:
    """The flag a printed command needs to act on this run's output: ``" --sandbox"`` or ``""``."""
    return " --sandbox" if _active else ""


def run_flags() -> str:
    """``flag()``, and the ``--scenario`` given, for a printed ``agac run`` or ``agac retry``."""
    if _active and _scenario_flag is not None:
        return f"{flag()} --scenario {shlex.quote(_scenario_flag)}"
    return flag()


def run_dir(io_dir: Path) -> Path:
    """The folder that holds a run's ``target/``, ``logs/`` and status file."""
    return io_dir / SANDBOX_DIR if _active else io_dir


def status_file(io_dir: Path) -> Path:
    return run_dir(io_dir) / STATUS_FILE_NAME


def store_file(io_dir: Path, workflow_name: str) -> Path:
    suffix = SANDBOX_STORE_SUFFIX if _active else ".db"
    return io_dir / "store" / f"{workflow_name}{suffix}"


def is_sandbox_store(path: Path) -> bool:
    """True when *path* is a store ``store_file`` names for a sandbox run."""
    return path.name.endswith(SANDBOX_STORE_SUFFIX)


def point_at_mock(action_configs: dict[str, dict[str, Any]]) -> dict[str, str | None]:
    """Send each LLM action to the mock and approve each HITL review.

    Returns each LLM action with the base name of its version group, or None. The model
    name stays, for display. Tool actions and the other kinds are left as they are.
    """
    mocked: dict[str, str | None] = {}
    for name, config in action_configs.items():
        kind = config.get("kind") or DEFAULT_ACTION_KIND
        kind = getattr(kind, "value", kind)
        if kind == DEFAULT_ACTION_KIND:
            config[MODEL_VENDOR_KEY] = SANDBOX_VENDOR
            group = config.get("version_base_name") if config.get("is_versioned_agent") else None
            mocked[name] = group if isinstance(group, str) and group else None
        elif kind == "hitl":
            config[AUTO_APPROVE_KEY] = True
    return mocked
