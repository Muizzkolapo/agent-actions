"""Collect a framework logger's records from that logger itself.

``caplog`` reads the root logger, which a record reaches only while the
``agent_actions`` logger propagates; the suite's fixture keeps it propagating through
every logging setup (#1627). A setup also clears the handlers on ``agent_actions``, so a
handler added there is lost when a command runs in-process; one on the logger that emits
the record is not touched.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def framework_records(name: str, level: int = logging.WARNING) -> Iterator[list[logging.LogRecord]]:
    """The records the logger *name* emits at *level* or above inside the block."""
    logger = logging.getLogger(name)
    handler = _Collect()
    handler.setLevel(level)
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(level)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
