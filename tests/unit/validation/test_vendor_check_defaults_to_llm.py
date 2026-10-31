from agent_actions.validation.preflight.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)


def test_an_action_with_no_kind_is_asked_for_a_vendor_like_an_llm():
    check = VendorCompatibilityValidator()

    check.validate_vendor_config({"agent_type": "summarize", "model_vendor": ""})

    assert check.get_errors() == ["model_vendor is required for non-tool agents"]
