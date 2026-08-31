"""prompt_trace rows carry the durable record identity.

``record_id`` keeps holding the prepare-time ``target_id`` (per-run,
re-minted on every prepare); joins and response updates key on the durable
``source_guid`` — expansion children reach their parent's trace via
``parent_source_guid``. ``run_id`` marks the writing run and reprompt rounds
stamp ``attempt``, so the table works as the bounded historical log it is
documented to be.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.prepared_task import PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "score"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "test.db"), workflow_name="test_workflow")
    b.initialize()
    return b


def _prepare(backend, *, source_guid="sg-1", run_id=None, attempt=None):
    """Run the real prepare() trace write against a real backend."""
    ctx = PreparationContext(
        agent_config={"model_name": "m1", "model_vendor": "v1"},
        agent_name=ACTION,
        workflow_metadata={"name": "wf", "run_id": run_id or ""},
        storage_backend=backend,
    )
    preparer = TaskPreparer()
    item = {"content": {"q": 1}, "source_guid": source_guid}
    rendered = SimpleNamespace(
        formatted_prompt="compiled prompt",
        llm_context={},
        passthrough_fields={},
        prompt_context={},
    )
    kwargs = {} if attempt is None else {"attempt": attempt}
    with (
        patch.object(preparer, "_normalize_input", return_value=(item, source_guid, item)),
        patch.object(preparer, "_load_full_context", return_value={}),
        patch.object(preparer, "_render_prompt", return_value=rendered),
    ):
        return preparer.prepare(item, ctx, **kwargs)


class TestTraceRowsCarryDurableIdentity:
    def test_prepared_trace_row_carries_source_guid_and_run_id(self, backend):
        _prepare(backend, source_guid="sg-1", run_id="run-123")

        rows = backend.get_prompt_traces(ACTION)
        assert len(rows) == 1
        assert rows[0]["source_guid"] == "sg-1"
        assert rows[0]["run_id"] == "run-123"
        # record_id keeps holding the prepare-time target_id.
        assert rows[0]["record_id"] not in (None, "", "sg-1")

    def test_unregistered_run_stores_null_run_id(self, backend):
        """Batch prep can run before any run is registered — honest NULL, not ""."""
        _prepare(backend, source_guid="sg-1", run_id=None)

        rows = backend.get_prompt_traces(ACTION)
        assert rows[0]["run_id"] is None

    def test_disposition_join_on_source_guid_is_real(self, backend):
        """The cross-table join dispositions ⋈ traces was 0 rows for every
        store measured — both tables must key on the same identity space."""
        _prepare(backend, source_guid="sg-1")
        backend.set_disposition(ACTION, "sg-1", "success")

        cursor = backend.connection.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) AS n
            FROM record_disposition d
            JOIN prompt_trace p
              ON d.action_name = p.action_name AND d.record_id = p.source_guid
            WHERE d.action_name = ?
            """,
            (ACTION,),
        )
        assert cursor.fetchone()["n"] == 1

    def test_legacy_store_gains_identity_columns_on_open(self, tmp_path):
        """A pre-migration store gets the columns ALTER-added; old rows keep
        NULL and stay readable."""
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE prompt_trace ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  action_name TEXT NOT NULL,"
            "  record_id TEXT NOT NULL,"
            "  attempt INTEGER NOT NULL DEFAULT 0,"
            "  compiled_prompt TEXT NOT NULL,"
            "  llm_context TEXT, response_text TEXT, model_name TEXT,"
            "  model_vendor TEXT, run_mode TEXT, prompt_length INTEGER,"
            "  context_length INTEGER, response_length INTEGER,"
            "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,"
            "  UNIQUE(action_name, record_id, attempt))"
        )
        conn.execute(
            "INSERT INTO prompt_trace (action_name, record_id, compiled_prompt)"
            " VALUES ('act', 'tid-old', 'old prompt')"
        )
        conn.commit()
        conn.close()

        b = SQLiteBackend(str(db_path), workflow_name="legacy")
        b.initialize()
        rows = b.get_prompt_traces("act")
        assert len(rows) == 1
        assert rows[0]["compiled_prompt"] == "old prompt"
        assert rows[0]["source_guid"] is None
        assert rows[0]["run_id"] is None


class TestResponseUpdatesKeyOnIdentity:
    def test_response_lands_by_source_guid_not_prepare_time_id(self, backend):
        backend.write_prompt_trace(ACTION, "tid-1", "prompt", source_guid="g1", run_id="run-1")

        backend.update_prompt_trace_response(ACTION, source_guid="g1", response_text="resp")

        rows = backend.get_prompt_traces(ACTION)
        assert rows[0]["response_text"] == "resp"

    def test_response_lands_on_newest_attempt(self, backend):
        """A reprompt round adds attempt=1; the final response belongs to it,
        never to the superseded attempt-0 prompt."""
        backend.write_prompt_trace(ACTION, "tid-1", "prompt v1", source_guid="g1", attempt=0)
        backend.write_prompt_trace(ACTION, "tid-1", "prompt v2", source_guid="g1", attempt=1)

        backend.update_prompt_trace_response(ACTION, source_guid="g1", response_text="final")

        by_attempt = {r["attempt"]: r for r in backend.get_prompt_traces(ACTION)}
        assert by_attempt[1]["response_text"] == "final"
        assert by_attempt[0]["response_text"] is None

    def test_batch_expansion_response_lands_on_parent_trace(self, backend):
        """The measured defect: batch expansion children carry re-minted
        target_ids, so the shipped UPDATE matched zero rows and every
        expansion trace kept NULL response_text (4/4 measured)."""
        from agent_actions.llm.batch.services.processing import BatchProcessingService
        from agent_actions.record.state import RecordState

        backend.write_prompt_trace(ACTION, "tid-parent", "prompt", source_guid="gp")

        service = SimpleNamespace(_storage_backend=backend)
        items = [
            {
                "_state": RecordState.PROCESSED.value,
                "target_id": "tid-child-reminted",
                "source_guid": "gc-child",
                "parent_source_guid": "gp",
                "content": {ACTION: {"answer": 42}},
            }
        ]
        BatchProcessingService._update_prompt_trace_responses(service, items, ACTION)

        rows = backend.get_prompt_traces(ACTION)
        assert rows[0]["response_text"] == '{"answer": 42}'

    def test_missing_trace_row_is_a_noop(self, backend):
        backend.update_prompt_trace_response(
            ACTION, source_guid="never-written", response_text="resp"
        )
        assert backend.get_prompt_traces(ACTION) == []


class TestScanPreviewAttachesByIdentity:
    def _seed_target(self, backend, records):
        backend.write_target(ACTION, "out.json", records, force_full=True)

    def test_expansion_children_get_their_parents_trace(self, backend):
        """The shipped reader joined preview target_ids against record_id —
        measured: no expansion action ever got a _trace attached."""
        backend.write_prompt_trace(ACTION, "tid-parent", "parent prompt", source_guid="gp")
        self._seed_target(
            backend,
            [
                {"source_guid": "gc-1", "parent_source_guid": "gp", "target_id": "tid-c1"},
                {"source_guid": "gc-2", "parent_source_guid": "gp", "target_id": "tid-c2"},
            ],
        )

        result = backend.scan_data()
        preview = result["nodes"][ACTION]["preview"]
        assert len(preview) == 2
        for rec in preview:
            assert rec.get("_trace") is not None
            assert rec["_trace"]["compiled_prompt"] == "parent prompt"

    def test_one_to_one_records_join_their_own_trace(self, backend):
        backend.write_prompt_trace(ACTION, "tid-1", "own prompt", source_guid="g1")
        self._seed_target(backend, [{"source_guid": "g1", "target_id": "tid-1"}])

        result = backend.scan_data()
        preview = result["nodes"][ACTION]["preview"]
        assert preview[0].get("_trace") is not None
        assert preview[0]["_trace"]["compiled_prompt"] == "own prompt"

    def test_newest_attempt_wins_the_attachment(self, backend):
        backend.write_prompt_trace(ACTION, "tid-1", "prompt v1", source_guid="g1", attempt=0)
        backend.write_prompt_trace(ACTION, "tid-1", "prompt v2", source_guid="g1", attempt=1)
        self._seed_target(backend, [{"source_guid": "g1", "target_id": "tid-1"}])

        result = backend.scan_data()
        assert result["nodes"][ACTION]["preview"][0]["_trace"]["attempt"] == 1

    def test_record_without_identity_gets_no_trace(self, backend):
        backend.write_prompt_trace(ACTION, "tid-1", "prompt", source_guid="g1")
        self._seed_target(backend, [{"target_id": "tid-1"}])

        result = backend.scan_data()
        assert "_trace" not in result["nodes"][ACTION]["preview"][0]


class TestRepromptRoundsStampAttempt:
    def test_prepare_stamps_the_round_attempt(self, backend):
        """Round N's re-prepare must land at attempt=N, not overwrite attempt 0."""
        _prepare(backend, source_guid="sg-1", attempt=0)
        _prepare(backend, source_guid="sg-1", attempt=1)

        attempts = sorted(r["attempt"] for r in backend.get_prompt_traces(ACTION))
        assert attempts == [0, 1]

    def test_submit_reprompt_batch_threads_its_round_number(self):
        """The round owner passes its attempt through to task preparation."""
        from agent_actions.llm.providers.batch_base import BatchResult

        with (
            patch(
                "agent_actions.llm.batch.services.reprompt_ops._load_source_data_for_reprompt",
                return_value=[],
            ),
            patch(
                "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
            ) as MockPreparator,
            patch("agent_actions.processing.recovery.reprompt.parse_reprompt_config") as mock_parse,
            patch(
                "agent_actions.processing.recovery.validation.get_validation_function",
                return_value=(lambda x: False, "fix it"),
            ),
        ):
            from agent_actions.llm.batch.services.reprompt_ops import submit_reprompt_batch

            mock_parse.return_value = MagicMock(
                validation_name="check_it", max_attempts=3, on_exhausted="return_last"
            )
            prep = MockPreparator.return_value
            prep.prepare_tasks.return_value = MagicMock(tasks=[{"target_id": "t1"}])
            provider = MagicMock()
            provider.submit_batch.return_value = ("batch-1", "submitted")

            submit_reprompt_batch(
                action_indices={},
                dependency_configs={},
                storage_backend=MagicMock(),
                provider=provider,
                failed_results=[BatchResult(custom_id="t1", content="bad", success=True)],
                context_map={"t1": {"content": {"q": "a"}, "user_content": "u"}},
                output_directory="/tmp/out",
                file_name="batch_1",
                agent_config={"reprompt": {"validation": "check_it"}},
                attempt=2,
            )

            assert prep.prepare_tasks.call_args.kwargs.get("attempt") == 2
