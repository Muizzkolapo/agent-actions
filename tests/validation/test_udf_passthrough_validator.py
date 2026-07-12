from agent_actions.validation.udf_passthrough_validator import find_passthrough_schema_risks

# Appends an item taken straight off the bus — opaque upstream keys reach output.
_PASSTHROUGH = (
    "def flatten(data):\n"
    "    out = []\n"
    "    for c in data.get('canonicalize', {}).get('items', []):\n"
    "        out.append(c)\n"
    "    return out\n"
)
# Returns a list of dict literals whose keys are visible and bounded — safe.
_CONSTRUCTED = (
    "def build(data):\n"
    "    src = data.get('upstream', {})\n"
    "    return [{'key': src.get('key'), 'summary': src.get('summary')}]\n"
)
# Builds a dict literal in a loop variable, then appends it — the idiomatic
# safe constructing tool. Must NOT be flagged.
_CONSTRUCTED_VAR = (
    "def build(data):\n"
    "    out = []\n"
    "    for i in data.get('ns', []):\n"
    "        item = {'key': i['key'], 'summary': i['summary']}\n"
    "        out.append(item)\n"
    "    return out\n"
)
# Delegates construction to a helper — the call is a construction boundary, safe.
_WRAPPER_CALL = "def build(data):\n    return build_items(data.get('ns'))\n"
# Appends a dict literal directly — keys visible, safe.
_APPEND_DICT_LITERAL = (
    "def build(data):\n"
    "    out = []\n"
    "    for i in data.get('ns', []):\n"
    "        out.append({'key': i['key']})\n"
    "    return out\n"
)
# extend / += / comprehension are all pass-through idioms the draft missed.
_EXTEND = "def flatten(data):\n    out = []\n    out.extend(data.get('ns'))\n    return out\n"
_AUGASSIGN = "def flatten(data):\n    out = []\n    out += data.get('ns')\n    return out\n"
_COMPREHENSION = "def flatten(data):\n    return [c for c in data.get('ns')]\n"
_RETURN_DIRECT = "def flatten(data):\n    return data.get('ns')\n"


def _risks(source, additional_properties=False):
    return find_passthrough_schema_risks({"f": {"source": source, "additional_properties": additional_properties}})


def test_passthrough_with_strict_schema_is_flagged():
    assert any("f" in finding for finding in _risks(_PASSTHROUGH))


def test_passthrough_with_additionalproperties_true_is_ok():
    assert _risks(_PASSTHROUGH, additional_properties=True) == []


def test_constructed_dicts_not_flagged():
    assert _risks(_CONSTRUCTED) == []


def test_constructed_var_appended_not_flagged():
    assert _risks(_CONSTRUCTED_VAR) == []


def test_wrapper_call_not_flagged():
    assert _risks(_WRAPPER_CALL) == []


def test_append_dict_literal_not_flagged():
    assert _risks(_APPEND_DICT_LITERAL) == []


def test_extend_bus_read_is_flagged():
    assert _risks(_EXTEND) != []


def test_augassign_bus_read_is_flagged():
    assert _risks(_AUGASSIGN) != []


def test_comprehension_passthrough_is_flagged():
    assert _risks(_COMPREHENSION) != []


def test_return_direct_bus_read_is_flagged():
    assert _risks(_RETURN_DIRECT) != []


def test_multiple_actions_each_reported_once():
    actions = {
        "flatten": {"source": _PASSTHROUGH, "additional_properties": False},
        "build": {"source": _CONSTRUCTED, "additional_properties": False},
        "extend": {"source": _EXTEND, "additional_properties": False},
    }
    findings = find_passthrough_schema_risks(actions)
    flagged = {name for name in ("flatten", "build", "extend") if any(name in f for f in findings)}
    assert flagged == {"flatten", "extend"}


def test_missing_source_is_ignored():
    assert find_passthrough_schema_risks({"f": {"additional_properties": False}}) == []


def test_syntactically_invalid_source_is_ignored():
    assert _risks("def f(data):\n    this is not python\n") == []
