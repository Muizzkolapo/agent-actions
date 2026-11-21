"""Token usage accounting: what every model call of an action used, summed.

`record_usage` is the one place an online call is counted and `record_batch` the one place
a batch's results are. Both add to the ledger the executor opened for the action
(`accounting`), under the kind in force (`counted_as`), per kind, pricing and model. The
ledger is reached through a context variable: a record thread or a side-call copy runs in
a copy of the context and adds to the same ledger, which locks.

The sums are kept in the workflow's store, so the runs that submit and collect one batch
add up; a batch is stored under its id by the run that reads it first.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

MAIN = "main"
REPAIR = "repair"
UNKNOWN_MODEL = "unknown"

# ``input_tokens`` is the prompt the vendor neither read from nor wrote to its cache, as
# Anthropic reports it: the three input fields are disjoint and add up to the prompt.
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
USAGE_FIELDS = ("calls", *TOKEN_FIELDS)

_STORE_PREFIX = "usage:"
_SAVE_EVERY_SECONDS = 10.0

Row = dict[str, Any]


def _in_report_order(key: tuple[str, bool, str]) -> tuple[int, str, bool, str]:
    """An action's own calls first, then its repairs, then each side call by name."""
    kind, batch, model = key
    return ({MAIN: 0, REPAIR: 1}.get(kind, 2), kind, batch, model)


def totals(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """The sum of *rows*, as the five usage fields."""
    total = dict.fromkeys(USAGE_FIELDS, 0)
    for row in rows:
        for field in USAGE_FIELDS:
            total[field] += int(row.get(field) or 0)
    return total


def merged(rows: Iterable[Mapping[str, Any]]) -> list[Row]:
    """*rows* with those of one kind, pricing and model added together, in a stable order."""
    groups: dict[tuple[str, bool, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = (str(row["kind"]), bool(row["batch"]), str(row["model"]))
        groups.setdefault(key, []).append(row)
    return [
        {"kind": kind, "batch": batch, "model": model, **totals(group)}
        for (kind, batch, model), group in sorted(
            groups.items(), key=lambda item: _in_report_order(item[0])
        )
    ]


def summarised(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The total of *rows* and, under ``by_kind``, the sum per kind, pricing and model."""
    by_kind = merged(rows)
    return {**totals(by_kind), "by_kind": by_kind}


def prompt_and_completion(rows: Iterable[Mapping[str, Any]]) -> dict[str, int] | None:
    """*rows* as the run line counts tokens: the whole prompt, the output and their sum."""
    total = totals(rows)
    prompt = (
        total["input_tokens"]
        + total["cache_read_input_tokens"]
        + total["cache_creation_input_tokens"]
    )
    if not prompt and not total["output_tokens"]:
        return None
    return {
        "input_tokens": prompt,
        "output_tokens": total["output_tokens"],
        "total_tokens": prompt + total["output_tokens"],
    }


class UsageLedger:
    """What one action's calls used in one run of the workflow.

    With a *run_id* and a *backend* the sums are stored: the online calls under the run,
    every few seconds and on `save`, and each batch under its id as it is counted.
    """

    def __init__(self, action_name: str, run_id: str | None = None, backend: Any = None) -> None:
        self.action_name = action_name
        self._run_id = run_id
        self._backend = backend if run_id else None
        self._rows: dict[tuple[str, bool, str], dict[str, int]] = {}
        self._batches: set[str] = set()
        self._lock = threading.Lock()
        # Held from reading the rows to writing them, so an older sum never lands last.
        self._store_lock = threading.Lock()
        self._saved_at = time.monotonic()

    def add(
        self,
        kind: str,
        model: str | None,
        usage: Mapping[str, int],
        *,
        batch: bool = False,
        calls: int = 1,
    ) -> None:
        with self._lock:
            row = self._rows.setdefault(
                (kind, batch, model or UNKNOWN_MODEL), dict.fromkeys(USAGE_FIELDS, 0)
            )
            row["calls"] += calls
            for field in TOKEN_FIELDS:
                row[field] += int(usage.get(field) or 0)
        if time.monotonic() - self._saved_at >= _SAVE_EVERY_SECONDS:
            self.save()

    def add_batch(
        self, batch_id: str, kind: str, model: str | None, usage: Mapping[str, int], calls: int
    ) -> None:
        """Count the results of *batch_id*, unless this or an earlier run has counted them."""
        with self._store_lock:
            if batch_id in self._batches:
                return
            self._batches.add(batch_id)
            if self._backend is not None:
                key = f"{_STORE_PREFIX}{self.action_name}:batch:{batch_id}"
                row = {
                    "kind": kind,
                    "batch": True,
                    "model": model or UNKNOWN_MODEL,
                    "calls": calls,
                    **{field: int(usage.get(field) or 0) for field in TOKEN_FIELDS},
                }
                try:
                    if isinstance(self._backend.load_metadata(key), str):
                        return
                    self._backend.save_metadata(key, self._entry([row], batch_id=batch_id))
                except Exception as error:
                    self._warn_not_stored(error)
        self.add(kind, model, usage, batch=True, calls=calls)

    def rows(self) -> list[Row]:
        """The sums so far, one row per kind, pricing and model."""
        with self._lock:
            return [
                {"kind": kind, "batch": batch, "model": model, **row}
                for (kind, batch, model), row in sorted(
                    self._rows.items(), key=lambda item: _in_report_order(item[0])
                )
            ]

    def save(self) -> None:
        """Store the run's online calls of the action; a batch is stored as it is counted."""
        if self._backend is None:
            return
        with self._store_lock:
            self._saved_at = time.monotonic()
            online = [row for row in self.rows() if not row["batch"]]
            if not online:
                return
            key = f"{_STORE_PREFIX}{self.action_name}:run:{self._run_id}"
            try:
                self._backend.save_metadata(key, self._entry(online))
            except Exception as error:
                self._warn_not_stored(error)

    def _entry(self, rows: list[Row], **extra: str) -> str:
        return json.dumps(
            {"action": self.action_name, "run_id": self._run_id, **extra, "rows": rows}
        )

    def _warn_not_stored(self, error: Exception) -> None:
        logger.warning(
            "Could not store the token usage of %s: %s. The run goes on; "
            "the stored sums will not hold these calls",
            self.action_name,
            error,
        )


_ledger: ContextVar[UsageLedger | None] = ContextVar("_usage_ledger", default=None)
_kind: ContextVar[str] = ContextVar("_usage_kind", default=MAIN)


@contextmanager
def accounting(ledger: UsageLedger) -> Iterator[UsageLedger]:
    """Count the calls made inside the block on *ledger*, and no call made outside it."""
    token = _ledger.set(ledger)
    try:
        yield ledger
    finally:
        _ledger.reset(token)


@contextmanager
def counted_as(kind: str) -> Iterator[None]:
    """Count the calls made inside the block as *kind*."""
    token = _kind.set(kind)
    try:
        yield
    finally:
        _kind.reset(token)


def record_usage(usage: Mapping[str, int], *, model: str | None) -> None:
    """Count one online call, keyed as `TOKEN_FIELDS`; outside an action, nothing."""
    ledger = _ledger.get()
    if ledger is not None:
        ledger.add(_kind.get(), model, usage)


def record_batch(
    batch_id: str, usage: Mapping[str, int], *, calls: int, kind: str, model: str | None
) -> None:
    """Count what the results of one batch used, once however often the batch is read."""
    ledger = _ledger.get()
    if ledger is not None and calls:
        ledger.add_batch(batch_id, kind, model, usage, calls)


def forget_usage(backend: Any) -> None:
    """Delete every entry the workflow's runs stored."""
    backend.delete_metadata_prefix(_STORE_PREFIX)


def stored_usage(backend: Any) -> list[dict[str, Any]]:
    """Every entry the workflow's runs stored: ``action``, ``run_id`` and its ``rows``."""
    entries = []
    for key in backend.list_metadata_prefix(_STORE_PREFIX):
        raw = backend.load_metadata(key)
        try:
            entry = json.loads(raw) if raw else None
        except ValueError:
            entry = None
        if not isinstance(entry, dict) or not isinstance(entry.get("rows"), list):
            logger.warning("The stored usage entry %s cannot be read and is left out", key)
            continue
        entries.append(entry)
    return entries
