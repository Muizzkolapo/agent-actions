"""Unit tests for TaskPreparer (Phase 2 #890)."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.prepared_task import GuardStatus, PreparationContext, PreparedTask
from agent_actions.processing.task_preparer import TaskPreparer


@pytest.fixture
def basic_agent_config():
    """Basic agent configuration."""
    return {
        "agent_type": "test_agent",
        "prompt": "Test prompt: {{ content }}",
    }


@pytest.fixture
def basic_context(basic_agent_config):
    """Basic preparation context."""
    return PreparationContext(
        agent_config=basic_agent_config,
        agent_name="test_agent",
        is_first_stage=True,
    )


@pytest.fixture
def subsequent_stage_context(basic_agent_config):
    """Subsequent stage preparation context."""
    return PreparationContext(
        agent_config=basic_agent_config,
        agent_name="test_agent",
        is_first_stage=False,
        source_data=[{"source_guid": "guid-123", "content": {"original": "data"}}],
    )


class TestPreparedTaskDataclass:
    """Tests for PreparedTask dataclass."""

    @pytest.mark.parametrize(
        "guard_status,guard_behavior,should_execute,is_passthrough,is_filtered",
        [
            pytest.param(GuardStatus.PASSED, None, True, False, False, id="passed"),
            pytest.param(GuardStatus.SKIPPED, "skip", False, True, False, id="skipped"),
            pytest.param(GuardStatus.FILTERED, "filter", False, False, True, id="filtered"),
        ],
    )
    def test_guard_status_properties(
        self, guard_status, guard_behavior, should_execute, is_passthrough, is_filtered
    ):
        task = PreparedTask(
            target_id="t1",
            source_guid="g1",
            guard_status=guard_status,
            guard_behavior=guard_behavior,
        )
        assert task.should_execute is should_execute
        assert task.is_passthrough is is_passthrough
        assert task.is_filtered is is_filtered


class TestPreparationContext:
    """Tests for PreparationContext dataclass."""

    def test_from_processing_context(self):
        """Test creating PreparationContext from ProcessingContext."""
        from agent_actions.config.types import RunMode
        from agent_actions.processing.types import ProcessingContext

        processing_ctx = ProcessingContext(
            agent_config={"agent_type": "test", "prompt": "test"},
            agent_name="test_agent",
            mode=RunMode.ONLINE,
            is_first_stage=True,
            source_data=[{"a": 1}],
            file_path="/tmp/test.json",
            version_context={"i": 0},
        )

        prep_ctx = PreparationContext.from_processing_context(processing_ctx)

        assert prep_ctx.agent_config == processing_ctx.agent_config
        assert prep_ctx.agent_name == "test_agent"
        assert prep_ctx.is_first_stage is True
        assert prep_ctx.source_data == [{"a": 1}]
        assert prep_ctx.file_path == "/tmp/test.json"
        assert prep_ctx.version_context == {"i": 0}


class TestPreparationContextBatchMode:
    """Tests for batch mode derivation in PreparationContext."""

    def test_preparation_context_batch_mode_derived(self):
        """mode is RunMode.BATCH when ProcessingContext.mode is BATCH."""
        from agent_actions.config.types import RunMode
        from agent_actions.processing.types import ProcessingContext

        processing_ctx = ProcessingContext(
            agent_config={"agent_type": "test", "prompt": "test"},
            agent_name="test_agent",
            mode=RunMode.BATCH,
            is_first_stage=True,
        )

        prep_ctx = PreparationContext.from_processing_context(processing_ctx)

        assert prep_ctx.mode == RunMode.BATCH

    def test_preparation_context_online_mode_not_batch(self):
        """mode is RunMode.ONLINE when ProcessingContext.mode is ONLINE."""
        from agent_actions.config.types import RunMode
        from agent_actions.processing.types import ProcessingContext

        processing_ctx = ProcessingContext(
            agent_config={"agent_type": "test", "prompt": "test"},
            agent_name="test_agent",
            mode=RunMode.ONLINE,
            is_first_stage=True,
        )

        prep_ctx = PreparationContext.from_processing_context(processing_ctx)

        assert prep_ctx.mode == RunMode.ONLINE


class TestTaskPreparerNormalization:
    """Tests for TaskPreparer input normalization."""

    def test_first_stage_generates_source_guid(self, basic_context):
        """Test first-stage generates source_guid."""
        preparer = TaskPreparer()
        content, source_guid, snapshot = preparer._normalize_input(
            {"field": "value"}, basic_context
        )

        assert content == {"field": "value"}
        assert source_guid  # Non-empty
        assert snapshot == {"field": "value"}

    def test_first_stage_filters_chunk_info(self, basic_context):
        """Test first-stage filters chunk_info metadata."""
        preparer = TaskPreparer()
        item = {
            "field": "value",
            "chunk_info": {"index": 0},
            "target_id": "should_be_removed",
            "record_index": 5,
        }
        content, source_guid, snapshot = preparer._normalize_input(item, basic_context)

        # Snapshot should have chunk_info but not target_id/record_index
        assert "chunk_info" in snapshot
        assert "target_id" not in snapshot
        assert "record_index" not in snapshot
        assert "field" in snapshot

    def test_subsequent_stage_extracts_content(self, subsequent_stage_context):
        """Test subsequent-stage extracts content and source_guid."""
        preparer = TaskPreparer()
        item = {"content": {"extracted": "data"}, "source_guid": "guid-456"}

        content, source_guid, snapshot = preparer._normalize_input(item, subsequent_stage_context)

        assert content == {"extracted": "data"}
        assert source_guid == "guid-456"
        assert snapshot == item

    def test_subsequent_stage_non_dict_input(self, subsequent_stage_context):
        """Test subsequent-stage handles non-dict input."""
        preparer = TaskPreparer()
        content, source_guid, snapshot = preparer._normalize_input(
            "raw string", subsequent_stage_context
        )

        assert content == "raw string"
        assert source_guid is None  # None triggers fallback lineage/recovery
        assert snapshot is None


class TestTaskPreparerGuardEvaluation:
    """Tests for guard evaluation."""

    def test_no_guard_passes(self, basic_context):
        """Test no guard config means task passes."""
        preparer = TaskPreparer()

        # Mock context loading and prompt rendering
        with (
            patch.object(preparer, "_load_full_context") as mock_ctx,
            patch.object(preparer, "_render_prompt") as mock_prep,
        ):
            mock_ctx.return_value = {"content": "test"}
            mock_result = MagicMock()
            mock_result.formatted_prompt = "test"
            mock_result.llm_context = {}
            mock_result.passthrough_fields = {}
            mock_result.prompt_context = {}
            mock_prep.return_value = mock_result

            result = preparer.prepare({"status": "active"}, basic_context)

        assert result.guard_status == GuardStatus.PASSED
        assert result.should_execute is True


class TestTaskPreparerPrepare:
    """Tests for TaskPreparer.prepare() method."""

    @patch("agent_actions.processing.task_preparer.TaskPreparer._load_full_context")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._render_prompt")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._evaluate_guard")
    def test_prepare_returns_prepared_task(
        self, mock_guard, mock_render_prompt, mock_load_ctx, basic_context
    ):
        """Test prepare returns PreparedTask with all fields."""
        # Setup mocks - context loading
        mock_load_ctx.return_value = {"content": "test", "full": "context"}

        # Setup mocks - guard passes
        mock_guard_result = MagicMock()
        mock_guard_result.should_execute = True
        mock_guard.return_value = mock_guard_result

        mock_prep_result = MagicMock()
        mock_prep_result.formatted_prompt = "Rendered prompt"
        mock_prep_result.llm_context = {"key": "value"}
        mock_prep_result.passthrough_fields = {"pass": "through"}
        mock_prep_result.prompt_context = {"full": "context"}
        mock_render_prompt.return_value = mock_prep_result

        # Add guard to trigger evaluation
        basic_context.agent_config["guard"] = {"clause": "True", "behavior": "skip"}

        preparer = TaskPreparer()
        result = preparer.prepare({"content": "test"}, basic_context)

        assert isinstance(result, PreparedTask)
        assert result.formatted_prompt == "Rendered prompt"
        assert result.llm_context == {"key": "value"}
        assert result.passthrough_fields == {"pass": "through"}
        assert result.guard_status == GuardStatus.PASSED
        assert result.should_execute is True

    @patch("agent_actions.processing.task_preparer.TaskPreparer._load_full_context")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._evaluate_guard")
    def test_prepare_guard_skip(self, mock_guard, mock_load_ctx, basic_context):
        """Test prepare returns skipped task when guard skips (no prompt rendering)."""
        # Setup context loading
        mock_load_ctx.return_value = {"content": "test"}

        # Guard skips - prompt should NOT be rendered
        mock_guard_result = MagicMock()
        mock_guard_result.should_execute = False
        mock_guard_result.behavior = "skip"
        mock_guard.return_value = mock_guard_result

        basic_context.agent_config["guard"] = {"clause": "x == 1", "behavior": "skip"}

        preparer = TaskPreparer()
        result = preparer.prepare({"content": "test"}, basic_context)

        assert result.guard_status == GuardStatus.SKIPPED
        assert result.guard_behavior == "skip"
        assert result.should_execute is False
        assert result.is_passthrough is True
        # Prompt should NOT be rendered for skipped items
        assert result.formatted_prompt == ""

    @patch("agent_actions.processing.task_preparer.TaskPreparer._load_full_context")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._evaluate_guard")
    def test_prepare_guard_filter(self, mock_guard, mock_load_ctx, basic_context):
        """Test prepare returns filtered task when guard filters (no prompt rendering)."""
        # Setup context loading
        mock_load_ctx.return_value = {"content": "test"}

        # Guard filters - prompt should NOT be rendered
        mock_guard_result = MagicMock()
        mock_guard_result.should_execute = False
        mock_guard_result.behavior = "filter"
        mock_guard.return_value = mock_guard_result

        basic_context.agent_config["guard"] = {"clause": "x == 1", "behavior": "filter"}

        preparer = TaskPreparer()
        result = preparer.prepare({"content": "test"}, basic_context)

        assert result.guard_status == GuardStatus.FILTERED
        assert result.guard_behavior == "filter"
        assert result.should_execute is False
        assert result.is_filtered is True
        # Prompt should NOT be rendered for filtered items
        assert result.formatted_prompt == ""


class TestGuardEvaluatedOnce:
    """Tests to verify guards are evaluated exactly once."""

    @patch("agent_actions.processing.task_preparer.TaskPreparer._load_full_context")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._render_prompt")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._evaluate_guard")
    def test_guard_evaluated_exactly_once(self, mock_guard, mock_render_prompt, mock_load_ctx):
        """Verify _evaluate_guard is called exactly once per prepare() call."""
        # Setup mocks
        mock_load_ctx.return_value = {"x": 10}

        mock_guard_result = MagicMock()
        mock_guard_result.should_execute = True
        mock_guard.return_value = mock_guard_result

        mock_prep_result = MagicMock()
        mock_prep_result.formatted_prompt = "test"
        mock_prep_result.llm_context = {}
        mock_prep_result.passthrough_fields = {}
        mock_prep_result.prompt_context = {}
        mock_render_prompt.return_value = mock_prep_result

        context = PreparationContext(
            agent_config={"agent_type": "test", "prompt": "test", "guard": {"clause": "x > 0"}},
            agent_name="test",
            is_first_stage=True,
        )

        preparer = TaskPreparer()
        preparer.prepare({"x": 10}, context)

        # Guard should be evaluated exactly once
        assert mock_guard.call_count == 1

    @patch("agent_actions.processing.task_preparer.TaskPreparer._load_full_context")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._render_prompt")
    def test_no_guard_skips_evaluation(self, mock_render_prompt, mock_load_ctx):
        """Verify _evaluate_guard is NOT called when no guard configured."""
        mock_load_ctx.return_value = {"x": 10}

        mock_prep_result = MagicMock()
        mock_prep_result.formatted_prompt = "test"
        mock_prep_result.llm_context = {}
        mock_prep_result.passthrough_fields = {}
        mock_prep_result.prompt_context = {}
        mock_render_prompt.return_value = mock_prep_result

        context = PreparationContext(
            agent_config={"agent_type": "test", "prompt": "test"},  # No guard
            agent_name="test",
            is_first_stage=True,
        )

        preparer = TaskPreparer()
        with patch.object(preparer, "_evaluate_guard") as mock_guard:
            preparer.prepare({"x": 10}, context)
            # Guard should NOT be called when no guard config
            assert mock_guard.call_count == 0


class TestModeSelection:
    """Tests for batch/online mode selection based on RunMode."""

    @patch(
        "agent_actions.prompt.service.PromptPreparationService.prepare_prompt_with_field_context"
    )
    @patch("agent_actions.processing.task_preparer.TaskPreparer._load_full_context")
    def test_online_mode_uses_online(self, mock_load_ctx, mock_prepare):
        """Test that online processing (mode=RunMode.ONLINE) uses online mode."""
        from agent_actions.config.types import RunMode

        mock_load_ctx.return_value = {"content": "test"}

        mock_result = MagicMock()
        mock_result.formatted_prompt = "test"
        mock_result.llm_context = {}
        mock_result.passthrough_fields = {}
        mock_result.prompt_context = {}
        mock_prepare.return_value = mock_result

        context = PreparationContext(
            agent_config={"agent_type": "test", "prompt": "test"},
            agent_name="test",
            is_first_stage=True,
            mode=RunMode.ONLINE,
            version_context=None,
        )

        preparer = TaskPreparer()
        preparer.prepare({"content": "test"}, context)

        mock_prepare.assert_called_once()
        call_kwargs = mock_prepare.call_args[1]
        assert call_kwargs["mode"] == RunMode.ONLINE

    @patch(
        "agent_actions.prompt.service.PromptPreparationService.prepare_prompt_with_field_context"
    )
    @patch("agent_actions.processing.task_preparer.TaskPreparer._load_full_context")
    def test_batch_mode_uses_batch(self, mock_load_ctx, mock_prepare):
        """Test that batch processing (mode=RunMode.BATCH) uses batch mode."""
        from agent_actions.config.types import RunMode

        mock_load_ctx.return_value = {"content": "test"}

        mock_result = MagicMock()
        mock_result.formatted_prompt = "test"
        mock_result.llm_context = {}
        mock_result.passthrough_fields = {}
        mock_result.prompt_context = {}
        mock_prepare.return_value = mock_result

        context = PreparationContext(
            agent_config={"agent_type": "test", "prompt": "test"},
            agent_name="test",
            is_first_stage=False,
            mode=RunMode.BATCH,
        )

        preparer = TaskPreparer()
        preparer.prepare({"content": "test"}, context)

        mock_prepare.assert_called_once()
        call_kwargs = mock_prepare.call_args[1]
        assert call_kwargs["mode"] == RunMode.BATCH

    @patch(
        "agent_actions.prompt.service.PromptPreparationService.prepare_prompt_with_field_context"
    )
    @patch("agent_actions.processing.task_preparer.TaskPreparer._load_full_context")
    def test_online_with_loop_uses_online(self, mock_load_ctx, mock_prepare):
        """Test that online processing with loop context also uses online mode."""
        from agent_actions.config.types import RunMode

        mock_load_ctx.return_value = {"content": "test"}

        mock_result = MagicMock()
        mock_result.formatted_prompt = "test"
        mock_result.llm_context = {}
        mock_result.passthrough_fields = {}
        mock_result.prompt_context = {}
        mock_prepare.return_value = mock_result

        context = PreparationContext(
            agent_config={"agent_type": "test", "prompt": "test"},
            agent_name="test",
            is_first_stage=False,
            mode=RunMode.ONLINE,
            version_context={"iteration": 1},
        )

        preparer = TaskPreparer()
        preparer.prepare({"content": "test"}, context)

        mock_prepare.assert_called_once()
        call_kwargs = mock_prepare.call_args[1]
        assert call_kwargs["mode"] == RunMode.ONLINE


class TestGuardBeforePromptRendering:
    """Tests to verify guards are evaluated BEFORE prompt rendering.

    This prevents template errors on rows that should be filtered.
    """

    @patch("agent_actions.processing.task_preparer.TaskPreparer._load_full_context")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._evaluate_guard")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._render_prompt")
    def test_guard_filter_prevents_prompt_rendering(
        self, mock_render_prompt, mock_guard, mock_load_ctx
    ):
        """Verify filtered items don't trigger prompt rendering."""
        # Setup context loading
        mock_load_ctx.return_value = {"status": "inactive"}

        # Guard filters the item
        mock_guard_result = MagicMock()
        mock_guard_result.should_execute = False
        mock_guard_result.behavior = "filter"
        mock_guard.return_value = mock_guard_result

        context = PreparationContext(
            agent_config={
                "agent_type": "test",
                "prompt": "{{ missing_field }}",  # Would fail if rendered
                "guard": {"clause": "status == 'active'", "behavior": "filter"},
            },
            agent_name="test",
            is_first_stage=True,
        )

        preparer = TaskPreparer()
        # Item is missing 'missing_field' but should be filtered, not error
        result = preparer.prepare({"status": "inactive"}, context)

        # Guard should be called
        assert mock_guard.call_count == 1
        # Prompt should NOT be rendered for filtered items
        assert mock_render_prompt.call_count == 0
        assert result.guard_status == GuardStatus.FILTERED
        assert result.formatted_prompt == ""

    @patch("agent_actions.processing.task_preparer.TaskPreparer._load_full_context")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._evaluate_guard")
    @patch("agent_actions.processing.task_preparer.TaskPreparer._render_prompt")
    def test_guard_pass_triggers_prompt_rendering(
        self, mock_render_prompt, mock_guard, mock_load_ctx
    ):
        """Verify passing items DO trigger prompt rendering."""
        # Setup context loading
        mock_load_ctx.return_value = {"status": "active", "field": "value"}

        # Guard passes the item
        mock_guard_result = MagicMock()
        mock_guard_result.should_execute = True
        mock_guard.return_value = mock_guard_result

        mock_prep_result = MagicMock()
        mock_prep_result.formatted_prompt = "Rendered: value"
        mock_prep_result.llm_context = {}
        mock_prep_result.passthrough_fields = {}
        mock_prep_result.prompt_context = {}
        mock_render_prompt.return_value = mock_prep_result

        context = PreparationContext(
            agent_config={
                "agent_type": "test",
                "prompt": "{{ field }}",
                "guard": {"clause": "status == 'active'", "behavior": "filter"},
            },
            agent_name="test",
            is_first_stage=True,
        )

        preparer = TaskPreparer()
        result = preparer.prepare({"status": "active", "field": "value"}, context)

        # Guard should be called
        assert mock_guard.call_count == 1
        # Prompt SHOULD be rendered for passing items
        assert mock_render_prompt.call_count == 1
        assert result.guard_status == GuardStatus.PASSED
        assert result.formatted_prompt == "Rendered: value"
