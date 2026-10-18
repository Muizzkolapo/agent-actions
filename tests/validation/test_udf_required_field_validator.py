"""Unit tests for the conditional-required-field detector.

The validator's contract: given the UDF source + the schema's compiled
required list + a boolean for additionalProperties, return one warning per
required field the UDF cannot statically be shown to emit unconditionally.
"""

import pytest

from agent_actions.validation.udf_required_field_validator import (
    find_conditional_required_field_risks,
    unconditional_output_keys,
)

# The reproducer from a real user project, shrunk: `options`, `answer`, `answer_text` land in
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


# 1491: the scan reads every spelling of the initial output dict the same way.
_SET_IN_A_BRANCH = (
    "def build(data):\n"
    "    {initialiser}\n"
    "    if data.get('flag'):\n"
    "        out['answer'] = []\n"
    "    return out\n"
)


@pytest.mark.parametrize(
    "initialiser",
    [
        "out = {'options': []}",
        "out: dict = {'options': []}",
        "out: dict[str, Any] = {'options': []}",
        "out = dict(options=[])",
        "out: dict[str, Any] = dict(options=[])",
    ],
)
def test_a_key_set_only_in_a_branch_is_flagged_in_every_spelling(initialiser):
    source = _SET_IN_A_BRANCH.format(initialiser=initialiser)
    findings = _risks(source, ["options", "answer"])
    assert len(findings) == 1
    assert "f: output schema requires 'answer'" in findings[0]
    assert "at line 4, inside an `if`" in findings[0]


@pytest.mark.parametrize(
    "initialiser", ["out = dict(data, options=[])", "out = dict(**data, options=[])"]
)
def test_a_dict_call_with_a_spread_or_a_positional_is_not_read(initialiser):
    source = _SET_IN_A_BRANCH.format(initialiser=initialiser)
    assert _risks(source, ["options", "answer"]) == []


@pytest.mark.parametrize(
    "line",
    [
        "out |= {'answer': []}",
        "out.update(answer=[])",
        "out.setdefault('answer', [])",
    ],
)
def test_a_key_set_on_every_path_by_a_later_line_is_not_flagged(line):
    source = (
        "def build(data):\n"
        "    out = {'options': []}\n"
        f"    {line}\n"
        "    if data.get('flag'):\n"
        "        out['answer'] = [1]\n"
        "    return out\n"
    )
    assert _risks(source, ["options", "answer"]) == []


def test_the_finding_names_the_function_file_line_and_branch():
    findings = find_conditional_required_field_risks(
        {
            "producer": {
                "source": _SET_IN_A_BRANCH.format(initialiser="out: dict = {'options': []}"),
                "required": ["options", "answer"],
                "file": "/proj/tools/w/build.py",
                "first_line": 20,
            }
        }
    )
    assert len(findings) == 1
    assert "'build' sets it only at line 23 of build.py, inside an `if`" in findings[0]


def test_a_key_set_through_a_computed_name_is_not_flagged():
    """Which keys `out[k] = ...` sets is unknowable, so the scan declines (1510)."""
    source = (
        "def build(data):\n"
        "    out = {'options': []}\n"
        "    for k in data:\n"
        "        out[k] = data[k]\n"
        "    return out\n"
    )
    assert _risks(source, ["options", "answer"]) == []


def test_a_key_never_set_is_named_as_such():
    source = "def build(data):\n    out = {'options': []}\n    return out\n"
    (finding,) = _risks(source, ["options", "answer"])
    assert "'build' sets it only through a computed key, or not at all" in finding


def test_an_annotation_without_a_value_sets_nothing():
    source = (
        "def build(data):\n"
        "    out = {'options': []}\n"
        "    out['answer']: list\n"
        "    if data:\n"
        "        out['answer'] = []\n"
        "    return out\n"
    )
    (finding,) = _risks(source, ["options", "answer"])
    assert "at line 5, inside an `if`" in finding


def test_a_returned_dict_call_is_read_like_a_returned_literal():
    source = "def build(data):\n    return dict(options=[])\n"
    assert _risks(source, ["options"]) == []
    (finding,) = _risks(source, ["options", "answer"])
    assert "requires 'answer'" in finding


def test_a_key_set_in_a_with_body_is_set_on_every_path():
    source = (
        "def build(data):\n"
        "    out = {'options': []}\n"
        "    with open(data['path']) as f:\n"
        "        out['answer'] = f.read()\n"
        "    return out\n"
    )
    assert _risks(source, ["options", "answer"]) == []


@pytest.mark.parametrize(
    ("block", "named"),
    [
        ("for x in data:", "a `for` loop"),
        ("while data:", "a `while` loop"),
        ("try:", "a `try`"),
    ],
)
def test_the_finding_names_the_block_the_key_is_set_in(block, named):
    tail = "    except KeyError:\n        pass\n" if block == "try:" else ""
    source = (
        "def build(data):\n"
        "    out = {'options': []}\n"
        f"    {block}\n"
        "        out['answer'] = 1\n"
        f"{tail}"
        "    return out\n"
    )
    (finding,) = _risks(source, ["options", "answer"])
    assert f"at line 4, inside {named}" in finding


# 1510: a one-element list, a re-raising `except`, removed keys and a re-bound dict.
_LIST_OF_ONE = (
    "def build(data):\n"
    "    out = {'options': []}\n"
    "    if data.get('flag'):\n"
    "        out['answer'] = []\n"
    "    return [out]\n"
)


def test_a_one_element_list_return_is_read_like_returning_the_dict():
    (finding,) = _risks(_LIST_OF_ONE, ["options", "answer"])
    assert "f: output schema requires 'answer'" in finding
    assert "at line 4, inside an `if`" in finding
    assert _risks(_LIST_OF_ONE, ["options"]) == []


def test_a_one_element_list_of_a_literal_is_read():
    source = "def build(data):\n    return [{'options': []}]\n"
    assert _risks(source, ["options"]) == []
    (finding,) = _risks(source, ["options", "answer"])
    assert "requires 'answer'" in finding


@pytest.mark.parametrize(
    "handler",
    ["raise", "raise ValueError('bad') from exc", "log(exc)\n        raise"],
)
def test_a_key_set_in_a_try_whose_except_always_re_raises_is_not_flagged(handler):
    source = (
        "def build(data):\n"
        "    out = {'options': []}\n"
        "    try:\n"
        "        out['answer'] = data['answer']\n"
        "    except KeyError as exc:\n"
        f"        {handler}\n"
        "    return out\n"
    )
    assert _risks(source, ["options", "answer"]) == []


def test_a_key_set_in_a_try_whose_except_can_fall_through_is_flagged():
    source = (
        "def build(data):\n"
        "    out = {'options': []}\n"
        "    try:\n"
        "        out['answer'] = data['answer']\n"
        "    except KeyError:\n"
        "        if data:\n"
        "            raise\n"
        "    return out\n"
    )
    (finding,) = _risks(source, ["options", "answer"])
    assert "at line 4, inside a `try`" in finding


@pytest.mark.parametrize(
    "removal",
    [
        "del out['answer']",
        "out.pop('answer')",
        "out.pop('answer', None)",
        "kept = out.pop('answer')",
    ],
)
def test_a_key_removed_on_every_path_is_flagged(removal):
    source = (
        "def build(data):\n"
        "    out = {'options': [], 'answer': []}\n"
        f"    {removal}\n"
        "    return out\n"
    )
    (finding,) = _risks(source, ["options", "answer"])
    assert "f: output schema requires 'answer'" in finding
    assert "removes it at line 3" in finding


def test_a_key_removed_and_set_again_is_not_flagged():
    source = (
        "def build(data):\n"
        "    out = {'options': [], 'answer': []}\n"
        "    del out['answer']\n"
        "    out['answer'] = [1]\n"
        "    return out\n"
    )
    assert _risks(source, ["options", "answer"]) == []


def test_a_re_bound_dict_is_read_from_its_last_binding():
    source = (
        "def build(data):\n"
        "    out = {'options': [], 'answer': []}\n"
        "    out = {'options': data}\n"
        "    return out\n"
    )
    (finding,) = _risks(source, ["options", "answer"])
    assert "f: output schema requires 'answer'" in finding
    assert "re-binds 'out' without it at line 3" in finding
    assert _risks(source, ["options"]) == []


# The scan follows each path to the tail return: a key counts when every path holds it.
@pytest.mark.parametrize(
    "body",
    [
        # both branches of an `if`
        "    if data:\n        out['answer'] = 1\n    else:\n        out['answer'] = 2\n",
        # the body of a `try`, and the `except` that falls back
        "    try:\n        out['answer'] = data['a']\n    except KeyError:\n"
        "        out['answer'] = None\n",
        # a `finally` runs on every path
        "    try:\n        data.load()\n    finally:\n        out['answer'] = 1\n",
        # every case of a `match` that has a catch-all
        "    match data:\n        case {'a': a}:\n            out['answer'] = a\n"
        "        case _:\n            out['answer'] = None\n",
        # a branch that raises never reaches the return
        "    if not data:\n        raise ValueError('empty')\n    else:\n        out['answer'] = 1\n",
        # set inside a `with`
        "    with lock:\n        out['answer'] = 1\n",
    ],
)
def test_a_key_every_path_to_the_return_holds_is_not_flagged(body):
    source = "def build(data):\n    out = {'options': []}\n" + body + "    return out\n"
    assert _risks(source, ["options", "answer"]) == []


@pytest.mark.parametrize(
    "body",
    [
        "    if data:\n        del out['answer']\n",
        "    for k in data:\n        out.pop('answer', None)\n",
        "    try:\n        out.clear()\n    except KeyError:\n        pass\n",
        "    match data:\n        case {'a': a}:\n            del out['answer']\n",
        "    if data:\n        out = {'options': []}\n",
    ],
)
def test_a_key_some_path_to_the_return_lacks_is_flagged(body):
    source = (
        "def build(data):\n    out = {'options': [], 'answer': 0}\n" + body + "    return out\n"
    )
    findings = _risks(source, ["options", "answer"])
    assert any("requires 'answer'" in finding for finding in findings), findings


def test_a_key_set_in_a_match_without_a_catch_all_is_flagged():
    source = (
        "def build(data):\n"
        "    out = {'options': []}\n"
        "    match data:\n"
        "        case {'a': a}:\n"
        "            out['answer'] = a\n"
        "    return out\n"
    )
    (finding,) = _risks(source, ["options", "answer"])
    assert "at line 5, inside a `match`" in finding


@pytest.mark.parametrize(
    "body",
    [
        # removed by a computed name: which key went is unknowable
        "    out.pop(data['key'])\n",
        "    del out[data['key']]\n",
        "    out.popitem()\n",
        # re-bound to something the scan cannot enumerate
        "    out = dict(out, extra=1)\n",
        "    out = build_from(out)\n",
        "    if (out := build_from(data)):\n        pass\n",
        # a path holding what a helper built makes the whole reading unknown
        "    if data:\n        out = build_from(data)\n    else:\n        out.pop('answer')\n",
    ],
)
def test_a_mapping_the_scan_cannot_follow_is_not_flagged(body):
    source = "def build(data):\n    out = {'options': []}\n" + body + "    return out\n"
    assert _risks(source, ["options", "answer"]) == []


def test_a_tail_return_inside_a_loop_is_not_read():
    source = (
        "def build(data):\n"
        "    for row in data:\n"
        "        out = {'options': row}\n"
        "        return out\n"
    )
    assert _risks(source, ["options", "answer"]) == []


def test_a_list_of_two_is_not_read():
    source = "def build(data):\n    out = {'options': []}\n    return [out, out]\n"
    assert _risks(source, ["options", "answer"]) == []


# 1510 review: loops that remove and set again, dicts filled by unknowable names, and
# re-bindings inside loops, branches and `try` bodies.
@pytest.mark.parametrize(
    "loop",
    [
        "    for r in data:\n        out['answer'] = out.pop('answer') + r\n",
        "    for r in data:\n        prev = out.pop('answer')\n        out['answer'] = prev + r\n",
        "    while data:\n        out['answer'] = out.pop('answer') + data.pop()\n",
        "    for r in data:\n        out.clear()\n        out.update({'options': [], 'answer': r})\n",
    ],
)
def test_a_key_a_loop_removes_and_sets_again_is_not_flagged(loop):
    source = (
        "def build(data):\n    out = {'options': [], 'answer': 0}\n" + loop + "    return out\n"
    )
    assert _risks(source, ["options", "answer"]) == []
    assert unconditional_output_keys(source) == {"options", "answer"}


@pytest.mark.parametrize("returned", ["out", "[out]"])
@pytest.mark.parametrize(
    "fill",
    [
        "    out.update(build_from(data))\n",
        "    out |= build_from(data)\n",
        "    for field in FIELDS:\n        out[field] = data.get(field)\n",
        "    out.setdefault(data['key'], 1)\n",
        "    out[data['key']], extra = 1, 2\n",
    ],
)
def test_a_dict_filled_by_names_the_scan_cannot_know_is_not_read(fill, returned):
    source = f"def build(data):\n    out = {{}}\n{fill}    return {returned}\n"
    assert _risks(source, ["answer"]) == []
    assert unconditional_output_keys(source) is None


def test_a_loop_over_a_literal_list_of_names_sets_each_of_them():
    source = (
        "def build(data):\n"
        "    out = {}\n"
        "    for field in ('options', 'answer'):\n"
        "        out[field] = data.get(field)\n"
        "    return out\n"
    )
    assert _risks(source, ["options", "answer"]) == []
    assert unconditional_output_keys(source) == {"options", "answer"}


def test_a_loop_that_re_binds_the_dict_to_a_literal_keeps_only_what_every_binding_holds():
    source = (
        "def build(data):\n"
        "    out = {'options': [], 'answer': 1}\n"
        "    for r in data:\n"
        "        out = {'options': r}\n"
        "    return out\n"
    )
    assert unconditional_output_keys(source) == {"options"}
    (finding,) = _risks(source, ["options", "answer"])
    assert "requires 'answer'" in finding


@pytest.mark.parametrize(
    "body",
    [
        "    for r in data:\n        out = build_from(r)\n",
        "    while data:\n        out = data.pop()\n",
        "    if data:\n        out = build_from(data)\n",
        "    try:\n        out = build_from(data)\n    except KeyError:\n        pass\n",
    ],
)
def test_a_re_binding_the_scan_cannot_read_makes_the_reading_unknown(body):
    source = (
        "def build(data):\n    out = {'options': [], 'answer': 1}\n" + body + "    return out\n"
    )
    assert unconditional_output_keys(source) is None


def test_a_key_set_before_the_break_of_a_while_true_is_not_flagged():
    source = (
        "def build(data):\n"
        "    out = {'options': []}\n"
        "    while True:\n"
        "        out['answer'] = data.next()\n"
        "        if out['answer']:\n"
        "            break\n"
        "    return out\n"
    )
    assert _risks(source, ["options", "answer"]) == []


# 1519: every return hands back a record to validate, not only the last one.
@pytest.mark.parametrize(
    "early",
    [
        "    if not data.get('x'):\n        return {'options': []}\n",
        "    if not data.get('x'):\n        return [{'options': []}]\n",
        "    if not data.get('x'):\n        return dict(options=[])\n",
        "    try:\n        data['x']\n    except KeyError:\n        return {'options': []}\n",
        "    for r in data:\n        if r:\n            return {'options': r}\n",
        "    match data:\n        case {'x': 1}:\n            return {'options': []}\n",
    ],
    ids=["dict", "list_of_one", "dict_call", "in_except", "in_loop", "in_case"],
)
@pytest.mark.parametrize(
    "tail",
    [
        "    return {'options': [], 'answer': 1}\n",
        "    out = {'options': []}\n    out['answer'] = 1\n    return [out]\n",
        # The last return cannot be read; the early one still can.
        "    return build_from(data)\n",
    ],
    ids=["tail_literal", "tail_list_of_name", "tail_unreadable"],
)
def test_an_early_return_without_a_required_key_is_flagged(early, tail):
    source = "def build(data):\n" + early + tail
    (finding,) = _risks(source, ["options", "answer"])
    assert "requires 'answer'" in finding
    assert "returns without it at line" in finding
    assert unconditional_output_keys(source) == {"options"}


def test_an_early_return_of_the_dict_before_the_key_is_set_is_flagged():
    source = (
        "def build(data):\n"
        "    out = {'options': []}\n"
        "    if not data:\n"
        "        return out\n"
        "    out['answer'] = 1\n"
        "    return out\n"
    )
    (finding,) = _risks(source, ["options", "answer"])
    assert "returns without it at line 4, inside an `if`" in finding
    assert unconditional_output_keys(source) == {"options"}


@pytest.mark.parametrize(
    "early",
    [
        "    if not data:\n        return None\n",
        "    if not data:\n        return\n",
        "    if not data:\n        return []\n",
        "    if not isinstance(data, dict):\n        return data\n",
        "    if data.get('raw'):\n        return {**data}\n",
        "    if data.get('raw'):\n        return build_from(data)\n",
        "    if data.get('raw'):\n        return [{'options': []}, {'options': []}]\n",
        "    if not data:\n        raise ValueError('no data')\n",
        "    if data.get('raw'):\n        result = build_from(data)\n        return result\n",
        "    def helper():\n        return {'options': []}\n",
        # after an unconditional return: no path reaches it
        "    if data:\n        return {'options': [], 'answer': 1}\n"
        "    else:\n        return {'options': [], 'answer': 2}\n"
        "    return {'options': []}\n",
        "    if data.get('serve'):\n        while True:\n            pass\n"
        "        return {'options': []}\n",
    ],
    ids=[
        "none",
        "bare",
        "empty_list",
        "parameter",
        "spread",
        "helper_call",
        "list_of_two",
        "raises",
        "helper_bound_name",
        "nested_def",
        "after_return",
        "after_while_true",
    ],
)
def test_an_early_return_handing_back_no_readable_record_is_not_flagged(early):
    source = "def build(data):\n" + early + "    return {'options': [], 'answer': 1}\n"
    assert _risks(source, ["options", "answer"]) == []
    assert unconditional_output_keys(source) == {"options", "answer"}


def test_an_early_return_of_the_dict_once_every_key_is_set_is_not_flagged():
    source = (
        "def build(data):\n"
        "    out = {'options': [], 'answer': 0}\n"
        "    if not data:\n"
        "        return out\n"
        "    out['answer'] = 1\n"
        "    return out\n"
    )
    assert _risks(source, ["options", "answer"]) == []


def test_the_last_return_is_named_when_it_lacks_the_key_too():
    source = (
        "def build(data):\n"
        "    if not data:\n"
        "        return {'options': []}\n"
        "    out = {'options': []}\n"
        "    if data.get('flag'):\n"
        "        out['answer'] = 1\n"
        "    return out\n"
    )
    (finding,) = _risks(source, ["options", "answer"])
    assert "sets it only at line 6, inside an `if`" in finding


def test_a_tool_with_only_returns_of_nothing_is_not_read():
    source = "def build(data):\n    if not data:\n        return None\n    return []\n"
    assert _risks(source, ["options"]) == []
    assert unconditional_output_keys(source) is None
