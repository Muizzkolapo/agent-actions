"""prompt_trace rows carry both identities a consumer can need.

``source_guid`` is durable and shared with ``record_disposition``, so the two
tables finally join. ``record_id`` stays the prepare-time ``target_id``, which
answers "which prompt produced this record on this run" without reaching rows
an earlier run left behind; an expansion's children reach their prompt through
``parent_target_id``.
"""

from __future__ import annotations

import logging
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

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


def _batch_update(backend, items: list[dict]) -> None:
    """Drive the real batch trace-update over already-processed items."""
    from agent_actions.llm.batch.services.processing import BatchProcessingService
    from agent_actions.record.state import RecordState

    service = SimpleNamespace(_storage_backend=backend)
    BatchProcessingService._update_prompt_trace_responses(
        service,
        [{"_state": RecordState.PROCESSED.value, **item} for item in items],
        ACTION,
    )


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

    def test_legacy_store_stays_readable_opened_read_only(self, tmp_path):
        """A read-only open never runs the ALTER pass, so naming the new
        columns unconditionally would turn every read of an old store into
        an error — which is how the docs scanner reads them."""
        db_path = tmp_path / "legacy_ro.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE prompt_trace ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  action_name TEXT NOT NULL, record_id TEXT NOT NULL,"
            "  attempt INTEGER NOT NULL DEFAULT 0, compiled_prompt TEXT NOT NULL,"
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

        b = SQLiteBackend.create_readonly(db_path)
        try:
            rows = b.get_prompt_traces("act")
            assert [r["compiled_prompt"] for r in rows] == ["old prompt"]
            preview = b.preview_prompt_traces("act")
            assert preview["total_count"] == 1
            assert "source_guid" not in preview["records"][0]
        finally:
            b.close()

    def test_a_records_own_identifier_is_never_rejected(self, backend):
        """A first-stage row may bring its own source_guid — an order number,
        an email, anything. Refusing one here would fail the record out of
        processing entirely over a telemetry write."""
        for guid in ("ORD-2024:001", "user@example.com", "a+b", "café-1"):
            prepared = _prepare(backend, source_guid=guid)
            assert prepared.source_guid == guid

        stored = {r["source_guid"] for r in backend.get_prompt_traces(ACTION)}
        assert stored == {"ORD-2024:001", "user@example.com", "a+b", "café-1"}


class TestResponseUpdatesReachTheRecordsOwnPrompt:
    def test_response_lands_on_the_prepared_task(self, backend):
        backend.write_prompt_trace(ACTION, "tid-1", "prompt", source_guid="g1", run_id="run-1")

        backend.update_prompt_trace_response(ACTION, record_id="tid-1", response_text="resp")

        rows = backend.get_prompt_traces(ACTION)
        assert rows[0]["response_text"] == "resp"

    def test_response_lands_on_newest_attempt(self, backend):
        """A reprompt round adds attempt=1; the final response belongs to it,
        never to the superseded attempt-0 prompt."""
        backend.write_prompt_trace(ACTION, "tid-1", "prompt v1", source_guid="g1", attempt=0)
        backend.write_prompt_trace(ACTION, "tid-1", "prompt v2", source_guid="g1", attempt=1)

        backend.update_prompt_trace_response(ACTION, record_id="tid-1", response_text="final")

        by_attempt = {r["attempt"]: r for r in backend.get_prompt_traces(ACTION)}
        assert by_attempt[1]["response_text"] == "final"
        assert by_attempt[0]["response_text"] is None

    def test_batch_expansion_response_lands_on_parent_trace(self, backend):
        """The measured defect: batch expansion children carry re-minted
        target_ids, so the shipped UPDATE matched zero rows and every
        expansion trace kept NULL response_text (4/4 measured)."""
        backend.write_prompt_trace(ACTION, "tid-parent", "prompt", source_guid="gp")

        _batch_update(
            backend,
            [
                {
                    "target_id": "tid-child-reminted",
                    "parent_target_id": "tid-parent",
                    "source_guid": "gc-child",
                    "parent_source_guid": "gp",
                    "content": {ACTION: {"answer": 42}},
                }
            ],
        )

        rows = backend.get_prompt_traces(ACTION)
        assert rows[0]["response_text"] == '{"answer": 42}'

    def test_a_record_prepared_here_keeps_its_own_response(self, backend):
        """A fan-in action can prepare both an expansion child and the
        unexpanded sibling it descends from. The child was prompted here in its
        own right, so its response belongs to its own trace — never to the
        ancestor its parent pointer still names."""
        # The ancestor's row is written last, so insertion order alone would
        # hand this record's response to it.
        backend.write_prompt_trace(ACTION, "tid-child", "CHILD prompt", source_guid="gc")
        backend.write_prompt_trace(ACTION, "tid-ancestor", "ANCESTOR prompt", source_guid="gp")

        _batch_update(
            backend,
            [
                {
                    "target_id": "tid-child",
                    "parent_target_id": "tid-ancestor",
                    "source_guid": "gc",
                    "content": {ACTION: {"who": "child"}},
                }
            ],
        )

        rows = {r["record_id"]: r for r in backend.get_prompt_traces(ACTION)}
        assert rows["tid-child"]["response_text"] == '{"who": "child"}'
        assert rows["tid-ancestor"]["response_text"] is None

    def test_a_new_runs_response_never_lands_on_the_previous_runs_trace(self, backend):
        """Traces accumulate across runs under a durable guid; only the
        per-run prepared id keeps this run's response off last run's row."""
        backend.write_prompt_trace(
            ACTION, "tid-run1", "run1 prompt", source_guid="g1", run_id="run-1", attempt=0
        )
        backend.write_prompt_trace(
            ACTION, "tid-run1", "run1 reprompt", source_guid="g1", run_id="run-1", attempt=1
        )
        backend.write_prompt_trace(
            ACTION, "tid-run2", "run2 prompt", source_guid="g1", run_id="run-2", attempt=0
        )

        backend.update_prompt_trace_response(
            ACTION, record_id="tid-run2", response_text="run2 resp"
        )

        by_run = {(r["run_id"], r["attempt"]): r for r in backend.get_prompt_traces(ACTION)}
        assert by_run[("run-2", 0)]["response_text"] == "run2 resp"
        assert by_run[("run-1", 1)]["response_text"] is None

    def test_online_response_lands_on_the_records_trace(self, backend):
        """End-to-end on the everyday online path: prepare writes the trace and
        the response must reach it. This is asserted nowhere else, so a wrong
        key here would leave every online trace NULL, silently."""
        from agent_actions.processing.invocation.result import InvocationResult
        from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
        from agent_actions.processing.types import ProcessingContext

        agent_config = {"model_name": "m1"}
        invocation = SimpleNamespace(
            invoke=lambda prepared, context: InvocationResult(
                response={"answer": "online"}, executed=True
            )
        )
        strategy = OnlineLLMStrategy(agent_config, ACTION, invocation_strategy=invocation)
        context = ProcessingContext(agent_config=agent_config, agent_name=ACTION)
        context.storage_backend = backend

        with patch(
            "agent_actions.prompt.service.PromptPreparationService."
            "prepare_prompt_with_field_context",
            return_value=SimpleNamespace(
                formatted_prompt="p", llm_context={}, passthrough_fields={}, prompt_context={}
            ),
        ):
            strategy.process_record({"content": {"q": 1}, "source_guid": "g1"}, context)

        rows = backend.get_prompt_traces(ACTION)
        assert len(rows) == 1
        assert rows[0]["source_guid"] == "g1"
        assert rows[0]["response_text"] == '{"answer": "online"}'

    def test_a_response_with_no_trace_row_is_reported(self, backend, caplog):
        """Silence here is how the expansion defect stayed hidden: the UPDATE
        matched nothing and said nothing."""
        with caplog.at_level(logging.WARNING):
            backend.update_prompt_trace_response(
                ACTION, record_id="never-written", response_text="resp"
            )

        assert backend.get_prompt_traces(ACTION) == []
        assert any("never-written" in r.getMessage() for r in caplog.records), (
            "a response with no row to land on must be reported"
        )


class TestScanPreviewAttachesByIdentity:
    def _seed_target(self, backend, records):
        backend.write_target(ACTION, "out.json", records, force_full=True)

    def test_expansion_children_get_their_parents_trace(self, backend):
        """The shipped reader looked only at the child's own target_id, which
        was minted after the prompt ran — measured: no expansion action ever
        got a _trace attached."""
        backend.write_prompt_trace(ACTION, "tid-parent", "parent prompt", source_guid="gp")
        self._seed_target(
            backend,
            [
                {"source_guid": "gc-1", "target_id": "tid-c1", "parent_target_id": "tid-parent"},
                {"source_guid": "gc-2", "target_id": "tid-c2", "parent_target_id": "tid-parent"},
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

    def test_record_that_was_never_prompted_gets_no_trace(self, backend):
        """A guard-skipped record has no trace of its own; it must not inherit
        one from a record that was prompted."""
        backend.write_prompt_trace(ACTION, "tid-prompted", "prompt", source_guid="g1")
        self._seed_target(backend, [{"source_guid": "g-skipped", "target_id": "tid-skipped"}])

        result = backend.scan_data()
        assert "_trace" not in result["nodes"][ACTION]["preview"][0]

    def test_a_tombstone_does_not_inherit_a_previous_runs_prompt(self, backend):
        """source_guid is durable across runs, so keying previews on it would
        show last run's prompt for a record this run never prompted."""
        backend.write_prompt_trace(
            ACTION, "tid-run1", "run1 prompt", source_guid="g1", run_id="run-1"
        )
        self._seed_target(backend, [{"source_guid": "g1", "target_id": "tid-run2-skipped"}])

        result = backend.scan_data()
        assert "_trace" not in result["nodes"][ACTION]["preview"][0]

    def test_a_record_prepared_here_shows_its_own_prompt(self, backend):
        """A record carries a parent pointer from an earlier stage while also
        having been prompted here in its own right; its preview must show the
        prompt this action ran for it, not the one its parent pointer names."""
        backend.write_prompt_trace(ACTION, "tid-ancestor", "ANCESTOR prompt", source_guid="gp")
        backend.write_prompt_trace(ACTION, "tid-1", "own prompt", source_guid="gc-1")
        self._seed_target(
            backend,
            [{"source_guid": "gc-1", "target_id": "tid-1", "parent_target_id": "tid-ancestor"}],
        )

        result = backend.scan_data()
        trace = result["nodes"][ACTION]["preview"][0].get("_trace")
        assert trace is not None
        assert trace["compiled_prompt"] == "own prompt"

    def test_preview_shows_the_current_runs_prompt(self, backend):
        """A previous run's reprompt round must not outrank this run's trace."""
        backend.write_prompt_trace(
            ACTION, "tid-run1", "run1 reprompt", source_guid="g1", run_id="run-1", attempt=1
        )
        backend.write_prompt_trace(
            ACTION, "tid-run2", "run2 prompt", source_guid="g1", run_id="run-2", attempt=0
        )
        self._seed_target(backend, [{"source_guid": "g1", "target_id": "tid-run2"}])

        result = backend.scan_data()
        assert result["nodes"][ACTION]["preview"][0]["_trace"]["compiled_prompt"] == "run2 prompt"


class TestRunIdReachesTheWriter:
    def test_first_stage_carries_the_run_namespace(self):
        """The first stage builds its own workflow metadata; dropping the
        runner's leaves run_id NULL on every trace a first action writes —
        measured on a live run before this was threaded."""
        from agent_actions.workflow.strategies import InitialStrategy, StrategyExecutionParams

        with patch(
            "agent_actions.workflow.strategies.process_initial_stage", return_value="out.json"
        ) as mock_stage:
            InitialStrategy().execute(
                StrategyExecutionParams(
                    action_config={},
                    action_name=ACTION,
                    file_path="in.json",
                    base_directory="/base",
                    output_directory="/out",
                    idx=0,
                    workflow_metadata={"name": "wf", "run_id": "run-123"},
                )
            )

        ctx = mock_stage.call_args.args[0]
        assert ctx.workflow_metadata == {"name": "wf", "run_id": "run-123"}

    def test_a_first_stage_trace_records_its_run(self, backend, tmp_path):
        """End-to-end past the context hand-off: the run must survive all the
        way onto the row. Asserting only that the context carries it leaves the
        two lines that actually spend it unpinned."""
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )
        from agent_actions.processing.invocation.result import InvocationResult

        src = tmp_path / "in.json"
        src.write_text('[{"q": 1}]')
        out = tmp_path / "out"
        out.mkdir()

        with (
            patch(
                "agent_actions.processing.invocation.factory.InvocationStrategyFactory.create",
                return_value=SimpleNamespace(
                    invoke=lambda prepared, context: InvocationResult(
                        response={"a": 1}, executed=True
                    )
                ),
            ),
            patch(
                "agent_actions.prompt.service.PromptPreparationService."
                "prepare_prompt_with_field_context",
                return_value=SimpleNamespace(
                    formatted_prompt="p", llm_context={}, passthrough_fields={}, prompt_context={}
                ),
            ),
        ):
            process_initial_stage(
                InitialStageContext(
                    agent_config={
                        "model_name": "m1",
                        "file_type": "json",
                        "context_scope": {"observe": ["*"]},
                    },
                    agent_name=ACTION,
                    file_path=str(src),
                    base_directory=str(tmp_path),
                    output_directory=str(out),
                    storage_backend=backend,
                    workflow_metadata={"name": "wf", "run_id": "run-abc"},
                )
            )

        rows = backend.get_prompt_traces(ACTION)
        assert rows, "the first stage must write a trace"
        assert all(r["run_id"] == "run-abc" for r in rows)
