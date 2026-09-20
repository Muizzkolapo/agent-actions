"""The per-action record and file limits are resolved in one place."""

from __future__ import annotations

import pytest

from agent_actions.utils.limits import (
    FILE_LIMIT_KEY,
    RECORD_LIMIT_KEY,
    check_environment,
    record_indices_to_process,
    records_kept_by_limit,
    resolve_file_limit,
    resolve_record_limit,
    rows_this_action_holds_per_record,
)


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    """A developer shell exporting either variable must not decide these tests."""
    for name in ("AGAC_RECORD_LIMIT", "AGAC_FILE_LIMIT", "AGAC_MAX_RECORDS"):
        monkeypatch.delenv(name, raising=False)


class TestResolveRecordLimit:
    def test_a_configured_limit_is_returned(self):
        assert resolve_record_limit({"record_limit": 23})[0] == 23

    def test_an_absent_limit_is_unlimited(self):
        assert resolve_record_limit({})[0] is None

    @pytest.mark.parametrize("value", [None, 0, -1, "23", 23.0, True])
    def test_a_value_that_cannot_cap_anything_is_unlimited(self, value):
        assert resolve_record_limit({"record_limit": value})[0] is None


class TestResolveFileLimit:
    """The file axis reads the same precedence rules as the record axis, so a
    run is reachable from outside the project along both."""

    def test_a_configured_limit_is_returned(self):
        assert resolve_file_limit({"file_limit": 3})[0] == 3

    def test_an_absent_limit_is_unlimited(self):
        assert resolve_file_limit({})[0] is None

    @pytest.mark.parametrize("value", [None, 0, -1, "3", 3.0, True])
    def test_a_value_that_cannot_bound_anything_is_unlimited(self, value):
        assert resolve_file_limit({"file_limit": value})[0] is None

    def test_the_variable_bounds_a_larger_configured_limit(self, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "2")

        assert resolve_file_limit({"file_limit": 9})[0] == 2

    def test_the_variable_does_not_raise_a_smaller_configured_limit(self, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "9")

        assert resolve_file_limit({"file_limit": 2})[0] == 2

    def test_the_variable_applies_where_the_config_sets_none(self, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "2")

        assert resolve_file_limit({})[0] == 2

    @pytest.mark.parametrize("value", ["nonsense", "", "0", "-1", "2.5"])
    def test_a_variable_that_cannot_bound_anything_is_refused_loudly(self, monkeypatch, value):
        monkeypatch.setenv("AGAC_FILE_LIMIT", value)

        with pytest.raises(ValueError, match="AGAC_FILE_LIMIT"):
            resolve_file_limit({"file_limit": 9})

    def test_the_flag_wins_even_when_the_variable_is_stricter(self, monkeypatch):
        """Precedence is by source, not by which number is smaller."""
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")

        assert resolve_file_limit({"file_limit": 9, FILE_LIMIT_KEY: 4})[0] == 4

    def test_an_unusable_variable_fails_the_run_even_when_a_flag_outranks_it(self, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "nonsense")

        with pytest.raises(ValueError, match="AGAC_FILE_LIMIT"):
            resolve_file_limit({FILE_LIMIT_KEY: 2})

    @pytest.mark.parametrize("value", [0, -1, "2", 2.5, True])
    def test_a_flag_value_that_cannot_bound_anything_is_refused_loudly(self, value):
        with pytest.raises(ValueError, match="file-limit"):
            resolve_file_limit({FILE_LIMIT_KEY: value})

    def test_the_source_names_the_door_that_bounded_the_run(self, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "5")

        assert resolve_file_limit({"file_limit": 9})[1] == "AGAC_FILE_LIMIT"
        assert resolve_file_limit({"file_limit": 9, FILE_LIMIT_KEY: 2})[1] == "--file-limit"
        assert resolve_file_limit({"file_limit": 1})[1] == "file_limit"

    def test_it_never_logs(self, monkeypatch, caplog):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "2")

        with caplog.at_level("DEBUG", logger="agent_actions.utils.limits"):
            resolve_file_limit({"file_limit": 9})

        assert caplog.records == [], [r.message for r in caplog.records]

    def test_the_two_axes_do_not_read_each_other(self, monkeypatch):
        """One variable per axis; a record cap must not bound the walk, and a
        file bound must not slice records."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")
        monkeypatch.delenv("AGAC_FILE_LIMIT", raising=False)

        assert resolve_file_limit({})[0] is None
        assert resolve_record_limit({})[0] == 2


class TestTheEnvironmentIsCheckedBeforeTheRunStarts:
    """The walk does not consult a file limit until a file has been processed,
    so an unusable one found there leaves that action's work done and unstamped.
    """

    @pytest.mark.parametrize("value", ["nonsense", "0", "-1"])
    def test_an_unusable_file_limit_is_refused(self, monkeypatch, value):
        monkeypatch.setenv("AGAC_FILE_LIMIT", value)

        with pytest.raises(ValueError, match="AGAC_FILE_LIMIT"):
            check_environment()

    @pytest.mark.parametrize("value", ["nonsense", "0", "-1"])
    def test_an_unusable_record_limit_is_refused(self, monkeypatch, value):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", value)

        with pytest.raises(ValueError, match="AGAC_RECORD_LIMIT"):
            check_environment()

    def test_usable_values_pass(self, monkeypatch):
        monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")

        check_environment()


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
    """The limit keeps the first N by position. Beyond that it keeps exactly as
    many positions of an identity as the action already holds rows for."""

    def test_the_first_n_are_kept(self):
        assert records_kept_by_limit(_records(6), 2) == [0, 1]

    def test_a_limit_past_the_end_keeps_everything(self):
        assert records_kept_by_limit(_records(3), 10) == [0, 1, 2]

    def test_a_limit_below_one_keeps_nothing_by_position(self):
        assert records_kept_by_limit(_records(3), -1) == []

    def test_nothing_held_means_the_limit_alone_decides(self):
        assert records_kept_by_limit(_records(6), 2, {}) == [0, 1]

    def test_a_held_record_beyond_the_limit_is_kept(self):
        assert records_kept_by_limit(_records(6), 2, {"r4": 1}) == [0, 1, 4]

    def test_the_record_immediately_past_the_limit_is_kept(self):
        """The boundary. A range starting one late would silently leave it out."""
        assert records_kept_by_limit(_records(6), 2, {"r2": 1}) == [0, 1, 2]

    def test_indices_come_back_in_order(self):
        assert records_kept_by_limit(_records(6), 2, {"r5": 1, "r3": 1}) == [0, 1, 3, 5]

    def test_an_identity_with_no_rows_held_is_dropped(self):
        assert records_kept_by_limit(_records(6), 2, {"absent": 1}) == [0, 1]

    def test_a_record_with_no_guid_is_not_kept(self):
        records = [{"source_guid": "r0"}, {"source_guid": "r1"}, {}, {"source_guid": "r3"}]

        assert records_kept_by_limit(records, 2, {"r3": 1}) == [0, 1, 3]

    def test_records_that_are_not_mappings_are_not_kept(self):
        assert records_kept_by_limit(["a", "b", "c", "d", "e"], 2, {"r4": 1}) == [0, 1]


class TestAsManyPositionsAsRowsHeld:
    """source_guid is a content hash, so byte-identical records share one and an
    action can hold several rows under it. Keeping too few writes one row where
    three stood; keeping too many writes three where one did, backfilling past a
    limit that was deliberately holding records back."""

    def test_every_copy_is_kept_when_every_copy_is_held(self):
        records = [{"source_guid": "X"}, {"source_guid": "G"}, {"source_guid": "G"}]

        assert records_kept_by_limit(records, 1, {"X": 1, "G": 2}) == [0, 1, 2]

    def test_only_as_many_copies_as_are_held(self):
        """Three copies in the input, one row in the store: one row comes back."""
        records = [{"source_guid": "X"}, {"source_guid": "G"}, {"source_guid": "G"}]

        assert records_kept_by_limit(records, 1, {"X": 1, "G": 1}) == [0, 1]

    def test_a_position_the_limit_keeps_spends_the_same_budget(self):
        """Otherwise a copy inside the limit and a copy outside it would both be
        kept against one held row, and the action would grow by one."""
        records = [{"source_guid": "G"}, {"source_guid": "G"}, {"source_guid": "G"}]

        assert records_kept_by_limit(records, 1, {"G": 1}) == [0]

    def test_holding_more_rows_than_the_input_has_copies_keeps_them_all(self):
        records = [{"source_guid": "G"}, {"source_guid": "G"}]

        assert records_kept_by_limit(records, 0, {"G": 5}) == [0, 1]


class _Backend:
    """Only what the lookup asks of a backend, plus a count of the asking."""

    def __init__(self, rows_by_action):
        self._rows = rows_by_action
        self.calls = 0

    def target_rows_per_source_guid(self, action_name):
        self.calls += 1
        return dict(self._rows.get(action_name, {}))


class TestRowsThisActionHoldsPerRecord:
    """Counting belongs to the backend and is tested there. What lives here is
    that the answer is asked for once and survives a missing backend."""

    def test_it_returns_what_the_action_holds(self):
        backend = _Backend({"act": {"g0": 1, "g1": 3}})

        assert rows_this_action_holds_per_record(backend, "act") == {"g0": 1, "g1": 3}

    def test_no_backend_means_nothing_is_known_to_be_held(self):
        assert rows_this_action_holds_per_record(None, "act") == {}

    def test_an_action_is_asked_once_however_many_files_ask(self):
        """A cost guard, not a correctness one: the caller asks per input file, and
        reading the store each time is quadratic in files. Counting the asking is
        the only way to see that, since the answer is the same either way."""
        backend = _Backend({"act": {"g0": 1}})

        for _ in range(5):
            rows_this_action_holds_per_record(backend, "act")

        assert backend.calls == 1

    def test_the_answer_does_not_change_when_the_store_does(self):
        """What the cache is for: the answer wanted is what the action held before
        this run, and the run writes to that store as it goes."""
        backend = _Backend({"act": {"g0": 1}})
        first = rows_this_action_holds_per_record(backend, "act")

        backend._rows["act"] = {"g0": 1, "written_during_the_run": 1}

        assert rows_this_action_holds_per_record(backend, "act") == first

    def test_each_action_is_asked_for_separately(self):
        backend = _Backend({"a": {"g0": 1}, "b": {"g1": 1}})

        assert rows_this_action_holds_per_record(backend, "a") == {"g0": 1}
        assert rows_this_action_holds_per_record(backend, "b") == {"g1": 1}
        assert backend.calls == 2

    def test_two_backends_do_not_share_an_answer(self):
        """Keyed on the backend, so a second run in the same process reads its
        own store rather than the previous one's."""
        first = _Backend({"act": {"g0": 1}})
        second = _Backend({"act": {"g1": 1, "g2": 1}})

        rows_this_action_holds_per_record(first, "act")

        assert rows_this_action_holds_per_record(second, "act") == {"g1": 1, "g2": 1}


class TestRepairingWithoutAStore:
    """Without a backend only the named records can be spared, which is the
    behaviour the held-rows rule replaces. It must not happen quietly."""

    def test_it_says_so_when_records_were_dropped(self, caplog):
        records = [{"source_guid": f"r{i}"} for i in range(6)]

        with caplog.at_level("WARNING", logger="agent_actions.utils.limits"):
            record_indices_to_process(
                records, {"record_limit": 1}, "flatten", retried=frozenset({"r5"})
            )

        said = " ".join(r.getMessage() for r in caplog.records)
        assert "flatten" in said, said
        assert "storage backend" in said, said

    def test_it_still_spares_the_named_records(self):
        records = [{"source_guid": f"r{i}"} for i in range(6)]

        kept = record_indices_to_process(
            records, {"record_limit": 1}, "flatten", retried=frozenset({"r5"})
        )

        assert kept == [0, 5]

    def test_nothing_is_said_when_nothing_was_dropped(self, caplog):
        """It names a loss, not a possibility."""
        records = [{"source_guid": f"r{i}"} for i in range(2)]

        with caplog.at_level("WARNING", logger="agent_actions.utils.limits"):
            record_indices_to_process(
                records, {"record_limit": 5}, "flatten", retried=frozenset({"r1"})
            )

        assert [r.getMessage() for r in caplog.records if "storage backend" in r.getMessage()] == []

    def test_a_run_that_is_not_repairing_says_nothing(self, caplog):
        records = [{"source_guid": f"r{i}"} for i in range(6)]

        with caplog.at_level("WARNING", logger="agent_actions.utils.limits"):
            record_indices_to_process(records, {"record_limit": 1}, "flatten")

        assert [r.getMessage() for r in caplog.records if "storage backend" in r.getMessage()] == []
