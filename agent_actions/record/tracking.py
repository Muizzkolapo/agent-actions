"""TrackedItem — dict subclass with hidden provenance for FILE mode tools."""

from __future__ import annotations

from typing import Any, TypeGuard


class TrackedItem(dict):
    """Dict subclass that carries provenance. User treats it as a normal dict.

    Framework wraps each input item before calling a FILE tool.
    User code accesses fields normally: item["question_text"].
    Framework reads _source_index after tool returns to map output to input.

    If user does {**item}, _source_index is lost (plain dict created).
    Framework detects this and raises ValueError.
    """

    def __init__(self, data: dict[str, Any], source_index: int):
        super().__init__(data)
        self._source_index = source_index


def is_input_position(value: Any, count: int | None = None) -> TypeGuard[int]:
    """Whether *value* names a position in an input list of *count* records.

    A ``bool`` is refused although it is an ``int``: ``True`` would name position
    1, a real row and the wrong one. Omit *count* where the upper bound is
    unknown, which is all the declaring boundary can check.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return False
    return count is None or value < count
