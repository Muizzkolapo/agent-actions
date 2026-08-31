"""prompt_trace rows carry both identities a consumer can need.

``source_guid`` is durable and shared with ``record_disposition``, so the two
tables finally join. ``record_id`` stays the prepare-time ``target_id``, which
answers "which prompt produced this record on this run" without reaching rows
an earlier run left behind; an expansion's children reach their prompt through
``parent_target_id``.
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

    def test_missing_trace_row_is_a_noop(self, backend):
        backend.update_prompt_trace_response(
            ACTION, record_id="never-written", response_text="resp"
        )
        assert backend.get_prompt_traces(ACTION) == []


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


class TestRepromptRoundsStampAttempt:
    def test_prepare_stamps_the_round_attempt(self, backend):
        """Round N's re-prepare must land at attempt=N, not overwrite attempt 0."""
        _prepare(backend, source_guid="sg-1", attempt=0)
        _prepare(backend, source_guid="sg-1", attempt=1)

        attempts = sorted(r["attempt"] for r in backend.get_prompt_traces(ACTION))
        assert attempts == [0, 1]

    def test_batch_preparation_stamps_the_round_on_the_trace(self, backend):
        """The round number crosses three layers that each default it to 0;
        this pins the whole chain against a real backend, so a dropped
        hand-off writes attempt 0 and the round overwrites its predecessor."""
        from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator

        preparator = BatchTaskPreparator(storage_backend=backend)
        provider = MagicMock()
        provider.prepare_tasks.side_effect = lambda tasks, config: tasks

        with (
            patch.object(BatchTaskPreparator, "_validate_config", return_value=None),
            patch.object(BatchTaskPreparator, "_run_preflight_validation", return_value=None),
            patch(
                "agent_actions.prompt.formatter.PromptFormatter.get_raw_prompt",
                return_value="prompt",
            ),
            patch(
                "agent_actions.prompt.service.PromptPreparationService."
                "prepare_prompt_with_field_context",
                return_value=SimpleNamespace(
                    formatted_prompt="p", llm_context={}, passthrough_fields={}, prompt_context={}
                ),
            ),
        ):
            preparator.prepare_tasks(
                agent_config={"name": ACTION},
                data=[{"target_id": "tid-1", "source_guid": "g1", "content": {"q": 1}}],
                provider=provider,
                output_directory="/tmp/out",
                batch_name="b1",
                attempt=2,
            )

        rows = backend.get_prompt_traces(ACTION)
        assert len(rows) == 1
        assert rows[0]["attempt"] == 2
        assert rows[0]["source_guid"] == "g1"

    def test_the_synchronous_reprompt_loop_threads_its_round_number(self):
        """There are two reprompt submitters; the synchronous loop runs on every
        batch run. Left at the default the round reuses its target_id at
        attempt 0 and INSERT OR REPLACE overwrites the previous round."""
        from agent_actions.llm.batch.services.reprompt_ops import validate_and_reprompt
        from agent_actions.llm.providers.batch_base import BatchResult

        with (
            patch(
                "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
            ) as MockPreparator,
            patch(
                "agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop"
            ) as mock_setup,
            patch(
                "agent_actions.llm.batch.services.reprompt_ops._load_source_data_for_reprompt",
                return_value=[],
            ),
        ):
            loop = MagicMock()
            loop.split.return_value = (
                [],
                [BatchResult(custom_id="t1", content="bad", success=True)],
                {},
            )
            strategy = MagicMock(
                max_attempts=2,
                on_exhausted="return_last",
                _feedback_message="fix it",
                _strategies=[],
            )
            strategy.name = "check_it"
            mock_setup.return_value = (loop, strategy)
            prep = MockPreparator.return_value
            prep.prepare_tasks.return_value = MagicMock(tasks=[{"target_id": "t1"}])
            provider = MagicMock()
            # Stop the round right after preparation — submission and polling
            # are not what this pins.
            provider.submit_batch.side_effect = RuntimeError("stop after prepare")

            with pytest.raises(RuntimeError, match="stop after prepare"):
                validate_and_reprompt(
                    action_indices={},
                    dependency_configs={},
                    storage_backend=MagicMock(),
                    results=[BatchResult(custom_id="t1", content="bad", success=True)],
                    provider=provider,
                    context_map={"t1": {"content": {"q": "a"}, "user_content": "u"}},
                    output_directory="/tmp/out",
                    file_name="batch_1",
                    agent_config={"reprompt": {"validation": "check_it"}},
                )

        assert prep.prepare_tasks.called, "the synchronous loop must reach task preparation"
        assert prep.prepare_tasks.call_args.kwargs.get("attempt") == 1

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
