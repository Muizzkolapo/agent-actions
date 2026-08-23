"""OnlineStrategy attaches the verdict to the record in observe mode."""

from types import SimpleNamespace

from agent_actions.config.types import RunMode
from agent_actions.expectations.service import ExpectationService
from agent_actions.expectations.types import Suite
from agent_actions.processing.invocation.factory import InvocationStrategyFactory
from agent_actions.processing.invocation.online import OnlineStrategy

SUITE = Suite(
    name="s",
    expectations=[{"id": "count", "type": "item_count", "field": "ideas", "params": {"min": 2}}],
)


def make_task():
    return SimpleNamespace(
        should_execute=True,
        is_passthrough=False,
        original_content={},
        passthrough_fields={},
        formatted_prompt="PROMPT",
        llm_context=None,
        target_id="r1",
    )


def make_context():
    return SimpleNamespace(agent_name="brainstorm", agent_config={}, storage_backend=None)


def test_verdict_is_attached_under_the_expect_key(monkeypatch):
    strategy = OnlineStrategy(expectation_service=ExpectationService(SUITE, repair="none"))
    monkeypatch.setattr(
        OnlineStrategy, "_call_llm", lambda self, task, ctx, prompt: ({"ideas": ["a"]}, True)
    )
    result = strategy.invoke(make_task(), make_context())
    assert result.response["expect"]["overall_pass"] is False
    assert result.response["expect"]["failed"] == ["count"]


def test_verdict_is_attached_for_the_real_single_item_list_shape_call_llm_produces(monkeypatch):
    # _call_llm's real return is run_dynamic_agent's raw list (create_dynamic_agent
    # always returns list[Any]) -- a bare dict, as every other test in this file
    # mocks, is not the shape a real record-granularity online call produces.
    strategy = OnlineStrategy(expectation_service=ExpectationService(SUITE, repair="none"))
    monkeypatch.setattr(
        OnlineStrategy, "_call_llm", lambda self, task, ctx, prompt: ([{"ideas": ["a"]}], True)
    )
    result = strategy.invoke(make_task(), make_context())
    assert result.response["expect"]["overall_pass"] is False
    assert result.response["expect"]["failed"] == ["count"]
    assert result.response["ideas"] == ["a"]


def test_original_fields_survive_the_attachment(monkeypatch):
    strategy = OnlineStrategy(expectation_service=ExpectationService(SUITE, repair="none"))
    monkeypatch.setattr(
        OnlineStrategy, "_call_llm", lambda self, task, ctx, prompt: ({"ideas": ["a", "b"]}, True)
    )
    result = strategy.invoke(make_task(), make_context())
    assert result.response["ideas"] == ["a", "b"]
    assert result.response["expect"]["overall_pass"] is True


def test_no_expect_key_is_added_when_no_service_is_configured(monkeypatch):
    strategy = OnlineStrategy()
    monkeypatch.setattr(
        OnlineStrategy, "_call_llm", lambda self, task, ctx, prompt: ({"ideas": ["a"]}, True)
    )
    result = strategy.invoke(make_task(), make_context())
    assert "expect" not in result.response


def test_llm_context_reaches_a_judged_expectations_context_ref(monkeypatch):
    from agent_actions.expectations.types import Suite as SuiteType

    captured = {}

    def fake_judge(expectation, value, context):
        captured["context"] = context
        return True, "ok", False

    suite = SuiteType(
        name="s",
        expectations=[
            {
                "id": "on_topic",
                "type": "llm_judge",
                "field": "ideas",
                "params": {"rule": "on topic", "context": ["extract_context.source_context"]},
            }
        ],
    )
    strategy = OnlineStrategy(
        expectation_service=ExpectationService(suite, repair="none", judge=fake_judge)
    )
    monkeypatch.setattr(
        OnlineStrategy, "_call_llm", lambda self, task, ctx, prompt: ({"ideas": ["a"]}, True)
    )
    task = make_task()
    task.llm_context = {"extract_context": {"source_context": "the docs say X"}}
    result = strategy.invoke(task, make_context())
    assert captured["context"] == {"extract_context.source_context": "the docs say X"}
    assert result.response["expect"]["overall_pass"] is True


def test_factory_threads_the_schema_into_the_structural_gate(monkeypatch):
    agent_config = {
        "name": "brainstorm",
        "schema": {
            "type": "object",
            "properties": {"ideas": {"type": "array"}},
            "required": ["ideas"],
            "additionalProperties": False,
        },
        "expect": {
            "repair": "retry",
            "expectations": [{"id": "count", "type": "item_count", "field": "ideas", "min": 1}],
        },
    }
    calls = []

    def fake_call(self, task, ctx, prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return [{"wrong_key": 1}], True
        return [{"ideas": ["a"]}], True

    monkeypatch.setattr(OnlineStrategy, "_call_llm", fake_call)
    strategy = InvocationStrategyFactory.create(RunMode.ONLINE, agent_config)
    result = strategy.invoke(make_task(), make_context())
    assert len(calls) == 2
    assert result.response["expect"]["overall_pass"] is True
    assert result.response["ideas"] == ["a"]


def test_exhausted_fail_mode_converts_to_the_tombstone_channel(monkeypatch):
    service = ExpectationService(SUITE, repair="retry", max_iterations=2, on_exhausted="fail")
    strategy = OnlineStrategy(expectation_service=service)
    monkeypatch.setattr(
        OnlineStrategy, "_call_llm", lambda self, task, ctx, prompt: ([{"ideas": ["a"]}], True)
    )
    result = strategy.invoke(make_task(), make_context())
    assert result.executed is False
    assert result.response is None
    meta = result.recovery_metadata
    assert meta is not None
    assert meta.expectations is not None
    assert meta.expectations.attempts == 2
    assert meta.expectations.failed == ["count"]


def test_exhausted_non_record_under_return_last_also_converts(monkeypatch):
    service = ExpectationService(
        SUITE, repair="retry", max_iterations=2, on_exhausted="return_last"
    )
    strategy = OnlineStrategy(expectation_service=service)
    monkeypatch.setattr(
        OnlineStrategy, "_call_llm", lambda self, task, ctx, prompt: ("not a record", True)
    )
    result = strategy.invoke(make_task(), make_context())
    assert result.executed is False
    assert result.response is None
    assert result.recovery_metadata is not None
    assert result.recovery_metadata.expectations is not None
    assert result.recovery_metadata.expectations.failed == ["_structural"]


def test_exhausted_return_last_record_still_ships_annotated(monkeypatch):
    service = ExpectationService(
        SUITE, repair="retry", max_iterations=2, on_exhausted="return_last"
    )
    strategy = OnlineStrategy(expectation_service=service)
    monkeypatch.setattr(
        OnlineStrategy, "_call_llm", lambda self, task, ctx, prompt: ([{"ideas": ["a"]}], True)
    )
    result = strategy.invoke(make_task(), make_context())
    assert result.executed is True
    assert result.response["expect"]["overall_pass"] is False
    assert result.response["expect"]["failed"] == ["count"]
    assert result.recovery_metadata is None or result.recovery_metadata.expectations is None


def test_a_guard_skip_is_not_misrouted_to_the_exhaustion_channel(monkeypatch):
    service = ExpectationService(SUITE, repair="retry", max_iterations=3, on_exhausted="fail")
    strategy = OnlineStrategy(expectation_service=service)
    monkeypatch.setattr(OnlineStrategy, "_call_llm", lambda self, task, ctx, prompt: (None, False))
    result = strategy.invoke(make_task(), make_context())
    assert result.executed is False
    assert result.recovery_metadata is None or result.recovery_metadata.expectations is None


class _ScriptedReprompt:
    def __init__(self, results):
        self._results = iter(results)

    def execute(self, llm_operation, original_prompt, context=""):
        return next(self._results)


def test_recovery_metadata_describes_the_shipped_generation_only():
    # Iteration 1's inner reprompt needs 2 attempts and its output fails the
    # suite; iteration 2 passes first try. The shipped record must not carry
    # the discarded generation's reprompt metadata.
    from agent_actions.processing.recovery.reprompt import RepromptResult

    reprompt = _ScriptedReprompt(
        [
            RepromptResult(
                response={"ideas": ["a"]},
                executed=True,
                attempts=2,
                passed=True,
                validation_name="check",
            ),
            RepromptResult(
                response={"ideas": ["a", "b", "c"]},
                executed=True,
                attempts=1,
                passed=True,
                validation_name="check",
            ),
        ]
    )
    service = ExpectationService(SUITE, repair="retry", max_iterations=3)
    strategy = OnlineStrategy(reprompt_service=reprompt, expectation_service=service)
    result = strategy.invoke(make_task(), make_context())
    assert result.response["ideas"] == ["a", "b", "c"]
    assert result.recovery_metadata is None or result.recovery_metadata.reprompt is None
