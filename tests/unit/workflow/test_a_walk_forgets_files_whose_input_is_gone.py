"""A complete walk deletes what the action stores for an input that is gone (1258).

A reset relies on the re-run writing each file again, and a file whose input was
removed is never written, so its rows stood. The walk is the one place that knows
which inputs it reached, so it deletes the rest once it has reached every input
there is, and only then: a file limit that stopped it, an entry it lost, or a
repair each leave the stored files alone.

Each test's processing writes nothing, as a batch submission does: what is kept
is what the walk can name, not what it happened to rewrite.
"""

from __future__ import annotations

import logging
import sqlite3
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import AgentActionsError, DependencyError, mark_action_fatal
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow import runner_file_processing
from agent_actions.workflow.runner import ActionRunner, FileProcessParams
from agent_actions.workflow.runner_file_processing import process_files


def _configured(runner: ActionRunner) -> ActionRunner:
    """A runner as a run sets it up: it reads stored input only with its action configs."""
    runner.action_configs = {}
    return runner


ACTION = "flatten"
UPSTREAM = "extract"


@pytest.fixture(autouse=True)
def _no_ambient_limit(monkeypatch):
    for name in ("AGAC_RECORD_LIMIT", "AGAC_FILE_LIMIT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _runner(backend, *, fail=()) -> ActionRunner:
    """A runner whose processing stores nothing and fails for the files named."""
    runner = _configured(ActionRunner(use_tools=True, storage_backend=backend))

    def process(params):
        if params.locations.item.name in fail:
            raise RuntimeError("down")

    runner._process_single_file = process  # type: ignore[method-assign]
    return runner


def _params(dirs, *, action_config=None) -> FileProcessParams:
    return FileProcessParams(
        action_config=action_config or {},
        action_name=ACTION,
        strategy=MagicMock(),
        upstream_data_dirs=[str(d) for d in dirs],
        output_directory="out",
        idx=0,
    )


def _staged(tmp_path, *names):
    staging = tmp_path / "staging"
    for name in names:
        (staging / name).parent.mkdir(parents=True, exist_ok=True)
        (staging / name).write_text("[]")
    staging.mkdir(exist_ok=True)
    return staging


def _store(backend, *names, action=ACTION):
    for name in names:
        backend._write_target_raw(
            action, name, [{"source_guid": name, "_state": "processed", "_delta_mode": "full"}]
        )


def _held(backend, action=ACTION):
    return backend.list_target_files(action)


def _two_upstreams(tmp_path, *names):
    """Two upstream directories a merged walk reads, each holding *names*."""
    first, second = tmp_path / "first", tmp_path / "second"
    for directory in (first, second):
        directory.mkdir()
        for name in names:
            (directory / name).write_text("[]")
    return first, second


class TestAStagingWalk:
    def test_the_file_of_an_input_that_is_gone_goes(self, backend, tmp_path):
        _store(backend, "gone.json", "pages.json")

        process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _held(backend) == ["pages.json"]

    def test_an_input_is_matched_by_its_path_and_the_name_it_is_stored_under(
        self, backend, tmp_path
    ):
        """A first stage stores `notes.csv` as `notes.json`, and a nested file by its path."""
        _store(backend, "notes.json", "sub/pages.json", "pages.json", "sub/gone.json")

        process_files(
            _runner(backend), _params([_staged(tmp_path, "notes.csv", "sub/pages.json")])
        )

        assert _held(backend) == ["notes.json", "sub/pages.json"]

    def test_an_input_is_matched_by_the_name_the_store_gives_it(self, backend, tmp_path):
        """The store strips the whitespace around a name and turns a backslash into a slash."""
        _store(backend, " lead.json", "export\\part.json", "gone.json")

        process_files(
            _runner(backend), _params([_staged(tmp_path, " lead.json", "export\\part.json")])
        )

        assert _held(backend) == ["export/part.json", "lead.json"]

    def test_a_file_that_failed_keeps_its_rows(self, backend, tmp_path):
        _store(backend, "broken.json", "gone.json", "pages.json")

        process_files(
            _runner(backend, fail={"broken.json"}),
            _params([_staged(tmp_path, "broken.json", "pages.json")]),
        )

        assert _held(backend) == ["broken.json", "pages.json"]

    def test_a_walk_where_every_file_failed_deletes_nothing(self, backend, tmp_path):
        """It raises, and a walk that raised has said nothing about what is gone."""
        _store(backend, "gone.json", "pages.json")

        with pytest.raises(DependencyError):
            process_files(
                _runner(backend, fail={"pages.json"}), _params([_staged(tmp_path, "pages.json")])
            )

        assert _held(backend) == ["gone.json", "pages.json"]

    def test_a_walk_that_lost_an_entry_deletes_nothing(self, backend, tmp_path):
        """It cannot say which inputs are gone."""
        staging = _staged(tmp_path, "pages.json")
        (staging / "dangling.json").symlink_to(staging / "nowhere.json")
        _store(backend, "gone.json", "pages.json")

        process_files(_runner(backend), _params([staging]))

        assert _held(backend) == ["gone.json", "pages.json"]

    def test_a_walk_that_could_not_list_a_directory_deletes_nothing(
        self, backend, tmp_path, monkeypatch
    ):
        """What lay beneath it may still be there."""
        staging = _staged(tmp_path, "pages.json")
        _store(backend, "gone.json", "pages.json", "sub/kept.json")
        walk_files = runner_file_processing.walk_files

        def walk(root, on_error):
            on_error(PermissionError(13, "Permission denied", str(root / "sub")))
            return walk_files(root, on_error)

        monkeypatch.setattr(runner_file_processing, "walk_files", walk)

        process_files(_runner(backend), _params([staging]))

        assert _held(backend) == ["gone.json", "pages.json", "sub/kept.json"]

    def test_a_file_limit_that_stops_the_walk_deletes_nothing(self, backend, tmp_path):
        """A file it never opened keeps what the last run put there, on purpose."""
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(
            _runner(backend),
            _params([_staged(tmp_path, "a.json", "b.json")], action_config={"file_limit": 1}),
        )

        assert _held(backend) == ["a.json", "b.json", "gone.json"]

    def test_a_file_limit_reached_on_the_last_file_left_still_deletes(self, backend, tmp_path):
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(
            _runner(backend),
            _params([_staged(tmp_path, "a.json", "b.json")], action_config={"file_limit": 2}),
        )

        assert _held(backend) == ["a.json", "b.json"]

    def test_a_repair_deletes_nothing(self, backend, tmp_path):
        """It touches only the records it named."""
        _store(backend, "gone.json", "pages.json")
        runner = _runner(backend)
        runner.retried_records = frozenset({"g0"})

        process_files(runner, _params([_staged(tmp_path, "pages.json")]))

        assert _held(backend) == ["gone.json", "pages.json"]

    def test_a_warning_names_the_files_deleted(self, backend, tmp_path, caplog):
        """A reset that a flag set off can delete stored output; the user hears which."""
        _store(backend, "gone.json", "pages.json")

        with caplog.at_level(logging.WARNING, logger=runner_file_processing.__name__):
            process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert "gone.json" in warning.getMessage()
        assert "pages.json" not in warning.getMessage()

    def test_a_warning_names_a_few_of_many_files_deleted_and_counts_the_rest(
        self, backend, tmp_path, caplog
    ):
        """It is logged for every action that reads the input, so it stays one line."""
        _store(backend, *(f"gone_{n}.json" for n in range(5)), "pages.json")

        with caplog.at_level(logging.WARNING, logger=runner_file_processing.__name__):
            process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert "gone_0.json, gone_1.json, gone_2.json (and 2 more)" in warning.getMessage()
        assert "gone_3.json" not in warning.getMessage()
        assert _held(backend) == ["pages.json"]

    def test_a_delete_that_fails_only_warns(self, backend, tmp_path, monkeypatch, caplog):
        _store(backend, "gone.json", "pages.json")

        def refuse(*_args):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(backend, "delete_target_files", refuse)
        with caplog.at_level(logging.WARNING, logger=runner_file_processing.__name__):
            process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _held(backend) == ["gone.json", "pages.json"]
        assert "database is locked" in caplog.text


def _sent(backend, name, *, status="completed", collected=True, parent=None, key=None):
    """A registry entry for *name*, and for a main batch its context map and recorded inputs."""
    from agent_actions.llm.batch.core.batch_models import BatchJobEntry
    from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

    BatchRegistryManager(backend, ACTION).save_batch_job(
        key or name,
        BatchJobEntry(
            batch_id=f"batch-{key or name}",
            status=status,
            timestamp="2026-11-24T00:00:00+00:00",
            provider="openai",
            file_name=key or name,
            parent_file_name=parent,
            recovery_type="retry" if parent else None,
            collected_at="2026-11-24T00:01:00+00:00" if collected else None,
        ),
    )
    if parent is None:
        _recorded(backend, name)


def _recorded(backend, name):
    """The batch state a run keeps in metadata for *name*, with no registry entry."""
    from agent_actions.llm.batch.infrastructure.context import BatchContextManager

    BatchContextManager.save_batch_context_map(backend, ACTION, {"c1": {}}, name)
    BatchContextManager.save_batch_inputs(backend, ACTION, ["g1"], name)


def _batch_state(backend):
    from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

    keys = {
        key.split(":", 2)[2].split("#", 1)[0]
        for prefix in ("batch_context", "batch_inputs")
        for key in backend.list_metadata_prefix(f"{prefix}:{ACTION}:")
    }
    return sorted(keys), sorted(BatchRegistryManager(backend, ACTION).get_all_jobs())


def _metadata(backend):
    """Every batch metadata key the action holds, and the registry's entries."""
    from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

    keys = [
        key
        for prefix in ("batch_context", "batch_inputs", "batch_no_input", "recovery_state")
        for key in backend.list_metadata_prefix(f"{prefix}:{ACTION}:")
    ]
    return keys, sorted(BatchRegistryManager(backend, ACTION).get_all_jobs())


@pytest.fixture
def released(monkeypatch):
    """The batch ids whose local record is released; each release succeeds."""
    from agent_actions.llm.providers import local_batch_records

    ids: list[str] = []

    def release(batch_id):
        ids.append(batch_id)
        return True

    monkeypatch.setattr(local_batch_records, "release_local_batch_record", release)
    return ids


# "expired" is a status agac does not know: it is taken as still running.
STATUSES = [
    "submitted",
    "validating",
    "in_progress",
    "finalizing",
    "completed",
    "expired",
    "failed",
    "cancelled",
]


def _owed(status, collected):
    return not collected and status not in {"failed", "cancelled"}


class TestTheBatchStateOfAFileWhoseInputIsGone:
    def test_it_goes_with_the_file_and_the_other_file_keeps_its_own(self, backend, tmp_path):
        _store(backend, "gone.json", "pages.json")
        for name in ("gone.json", "pages.json"):
            _sent(backend, name)
        _sent(backend, "", parent="gone.json", key="gone.json_retry_1")

        process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _held(backend) == ["pages.json"]
        assert _batch_state(backend) == (["pages.json"], ["pages.json"])

    def test_a_batch_still_owed_keeps_it_with_a_warning(self, backend, tmp_path, caplog):
        """Its results are paid for, and a collect pass reads the state to write them."""
        _store(backend, "gone.json", "pages.json")
        _sent(backend, "gone.json", status="submitted", collected=False)

        with caplog.at_level(logging.WARNING, logger=runner_file_processing.__name__):
            process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _batch_state(backend) == (["gone.json"], ["gone.json"])
        assert "batch batch-gone.json sent for it is not collected" in caplog.text
        assert _held(backend) == ["pages.json"]

    @pytest.mark.parametrize("collected", [False, True], ids=["uncollected", "collected"])
    @pytest.mark.parametrize("status", STATUSES)
    def test_a_main_batch_keeps_it_only_while_owed(
        self, backend, tmp_path, released, status, collected
    ):
        """A batch completed and not collected is owed: its results are not written yet."""
        _store(backend, "gone.json", "pages.json")
        _sent(backend, "gone.json", status=status, collected=collected)
        before = _metadata(backend)

        process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        if _owed(status, collected):
            assert _metadata(backend) == before
            assert released == []
        else:
            assert _metadata(backend) == ([], [])
            assert released == ["batch-gone.json"]
        assert _held(backend) == ["pages.json"]

    @pytest.mark.parametrize("collected", [False, True], ids=["uncollected", "collected"])
    @pytest.mark.parametrize("status", STATUSES)
    def test_a_recovery_batch_keeps_it_only_while_owed(
        self, backend, tmp_path, released, status, collected
    ):
        """Also when the main batch is collected: the recovery round is owed on its own."""
        _store(backend, "gone.json", "pages.json")
        _sent(backend, "gone.json")
        _sent(
            backend,
            "",
            status=status,
            collected=collected,
            parent="gone.json",
            key="gone.json_retry_1",
        )
        before = _metadata(backend)

        process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        if _owed(status, collected):
            assert _metadata(backend) == before
            assert released == []
        else:
            assert _metadata(backend) == ([], [])
            assert sorted(released) == ["batch-gone.json", "batch-gone.json_retry_1"]
        assert _held(backend) == ["pages.json"]

    def test_its_recovery_state_and_no_input_mark_go(self, backend, tmp_path, released):
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager

        _store(backend, "gone.json", "pages.json")
        _sent(backend, "gone.json")
        backend.save_metadata(f"recovery_state:{ACTION}:gone.json", "{}")
        BatchContextManager.record_no_input(backend, ACTION, "gone.json")

        process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert backend.load_metadata(f"recovery_state:{ACTION}:gone.json") is None
        assert backend.load_metadata(f"batch_no_input:{ACTION}:gone.json") is None
        assert _metadata(backend) == ([], [])

    def test_a_file_no_registry_entry_names_goes(self, backend, tmp_path, released):
        """A submission that stopped before it saved its entry leaves only the metadata."""
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager

        _store(backend, "gone.json", "pages.json")
        _recorded(backend, "gone.json")
        backend.save_metadata(f"recovery_state:{ACTION}:gone.json", "{}")
        BatchContextManager.record_no_input(backend, ACTION, "gone.json")

        process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _metadata(backend) == ([], [])
        assert _held(backend) == ["pages.json"]

    @pytest.mark.parametrize("prefix", ["recovery_state", "batch_no_input", "batch_inputs"])
    def test_a_file_one_key_alone_names_goes(self, backend, tmp_path, released, prefix):
        _store(backend, "gone.json", "pages.json")
        backend.save_metadata(f"{prefix}:{ACTION}:gone.json", "{}")

        process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _metadata(backend) == ([], [])

    def test_parts_its_parts_key_does_not_name_go(self, backend, tmp_path, released):
        """A save that stopped after it wrote its parts key leaves the earlier parts."""
        _store(backend, "gone.json", "pages.json", "gone.json.bak")
        _sent(backend, "gone.json")
        backend.save_metadata(f"batch_context:{ACTION}:gone.json#0123456789ab:000000", "{}")
        backend.save_metadata(f"batch_context:{ACTION}:gone.json.bak#parts", "{}")

        process_files(
            _runner(backend), _params([_staged(tmp_path, "pages.json", "gone.json.bak")])
        )

        assert _metadata(backend) == ([f"batch_context:{ACTION}:gone.json.bak#parts"], [])
        assert _held(backend) == ["gone.json.bak", "pages.json"]

    def test_an_unreadable_parts_key_goes_with_its_parts(self, backend, tmp_path, released):
        _store(backend, "gone.json", "pages.json")
        _sent(backend, "gone.json")
        parts_key = f"batch_context:{ACTION}:gone.json#parts"
        backend.save_metadata(parts_key, "not json")

        process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _metadata(backend) == ([], [])
        assert _held(backend) == ["pages.json"]

    def test_a_file_whose_name_differs_only_in_case_keeps_its_own(
        self, backend, tmp_path, released
    ):
        """An input renamed from item.json to Item.json: the gone item.json takes nothing of
        Item.json's batch state, which the next run reads to collect its batch."""
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager

        _store(backend, "item.json", "Item.json")
        for name in ("item.json", "Item.json"):
            _sent(backend, name)

        process_files(_runner(backend), _params([_staged(tmp_path, "Item.json")]))

        assert _held(backend) == ["Item.json"]
        assert _batch_state(backend) == (["Item.json"], ["Item.json"])
        assert BatchContextManager.load_batch_context_map(backend, ACTION, "Item.json") == {
            "c1": {}
        }

    def test_a_release_that_fails_keeps_the_entry_and_deletes_the_rows(
        self, backend, tmp_path, monkeypatch, caplog
    ):
        """The walk does not come back to a file it deleted, so the warning says what does."""
        from agent_actions.llm.providers import local_batch_records

        _store(backend, "gone.json", "pages.json")
        _sent(backend, "gone.json")
        monkeypatch.setattr(local_batch_records, "release_local_batch_record", lambda _id: False)

        with caplog.at_level(logging.WARNING, logger=runner_file_processing.__name__):
            process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _batch_state(backend) == (["gone.json"], ["gone.json"])
        assert _held(backend) == ["pages.json"]
        assert "the local record of batch batch-gone.json is not released" in caplog.text
        assert "agac clean --all" in caplog.text

    def test_a_cleanup_that_fails_keeps_that_file_s_batch_state_and_deletes_the_rows(
        self, backend, tmp_path, monkeypatch, caplog, released
    ):
        """The other files' batch state goes, and the warning names the batch state left."""
        from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryStateManager

        _store(backend, "a.json", "b.json", "c.json", "pages.json")
        for name in ("a.json", "b.json", "c.json"):
            _sent(backend, name)
        delete = RecoveryStateManager.delete

        def refuse_b(store, action_name, file_name):
            if file_name == "b.json":
                raise sqlite3.OperationalError("database is locked")
            return delete(store, action_name, file_name)

        monkeypatch.setattr(RecoveryStateManager, "delete", staticmethod(refuse_b))

        with caplog.at_level(logging.WARNING, logger=runner_file_processing.__name__):
            process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _held(backend) == ["pages.json"]
        assert _batch_state(backend)[1] == ["b.json"]
        assert sorted(released) == ["batch-a.json", "batch-b.json", "batch-c.json"]
        assert f"Could not delete the batch state '{ACTION}' holds for b.json" in caplog.text
        assert "database is locked" in caplog.text
        assert "agac clean --all" in caplog.text
        assert "Could not delete what" not in caplog.text

    def test_batch_state_it_could_not_read_stays_and_the_rows_go(
        self, backend, tmp_path, monkeypatch, caplog
    ):
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

        _store(backend, "gone.json", "pages.json")
        _sent(backend, "gone.json")

        def unreadable(self):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(BatchRegistryManager, "get_all_jobs", unreadable)

        with caplog.at_level(logging.WARNING, logger=runner_file_processing.__name__):
            process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))
        monkeypatch.undo()

        assert _held(backend) == ["pages.json"]
        assert _batch_state(backend) == (["gone.json"], ["gone.json"])
        assert f"Could not read the batch state of '{ACTION}'" in caplog.text
        assert "agac clean --all" in caplog.text


class TestAStorageWalk:
    def test_a_reader_lets_go_of_a_file_its_upstream_no_longer_holds(self, backend, tmp_path):
        _store(backend, "pages.json", action=UPSTREAM)
        _store(backend, "gone.json", "pages.json")

        process_files(_runner(backend), _params([tmp_path / "target" / UPSTREAM]))

        assert _held(backend) == ["pages.json"]

    def test_a_file_that_failed_keeps_its_rows(self, backend, tmp_path):
        _store(backend, "a.json", "b.json", action=UPSTREAM)
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(_runner(backend, fail={"b.json"}), _params([tmp_path / "target" / UPSTREAM]))

        assert _held(backend) == ["a.json", "b.json"]

    def test_a_file_limit_that_stops_the_walk_deletes_nothing(self, backend, tmp_path):
        """`--file-limit` stops a reader as it stops a first stage."""
        _store(backend, "a.json", "b.json", action=UPSTREAM)
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(
            _runner(backend),
            _params([tmp_path / "target" / UPSTREAM], action_config={"file_limit": 1}),
        )

        assert _held(backend) == ["a.json", "b.json", "gone.json"]

    def test_a_stored_file_it_could_not_read_keeps_everything(
        self, backend, tmp_path, monkeypatch
    ):
        _store(backend, "a.json", "b.json", action=UPSTREAM)
        _store(backend, "a.json", "b.json", "gone.json")
        read = backend.read_target

        def read_target(action_name, relative_path):
            if action_name == UPSTREAM and relative_path == "b.json":
                raise sqlite3.OperationalError("disk I/O error")
            return read(action_name, relative_path)

        monkeypatch.setattr(backend, "read_target", read_target)

        process_files(_runner(backend), _params([tmp_path / "target" / UPSTREAM]))

        assert _held(backend) == ["a.json", "b.json", "gone.json"]

    def test_a_walk_an_action_fatal_error_stopped_deletes_nothing(self, backend, tmp_path):
        _store(backend, "a.json", "b.json", action=UPSTREAM)
        _store(backend, "a.json", "b.json", "gone.json")
        runner = _runner(backend)

        def process(params):
            if params.locations.item.name == "b.json":
                raise mark_action_fatal(AgentActionsError("provider refused the key"))

        runner._process_single_file = process  # type: ignore[method-assign]

        with pytest.raises(DependencyError):
            process_files(runner, _params([tmp_path / "target" / UPSTREAM]))

        assert _held(backend) == ["a.json", "b.json", "gone.json"]

    def test_a_version_merge_is_walked_through_the_input_it_is_handed(self, backend, tmp_path):
        """Not through its own stored files, which hold its answers (1318)."""
        _store(backend, "a.json", "gone.json")
        walked = []
        runner = _runner(backend)
        runner._process_single_file = lambda p: walked.append((p.locations.item.name, p.data))  # type: ignore[method-assign]
        params = _params([tmp_path / "target" / ACTION])
        params.correlated_input = {"a.json": [{"source_guid": "merged"}], "empty.json": []}

        process_files(runner, params)

        assert walked == [("a.json", [{"source_guid": "merged"}]), ("empty.json", [])]
        assert _held(backend) == ["a.json"]

    def test_an_upstream_it_could_not_list_keeps_everything(self, backend, tmp_path, monkeypatch):
        other = "lister"
        _store(backend, "pages.json", action=UPSTREAM)
        _store(backend, "gone.json", "pages.json")
        listed = backend.list_target_files

        def list_target_files(action_name):
            if action_name == other:
                raise sqlite3.OperationalError("disk I/O error")
            return listed(action_name)

        monkeypatch.setattr(backend, "list_target_files", list_target_files)
        dirs = [tmp_path / "target" / UPSTREAM, tmp_path / "target" / other]

        process_files(_runner(backend), _params(dirs))

        assert listed(ACTION) == ["gone.json", "pages.json"]


class TestAMergedWalk:
    def test_the_file_of_an_input_no_upstream_holds_goes(self, backend, tmp_path):
        _store(backend, "gone.json", "pages.json")

        process_files(_runner(backend), _params(_two_upstreams(tmp_path, "pages.json")))

        assert _held(backend) == ["pages.json"]

    def test_a_file_that_failed_keeps_its_rows(self, backend, tmp_path):
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(
            _runner(backend, fail={"b.json"}),
            _params(_two_upstreams(tmp_path, "a.json", "b.json")),
        )

        assert _held(backend) == ["a.json", "b.json"]

    def test_a_file_limit_that_stops_the_walk_deletes_nothing(self, backend, tmp_path):
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(
            _runner(backend),
            _params(_two_upstreams(tmp_path, "a.json", "b.json"), action_config={"file_limit": 1}),
        )

        assert _held(backend) == ["a.json", "b.json", "gone.json"]

    def test_a_walk_that_lost_an_entry_deletes_nothing(self, backend, tmp_path):
        first, second = _two_upstreams(tmp_path, "a.json")
        (first / "dangling.json").symlink_to(first / "nowhere.json")
        _store(backend, "a.json", "gone.json")

        process_files(_runner(backend), _params([first, second]))

        assert _held(backend) == ["a.json", "gone.json"]
