"""TrackedItem — dict subclass with hidden provenance for FILE mode tools."""

from __future__ import annotations

from typing import Any


class TrackedItem(dict):
    """Dict subclass that carries provenance. User treats it as a normal dict.

    Framework wraps each input item before calling a FILE tool.
    User code accesses fields normally: item["question_text"].
    Framework reads _source_index after tool returns to map output to input.

    If user does {**item}, _source_index is lost (plain dict created).
    Framework detects this and raises ValueError.
    """

    __slots__ = ("_source_index",)

    def __init__(self, data: dict[str, Any], source_index: int):
        super().__init__(data)
        self._source_index = source_index
