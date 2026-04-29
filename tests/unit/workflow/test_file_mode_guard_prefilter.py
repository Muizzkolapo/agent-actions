"""Tests for FILE-mode guard pre-filter."""

from unittest.mock import MagicMock, patch

from agent_actions.input.preprocessing.filtering.evaluator import GuardResult
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard


def _make_evaluator(pass_fn):
    """Create a mock evaluator whose evaluate delegates to pass_fn.

    pass_fn receives the eval_item dict and returns True if the item should pass.
    """
    evaluator = MagicMock()

    def side_effect(*, item, guard_config, context=None, conditional_clause=None):
        if pass_fn(item):
            return GuardResult.passed()
        return GuardResult.filtered()

    evaluator.evaluate.side_effect = side_effect
    return evaluator


class TestPrefilterByGuard:
    """Tests for prefilter_by_guard()."""

    def test_no_guard_returns_all(self):
        """No guard config -> all records pass, no skipped."""
        data = [{"content": {"x": 1}}, {"content": {"x": 2}}]
        passing, skipped, original_passing = prefilter_by_guard(data, {}, "test")
        assert passing == data
        assert skipped == []
        assert original_passing == data

    def test_no_guard_with_original_data(self):
        """No guard config with original_data -> original_passing is original_data."""
        data = [{"content": {"x": 1}}]
        raw = [{"content": {"x": 1}, "extra_field": "preserved"}]
        passing, skipped, original_passing = prefilter_by_guard(data, {}, "test", original_data=raw)
        assert passing == data
        assert original_passing == raw

    def test_filter_removes_failing_records(self):
        """behavior: filter -> failing records excluded from both lists."""
        data = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
            {"content": {"score": 85}},
        ]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 2
        assert passing[0]["content"]["score"] == 90
        assert passing[1]["content"]["score"] == 85
        assert skipped == []
        assert original_passing == passing

    def test_skip_preserves_failing_records(self):
        """behavior: skip -> failing records in skipped list."""
        data = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
            {"content": {"score": 85}},
        ]
        config = {"guard": {"clause": "score >= 80", "behavior": "skip"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 2
        assert len(skipped) == 1
        assert skipped[0]["content"]["score"] == 40

    def test_all_pass(self):
        """All records pass guard -> all in passing, none skipped."""
        data = [{"content": {"score": 90}}, {"content": {"score": 95}}]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 2
        assert skipped == []

    def test_all_filtered(self):
        """All records fail with filter -> both lists empty."""
        data = [{"content": {"score": 10}}, {"content": {"score": 20}}]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert passing == []
        assert skipped == []
        assert original_passing == []

    def test_all_skipped(self):
        """All records fail with skip -> all in skipped."""
        data = [{"content": {"score": 10}}, {"content": {"score": 20}}]
        config = {"guard": {"clause": "score >= 80", "behavior": "skip"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert passing == []
        assert len(skipped) == 2
        assert original_passing == []

    def test_does_not_mutate_input(self):
        """Pre-filter must not mutate the input list."""
        data = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
        ]
        original_len = len(data)
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            prefilter_by_guard(data, config, "test")

        assert len(data) == original_len

    def test_default_behavior_is_filter(self):
        """When behavior is not specified, default is filter."""
        data = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
        ]
        config = {"guard": {"clause": "score >= 80"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 1
        assert skipped == []

    # -- original_data preservation tests --

    def test_original_data_preserves_pre_observe_fields(self):
        """original_passing returns items from original_data, not from data."""
        # Simulate observe-filtered data (fewer fields) vs raw data (all fields)
        filtered = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
            {"content": {"score": 85}},
        ]
        raw = [
            {"content": {"score": 90, "name": "Alice"}, "source_guid": "sg-1"},
            {"content": {"score": 40, "name": "Bob"}, "source_guid": "sg-2"},
            {"content": {"score": 85, "name": "Carol"}, "source_guid": "sg-3"},
        ]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(
                filtered, config, "test", original_data=raw
            )

        # passing has observe-filtered items
        assert len(passing) == 2
        assert "name" not in passing[0]["content"]

        # original_passing has the raw items with all fields preserved
        assert len(original_passing) == 2
        assert original_passing[0]["content"]["name"] == "Alice"
        assert original_passing[0]["source_guid"] == "sg-1"
        assert original_passing[1]["content"]["name"] == "Carol"
        assert original_passing[1]["source_guid"] == "sg-3"

    def test_original_data_with_skip_behavior(self):
        """original_passing only includes passing items, not skipped."""
        filtered = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
        ]
        raw = [
            {"content": {"score": 90, "name": "Alice"}, "source_guid": "sg-1"},
            {"content": {"score": 40, "name": "Bob"}, "source_guid": "sg-2"},
        ]
        config = {"guard": {"clause": "score >= 80", "behavior": "skip"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(
                filtered, config, "test", original_data=raw
            )

        assert len(passing) == 1
        assert len(skipped) == 1
        assert len(original_passing) == 1
        assert original_passing[0]["content"]["name"] == "Alice"

    # -- Edge case tests --

    def test_empty_data(self):
        """Empty data list -> all empty results."""
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: True)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard([], config, "test")

        assert passing == []
        assert skipped == []
        assert original_passing == []

    def test_non_dict_content(self):
        """Non-dict content yields empty eval_item — guard cannot match."""
        data = [{"content": "plain-text-value"}]
        config = {"guard": {"clause": "always_true", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: bool(item))

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 0

    def test_missing_content_key(self):
        """Item without content key yields empty eval_item — guard cannot match."""
        data = [{"score": 90, "name": "Alice"}]
        config = {"guard": {"clause": "score >= 80", "behavior": "filter"}}
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, skipped, original_passing = prefilter_by_guard(data, config, "test")

        assert len(passing) == 0


class TestGuardFilterFileMode:
    """Tests for UnifiedProcessor._guard_filter_file_mode() skip-wrapping behavior.

    These tests verify that FILE-mode guard-skipped records are correctly
    converted to UNPROCESSED ProcessingResults with null namespace markers.
    """

    @staticmethod
    def _make_context(action_name="my_action"):
        return ProcessingContext(
            agent_config={"guard": {"clause": "score >= 80", "behavior": "skip"}},
            agent_name=action_name,
        )

    @staticmethod
    def _run_filter(records, raw_records, context):
        processor = UnifiedProcessor()
        return processor._guard_filter_file_mode(records, context, raw_records)

    def test_no_guard_returns_all(self):
        """No guard -> all records pass, no guard results."""
        data = [{"content": {"x": 1}}, {"content": {"x": 2}}]
        context = ProcessingContext(agent_config={}, agent_name="test")
        passing, guard_results, original_passing = self._run_filter(data, data, context)
        assert passing == data
        assert guard_results == []
        assert original_passing == data

    def test_skipped_items_become_unprocessed(self):
        """Each guard-skipped item produces an UNPROCESSED result."""
        data = [
            {"content": {"score": 40}, "source_guid": "sg-1"},
            {"content": {"score": 20}, "source_guid": "sg-2"},
        ]
        context = self._make_context()
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, guard_results, original_passing = self._run_filter(data, data, context)

        assert passing == []
        assert len(guard_results) == 2
        for i, result in enumerate(guard_results):
            assert result.status == ProcessingStatus.UNPROCESSED
            assert result.source_guid == data[i]["source_guid"]
            # Null namespace marker added by RecordEnvelope.build_skipped
            assert result.data[0]["content"]["my_action"] is None

    def test_missing_source_guid(self):
        """Items without source_guid get None on the result."""
        data = [{"content": {"score": 40}}]
        context = self._make_context()
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            _, guard_results, _ = self._run_filter(data, data, context)

        assert len(guard_results) == 1
        assert guard_results[0].source_guid is None
        assert guard_results[0].status == ProcessingStatus.UNPROCESSED

    def test_adds_null_namespace(self):
        """Skipped items get a null namespace marker via RecordEnvelope."""
        data = [{"content": {"prev_action": {"key": "val"}}, "source_guid": "sg-1"}]
        context = self._make_context()
        evaluator = _make_evaluator(lambda item: False)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            _, guard_results, _ = self._run_filter(data, data, context)

        assert len(guard_results) == 1
        item = guard_results[0].data[0]
        assert item["content"]["my_action"] is None
        assert item["content"]["prev_action"] == {"key": "val"}
        assert item["source_guid"] == "sg-1"

    def test_preserves_framework_fields(self):
        """Framework fields survive the envelope merge for skipped records."""
        data = [
            {
                "content": {"prev": {}},
                "source_guid": "sg-1",
                "target_id": "t-1",
                "_unprocessed": True,
                "metadata": {"key": "val"},
                "batch_id": "b-1",
            }
        ]
        context = self._make_context(action_name="act")
        evaluator = _make_evaluator(lambda item: False)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            _, guard_results, _ = self._run_filter(data, data, context)

        item = guard_results[0].data[0]
        assert item["content"]["act"] is None
        assert item["target_id"] == "t-1"
        assert item["_unprocessed"] is True
        assert item["metadata"] == {"key": "val"}
        assert item["batch_id"] == "b-1"

    def test_skips_when_namespace_already_present(self):
        """If action_name already in content, no null namespace added."""
        data = [{"content": {"my_action": {"existing": True}}, "source_guid": "sg-1"}]
        context = self._make_context()
        evaluator = _make_evaluator(lambda item: False)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            _, guard_results, _ = self._run_filter(data, data, context)

        item = guard_results[0].data[0]
        assert item["content"]["my_action"] == {"existing": True}

    def test_filtered_items_become_filtered_results(self):
        """Guard-filtered items produce FILTERED results."""
        data = [
            {"content": {"score": 40}, "source_guid": "sg-1"},
        ]
        context = ProcessingContext(
            agent_config={"guard": {"clause": "score >= 80", "behavior": "filter"}},
            agent_name="test",
        )
        evaluator = _make_evaluator(lambda item: False)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, guard_results, original_passing = self._run_filter(data, data, context)

        assert passing == []
        assert original_passing == []
        assert len(guard_results) == 1
        assert guard_results[0].status == ProcessingStatus.FILTERED

    def test_mixed_pass_skip_produces_correct_results(self):
        """Mixed pass/skip: passing records returned, skipped get null namespace."""
        data = [
            {"content": {"score": 90, "prev_action": {"key": "first"}}, "source_guid": "sg-1"},
            {"content": {"score": 40, "prev_action": {"key": "other"}}, "source_guid": "sg-2"},
            {"content": {"score": 30, "prev_action": {"key": "third"}}, "source_guid": "sg-3"},
        ]
        context = self._make_context(action_name="review_action")
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, guard_results, original_passing = self._run_filter(data, data, context)

        assert len(passing) == 1
        assert len(guard_results) == 2
        for result in guard_results:
            assert result.status == ProcessingStatus.UNPROCESSED
            item = result.data[0]
            assert "review_action" in item["content"]
            assert item["content"]["review_action"] is None

    def test_returns_original_passing(self):
        """original_passing returns items from raw_records, not from records."""
        filtered = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
        ]
        raw = [
            {"content": {"score": 90, "name": "Alice"}, "source_guid": "sg-1"},
            {"content": {"score": 40, "name": "Bob"}, "source_guid": "sg-2"},
        ]
        context = self._make_context()
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            passing, guard_results, original_passing = self._run_filter(filtered, raw, context)

        assert len(passing) == 1
        assert len(original_passing) == 1
        assert original_passing[0]["content"]["name"] == "Alice"
        assert original_passing[0]["source_guid"] == "sg-1"


class TestUnifiedProcessorFileModePath:
    """Integration test: UnifiedProcessor.process() with raw_records wires
    context.source_data correctly before invoking the strategy."""

    def test_process_sets_source_data_before_strategy_invoke(self):
        """Strategy receives context.source_data = original_passing (not raw input)."""
        from agent_actions.processing.unified import UnifiedProcessor

        # Records after context scope (what guard evaluates on)
        filtered = [
            {"content": {"score": 90}},
            {"content": {"score": 40}},
        ]
        # Raw pre-scope records (what original_passing should come from)
        raw = [
            {"content": {"score": 90, "name": "Alice"}, "source_guid": "sg-1"},
            {"content": {"score": 40, "name": "Bob"}, "source_guid": "sg-2"},
        ]
        context = ProcessingContext(
            agent_config={"guard": {"clause": "score >= 80", "behavior": "skip"}},
            agent_name="my_tool",
        )
        evaluator = _make_evaluator(lambda item: item.get("score", 0) >= 80)

        captured_source_data = {}

        class SpyStrategy:
            def invoke(self, records, ctx):
                captured_source_data["value"] = ctx.source_data
                from agent_actions.processing.types import ProcessingResult

                return [
                    ProcessingResult.success(
                        data=[{"content": {"my_tool": {"out": 1}}}],
                        source_guid="sg-1",
                    )
                ]

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            output, stats = UnifiedProcessor().process(
                filtered, context, SpyStrategy(), raw_records=raw
            )

        # Strategy must have seen original_passing (only the passing raw record)
        assert len(captured_source_data["value"]) == 1
        assert captured_source_data["value"][0]["content"]["name"] == "Alice"
        assert captured_source_data["value"][0]["source_guid"] == "sg-1"

        # Guard-skipped record should appear in output as UNPROCESSED
        assert stats.unprocessed == 1
        assert stats.success == 1
