"""The `on_empty: error` and `terminal_failure` halts finish the collect pass first.

Both are raised once their file is written, like `on_exhausted: raise`. Stopping at once
left a sibling file's finished batch uncollected until the next run.
"""

import pytest

from agent_actions.errors.base import terminal_failure
from agent_actions.errors.processing import EmptyOutputError

from .test_pass_finishes_before_halt import _service


def test_a_sibling_after_an_empty_output_halt_is_still_collected():
    service, visited = _service(
        ["a.json", "b.json"],
        {"a.json": EmptyOutputError("empty output (on_empty=error)"), "b.json": "/out/b.json"},
    )

    with pytest.raises(EmptyOutputError):
        service.process_all_batch_results("/out", {}, "act")

    assert visited == ["a.json", "b.json"]


def test_a_sibling_after_a_terminal_failure_is_still_collected():
    service, visited = _service(
        ["a.json", "b.json"],
        {"a.json": terminal_failure("nothing succeeded"), "b.json": "/out/b.json"},
    )

    with pytest.raises(RuntimeError, match="nothing succeeded"):
        service.process_all_batch_results("/out", {}, "act")

    assert visited == ["a.json", "b.json"]
