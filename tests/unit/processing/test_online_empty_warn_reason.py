"""The on_empty=warn reason must be tool-aware for tool actions (declared by
either `kind` or `model_vendor`) and keep the LLM wording for everything else."""

from agent_actions.processing.strategies.online_llm import _empty_warn_reason


def test_tool_action_by_kind_gets_tool_aware_reason():
    cfg = {"kind": "tool", "name": "flatten_code", "on_empty": "warn"}
    assert "model_vendor" not in cfg  # isolate the kind path — no vendor marker present
    reason = _empty_warn_reason(cfg, agent_name="flatten_code", source_guid="rec-abc-123")
    assert "Tool" in reason
    assert "empty list" in reason
    assert "rec-abc-123" in reason
    assert "LLM response" not in reason


def test_tool_action_by_model_vendor_gets_tool_aware_reason():
    # A tool declared via model_vendor (kind left at its LLM default) is routed
    # and executed as a tool, so its empty-output reason must be tool-aware too.
    cfg = {"model_vendor": "tool", "name": "flatten_code", "on_empty": "warn"}
    assert cfg.get("kind") != "tool"  # isolate the model_vendor path — kind is not the trigger
    reason = _empty_warn_reason(cfg, agent_name="flatten_code", source_guid="rec-v-9")
    assert "Tool" in reason
    assert "empty list" in reason
    assert "rec-v-9" in reason
    assert "LLM response" not in reason


def test_llm_action_keeps_existing_message():
    reason = _empty_warn_reason(
        {"kind": "llm", "name": "summarize", "on_empty": "warn"},
        agent_name="summarize",
        source_guid="rec-llm-1",
    )
    assert "Empty LLM response" in reason
    assert "rec-llm-1" in reason


def test_missing_kind_and_vendor_defaults_to_llm_wording():
    reason = _empty_warn_reason(
        {"name": "mystery", "on_empty": "warn"},
        agent_name="mystery",
        source_guid="rec-2",
    )
    assert "Empty LLM response" in reason
