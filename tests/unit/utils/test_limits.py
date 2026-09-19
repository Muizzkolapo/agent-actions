"""The per-action record limit is resolved in one place."""

from __future__ import annotations

import pytest

from agent_actions.utils.limits import (
    RECORD_LIMIT_KEY,
    record_indices_to_process,
    records_kept_by_limit,
    records_this_action_has_output_for,
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


class TestRecordIndicesToProcess:
    """The one place a limit both slices and announces, so the two cannot drift."""

    def test_a_limit_that_drops_records_returns_their_indices(self):
        assert record_indices_to_process(_records(6), {"record_limit": 2}, "flatten") == [0, 1]

    def test_a_limit_that_drops_nothing_returns_none(self):
        """None rather than every index: the caller then neither re-slices nor
        announces a truncation that did not happen."""
        assert record_indices_to_process(_records(6), {"record_limit": 10}, "flatten") is None

    def test_a_limit_exactly_the_record_count_returns_none(self):
        assert record_indices_to_process(_records(6), {"record_limit": 6}, "flatten") is None

    def test_no_limit_at_all_returns_none(self):
        assert record_indices_to_process(_records(6), {}, "flatten") is None

    def test_records_that_are_not_a_list_are_left_alone(self):
        assert record_indices_to_process("not a list", {"record_limit": 2}, "flatten") is None

    def test_a_retried_record_beyond_the_limit_is_admitted(self):
        kept = record_indices_to_process(
            _records(6), {"record_limit": 2}, "flatten", frozenset({"r4"})
        )
        assert kept == [0, 1, 4]

    def test_a_retry_that_admits_everything_returns_none(self):
        """Nothing was dropped, so there is nothing to announce."""
        retried = frozenset({f"r{i}" for i in range(6)})
        assert record_indices_to_process(_records(6), {"record_limit": 2}, "flatten", retried) is (
            None
        )


class TestWhatATruncationAnnounces:
    def test_a_limit_from_the_environment_warns(self, monkeypatch, caplog):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        with caplog.at_level("DEBUG", logger="agent_actions.utils.limits"):
            record_indices_to_process(_records(6), {}, "flatten")

        (record,) = caplog.records
        assert record.levelname == "WARNING"
        assert "AGAC_RECORD_LIMIT" in record.message
        assert "2 of 6" in record.message
        assert "flatten" in record.message

    def test_a_limit_from_the_flag_warns_and_names_itself(self, caplog):
        with caplog.at_level("DEBUG", logger="agent_actions.utils.limits"):
            record_indices_to_process(_records(6), {RECORD_LIMIT_KEY: 2}, "flatten")

        (record,) = caplog.records
        assert record.levelname == "WARNING"
        assert "--record-limit" in record.message
        assert "AGAC_RECORD_LIMIT" not in record.message

    def test_the_config_own_limit_is_not_a_warning(self, caplog):
        """The run behaving as written is not news."""
        with caplog.at_level("DEBUG", logger="agent_actions.utils.limits"):
            record_indices_to_process(_records(6), {"record_limit": 2}, "flatten")

        (record,) = caplog.records
        assert record.levelname == "INFO"

    @pytest.mark.parametrize("config", [{"record_limit": 10}, {"record_limit": 6}, {}])
    def test_dropping_nothing_says_nothing(self, monkeypatch, caplog, config):
        """The announcement exists because a truncated run looks complete. One
        that fires when nothing was dropped spends that signal."""
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)

        with caplog.at_level("DEBUG", logger="agent_actions.utils.limits"):
            record_indices_to_process(_records(6), config, "flatten")

        assert caplog.records == [], [r.message for r in caplog.records]


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


class TestEveryRowOfAnIdentityIsAdmitted:
    """`source_guid` is a content hash, so byte-identical records share one — and
    three identical staged records really are three stored rows, measured. Keeping
    a single position for them writes one row where three stood."""

    def test_a_second_row_of_a_kept_identity_is_still_admitted(self):
        records = [{"source_guid": "r0"}, {"source_guid": "r1"}, {"source_guid": "r1"}]

        assert records_kept_by_limit(records, 2, frozenset({"r1"})) == [0, 1, 2]

    def test_every_copy_past_the_limit_is_admitted(self):
        records = [{"source_guid": "r0"}, {"source_guid": "r1"}, {"source_guid": "r1"}]

        assert records_kept_by_limit(records, 1, frozenset({"r1"})) == [0, 1, 2]

    def test_an_identity_not_in_the_set_is_still_dropped(self):
        """The control: admitting every copy must not become admitting everything."""
        records = [{"source_guid": "r0"}, {"source_guid": "r1"}, {"source_guid": "r1"}]

        assert records_kept_by_limit(records, 1, frozenset({"absent"})) == [0]

    def test_a_limit_below_one_keeps_nothing_by_position(self):
        """The resolver never returns one, but the helper is shared
        and a negative would index from the end."""
        records = [{"source_guid": f"r{i}"} for i in range(5)]
        assert records_kept_by_limit(records, -1) == []
        # r4 is last, so a range starting at -1 reaches it twice.
        assert records_kept_by_limit(records, -1, frozenset({"r4"})) == [4]


class _Backend:
    """Only what the lookup asks of a backend, plus a count of the asking."""

    def __init__(self, guids_by_action):
        self._guids = guids_by_action
        self.calls = 0

    def target_source_guids(self, action_name):
        self.calls += 1
        return frozenset(self._guids.get(action_name, ()))


class TestRecordsThisActionHasOutputFor:
    """Collection itself belongs to the backend and is tested there. What lives
    here is that the answer is asked for once and survives a missing backend."""

    def test_it_returns_what_the_action_holds(self):
        assert records_this_action_has_output_for(
            _Backend({"act": ["g0", "g1"]}), "act"
        ) == frozenset({"g0", "g1"})

    def test_no_backend_means_nothing_is_known_to_be_stored(self):
        assert records_this_action_has_output_for(None, "act") == frozenset()

    def test_an_action_is_asked_once_however_many_files_ask(self):
        """The caller asks per input file. Asking the store each time is
        quadratic in files, and every read after the first is of a store this
        run has already begun writing to."""
        backend = _Backend({"act": ["g0"]})

        for _ in range(5):
            records_this_action_has_output_for(backend, "act")

        assert backend.calls == 1

    def test_each_action_is_asked_for_separately(self):
        backend = _Backend({"a": ["g0"], "b": ["g1"]})

        assert records_this_action_has_output_for(backend, "a") == frozenset({"g0"})
        assert records_this_action_has_output_for(backend, "b") == frozenset({"g1"})
        assert backend.calls == 2

    def test_two_backends_do_not_share_an_answer(self):
        """The cache is keyed on the backend, so a second run in the same
        process reads its own store rather than the previous one's."""
        first = _Backend({"act": ["g0"]})
        second = _Backend({"act": ["g1", "g2"]})

        records_this_action_has_output_for(first, "act")

        assert records_this_action_has_output_for(second, "act") == frozenset({"g1", "g2"})


class TestRepairingWithoutAStore:
    """Without a backend only the named records can be spared, which is the
    behaviour the stored-row rule replaces. It must not happen quietly."""

    def test_it_says_so(self, caplog):
        records = [{"source_guid": f"r{i}"} for i in range(6)]

        with caplog.at_level("WARNING", logger="agent_actions.utils.limits"):
            record_indices_to_process(
                records, {"record_limit": 1}, "flatten", retried=frozenset({"r5"})
            )

        said = " ".join(r.getMessage() for r in caplog.records)
        assert "flatten" in said, said
        assert "storage backend" in said, said

    def test_it_still_spares_the_named_records(self, caplog):
        records = [{"source_guid": f"r{i}"} for i in range(6)]

        with caplog.at_level("WARNING", logger="agent_actions.utils.limits"):
            kept = record_indices_to_process(
                records, {"record_limit": 1}, "flatten", retried=frozenset({"r5"})
            )

        assert kept == [0, 5]

    def test_a_run_that_is_not_repairing_says_nothing(self, caplog):
        """The control: a normal run has no backend to miss."""
        records = [{"source_guid": f"r{i}"} for i in range(6)]

        with caplog.at_level("WARNING", logger="agent_actions.utils.limits"):
            record_indices_to_process(records, {"record_limit": 1}, "flatten")

        assert [r.getMessage() for r in caplog.records if "storage backend" in r.getMessage()] == []
