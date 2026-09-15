"""The per-action record limit is resolved in one place."""

from __future__ import annotations

import pytest

from agent_actions.utils.limits import MAX_RECORDS_KEY, effective_record_limit


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


class TestTheRunCeiling:
    """A cap asked for on the command line, carried on the action's config."""

    def test_it_caps_a_larger_configured_limit(self):
        assert effective_record_limit({"record_limit": 23, MAX_RECORDS_KEY: 2}) == 2

    def test_it_does_not_raise_a_smaller_configured_limit(self):
        assert effective_record_limit({"record_limit": 3, MAX_RECORDS_KEY: 50}) == 3

    def test_it_applies_where_the_config_sets_no_limit(self):
        assert effective_record_limit({MAX_RECORDS_KEY: 2}) == 2

    def test_it_wins_over_the_environment_variable(self, monkeypatch):
        """Typed for this run, so more specific than ambient configuration."""
        monkeypatch.setenv("AGAC_MAX_RECORDS", "50")

        assert effective_record_limit({"record_limit": 23, MAX_RECORDS_KEY: 2}) == 2

    def test_it_wins_even_when_the_variable_is_stricter(self, monkeypatch):
        """Precedence is by source, not by which number is smaller — otherwise
        ambient state could silently overrule what was asked for."""
        monkeypatch.setenv("AGAC_MAX_RECORDS", "2")

        assert effective_record_limit({"record_limit": 23, MAX_RECORDS_KEY: 10}) == 10

    def test_an_absent_run_ceiling_leaves_the_variable_in_charge(self, monkeypatch):
        monkeypatch.setenv("AGAC_MAX_RECORDS", "2")

        assert effective_record_limit({"record_limit": 23}) == 2

    @pytest.mark.parametrize("value", [0, -1, "2", 2.5, True])
    def test_a_value_that_cannot_be_a_ceiling_is_refused_loudly(self, value):
        with pytest.raises(ValueError, match="max-records"):
            effective_record_limit({"record_limit": 23, MAX_RECORDS_KEY: value})

    def test_a_null_cap_reads_as_no_cap(self, monkeypatch):
        """An absent key and an explicit None are the same lookup, so a null
        cannot be refused without also refusing every run that asked for none."""
        monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)

        assert effective_record_limit({"record_limit": 23, MAX_RECORDS_KEY: None}) == 23

    def test_an_active_ceiling_names_the_flag_not_the_variable(self, caplog):
        """The message has to name what actually capped the run."""
        with caplog.at_level("WARNING"):
            effective_record_limit({"record_limit": 23, MAX_RECORDS_KEY: 2})

        said = " ".join(r.message for r in caplog.records)
        assert "--max-records" in said, said
        assert "AGAC_MAX_RECORDS" not in said, said


class TestTheTwoSourcesTogether:
    def test_an_unusable_variable_fails_the_run_even_when_a_flag_outranks_it(self, monkeypatch):
        """The variable's guarantee is that it is never ignored. A flag winning
        the precedence is not the same as the variable going unread."""
        monkeypatch.setenv("AGAC_MAX_RECORDS", "nonsense")

        with pytest.raises(ValueError, match="AGAC_MAX_RECORDS"):
            effective_record_limit({"record_limit": 23, MAX_RECORDS_KEY: 2})

    @pytest.mark.parametrize("value", ["0", "-1", "2.5"])
    def test_a_variable_that_cannot_cap_fails_under_a_flag_too(self, monkeypatch, value):
        monkeypatch.setenv("AGAC_MAX_RECORDS", value)

        with pytest.raises(ValueError, match="AGAC_MAX_RECORDS"):
            effective_record_limit({MAX_RECORDS_KEY: 2})

    @pytest.mark.parametrize("configured", [0, -1, "23", True, None])
    def test_a_cap_applies_over_a_configured_limit_that_cannot_cap(self, configured):
        """Those values already mean unlimited, so the cap is what is left."""
        assert effective_record_limit({"record_limit": configured, MAX_RECORDS_KEY: 5}) == 5


class TestSilenceWhenNothingIsTruncated:
    """The warning exists because a truncated run that says nothing looks
    complete. An untruncated run announcing truncation is the same lie."""

    def test_no_warning_without_any_ceiling(self, monkeypatch, caplog):
        monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)

        with caplog.at_level("WARNING"):
            effective_record_limit({"record_limit": 23})

        assert caplog.records == [], [r.message for r in caplog.records]

    def test_no_warning_when_the_flag_does_not_bite(self, caplog):
        with caplog.at_level("WARNING"):
            effective_record_limit({"record_limit": 3, MAX_RECORDS_KEY: 50})

        assert caplog.records == [], [r.message for r in caplog.records]

    def test_no_warning_when_the_variable_does_not_bite(self, monkeypatch, caplog):
        monkeypatch.setenv("AGAC_MAX_RECORDS", "50")

        with caplog.at_level("WARNING"):
            effective_record_limit({"record_limit": 3})

        assert caplog.records == [], [r.message for r in caplog.records]
