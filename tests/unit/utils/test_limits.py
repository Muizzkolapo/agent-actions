"""The per-action record limit is resolved in one place."""

from __future__ import annotations

import pytest

from agent_actions.utils.limits import (
    RECORD_LIMIT_KEY,
    announce_truncation,
    records_kept_by_limit,
    resolve_record_limit,
)


class TestResolveRecordLimit:
    def test_a_configured_limit_is_returned(self):
        assert resolve_record_limit({"record_limit": 23})[0] == 23

    def test_an_absent_limit_is_unlimited(self):
        assert resolve_record_limit({})[0] is None

    @pytest.mark.parametrize("value", [None, 0, -1, "23", 23.0, True])
    def test_a_value_that_cannot_cap_anything_is_unlimited(self, value):
        assert resolve_record_limit({"record_limit": value})[0] is None


class TestTheRetiredEnvironmentName:
    """AGAC_MAX_RECORDS was renamed; reading it is an error, not a no-op."""

    def test_it_is_refused_and_names_its_replacement(self, monkeypatch):
        monkeypatch.setenv("AGAC_MAX_RECORDS", "2")

        with pytest.raises(ValueError, match="AGAC_RECORD_LIMIT"):
            resolve_record_limit({"record_limit": 23})

    def test_it_is_refused_even_when_the_run_asked_for_its_own_limit(self, monkeypatch):
        monkeypatch.setenv("AGAC_MAX_RECORDS", "2")

        with pytest.raises(ValueError, match="AGAC_RECORD_LIMIT"):
            resolve_record_limit({"record_limit": 23, RECORD_LIMIT_KEY: 5})

    def test_the_new_name_alone_is_fine(self, monkeypatch):
        monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        assert resolve_record_limit({"record_limit": 23})[0] == 2


class TestTheEnvironmentLimit:
    """AGAC_RECORD_LIMIT caps a run from outside the project's config."""

    def test_it_caps_a_larger_configured_limit(self, monkeypatch):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        assert resolve_record_limit({"record_limit": 23})[0] == 2

    def test_it_does_not_raise_a_smaller_configured_limit(self, monkeypatch):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "50")

        assert resolve_record_limit({"record_limit": 3})[0] == 3

    def test_it_applies_where_the_config_sets_no_limit(self, monkeypatch):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        assert resolve_record_limit({})[0] == 2

    def test_an_unset_variable_leaves_the_config_alone(self, monkeypatch):
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)

        assert resolve_record_limit({"record_limit": 23})[0] == 23

    @pytest.mark.parametrize("value", ["nonsense", "", "0", "-1", "2.5"])
    def test_a_value_that_cannot_be_a_limit_is_refused_loudly(self, monkeypatch, value):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", value)

        with pytest.raises(ValueError, match="AGAC_RECORD_LIMIT"):
            resolve_record_limit({"record_limit": 23})

    def test_it_is_named_as_the_source_when_it_wins(self, monkeypatch):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        assert resolve_record_limit({"record_limit": 23})[1] == "AGAC_RECORD_LIMIT"


class TestTheRunCeiling:
    """A cap asked for on the command line, carried on the action's config."""

    def test_it_caps_a_larger_configured_limit(self):
        assert resolve_record_limit({"record_limit": 23, RECORD_LIMIT_KEY: 2})[0] == 2

    def test_it_does_not_raise_a_smaller_configured_limit(self):
        assert resolve_record_limit({"record_limit": 3, RECORD_LIMIT_KEY: 50})[0] == 3

    def test_it_applies_where_the_config_sets_no_limit(self):
        assert resolve_record_limit({RECORD_LIMIT_KEY: 2})[0] == 2

    def test_it_wins_over_the_environment_variable(self, monkeypatch):
        """Typed for this run, so more specific than ambient configuration."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "50")

        assert resolve_record_limit({"record_limit": 23, RECORD_LIMIT_KEY: 2})[0] == 2

    def test_it_wins_even_when_the_variable_is_stricter(self, monkeypatch):
        """Precedence is by source, not by which number is smaller — otherwise
        ambient state could silently overrule what was asked for."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        assert resolve_record_limit({"record_limit": 23, RECORD_LIMIT_KEY: 10})[0] == 10

    def test_an_absent_run_limit_leaves_the_variable_in_charge(self, monkeypatch):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        assert resolve_record_limit({"record_limit": 23})[0] == 2

    @pytest.mark.parametrize("value", [0, -1, "2", 2.5, True])
    def test_a_value_that_cannot_be_a_limit_is_refused_loudly(self, value):
        with pytest.raises(ValueError, match="record-limit"):
            resolve_record_limit({"record_limit": 23, RECORD_LIMIT_KEY: value})

    def test_a_null_cap_reads_as_no_cap(self, monkeypatch):
        """An absent key and an explicit None are the same lookup, so a null
        cannot be refused without also refusing every run that asked for none."""
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)

        assert resolve_record_limit({"record_limit": 23, RECORD_LIMIT_KEY: None})[0] == 23

    def test_it_is_named_as_the_source_when_it_outranks_the_variable(self, monkeypatch):
        """Whatever actually capped the run is what a caller can name."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "5")

        assert resolve_record_limit({"record_limit": 23, RECORD_LIMIT_KEY: 2})[1] == (
            "--record-limit"
        )


class TestTheTwoSourcesTogether:
    def test_an_unusable_variable_fails_the_run_even_when_a_flag_outranks_it(self, monkeypatch):
        """The variable's guarantee is that it is never ignored. A flag winning
        the precedence is not the same as the variable going unread."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "nonsense")

        with pytest.raises(ValueError, match="AGAC_RECORD_LIMIT"):
            resolve_record_limit({"record_limit": 23, RECORD_LIMIT_KEY: 2})

    @pytest.mark.parametrize("value", ["0", "-1", "2.5"])
    def test_a_variable_that_cannot_cap_fails_under_a_flag_too(self, monkeypatch, value):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", value)

        with pytest.raises(ValueError, match="AGAC_RECORD_LIMIT"):
            resolve_record_limit({RECORD_LIMIT_KEY: 2})

    @pytest.mark.parametrize("configured", [0, -1, "23", True, None])
    def test_a_cap_applies_over_a_configured_limit_that_cannot_cap(self, configured):
        """Those values already mean unlimited, so the cap is what is left."""
        assert resolve_record_limit({"record_limit": configured, RECORD_LIMIT_KEY: 5})[0] == 5


class TestTheResolverIsSilent:
    """Whether records were dropped depends on how many there are, which the
    resolver never sees. Announcing from here describes a truncation that may
    not have happened."""

    @pytest.mark.parametrize(
        "config", [{"record_limit": 23}, {"record_limit": 23, RECORD_LIMIT_KEY: 2}, {}]
    )
    def test_it_never_logs(self, monkeypatch, caplog, config):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        with caplog.at_level("DEBUG", logger="agent_actions.utils.limits"):
            resolve_record_limit(config)

        assert caplog.records == [], [r.message for r in caplog.records]


class TestAnnounceTruncation:
    """The announcement a slice site makes once it knows records were dropped."""

    def test_a_limit_from_outside_the_config_warns(self, caplog):
        with caplog.at_level("DEBUG", logger="agent_actions.utils.limits"):
            announce_truncation("AGAC_RECORD_LIMIT", 2, 2, 6, "flatten")

        (record,) = caplog.records
        assert record.levelname == "WARNING"
        assert "AGAC_RECORD_LIMIT" in record.message
        assert "2 of 6" in record.message
        assert "flatten" in record.message

    def test_the_flag_warns_and_names_itself(self, caplog):
        with caplog.at_level("DEBUG", logger="agent_actions.utils.limits"):
            announce_truncation("--record-limit", 2, 2, 6, "flatten")

        (record,) = caplog.records
        assert record.levelname == "WARNING"
        assert "--record-limit" in record.message
        assert "AGAC_RECORD_LIMIT" not in record.message

    def test_the_config_own_limit_is_not_a_warning(self, caplog):
        """The run behaving as written is not news."""
        with caplog.at_level("DEBUG", logger="agent_actions.utils.limits"):
            announce_truncation("record_limit", 23, 23, 40, "flatten")

        (record,) = caplog.records
        assert record.levelname == "INFO"


def _records(count):
    return [{"source_guid": f"r{i}"} for i in range(count)]


class TestRecordsKeptByLimit:
    """A limit keeps the first N. A retry's records are admitted on top of them,
    never in place of them."""

    def test_the_first_n_are_kept(self):
        assert records_kept_by_limit(_records(6), 2) == [0, 1]

    def test_a_limit_past_the_end_keeps_everything(self):
        assert records_kept_by_limit(_records(3), 10) == [0, 1, 2]

    def test_a_retried_record_beyond_the_limit_is_admitted(self):
        retried = frozenset({"r4"})
        assert records_kept_by_limit(_records(6), 2, retried) == [0, 1, 4]

    def test_the_first_record_the_limit_excludes_is_admitted(self):
        """Index == limit is the boundary: the first record cut, and the one a
        range that starts too late would silently leave out."""
        retried = frozenset({"r2"})
        assert records_kept_by_limit(_records(6), 2, retried) == [0, 1, 2]

    def test_a_retried_record_inside_the_limit_is_not_duplicated(self):
        retried = frozenset({"r0"})
        assert records_kept_by_limit(_records(6), 2, retried) == [0, 1]

    def test_indices_come_back_in_order(self):
        retried = frozenset({"r5", "r3"})
        assert records_kept_by_limit(_records(6), 2, retried) == [0, 1, 3, 5]

    def test_a_retry_that_names_nothing_takes_only_the_first_n(self):
        assert records_kept_by_limit(_records(6), 2, frozenset()) == [0, 1]

    def test_an_unknown_id_admits_nothing(self):
        retried = frozenset({"absent"})
        assert records_kept_by_limit(_records(6), 2, retried) == [0, 1]

    def test_records_that_are_not_mappings_are_not_admitted(self):
        retried = frozenset({"r4"})
        assert records_kept_by_limit(["a", "b", "c", "d", "e"], 2, retried) == [0, 1]

    def test_a_record_with_no_guid_is_not_admitted(self):
        records = [{"source_guid": "r0"}, {"source_guid": "r1"}, {}, {"source_guid": "r3"}]
        retried = frozenset({"r3"})
        assert records_kept_by_limit(records, 2, retried) == [0, 1, 3]


class TestARecordIsAdmittedOnlyOnce:
    """`source_guid` is a content hash, so byte-identical rows share one. A retry
    names an identity; admitting it once per position would write it twice."""

    def test_a_duplicate_of_a_kept_record_is_not_admitted_again(self):
        records = [{"source_guid": "r0"}, {"source_guid": "r1"}, {"source_guid": "r1"}]
        retried = frozenset({"r1"})
        assert records_kept_by_limit(records, 2, retried) == [0, 1]

    def test_two_copies_past_the_limit_are_admitted_once(self):
        records = [{"source_guid": "r0"}, {"source_guid": "r1"}, {"source_guid": "r1"}]
        retried = frozenset({"r1"})
        assert records_kept_by_limit(records, 1, retried) == [0, 1]

    def test_a_limit_below_one_keeps_nothing_by_position(self):
        """The resolver never returns one, but the helper is shared
        and a negative would index from the end."""
        records = [{"source_guid": f"r{i}"} for i in range(5)]
        assert records_kept_by_limit(records, -1) == []
        # r4 is last, so a range starting at -1 reaches it twice.
        assert records_kept_by_limit(records, -1, frozenset({"r4"})) == [4]
