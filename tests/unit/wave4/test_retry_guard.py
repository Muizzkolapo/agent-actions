"""Test retry() decorator edge cases from Wave 4 hardening."""

import pytest

from agent_actions.input.loaders.base import retry


class TestRetryMaxAttemptsZero:
    """retry(max_attempts<=0) should invoke the function once without retrying."""

    @pytest.mark.parametrize("max_attempts", [0, -1], ids=["zero", "negative"])
    def test_non_positive_max_attempts_calls_once(self, max_attempts):
        call_count = 0

        @retry(max_attempts=max_attempts)
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

        with pytest.raises(ValueError, match="boom"):
            fn()
