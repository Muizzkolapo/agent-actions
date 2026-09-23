"""Tests for record_limit and file_limit feature.

Covers:
- record_limit slicing in process_initial_stage
- file_limit early break in all 3 file-walking paths
- Status invalidation when limits change between runs
- Edge cases: limit > total records, limit = total, None (no-op)
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.utils.limits import FILE_LIMIT_KEY, record_indices_to_process
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus
from agent_actions.workflow.runner_file_processing import (
    _file_limit_reached,
    collect_files_from_upstream,
    process_directory_files,
    process_from_storage_backend,
    process_merged_files,
)

# ── _file_limit_reached helper ────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    """A developer shell exporting either variable must not decide these tests."""
    for name in ("AGAC_RECORD_LIMIT", "AGAC_FILE_LIMIT", "AGAC_MAX_RECORDS"):
        monkeypatch.delenv(name, raising=False)


def _backend_holding_nothing():
    """A backend for an action with no stored rows yet.

    A bare MagicMock answers `target_rows_per_source_guid` with another mock, whose union
    and membership tests both quietly do nothing — so a test double has to state
    the empty set the real backend would return.
    """
    backend = MagicMock()
    backend.target_rows_per_source_guid.return_value = {}
    return backend


def _stops(action_config, count, retried=frozenset(), more_remain=True, probe=None):
    """Ask the file-limit check, over a runner and params carrying just what it reads."""
    runner = MagicMock()
    runner.retried_records = retried
    params = MagicMock()
    params.action_config = action_config
    params.action_name = "act"
    return _file_limit_reached(runner, params, count, probe or (lambda: more_remain))


_WALK_LOG = "agent_actions.workflow.runner_file_processing"


class TestFileLimitReached:
    def test_none_means_no_limit(self):
        assert _stops({}, 100) is False

    def test_below_limit(self):
        assert _stops({"file_limit": 5}, 3) is False

    def test_at_limit(self):
        assert _stops({"file_limit": 5}, 5) is True

    def test_above_limit(self):
        assert _stops({"file_limit": 5}, 10) is True

    def test_a_run_level_limit_applies_where_the_config_sets_none(self):
        assert _stops({FILE_LIMIT_KEY: 2}, 2) is True

    def test_a_run_level_limit_does_not_raise_a_smaller_configured_one(self):
        assert _stops({"file_limit": 1, FILE_LIMIT_KEY: 5}, 1) is True

    def test_the_environment_applies_where_the_config_sets_none(self, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "2")

        assert _stops({}, 2) is True

    def test_a_repair_is_never_held_back(self):
        """It walks the files holding the records it named; stopping short of one
        leaves that record's cleared disposition unwritten."""
        assert _stops({"file_limit": 1}, 5, retried=frozenset({"r1"})) is False

    def test_a_repair_is_not_held_back_by_the_environment_either(self, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")

        assert _stops({}, 5, retried=frozenset({"r1"})) is False

    def test_a_limit_from_outside_the_config_is_announced_loudly(self, monkeypatch, caplog):
        """A shortened walk looks like a complete one, and a variable the caller
        has forgotten is set is the case that needs saying."""
        monkeypatch.setenv("AGAC_FILE_LIMIT", "2")

        with caplog.at_level("INFO", logger=_WALK_LOG):
            _stops({}, 2)

        assert [r.levelname for r in caplog.records] == ["WARNING"]
        assert "AGAC_FILE_LIMIT=2" in caplog.records[0].message

    def test_a_configured_limit_is_announced_quietly(self, caplog):
        """The run behaving as the project wrote it."""
        with caplog.at_level("INFO", logger=_WALK_LOG):
            _stops({"file_limit": 2}, 2)

        assert [r.levelname for r in caplog.records] == ["INFO"]

    def test_a_walk_that_was_not_stopped_says_nothing(self, caplog):
        with caplog.at_level("INFO", logger=_WALK_LOG):
            _stops({"file_limit": 5}, 3)

        assert caplog.records == [], [r.message for r in caplog.records]

    def test_a_limit_that_equalled_the_input_says_nothing(self, monkeypatch, caplog):
        """Reaching a limit is not the same as being held back by one. A walk that
        took every file there was is a complete run, and announcing it as a
        shortened one spends the signal that exists to flag a truncation."""
        monkeypatch.setenv("AGAC_FILE_LIMIT", "2")

        with caplog.at_level("INFO", logger=_WALK_LOG):
            stopped = _stops({}, 2, more_remain=False)

        assert stopped is True
        assert caplog.records == [], [r.message for r in caplog.records]

    def test_the_remainder_is_not_asked_for_when_the_limit_does_not_bite(self):
        """Answering it can cost a filesystem sweep, so a walk the limit never
        bounds must not pay for one."""
        asked = []

        _stops({"file_limit": 5}, 3, probe=lambda: bool(asked.append(1)))

        assert asked == []

    def test_a_repair_does_not_ask_for_the_remainder_either(self):
        asked = []

        assert (
            _stops(
                {"file_limit": 1}, 5, retried=frozenset({"r1"}), probe=lambda: bool(asked.append(1))
            )
            is False
        )
        assert asked == []


# ── file_limit in process_directory_files ─────────────────────────────


class TestFileLimitDirectoryFiles:
    def _setup_files(self, tmp_path, count):
        """Create count JSON files in tmp_path."""
        for i in range(count):
            (tmp_path / f"file_{i:03d}.json").write_text(json.dumps([{"id": i}]))

    def test_file_limit_caps_files_processed(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        self._setup_files(input_dir, 5)
        output = tmp_path / "output"
        output.mkdir()

        runner = MagicMock()
        # A bare MagicMock answers `retried_records` with a truthy mock, which would
        # read as a repair in progress and narrow the walk. State the empty set a
        # runner that is not repairing actually carries.
        runner.retried_records = frozenset()
        runner._should_skip_item.return_value = False

        params = MagicMock()
        params.action_config = {"file_limit": 2}
        params.action_name = "test"
        params.strategy = MagicMock()
        params.idx = 0
        params.file_type_filter = None

        _found, processed, _errors = process_directory_files(
            runner, input_dir, output, str(input_dir), params, set()
        )
        assert processed == 2
        assert runner._process_single_file.call_count == 2

    def test_no_file_limit_processes_all(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        self._setup_files(input_dir, 5)
        output = tmp_path / "output"
        output.mkdir()

        runner = MagicMock()
        runner.retried_records = frozenset()
        runner._should_skip_item.return_value = False

        params = MagicMock()
        params.action_config = {}
        params.action_name = "test"
        params.strategy = MagicMock()
        params.idx = 0
        params.file_type_filter = None

        _found, processed, _errors = process_directory_files(
            runner, input_dir, output, str(input_dir), params, set()
        )
        assert processed == 5

    def test_file_limit_greater_than_total(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        self._setup_files(input_dir, 3)
        output = tmp_path / "output"
        output.mkdir()

        runner = MagicMock()
        runner.retried_records = frozenset()
        runner._should_skip_item.return_value = False

        params = MagicMock()
        params.action_config = {"file_limit": 100}
        params.action_name = "test"
        params.strategy = MagicMock()
        params.idx = 0
        params.file_type_filter = None

        _found, processed, _errors = process_directory_files(
            runner, input_dir, output, str(input_dir), params, set()
        )
        assert processed == 3


class TestTheWalksThemselvesStaySilentWhenNothingWasLeft:
    """Driven through the real walks, not an injected probe.

    Each walk builds its own answer to "was anything left unread", and a test
    that supplies that answer proves the helper's contract while leaving the
    three production closures free to say whatever they like.
    """

    def _quiet(self, caplog):
        return [r for r in caplog.records if "stopped after" in r.message]

    def test_the_directory_walk_is_silent_when_it_took_every_file(self, tmp_path, caplog):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        for i in range(2):
            (input_dir / f"file_{i}.json").write_text(json.dumps([{"id": i}]))
        output = tmp_path / "output"
        output.mkdir()
        runner = MagicMock()
        runner.retried_records = frozenset()
        params = MagicMock()
        params.action_config = {"file_limit": 2}
        params.action_name = "act"
        params.strategy = MagicMock()
        params.idx = 0
        params.file_type_filter = None

        with caplog.at_level("INFO", logger=_WALK_LOG):
            _found, processed, _errors = process_directory_files(
                runner, input_dir, output, str(input_dir), params, set()
            )

        assert processed == 2
        assert self._quiet(caplog) == []

    def test_the_directory_walk_speaks_when_a_file_was_left(self, tmp_path, caplog):
        """The control for the test above, through the same closure."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        for i in range(3):
            (input_dir / f"file_{i}.json").write_text(json.dumps([{"id": i}]))
        output = tmp_path / "output"
        output.mkdir()
        runner = MagicMock()
        runner.retried_records = frozenset()
        params = MagicMock()
        params.action_config = {"file_limit": 2}
        params.action_name = "act"
        params.strategy = MagicMock()
        params.idx = 0
        params.file_type_filter = None

        with caplog.at_level("INFO", logger=_WALK_LOG):
            process_directory_files(runner, input_dir, output, str(input_dir), params, set())

        assert len(self._quiet(caplog)) == 1

    def test_the_directory_walk_is_silent_when_only_skippable_entries_remain(
        self, tmp_path, caplog
    ):
        """A trailing directory is not a file left unread."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "a.json").write_text(json.dumps([{"id": 1}]))
        (input_dir / "zzz_subdir").mkdir()
        output = tmp_path / "output"
        output.mkdir()
        runner = MagicMock()
        runner.retried_records = frozenset()
        params = MagicMock()
        params.action_config = {"file_limit": 1}
        params.action_name = "act"
        params.strategy = MagicMock()
        params.idx = 0
        params.file_type_filter = None

        with caplog.at_level("INFO", logger=_WALK_LOG):
            process_directory_files(runner, input_dir, output, str(input_dir), params, set())

        assert self._quiet(caplog) == []

    def _merged(self, tmp_path, count, limit):
        upstream = tmp_path / "upstream"
        output = tmp_path / "output"
        upstream.mkdir()
        output.mkdir()
        for i in range(count):
            (upstream / f"file_{i}.json").write_text(json.dumps([{"id": i}]))
        runner = MagicMock()
        runner.retried_records = frozenset()
        params = MagicMock()
        params.upstream_data_dirs = [str(upstream)]
        params.output_directory = str(output)
        params.action_config = {"file_limit": limit}
        params.action_name = "act"
        params.strategy = MagicMock()
        params.idx = 0
        return runner, params

    def test_the_merged_walk_is_silent_when_it_took_every_group(self, tmp_path, caplog):
        runner, params = self._merged(tmp_path, count=2, limit=2)

        with caplog.at_level("INFO", logger=_WALK_LOG):
            process_merged_files(runner, params)

        assert self._quiet(caplog) == []

    def test_the_merged_walk_speaks_when_a_group_was_left(self, tmp_path, caplog):
        runner, params = self._merged(tmp_path, count=3, limit=2)

        with caplog.at_level("INFO", logger=_WALK_LOG):
            process_merged_files(runner, params)

        assert len(self._quiet(caplog)) == 1

    def _stored(self, tmp_path, names, limit):
        backend = MagicMock()
        backend.list_target_files.return_value = list(names)
        backend.read_target.side_effect = lambda action, path: [{"source_guid": path}]
        backend.load_metadata.return_value = None
        backend.get_disposition.return_value = []
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        params = MagicMock()
        params.upstream_data_dirs = [str(tmp_path / "target" / "upstream")]
        params.output_directory = str(tmp_path / "out")
        params.action_config = {"file_limit": limit}
        params.action_name = "act"
        return runner, params

    def test_the_stored_walk_is_silent_when_it_took_every_entry(self, tmp_path, caplog):
        runner, params = self._stored(tmp_path, ["a.json", "b.json"], limit=2)

        with caplog.at_level("INFO", logger=_WALK_LOG):
            process_from_storage_backend(runner, params)

        assert self._quiet(caplog) == []

    def test_the_stored_walk_speaks_when_an_entry_was_left(self, tmp_path, caplog):
        runner, params = self._stored(tmp_path, ["a.json", "b.json", "c.json"], limit=2)

        with caplog.at_level("INFO", logger=_WALK_LOG):
            process_from_storage_backend(runner, params)

        assert len(self._quiet(caplog)) == 1


class TestWhatTheFileLimitCounts:
    def test_a_file_that_fails_does_not_spend_the_budget(self, tmp_path):
        """The limit counts files an action got through, not files it opened, so
        a directory of unreadable files is attempted in full under a limit of one.
        Pinned because it is the difference between the limit bounding work and
        bounding output, and nothing else in the suite says which it is."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        for i in range(3):
            (input_dir / f"file_{i}.json").write_text(json.dumps([{"id": i}]))
        output = tmp_path / "output"
        output.mkdir()

        attempted = []

        def fail_then_succeed(params):
            attempted.append(params.locations.item.name)
            if len(attempted) < 3:
                raise RuntimeError("unreadable")

        runner = MagicMock()
        runner.retried_records = frozenset()
        runner._process_single_file = fail_then_succeed

        params = MagicMock()
        params.action_config = {"file_limit": 1}
        params.action_name = "act"
        params.strategy = MagicMock()
        params.idx = 0
        params.file_type_filter = None

        _found, processed, errors = process_directory_files(
            runner, input_dir, output, str(input_dir), params, set()
        )

        assert attempted == ["file_0.json", "file_1.json", "file_2.json"]
        assert processed == 1
        assert len(errors.messages) == 2


# ── file_limit in process_merged_files ────────────────────────────────


class TestFileLimitMergedFiles:
    def test_file_limit_caps_merged_groups(self, tmp_path):
        upstream = tmp_path / "upstream"
        output = tmp_path / "output"
        upstream.mkdir()
        output.mkdir()

        # Create 4 files
        for i in range(4):
            (upstream / f"file_{i}.json").write_text(json.dumps([{"id": i}]))

        runner = MagicMock()
        runner.retried_records = frozenset()

        params = MagicMock()
        params.upstream_data_dirs = [str(upstream)]
        params.output_directory = str(output)
        params.action_config = {"file_limit": 2}
        params.action_name = "test"
        params.strategy = MagicMock()
        params.idx = 0

        _found, processed, _errors = process_merged_files(runner, params)
        assert processed == 2
        assert runner._process_single_file.call_count == 2

    def test_a_repair_merges_every_group(self, tmp_path):
        upstream = tmp_path / "upstream"
        output = tmp_path / "output"
        upstream.mkdir()
        output.mkdir()

        for i in range(4):
            (upstream / f"file_{i}.json").write_text(json.dumps([{"id": i}]))

        runner = MagicMock()
        runner.retried_records = frozenset({"r1"})

        params = MagicMock()
        params.upstream_data_dirs = [str(upstream)]
        params.output_directory = str(output)
        params.action_config = {"file_limit": 2}
        params.action_name = "test"
        params.strategy = MagicMock()
        params.idx = 0

        _found, processed, _errors = process_merged_files(runner, params)
        assert processed == 4


class TestTheMergedWalkOrder:
    def test_files_come_back_in_sorted_order(self, tmp_path):
        """A file limit truncates this mapping, so raw filesystem order makes
        "the first N" mean whatever the directory happened to enumerate, and the
        union of several upstreams order by whichever was read first."""
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        for name in ("z.json", "m.json"):
            (first / name).write_text(json.dumps([{"id": name}]))
        (second / "a.json").write_text(json.dumps([{"id": "a"}]))

        collected = collect_files_from_upstream([str(first), str(second)])

        assert [str(path) for path in collected] == ["a.json", "m.json", "z.json"]


class TestFileLimitBackendEntries:
    """A downstream action reads its input from the store rather than the
    filesystem — the walk a repair's file narrowing never reached."""

    def _walk(self, tmp_path, retried=frozenset()):
        backend = MagicMock()
        backend.list_target_files.return_value = ["a.json", "b.json"]
        backend.read_target.side_effect = lambda action, path: [{"source_guid": path}]
        backend.load_metadata.return_value = None
        backend.get_disposition.return_value = []
        runner = MagicMock()
        runner.retried_records = retried
        runner.storage_backend = backend
        params = MagicMock()
        params.upstream_data_dirs = [str(tmp_path / "target" / "upstream")]
        params.output_directory = str(tmp_path / "out")
        params.action_config = {"file_limit": 1}
        params.action_name = "act"
        return runner, params

    def test_the_limit_caps_the_entries_walked(self, tmp_path):
        runner, params = self._walk(tmp_path)

        _found, processed, _errors = process_from_storage_backend(runner, params)

        assert processed == 1

    def test_the_entries_are_taken_in_sorted_order(self, tmp_path):
        """A limit truncates this mapping, and the union of several upstreams is
        otherwise ordered by whichever was read first."""
        runner, params = self._walk(tmp_path)
        runner.storage_backend.list_target_files.side_effect = [["m.json", "n.json"], ["a.json"]]
        params.upstream_data_dirs = [
            str(tmp_path / "target" / "first"),
            str(tmp_path / "target" / "second"),
        ]
        params.action_config = {"file_limit": 2}
        taken = []
        runner._process_single_file = lambda p: taken.append(p.locations.item.name)

        process_from_storage_backend(runner, params)

        assert taken == ["a.json", "m.json"]

    def test_a_repair_walks_every_entry(self, tmp_path):
        runner, params = self._walk(tmp_path, frozenset({"r1"}))

        _found, processed, _errors = process_from_storage_backend(runner, params)

        assert processed == 2


# ── record_limit in process_initial_stage ─────────────────────────────


class TestRecordLimitInitialStage:
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._save_source_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._validate_staged_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._prepare_online_data")
    @patch("agent_actions.input.loaders.file_reader.FileReader")
    @patch(
        "agent_actions.input.preprocessing.staging.initial_pipeline"
        "._process_online_mode_with_record_processor"
    )
    def test_record_limit_slices_data_before_source_save(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        all_records = [{"id": i} for i in range(50)]
        all_src = [{"source_guid": f"guid_{i}", "content": str(i)} for i in range(50)]
        mock_prep.return_value = (all_records, all_src)

        reader_instance = MagicMock()
        reader_instance.read.return_value = [{"page": "raw"}]
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance

        mock_process.return_value = "/output/file.json"

        ctx = InitialStageContext(
            agent_config={"record_limit": 10, "run_mode": "online"},
            agent_name="test",
            file_path="/input/data.json",
            base_directory="/input",
            output_directory="/output",
            storage_backend=_backend_holding_nothing(),
        )

        process_initial_stage(ctx)

        # Source save should receive only 10 records (sliced BEFORE save)
        save_args = mock_save.call_args
        saved_src = save_args[0][0]  # first positional arg = src_text
        saved_data = save_args[0][1]  # second positional arg = data_chunk
        assert len(saved_data) == 10
        assert len(saved_src) == 10

        # Processing should also receive 10 records
        process_args = mock_process.call_args
        processed_data = process_args[0][0]  # first positional arg = data_chunk
        assert len(processed_data) == 10

    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._save_source_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._validate_staged_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._prepare_online_data")
    @patch("agent_actions.input.loaders.file_reader.FileReader")
    @patch(
        "agent_actions.input.preprocessing.staging.initial_pipeline"
        "._process_online_mode_with_record_processor"
    )
    def test_a_retried_record_keeps_its_source_row(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        """The source text is positionally aligned with the records, so both are
        kept by the same indices — slicing one by the limit alone would misalign them.

        A repair saves the records it named and no others. The limit's own N is not
        added to them: deciding how much new work to take on is what a limit is for,
        and a repair takes on none, so a record the repair did not name is not work
        this run was asked to do however far inside the limit it sits."""
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        # Online mode returns one list under both names, as production does.
        rows = [{"source_guid": f"g{i}", "content": str(i)} for i in range(6)]
        mock_prep.return_value = (rows, rows)

        reader_instance = MagicMock()
        reader_instance.read.return_value = [{"page": "raw"}]
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance
        mock_process.return_value = "/output/file.json"

        process_initial_stage(
            InitialStageContext(
                agent_config={"record_limit": 2, "run_mode": "online"},
                agent_name="test",
                file_path="/input/data.json",
                base_directory="/input",
                output_directory="/output",
                storage_backend=_backend_holding_nothing(),
                retried_records=frozenset({"g5"}),
            )
        )

        saved_src, saved_data = mock_save.call_args[0][0], mock_save.call_args[0][1]
        assert [r["source_guid"] for r in saved_data] == ["g5"]
        assert [r["source_guid"] for r in saved_src] == ["g5"]

    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._save_source_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._validate_staged_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._prepare_online_data")
    @patch("agent_actions.input.loaders.file_reader.FileReader")
    @patch(
        "agent_actions.input.preprocessing.staging.initial_pipeline"
        "._process_online_mode_with_record_processor"
    )
    def test_record_limit_none_passes_all(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        all_records = [{"id": i} for i in range(50)]
        mock_prep.return_value = (all_records, [])

        reader_instance = MagicMock()
        reader_instance.read.return_value = [{"page": "raw"}]
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance

        mock_process.return_value = "/output/file.json"

        ctx = InitialStageContext(
            agent_config={"run_mode": "online"},
            agent_name="test",
            file_path="/input/data.json",
            base_directory="/input",
            output_directory="/output",
            storage_backend=_backend_holding_nothing(),
        )

        process_initial_stage(ctx)

        save_args = mock_save.call_args
        saved_data = save_args[0][1]
        assert len(saved_data) == 50

    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._save_source_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._validate_staged_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._prepare_online_data")
    @patch("agent_actions.input.loaders.file_reader.FileReader")
    @patch(
        "agent_actions.input.preprocessing.staging.initial_pipeline"
        "._process_online_mode_with_record_processor"
    )
    def test_record_limit_greater_than_total_is_noop(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        all_records = [{"id": i} for i in range(5)]
        mock_prep.return_value = (all_records, [])

        reader_instance = MagicMock()
        reader_instance.read.return_value = [{"page": "raw"}]
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance

        mock_process.return_value = "/output/file.json"

        ctx = InitialStageContext(
            agent_config={"record_limit": 100, "run_mode": "online"},
            agent_name="test",
            file_path="/input/data.json",
            base_directory="/input",
            output_directory="/output",
            storage_backend=_backend_holding_nothing(),
        )

        process_initial_stage(ctx)

        save_args = mock_save.call_args
        saved_data = save_args[0][1]
        assert len(saved_data) == 5


# ── Status invalidation when limits change ────────────────────────────


class TestRecordLimitInitialStageUnderBatch:
    """Batch takes a different preparation path to online, and it is the path
    immediately before the batch/online fork that slices."""

    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._save_source_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._validate_staged_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._prepare_batch_data")
    @patch("agent_actions.input.loaders.file_reader.FileReader")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._process_batch_mode")
    def test_a_held_record_beyond_the_limit_is_kept(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        rows = [{"source_guid": f"g{i}", "content": str(i)} for i in range(6)]
        mock_prep.return_value = (rows, [])
        reader_instance = MagicMock()
        reader_instance.read.return_value = [{"page": "raw"}]
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance
        mock_process.return_value = "/output/file.json"
        backend = MagicMock()
        backend.target_rows_per_source_guid.return_value = {"g5": 1}

        process_initial_stage(
            InitialStageContext(
                agent_config={"record_limit": 2, "run_mode": "batch"},
                agent_name="test",
                file_path="/input/data.json",
                base_directory="/input",
                output_directory="/output",
                storage_backend=backend,
                retried_records=frozenset({"g5"}),
            )
        )

        saved_data = mock_save.call_args[0][1]
        assert [r["source_guid"] for r in saved_data] == ["g5"]


class TestLimitStatusInvalidation:
    @pytest.fixture
    def mock_deps(self):
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = MagicMock(spec=ActionStateManager)
        # No marker in the stamp is the ordinary case; a mock would
        # otherwise answer with something truthy.
        deps.state_manager.adopt_truncation_marker.return_value = False
        deps.action_runner = MagicMock()
        deps.action_runner.retried_records = frozenset()
        deps.action_runner.workflow_name = "test"
        deps.action_runner.get_action_folder.return_value = "/tmp/io"
        deps.action_runner.execution_order = ["act_a"]
        deps.skip_evaluator = MagicMock()
        deps.output_manager = MagicMock()
        deps.batch_manager = MagicMock()
        return deps

    @pytest.fixture
    def executor(self, mock_deps):
        return ActionExecutor(mock_deps)

    def test_limits_changed_resets_to_pending(self, executor, mock_deps):
        """Action completed with limit=10, re-run with limit=None should re-execute."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 10,
            "file_limit": None,
        }
        # Config now has no limit
        action_config = {"record_limit": None, "file_limit": None}
        mock_deps.skip_evaluator.should_skip_action.return_value = False

        mock_deps.action_runner.run_action.return_value = ("/out", None)
        executor.execute_action_sync(
            "act_a", action_idx=0, action_config=action_config, is_last_action=True
        )

        # Should have reset to pending, then run the action
        update_calls = mock_deps.state_manager.update_status.call_args_list
        assert update_calls[0] == (("act_a", ActionStatus.PENDING),)

    def test_same_limits_skips_action(self, executor, mock_deps):
        """Action completed with same limits should be skipped."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 10,
            "file_limit": 2,
        }
        action_config = {"record_limit": 10, "file_limit": 2}

        storage = MagicMock()
        storage.list_target_files.return_value = ["file.json"]
        storage.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend = storage

        result = executor.execute_action_sync(
            "act_a", action_idx=0, action_config=action_config, is_last_action=False
        )

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED
        mock_deps.action_runner.run_action.assert_not_called()

    def test_limits_changed_clears_dispositions(self, executor, mock_deps):
        """When limits change, stale dispositions must be cleared alongside status reset."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 10,
            "file_limit": None,
        }
        storage = MagicMock()
        mock_deps.action_runner.storage_backend = storage

        result = executor._maybe_invalidate_completed_status(
            "act_a", {"record_limit": 2, "file_limit": None}, ActionStatus.COMPLETED
        )

        assert result == ActionStatus.PENDING
        storage.clear_disposition.assert_called_once_with("act_a")

    def test_limits_unchanged_does_not_clear_dispositions(self, executor, mock_deps):
        """When limits are unchanged, dispositions are untouched."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 10,
            "file_limit": None,
        }
        storage = MagicMock()
        mock_deps.action_runner.storage_backend = storage

        result = executor._maybe_invalidate_completed_status(
            "act_a", {"record_limit": 10, "file_limit": None}, ActionStatus.COMPLETED
        )

        assert result == ActionStatus.COMPLETED
        storage.clear_disposition.assert_not_called()

    def test_limits_changed_no_storage_backend(self, executor, mock_deps):
        """When limits change but no storage backend, status resets without error."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 10,
            "file_limit": None,
        }
        mock_deps.action_runner.storage_backend = None

        result = executor._maybe_invalidate_completed_status(
            "act_a", {"record_limit": 2, "file_limit": None}, ActionStatus.COMPLETED
        )

        assert result == ActionStatus.PENDING

    def test_no_limits_old_status_no_invalidation(self, executor, mock_deps):
        """Old status file without limit keys + config with no limits = no invalidation."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
        action_config = {}

        storage = MagicMock()
        storage.list_target_files.return_value = ["file.json"]
        storage.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend = storage

        result = executor.execute_action_sync(
            "act_a", action_idx=0, action_config=action_config, is_last_action=False
        )

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED
        mock_deps.action_runner.run_action.assert_not_called()


# ── Schema validation ─────────────────────────────────────────────────


class TestTheCompletionStamp:
    """What a completed action stores, and which parts of it are compared."""

    @pytest.fixture
    def executor(self):
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = MagicMock(spec=ActionStateManager)
        # No marker in the stamp is the ordinary case; a mock would
        # otherwise answer with something truthy.
        deps.state_manager.adopt_truncation_marker.return_value = False
        deps.action_runner = MagicMock()
        deps.action_runner.retried_records = frozenset()
        return ActionExecutor(deps)

    def test_a_recorded_cap_reopens_the_action(self, executor):
        """The stamp says completed under the configured limit, and the marker
        says the run that wrote it never reached that limit."""
        executor.deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 8,
        }
        executor.deps.state_manager.adopt_truncation_marker.return_value = True

        result = executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 8}, ActionStatus.COMPLETED
        )

        assert result == ActionStatus.PENDING

    def test_a_repair_does_not_consume_the_marker(self, executor):
        """Reading it erases it, so reading during a repair — which must not
        reopen the action — would lose the only record of the truncation."""
        executor.deps.action_runner.retried_records = frozenset({"r1"})
        executor.deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 8,
        }

        result = executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 8}, ActionStatus.COMPLETED
        )

        executor.deps.state_manager.adopt_truncation_marker.assert_not_called()
        assert result == ActionStatus.COMPLETED

    def test_no_marker_leaves_a_matching_stamp_completed(self, executor):
        executor.deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 8,
        }
        executor.deps.state_manager.adopt_truncation_marker.return_value = False

        result = executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 8}, ActionStatus.COMPLETED
        )

        assert result == ActionStatus.COMPLETED

    def test_it_stores_exactly_these_keys(self, executor):
        """Pinned as a set: a slot that silently reappears is how one limit
        source came to be recorded in a place nothing read."""
        stamp = executor._completion_metadata("act", {"record_limit": 2})

        assert set(stamp) == {
            "record_limit",
            "file_limit",
            "model_name",
            "model_vendor",
            "config_hash",
            "records_processed",
            "truncated",
        }

    def test_a_changed_file_limit_invalidates(self, executor):
        """Its own term in the comparison, not carried by record_limit."""
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": 10,
            "file_limit": 2,
        }

        status = executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 10, "file_limit": 5}, ActionStatus.COMPLETED
        )

        assert status == ActionStatus.PENDING

    def test_unchanged_limits_leave_the_action_completed(self, executor):
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": 10,
            "file_limit": 2,
        }

        status = executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 10, "file_limit": 2}, ActionStatus.COMPLETED
        )

        assert status == ActionStatus.COMPLETED

    def test_a_retry_lets_a_changed_limit_stand(self, executor):
        """A retry asks for named records, not for a different amount of work.
        Invalidating here clears the action's dispositions and re-runs it
        truncated, losing records the retry never named."""
        executor.deps.action_runner.retried_records = frozenset({"some-record"})
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": 10,
            "file_limit": None,
        }

        status = executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 2}, ActionStatus.COMPLETED
        )

        assert status == ActionStatus.COMPLETED

    def test_a_retry_leaves_the_stored_limit_where_it_found_it(self, executor):
        """The other half of suppressing the limit: recording the one a retry
        ran under would make the next ordinary run read a change, clear the
        action's dispositions and re-run it."""
        executor.deps.action_runner.retried_records = frozenset({"some-record"})
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": None,
            "file_limit": 4,
        }

        stamp = executor._completion_metadata("act", {"record_limit": 2, "file_limit": 1})

        assert stamp["record_limit"] is None
        assert stamp["file_limit"] == 4

    def test_a_retry_keeps_each_axis_stored_limit(self, executor):
        """Distinct non-null values on purpose: stubbing both axes to None lets
        the stamp read either key and still look right, so a swapped key — the
        likeliest slip once the key is a string argument — would pass."""
        executor.deps.action_runner.retried_records = frozenset({"r1"})
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": 7,
            "file_limit": 3,
        }

        stamp = executor._completion_metadata("act", {"record_limit": 2, "file_limit": 1})

        assert stamp["record_limit"] == 7
        assert stamp["file_limit"] == 3

    def test_an_ordinary_run_stores_the_limit_in_force(self, executor):
        stamp = executor._completion_metadata("act", {"record_limit": 2})

        assert stamp["record_limit"] == 2

    def test_a_stamp_that_cannot_say_what_it_processed_still_invalidates(
        self, monkeypatch, executor
    ):
        """Grandfathered: a stamp written before the count was recorded cannot
        tell a limit that bit from one that did not, and unknown has to keep
        re-running rather than skip an action it has no grounds to vouch for.
        What a stamp that *can* say does instead is in
        tests/unit/workflow/test_limit_that_drops_nothing.py."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1000")
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": None,
            "file_limit": None,
        }

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.PENDING

    def test_a_boolean_where_the_count_should_be_is_not_a_count(self, monkeypatch, executor):
        """``True`` compares equal to 1, so reading it as a count would serve any
        limit as one that cannot bite. Status details are persisted JSON, so the
        value arrives from outside the process."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1000")
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": None,
            "file_limit": None,
            "records_processed": True,
            "truncated": False,
        }

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.PENDING


class TestALimitAcrossTheBatchPause:
    """The run that walks the files submits them; a later run collects them.

    The stamp has to describe the run that did the work. Resolving the
    collecting run's own doors records a full pass over work never attempted,
    and the action is then skipped as complete for good.
    """

    @pytest.fixture
    def executor(self):
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = MagicMock(spec=ActionStateManager)
        deps.state_manager.adopt_truncation_marker.return_value = False
        deps.action_runner = MagicMock()
        deps.action_runner.retried_records = frozenset()
        return ActionExecutor(deps)

    def test_the_submitting_run_records_what_it_applied(self, executor, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")
        executor.deps.state_manager.get_status_details.return_value = {}

        stamp = executor._completion_metadata("act", {"record_limit": 4})

        assert stamp["record_limit"] == 4
        assert stamp["file_limit"] == 1

    def test_the_submission_records_the_whole_stamp_not_just_the_limits(self, executor):
        """A prompt edited between submitting and collecting would otherwise be
        stamped by the collecting run, and the action never re-runs under it."""
        executor.deps.state_manager.get_status_details.return_value = {}

        stamp = executor._completion_metadata("act", {"model_name": "m", "prompt": "p"})

        assert set(stamp) == {
            "record_limit",
            "file_limit",
            "model_name",
            "model_vendor",
            "config_hash",
            "records_processed",
            "truncated",
        }

    def test_the_collecting_run_keeps_the_submitted_config_hash(self, executor):
        """The config the collecting run holds describes a different run. Stamping
        its hash marks the action complete against a prompt it never used, and the
        comparison is skipped while a batch is in flight, so it never re-runs."""
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": None,
            "file_limit": 1,
            "model_name": "model-at-submission",
            "model_vendor": "vendor-at-submission",
            "config_hash": "hash-at-submission",
        }

        stamp = executor._completion_metadata(
            "act", {"model_name": "model-now", "prompt": "edited"}, keep_stored=True
        )

        assert stamp["config_hash"] == "hash-at-submission"
        assert stamp["model_name"] == "model-at-submission"
        assert stamp["model_vendor"] == "vendor-at-submission"

    def test_an_ordinary_resubmission_records_the_new_limit(self, executor, monkeypatch):
        """An earlier submission's stamp is still there, but this run is the one
        walking the files, so what it applied is what the stamp has to say. Only
        a repair and a collection defer to the stored value."""
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": None,
            "file_limit": 1,
        }
        monkeypatch.setenv("AGAC_FILE_LIMIT", "3")

        assert executor._completion_metadata("act", {})["file_limit"] == 3

    def test_a_bool_in_the_stored_count_is_not_carried_forward(self, executor):
        """A bool is an int to isinstance, so a stamped True would re-stamp as
        one record processed. The side that reads the count already rejects it;
        the side that writes it has to agree, or the junk survives every repair."""
        executor.deps.action_runner.retried_records = frozenset({"r1"})
        executor.deps.state_manager.get_status_details.return_value = {
            "records_processed": True,
            "truncated": False,
        }

        stamp = executor._completion_metadata("act", {})

        assert stamp["records_processed"] is None

    def test_a_repair_resubmitting_a_batch_keeps_the_stored_limits(self, executor, monkeypatch):
        """A repair re-runs a batch action by submitting it again. Recording what
        the repair happened to run under erases the cap the original submission
        was made under, and the collection reads that back as the completion
        stamp — turning a truncated action into a finished one for good."""
        executor.deps.action_runner.retried_records = frozenset({"r1"})
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": None,
            "file_limit": 1,
        }
        monkeypatch.delenv("AGAC_FILE_LIMIT", raising=False)

        stamp = executor._completion_metadata("act", {})

        assert stamp["file_limit"] == 1
        assert stamp["record_limit"] is None

    def test_a_repair_under_a_limit_does_not_stamp_it_on_the_submission(
        self, executor, monkeypatch
    ):
        """The other direction: stamping the repair's own limit makes the next
        ordinary run read a change, clear the action's dispositions and
        re-submit the whole batch."""
        executor.deps.action_runner.retried_records = frozenset({"r1"})
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": None,
            "file_limit": None,
        }
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")

        assert executor._completion_metadata("act", {})["file_limit"] is None

    def test_the_collecting_run_keeps_the_submitted_limits(self, executor, monkeypatch):
        """The collecting run was asked for nothing; resolving its own doors
        would stamp a full pass over files it never walked."""
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": 4,
            "file_limit": 1,
        }
        monkeypatch.delenv("AGAC_FILE_LIMIT", raising=False)
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)

        stamp = executor._completion_metadata("act", {}, keep_stored=True)

        assert stamp["file_limit"] == 1
        assert stamp["record_limit"] == 4

    def test_a_collecting_run_with_its_own_doors_still_keeps_the_submitted_ones(
        self, executor, monkeypatch
    ):
        """The control: it is the work that was bounded, not this run."""
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": 4,
            "file_limit": 1,
        }
        monkeypatch.setenv("AGAC_FILE_LIMIT", "9")

        stamp = executor._completion_metadata("act", {}, keep_stored=True)

        assert stamp["file_limit"] == 1

    def test_an_ordinary_completion_still_records_the_limit_in_force(self, executor, monkeypatch):
        """The other control: keeping the stored limit is for runs that did not
        do the work, not for every completion."""
        executor.deps.state_manager.get_status_details.return_value = {"file_limit": 1}
        monkeypatch.setenv("AGAC_FILE_LIMIT", "9")

        stamp = executor._completion_metadata("act", {})

        assert stamp["file_limit"] == 9

    def test_a_batch_submitted_before_the_limits_were_stamped_is_grandfathered(self, executor):
        """State written by an earlier version carries no limit key at all.
        Reading its absence as 'no limit' would make the next run see a change
        and re-submit the whole batch, so an absent key is answered from this
        run instead — the same grandfathering the model keys get."""
        executor.deps.state_manager.get_status_details.return_value = {
            "batch_submitted_at": "2026-01-01T00:00:00"
        }

        stamp = executor._completion_metadata("act", {"file_limit": 2}, keep_stored=True)

        assert stamp["file_limit"] == 2

    def test_a_submission_that_stamped_no_limit_is_not_grandfathered(self, executor):
        """The control: a present key holding None is a real answer from a run
        that was bounded by nothing, not missing state."""
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": None,
            "file_limit": None,
        }

        stamp = executor._completion_metadata("act", {"file_limit": 2}, keep_stored=True)

        assert stamp["file_limit"] is None


class TestAFileLimitMeetingAConfigChange:
    """A file limit bounds which files are opened, so one it never reaches keeps
    what the previous run wrote. That is what not walking a file means — but
    when the reset came from a changed prompt or model, the untouched files hold
    answers from the configuration being replaced, under a stamp saying complete.
    """

    @pytest.fixture
    def executor(self):
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = MagicMock(spec=ActionStateManager)
        deps.state_manager.adopt_truncation_marker.return_value = False
        deps.action_runner = MagicMock()
        deps.action_runner.retried_records = frozenset()
        return ActionExecutor(deps)

    def _reset_under(self, executor, caplog, action_config, stored):
        executor.deps.state_manager.get_status_details.return_value = stored
        with caplog.at_level("WARNING", logger="agent_actions.workflow.executor"):
            status = executor._maybe_invalidate_completed_status(
                "act", action_config, ActionStatus.COMPLETED
            )
        assert status == ActionStatus.PENDING
        return [r.message for r in caplog.records if "file limit" in r.message]

    def test_a_config_change_under_a_file_limit_is_announced(self, executor, caplog):
        said = self._reset_under(
            executor,
            caplog,
            {"file_limit": 1, "prompt": "new"},
            {"record_limit": None, "file_limit": 1, "config_hash": "stale"},
        )

        assert len(said) == 1
        assert "previous configuration" in said[0]

    def test_a_model_change_under_a_file_limit_is_announced(self, executor, caplog):
        said = self._reset_under(
            executor,
            caplog,
            {"file_limit": 2, "model_name": "new-model"},
            {"record_limit": None, "file_limit": 2, "model_name": "old-model"},
        )

        assert len(said) == 1

    def test_a_config_change_without_a_file_limit_says_nothing(self, executor, caplog):
        """The control: every file is walked, so the whole output is rebuilt."""
        said = self._reset_under(
            executor,
            caplog,
            {"prompt": "new"},
            {"record_limit": None, "file_limit": None, "config_hash": "stale"},
        )

        assert said == []

    def test_a_limit_change_alone_says_nothing(self, executor, caplog):
        """The control: nothing semantic changed, so the untouched files still
        hold answers this configuration would produce."""
        said = self._reset_under(
            executor,
            caplog,
            {"file_limit": 1},
            {"record_limit": None, "file_limit": 5},
        )

        assert said == []


class TestTheBatchPauseWiring:
    """The call sites, not just the helper they call.

    A stamp helper that behaves perfectly is worth nothing if the submission
    never writes it or the collection never asks to keep it, and both of those
    are one keyword argument.
    """

    @pytest.fixture
    def executor(self, tmp_path):
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = ActionStateManager(tmp_path / ".agent_status.json", ["act"])
        deps.action_runner = MagicMock()
        deps.action_runner.retried_records = frozenset()
        backend = MagicMock()
        backend.count_records_for_action.return_value = 0
        backend.get_storage_stats.return_value = {"total_records": 0}
        deps.action_runner.storage_backend = backend
        deps.output_manager = MagicMock()
        deps.batch_manager = MagicMock()
        executor = ActionExecutor(deps)
        executor._record_action_start = MagicMock()
        return executor

    def _submit(self, executor, action_config):
        params = MagicMock()
        params.action_name = "act"
        params.action_config = action_config
        executor._handle_run_success(
            params,
            output_folder="/out",
            duration=0.1,
            batch_status="batch_submitted",
            pre_run_count=0,
        )
        return executor.deps.state_manager.get_status_details("act")

    def test_the_submission_records_the_limits_it_walked_under(self, executor, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")

        stored = self._submit(executor, {})

        assert stored["file_limit"] == 1
        assert stored["status"] == ActionStatus.BATCH_SUBMITTED

    def test_the_submission_records_the_config_it_walked_under(self, executor):
        stored = self._submit(executor, {"model_name": "model-at-submission"})

        assert stored["model_name"] == "model-at-submission"
        assert stored["config_hash"]

    def test_the_collection_keeps_what_the_submission_recorded(self, executor, monkeypatch):
        """The whole point of the pause: a run that collects work it did not do
        must not describe it from its own configuration."""
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")
        self._submit(executor, {"model_name": "model-at-submission"})
        monkeypatch.delenv("AGAC_FILE_LIMIT")
        executor._compute_batch_wall_clock = MagicMock(return_value=1.0)
        executor._resolve_completion_status = MagicMock(return_value=ActionStatus.COMPLETED)
        executor._emit_action_complete = MagicMock()

        executor._resolve_batch_outcome(
            "act",
            0,
            {"model_name": "model-now"},
            "/out",
            "completed",
            1.0,
            0,
        )
        stored = executor.deps.state_manager.get_status_details("act")

        assert stored["file_limit"] == 1, "the collecting run's own doors overwrote the stamp"
        assert stored["model_name"] == "model-at-submission"
        assert stored["status"] == ActionStatus.COMPLETED

    def test_the_collection_keeps_what_the_submitting_run_observed(self, executor, monkeypatch):
        """The count and the truncation flag are observed while slicing, which
        only the submitting run does. The collecting process slices nothing, so
        resolving them there records the action as uncountable and throws away
        the one thing that can tell a short run from a complete one."""
        backend = executor.deps.action_runner.storage_backend
        record_indices_to_process(
            [{"source_guid": f"r{i}"} for i in range(5)],
            {"record_limit": 2},
            "act",
            storage_backend=backend,
        )
        self._submit(executor, {"record_limit": 2})
        assert executor.deps.state_manager.get_status_details("act")["records_processed"] == 2

        executor._compute_batch_wall_clock = MagicMock(return_value=1.0)
        executor._resolve_completion_status = MagicMock(return_value=ActionStatus.COMPLETED)
        executor._emit_action_complete = MagicMock()
        executor._resolve_batch_outcome("act", 0, {"record_limit": 2}, "/out", "completed", 1.0, 0)
        stored = executor.deps.state_manager.get_status_details("act")

        assert stored["records_processed"] == 2, "the collecting run overwrote the observation"
        assert stored["truncated"] is True

    def test_a_collected_batch_still_reopens_when_the_limit_is_lifted(self, executor, monkeypatch):
        """What the stamp is for: the next ordinary run must see the change."""
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")
        self._submit(executor, {})
        monkeypatch.delenv("AGAC_FILE_LIMIT")
        executor._compute_batch_wall_clock = MagicMock(return_value=1.0)
        executor._resolve_completion_status = MagicMock(return_value=ActionStatus.COMPLETED)
        executor._emit_action_complete = MagicMock()
        executor._resolve_batch_outcome("act", 0, {}, "/out", "completed", 1.0, 0)

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.PENDING


class TestLimitSchemaValidation:
    def test_record_limit_rejects_zero(self):
        from pydantic import ValidationError

        from agent_actions.config.schema import ActionConfig

        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            ActionConfig(
                name="test",
                intent="test",
                record_limit=0,
            )

    def test_record_limit_rejects_negative(self):
        from pydantic import ValidationError

        from agent_actions.config.schema import ActionConfig

        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            ActionConfig(
                name="test",
                intent="test",
                record_limit=-5,
            )

    def test_file_limit_rejects_zero(self):
        from pydantic import ValidationError

        from agent_actions.config.schema import ActionConfig

        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            ActionConfig(
                name="test",
                intent="test",
                file_limit=0,
            )

    def test_limits_accept_none(self):
        from agent_actions.config.schema import ActionConfig

        config = ActionConfig(name="test", intent="test")
        assert config.record_limit is None
        assert config.file_limit is None

    def test_limits_accept_positive(self):
        from agent_actions.config.schema import ActionConfig

        config = ActionConfig(name="test", intent="test", record_limit=10, file_limit=5)
        assert config.record_limit == 10
        assert config.file_limit == 5
