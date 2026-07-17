"""Unit tests for the conditional-required-field detector.

The validator's contract: given the UDF source + the schema's compiled
required list + a boolean for additionalProperties, return one warning per
required field the UDF cannot statically be shown to emit unconditionally.
"""

from agent_actions.validation.udf_required_field_validator import (
    find_conditional_required_field_risks,
)

# The qanalabs reproducer, shrunk: `options`, `answer`, `answer_text` land in
# the initial dict literal (unconditional), then `source_quote` and `question`
# are guarded by `if field in flat`.
_APPLY_EDITED_DISTRACTORS = (
    "def apply_edited_distractors(data):\n"
    "    flat = {}\n"
    "    for key, value in data.items():\n"
    "        if isinstance(value, dict):\n"
    "            flat.update(value)\n"
    "        else:\n"
    "            flat[key] = value\n"
    "    result = {\n"
    "        'options': flat.get('options', []),\n"
    "        'answer': flat.get('answer', []),\n"
    "        'answer_text': flat.get('answer_text', []),\n"
    "    }\n"
    "    for field in ('source_quote', 'question'):\n"
    "        if field in flat:\n"
    "            result[field] = flat[field]\n"
    "    return result\n"
)

_UNCONDITIONAL_DICT_LITERAL = (
    "def build(data):\n    return {'options': [], 'answer': [], 'answer_text': []}\n"
)

_UNCONDITIONAL_VIA_NAME = (
    "def build(data):\n"
    "    result = {'options': [], 'answer': [], 'answer_text': []}\n"
    "    return result\n"
)

# Written unconditionally at function top level, just after the initial literal.
_TOP_LEVEL_SUBSCRIPT_ASSIGN = (
    "def build(data):\n    result = {'options': []}\n    result['answer'] = []\n    return result\n"
)

_TOP_LEVEL_UPDATE_LITERAL = (
    "def build(data):\n"
    "    result = {'options': []}\n"
    "    result.update({'answer': []})\n"
    "    return result\n"
)

# `source_quote` only ever written inside a for-loop conditional — the runtime
# will crash whenever the guard misses.
_CONDITIONAL_ONLY = (
    "def build(data):\n"
    "    result = {'options': []}\n"
    "    for field in ('source_quote',):\n"
    "        if field in data:\n"
    "            result[field] = data[field]\n"
    "    return result\n"
)

# Name initialised via a helper call, not a dict literal — the helper is
# opaque, so declining to decide is safer than flagging every field.
_HELPER_INITIALISATION = "def build(data):\n    result = build_from(data)\n    return result\n"

# `**spread` means the returned literal contains unknown extra keys — skip.
_SPREAD_LITERAL = "def build(data):\n    return {**data, 'options': []}\n"

# Early guard return (`return data` on wrong type) must not shadow the tail return.
_EARLY_GUARD_RETURN = (
    "def build(data):\n"
    "    if not isinstance(data, dict):\n"
    "        return data\n"
    "    result = {'options': [], 'answer': []}\n"
    "    return result\n"
)

# List-emitting FILE-mode UDF — not our shape; skip.
_LIST_RETURN = (
    "def flatten(data):\n"
    "    out = []\n"
    "    for x in data.get('items', []):\n"
    "        out.append(x)\n"
    "    return out\n"
)

# A subscript assign INSIDE an `if` block is not top-level — must not be
# credited toward the unconditional set.
_SUBSCRIPT_INSIDE_IF = (
    "def build(data):\n"
    "    result = {'options': []}\n"
    "    if data.get('flag'):\n"
    "        result['answer'] = []\n"
    "    return result\n"
)

# A NESTED helper whose return sits below the outer function's tail return must
# not be picked as the outer's tail — the outer's conditional-only field would
# be silently exonerated by the inner's unrelated dict literal otherwise.
_NESTED_HELPER_AFTER_TAIL_RETURN = (
    "def build(data):\n"
    "    result = {'options': []}\n"
    "    if 'source_quote' in data:\n"
    "        result['source_quote'] = data['source_quote']\n"
    "    def _tail_helper():\n"
    "        return {'source_quote': None}\n"
    "    return result\n"
)


def _risks(source, required, additional_properties=True):
    return find_conditional_required_field_risks(
        {
            "f": {
                "source": source,
                "required": required,
                "additional_properties": additional_properties,
            }
        }
    )


def test_conditional_required_field_is_flagged():
    findings = _risks(_APPLY_EDITED_DISTRACTORS, ["options", "answer", "source_quote"])
    assert len(findings) == 1
    only = findings[0]
    assert "f" in only
    assert "source_quote" in only


def test_unconditional_dict_literal_return_is_not_flagged():
    assert _risks(_UNCONDITIONAL_DICT_LITERAL, ["options", "answer", "answer_text"]) == []


def test_unconditional_via_name_is_not_flagged():
    assert _risks(_UNCONDITIONAL_VIA_NAME, ["options", "answer", "answer_text"]) == []


def test_top_level_subscript_assign_is_not_flagged():
    assert _risks(_TOP_LEVEL_SUBSCRIPT_ASSIGN, ["options", "answer"]) == []


def test_top_level_update_literal_is_not_flagged():
    assert _risks(_TOP_LEVEL_UPDATE_LITERAL, ["options", "answer"]) == []


def test_conditional_only_field_is_flagged():
    findings = _risks(_CONDITIONAL_ONLY, ["options", "source_quote"])
    assert len(findings) == 1
    assert "source_quote" in findings[0]


def test_helper_initialisation_is_not_flagged():
    assert _risks(_HELPER_INITIALISATION, ["options", "answer"]) == []


def test_spread_literal_is_not_flagged():
    assert _risks(_SPREAD_LITERAL, ["options", "answer"]) == []


def test_early_guard_return_does_not_shadow_tail_return():
    assert _risks(_EARLY_GUARD_RETURN, ["options", "answer"]) == []


def test_list_return_is_not_flagged():
    assert _risks(_LIST_RETURN, ["items"]) == []


def test_subscript_assign_inside_if_is_not_credited():
    findings = _risks(_SUBSCRIPT_INSIDE_IF, ["options", "answer"])
    assert len(findings) == 1
    assert "answer" in findings[0]


def test_nested_helper_return_does_not_shadow_outer_tail():
    findings = _risks(_NESTED_HELPER_AFTER_TAIL_RETURN, ["options", "source_quote"])
    assert len(findings) == 1
    assert "source_quote" in findings[0]


def test_additional_properties_true_does_not_suppress_required_check():
    # Contrast with the sibling passthrough validator: additionalProperties
    # only allows extra keys — it does not weaken the required-fields
    # constraint, so the check must still fire.
    findings = _risks(_CONDITIONAL_ONLY, ["source_quote"], additional_properties=True)
    assert findings and "source_quote" in findings[0]


def test_no_required_fields_yields_no_findings():
    assert _risks(_APPLY_EDITED_DISTRACTORS, []) == []


def test_missing_source_is_ignored():
    assert (
        find_conditional_required_field_risks(
            {"f": {"required": ["x"], "additional_properties": True}}
        )
        == []
    )


def test_syntactically_invalid_source_is_ignored():
    assert _risks("def f(:\n    bad", ["options"]) == []


def test_two_flagged_actions_yield_two_findings():
    actions = {
        "safe": {
            "source": _UNCONDITIONAL_DICT_LITERAL,
            "required": ["options", "answer", "answer_text"],
            "additional_properties": False,
        },
        "risky_a": {
            "source": _CONDITIONAL_ONLY,
            "required": ["options", "source_quote"],
            "additional_properties": False,
        },
        "risky_b": {
            "source": _APPLY_EDITED_DISTRACTORS,
            "required": ["options", "source_quote"],
            "additional_properties": False,
        },
    }
    findings = find_conditional_required_field_risks(actions)
    flagged = {name for name in ("safe", "risky_a", "risky_b") if any(name in f for f in findings)}
    assert flagged == {"risky_a", "risky_b"}
