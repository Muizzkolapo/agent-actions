import json

from agent_actions.llm_invocation.realtime.services.context_service import ContextService


def test_prepare_context_data_tool_uses_llm_context():
    llm_context = {"observed": "value", "kept": "data"}
    original_context = {"original": "value"}

    result = ContextService.prepare_context_data(
        llm_context,
        original_context=original_context,
        is_tool=True,
    )

    assert result == llm_context
    assert result is llm_context


def test_prepare_tool_context_uses_llm_context():
    llm_context = {"observed": "value", "kept": "data"}
    original_context = {"original": "value"}

    result = ContextService.prepare_tool_context(
        llm_context,
        original_context=original_context,
    )

    assert result == json.dumps(llm_context, ensure_ascii=False)
