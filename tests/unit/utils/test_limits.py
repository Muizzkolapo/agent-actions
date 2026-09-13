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


class TestTheEnvironmentCeiling:
    """AGAC_MAX_RECORDS caps a run from outside the project's config."""

    def test_it_caps_a_larger_configured_limit(self, monkeypatch):
        monkeypatch.setenv("AGAC_MAX_RECORDS", "2")

        assert effective_record_limit({"record_limit": 23}) == 2

    def test_it_does_not_raise_a_smaller_configured_limit(self, monkeypatch):
        monkeypatch.setenv("AGAC_MAX_RECORDS", "50")

        assert effective_record_limit({"record_limit": 3}) == 3

    def test_it_applies_where_the_config_sets_no_limit(self, monkeypatch):
        monkeypatch.setenv("AGAC_MAX_RECORDS", "2")

        assert effective_record_limit({}) == 2

    def test_an_unset_variable_leaves_the_config_alone(self, monkeypatch):
        monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)

        assert effective_record_limit({"record_limit": 23}) == 23

    @pytest.mark.parametrize("value", ["nonsense", "", "0", "-1", "2.5"])
    def test_a_value_that_cannot_be_a_ceiling_is_refused_loudly(self, monkeypatch, value):
        monkeypatch.setenv("AGAC_MAX_RECORDS", value)

        with pytest.raises(ValueError, match="AGAC_MAX_RECORDS"):
            effective_record_limit({"record_limit": 23})

    def test_an_active_ceiling_says_so(self, monkeypatch, caplog):
        monkeypatch.setenv("AGAC_MAX_RECORDS", "2")

        with caplog.at_level("WARNING"):
            effective_record_limit({"record_limit": 23})

        assert any("AGAC_MAX_RECORDS" in r.message for r in caplog.records), (
            "a truncated run must announce itself"
        )
