"""Test retry() decorator edge cases from Wave 4 hardening."""

from agent_actions.input.loaders.base import retry


class TestRetryMaxAttemptsZero:
    """retry(max_attempts=0) should invoke the function once without retrying."""

    def test_max_attempts_zero_calls_once(self):
        call_count = 0

        @retry(max_attempts=0)
        def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert fn() == "ok"
        assert call_count == 1

    def test_max_attempts_zero_propagates_exception(self):
        @retry(max_attempts=0)
        def fn():
            raise ValueError("boom")

        import pytest

        with pytest.raises(ValueError, match="boom"):
            fn()

    def test_max_attempts_negative_calls_once(self):
        call_count = 0

        @retry(max_attempts=-1)
        def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert fn() == "ok"
        assert call_count == 1
