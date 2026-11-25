"""Choose the records a filtered ``--rerun`` answers again, from what an action stored."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

from agent_actions.input.preprocessing.filtering.guard_filter import (
    FilterItemRequest,
    get_global_guard_filter,
)

# The disposition a selected record is planned under: it did not fail, it was chosen.
SELECTED = "selected"


@dataclass(frozen=True)
class RecordFilter:
    """Which records of an action to answer again: a guard expression, ids, or both."""

    where: str | None = None
    record_ids: tuple[str, ...] | None = None
    # Where the ids were read from, for messages.
    records_from: str | None = None


@dataclass
class Selection:
    """The records a filter matched at an action, and the records its rerun names.

    *matched* are rows the action stored. *named* are the records the run narrows
    to: a matched row's own id where the action's input holds it, and otherwise the
    input records that produced it, with the row's id beside them so that what
    reads the action answers the row again even when it is written the same.
    """

    action: str
    considered: int
    # The actions the rerun starts at: the action, or each version of a versioned one.
    starts: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    named: set[str] = field(default_factory=set)
    unevaluated: int = 0
    first_error: str | None = None

    @property
    def kept(self) -> int:
        return self.considered - len(self.matched)

    def as_plan_rows(self) -> list[dict[str, Any]]:
        why = f"selected for rerun from {self.action}"
        return [
            {
                "action_name": self.starts[0] if self.starts else self.action,
                "record_id": record_id,
                "disposition": SELECTED,
                "reason": why,
            }
            for record_id in sorted(self.named)
        ]


def read_record_ids(path: str) -> tuple[str, ...]:
    """The ids *path* lists, one a line; blank lines and ``#`` comments are skipped."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise click.UsageError(
            f"--records cannot read {path}: {error.strerror or error}"
        ) from error
    ids = tuple(
        dict.fromkeys(
            line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")
        )
    )
    if not ids:
        raise click.UsageError(f"--records names no record: {path} holds no id.")
    return ids


def refuse_an_expression_that_does_not_parse(where: str) -> None:
    """Refuse a ``--where`` that is not a guard expression, before anything is read."""
    parsed = get_global_guard_filter().parser.parse(where)
    if not parsed.success:
        detail = parsed.error.message if parsed.error is not None else "not an expression"
        raise click.UsageError(
            f"--where is not a guard expression: {detail}. "
            "Write it as a guard condition, e.g. --where 'classify.label == \"other\"'"
        )


def select_records(
    rows: Iterable[dict[str, Any]],
    action: str,
    record_filter: RecordFilter,
    held_by_input: Callable[[Sequence[str]], set[str]],
) -> Selection:
    """The records of *rows* (what *action* stored) that *record_filter* matches.

    *held_by_input* tells which of the ids it is given are records *action* takes
    as input. A matched row whose id the input holds is named by it. One the action
    made from other records is named by those, since the action can only be run on
    what it reads. A row that resolves to no input record is refused: naming it
    would clear and re-answer below the action while the action itself ran nothing.
    """
    stored = [row for row in rows if isinstance(row, dict) and row.get("source_guid")]
    # A versioned action stores one row a version for each record.
    selection = Selection(action=action, considered=len({row["source_guid"] for row in stored}))
    wanted = set(record_filter.record_ids or ())
    found: set[str] = set()
    matched_rows: list[dict[str, Any]] = []
    chosen: set[str] = set()
    for row in stored:
        guid = row["source_guid"]
        if wanted:
            named_by = {guid, *_producers(row)} & wanted
            if not named_by:
                continue
            found |= named_by
        if record_filter.where and not _matches(row, record_filter.where, selection):
            continue
        if guid not in chosen:
            chosen.add(guid)
            matched_rows.append(row)

    unknown = sorted(wanted - found)
    if unknown:
        shown = ", ".join(unknown[:5]) + (
            f" and {len(unknown) - 5} more" if len(unknown) > 5 else ""
        )
        listed = record_filter.records_from or "--records"
        raise click.ClickException(
            f"{len(unknown)} of the {len(wanted)} id(s) in {listed} "
            f"name no record that '{action}' stored or was made from: {shown}. "
            f"List the ids with: agac records -A {action}"
        )
    if record_filter.where and stored and selection.unevaluated == len(stored):
        raise click.ClickException(
            f"--where could not be evaluated on any record of '{action}': {selection.first_error}"
        )

    candidates = [row["source_guid"] for row in matched_rows]
    candidates += [producer for row in matched_rows for producer in _producers(row)]
    in_input = held_by_input(list(dict.fromkeys(candidates)))
    unresolved: list[str] = []
    for row in matched_rows:
        guid = row["source_guid"]
        selection.matched.append(guid)
        if guid in in_input:
            selection.named.add(guid)
            continue
        producers = _producers(row)
        if producers and set(producers) <= in_input:
            selection.named.update(producers)
            selection.named.add(guid)
        else:
            unresolved.append(guid)
    if unresolved:
        raise click.ClickException(
            f"{len(unresolved)} matched record(s) of '{action}' cannot be traced to a record "
            f"it reads (first: {unresolved[0]}), so '{action}' cannot be run again for them. "
            "Rerun from the action that reads them instead."
        )
    return selection


def _producers(row: dict[str, Any]) -> list[str]:
    """The records *row* was made from, when the action that stored it minted its id."""
    made_by = row.get("producer_source_guids")
    if isinstance(made_by, list) and made_by:
        return [str(guid) for guid in made_by]
    parent = row.get("parent_source_guid")
    return [str(parent)] if parent else []


def _matches(row: dict[str, Any], where: str, selection: Selection) -> bool:
    content = row.get("content")
    if not isinstance(content, dict):
        selection.unevaluated += 1
        return False
    result = get_global_guard_filter().filter_item(
        FilterItemRequest(data=content, condition=where)
    )
    if not result.success:
        # A record without the field is not a match, as a guard would read it.
        selection.unevaluated += 1
        selection.first_error = selection.first_error or result.error
        return False
    return bool(result.matched)
