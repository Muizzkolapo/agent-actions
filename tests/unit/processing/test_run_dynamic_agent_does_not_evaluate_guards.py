"""`run_dynamic_agent` runs the agent; it does not decide whether the agent should run.

The guard has already been evaluated by the time a strategy calls it — `prefilter_by_guard`
online, `TaskPreparer.prepare` in batch — and both build their context through
`build_guard_context`, which `processing/guard_context.py` names the single source of truth
and says duplicating is a merge-blocking anti-pattern. A second evaluation here would be a
third surface, and one that reads a different `source`: it passed no `context` to
`evaluate()`, so `_build_evaluation_context` never ran and the guard saw the bare item.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_actions.processing.helpers import run_dynamic_agent

# The EXPANDED shape the evaluator reads, not the user-facing `condition`/`on_false` the
# expander normalises away. Written the YAML way this fixture is inert — `evaluate()`
# returns `passed()` on a missing `clause` — and every assertion below holds regardless.
GUARDED_CONFIG = {
    "model_vendor": "tool",
    "model_name": "my_tool",
    "guard": {"clause": "score > 100", "behavior": "filter"},
}

# The online-LLM shape. The removed branch was reachable from `online.py::_call_llm` too,
# and a reintroduction gated on "not a tool action" is the plausible one — every assertion
# here would hold on the tool fixture alone.
GUARDED_LLM_CONFIG = {
    "model_vendor": "openai",
    "model_name": "gpt-4o",
    "kind": "llm",
    "granularity": "record",
    "guard": {"clause": "score > 100", "behavior": "filter"},
}

# A registered UDF name, not an expression: the runtime resolves the string through
# `execute_user_defined_function`, and `_evaluate_conditional_clause` swallows
# `FunctionNotFoundError` by design, so a bare expression passes the record.
CLAUSE_UDF_NAME = "guard_clause_probe_1132"


@pytest.fixture
def falsy_clause_udf():
    """Register a real UDF the conditional_clause path can resolve, then unregister it."""
    from agent_actions.config.types import Granularity
    from agent_actions.utils.udf_management.registry import UDF_REGISTRY

    UDF_REGISTRY[CLAUSE_UDF_NAME] = {
        "function": lambda _input_data, **_kw: False,
        "module": __name__,
        "name": CLAUSE_UDF_NAME,
        "file": __file__,
        "docstring": "",
        "signature": None,
        "granularity": Granularity.RECORD,
    }
    try:
        yield CLAUSE_UDF_NAME
    finally:
        UDF_REGISTRY.pop(CLAUSE_UDF_NAME, None)


@pytest.fixture
def evaluator_spy():
    """Fail loudly if the guard evaluator is so much as requested."""
    with patch("agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator") as spy:
        spy.side_effect = AssertionError(
            "run_dynamic_agent requested the guard evaluator — the guard has already run"
        )
        yield spy


class TestRunDynamicAgentNeverEvaluatesGuards:
    @patch("agent_actions.llm.realtime.builder.create_dynamic_agent")
    def test_a_guard_that_would_filter_does_not_stop_the_call(self, mock_builder, evaluator_spy):
        """The agent runs, and the response is the builder's — not an early return.

        The guard in the fixture filters this item, so any surviving evaluation returns
        `(None, False)` here and the builder is never reached.
        """
        mock_builder.return_value = [{"result": "ok"}]

        response, executed = run_dynamic_agent(
            GUARDED_CONFIG, "test_action", {"score": 1}, "prompt text"
        )

        assert mock_builder.called, "the builder was never reached"
        assert response == [{"result": "ok"}]
        assert executed is True
        evaluator_spy.assert_not_called()

    @patch("agent_actions.llm.realtime.builder.create_dynamic_agent")
    def test_the_item_reaches_the_builder_unfiltered(self, mock_builder, evaluator_spy):
        """A filtering guard must not swap the payload for the bare context."""
        mock_builder.return_value = [{"result": "ok"}]
        item = {"score": 1, "text": "hello"}

        run_dynamic_agent(GUARDED_CONFIG, "test_action", item, "prompt text")

        assert mock_builder.call_args[0][1] == item

    @patch("agent_actions.llm.realtime.builder.create_dynamic_agent")
    def test_a_non_tool_action_is_not_guarded_either(self, mock_builder, evaluator_spy):
        """The online-LLM shape, where the removed branch would actually have bitten."""
        mock_builder.return_value = [{"result": "ok"}]

        response, executed = run_dynamic_agent(
            GUARDED_LLM_CONFIG, "test_action", {"score": 1}, "prompt text"
        )

        assert mock_builder.called, "the builder was never reached"
        assert response == [{"result": "ok"}]
        assert executed is True

    @patch("agent_actions.llm.realtime.builder.create_dynamic_agent")
    def test_a_conditional_clause_that_returns_false_does_not_stop_the_call(
        self, mock_builder, falsy_clause_udf, evaluator_spy
    ):
        """The other half of the removed call, which took a clause as well as a guard."""
        mock_builder.return_value = [{"result": "ok"}]
        config = {
            "model_vendor": "openai",
            "model_name": "gpt-4o",
            "kind": "llm",
            "granularity": "record",
            "conditional_clause": falsy_clause_udf,
        }

        response, executed = run_dynamic_agent(config, "test_action", {"score": 1}, "prompt text")

        assert mock_builder.called, "the builder was never reached"
        assert response == [{"result": "ok"}]
        assert executed is True

    def test_the_function_takes_no_guard_switch(self):
        """No `skip_guard_eval`: a parameter defaulting to "evaluate" is how the
        second surface came back the last time it was removed from the call sites."""
        import inspect

        params = inspect.signature(run_dynamic_agent).parameters
        assert "skip_guard_eval" not in params, sorted(params)
