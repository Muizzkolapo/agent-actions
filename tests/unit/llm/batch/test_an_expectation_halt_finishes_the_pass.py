"""An expectation halt finishes the collect pass the way a retry-exhaustion halt does.

The repair loop's `on_exhausted: raise` raises `ExpectationsExhaustedError`, which carries
the same policy tag a retry-exhaustion halt does. Both are the same deliberate stop, so
neither may strand a sibling file's finished batch.
"""

import pytest

from agent_actions.expectations.service import ExpectationsExhaustedError

from .test_pass_finishes_before_halt import _service


def test_a_sibling_after_an_expectation_halt_is_still_collected():
    service, visited = _service(
        ["a.json", "b.json"],
        {"a.json": ExpectationsExhaustedError("act", ["enough"], 2), "b.json": "/out/b.json"},
    )

    with pytest.raises(ExpectationsExhaustedError):
        service.process_all_batch_results("/out", {}, "act")

    assert visited == ["a.json", "b.json"]


def test_an_expectation_halt_on_the_only_file_is_raised_not_masked():
    service, _ = _service(["a.json"], {"a.json": ExpectationsExhaustedError("act", ["enough"], 2)})

    with pytest.raises(ExpectationsExhaustedError):
        service.process_all_batch_results("/out", {}, "act")
