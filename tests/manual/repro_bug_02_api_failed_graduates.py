"""Reproduce bug 074: API-failed records graduate validation.

When a BatchResult has success=False, ValidationStrategy.evaluate() returns
True — graduating the record without running the validation UDF.  These
records carry empty/corrupt content but appear in final output as validated.

Expected: success=False records land in still_failing, not graduated.

Run:
    python tests/manual/repro_bug_02_api_failed_graduates.py
"""

from unittest.mock import MagicMock

from agent_actions.processing.evaluation.loop import EvaluationLoop
from agent_actions.processing.evaluation.strategies.validation import ValidationStrategy


def _make_result(custom_id, content=None, success=True):
    r = MagicMock()
    r.custom_id = custom_id
    r.content = content
    r.success = success
    r.recovery_metadata = None
    return r


def main():
    strategy = ValidationStrategy(
        validation_func=lambda resp: isinstance(resp, dict) and "text" in resp,
        feedback_message="Must contain 'text' key",
    )
    loop = EvaluationLoop(strategy)

    results = [
        _make_result("ok-1", content={"text": "hello"}, success=True),
        _make_result("api-fail-1", content=None, success=False),
        _make_result("api-fail-2", content=None, success=False),
        _make_result("ok-2", content={"text": "world"}, success=True),
    ]

    graduated, still_failing = loop.split(results)

    grad_ids = [r.custom_id for r in graduated]
    fail_ids = [r.custom_id for r in still_failing]

    print(f"Graduated:     {grad_ids}")
    print(f"Still failing: {fail_ids}")

    # Correct behavior: API failures should NOT graduate
    api_fail_graduated = [r for r in graduated if not r.success]
    if api_fail_graduated:
        print(
            f"\nBUG CONFIRMED: {len(api_fail_graduated)} API-failed record(s) "
            "graduated without validation!"
        )
        return 1

    print("\nFIXED: API-failed records correctly routed to still_failing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
