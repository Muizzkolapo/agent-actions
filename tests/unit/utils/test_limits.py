"""The per-action record limit is resolved in one place."""

from __future__ import annotations

import pytest

from agent_actions.utils.limits import effective_record_limit


class TestEffectiveRecordLimit:
    def test_a_configured_limit_is_returned(self):
        assert effective_record_limit({"record_limit": 23}) == 23

    def test_an_absent_limit_is_unlimited(self):
        assert effective_record_limit({}) is None

    @pytest.mark.parametrize("value", [None, 0, -1, "23", 23.0, True])
    def test_a_value_that_cannot_cap_anything_is_unlimited(self, value):
        assert effective_record_limit({"record_limit": value}) is None
