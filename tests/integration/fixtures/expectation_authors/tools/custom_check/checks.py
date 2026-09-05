from agent_actions import expectation_check


@expectation_check("ends_with_full_stop", params=("allow_question",))
def ends_with_full_stop(value, params):
    text = str(value).rstrip()
    if text.endswith(".") or (params.get("allow_question") and text.endswith("?")):
        return True, ""
    return False, f"{text[-20:]!r} does not end with a full stop"
