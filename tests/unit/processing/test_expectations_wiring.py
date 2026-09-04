"""OnlineStrategy attaches the verdict to the record in observe mode."""

from types import SimpleNamespace

from agent_actions.expectations.service import ExpectationService
from agent_actions.expectations.types import Suite
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
