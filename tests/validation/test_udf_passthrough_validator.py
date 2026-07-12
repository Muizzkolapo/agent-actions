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
# Two-level namespace flatten with a ternary and `or []` guard — the canonical
# real-world flatten shape. Taint must survive the sub-read off a derived value.
_TWO_LEVEL = (
    "def flatten(data):\n"
    "    cq = data.get('canonicalize', {})\n"
    "    items = cq.get('items') if isinstance(cq, dict) else None\n"
    "    out = []\n"
    "    for q in items or []:\n"
    "        out.append(q)\n"
    "    return out\n"
)
# Reads via subscript, not .get.
_SUBSCRIPT = "def flatten(data):\n    return data['ns']\n"
# Bus param named something other than `data` — the runtime passes it positionally.
_NONDATA_PARAM = "def flatten(bus):\n    out = []\n    for c in bus.get('ns'):\n        out.append(c)\n    return out\n"
# out = out + bus_read (plain Assign with BinOp, the sibling of +=).
_BINOP_ASSIGN = "def flatten(data):\n    out = []\n    out = out + data.get('ns')\n    return out\n"
# Returns the whole input unchanged (pure filter) — input already conforms, safe.
_RETURN_INPUT = "def keep(record):\n    return record if record['ok'] else {}\n"
# Mutates the input record and returns it — out of scope (not a namespace read); safe.
_MUTATE_RETURN_INPUT = "def mark(record):\n    record['status'] = 'KEEP'\n    return record\n"
# Reads a sub-key but builds a fresh dict literal — safe.
_SUBKEY_CONSTRUCT = (
    "def build(data):\n    cfg = data.get('config', {})\n    return {'ok': cfg.get('threshold')}\n"
)
# String first param with sequence indexing — a prompt/parse helper, not a dict
# passthrough. Numeric index / slice must not be mistaken for a mapping read.
_STR_INDEX = "def make_prompt(context_str):\n    return context_str[0]\n"
_STR_SLICE = "def make_prompt(context_str):\n    return context_str[0:100]\n"
_NEG_INDEX = "def last(seq):\n    return seq[-1]\n"
# Variable string key is still a mapping read — real tools index by a key var.
_VAR_KEY = "def f(data):\n    k = 'ns'\n    return data[k]\n"


def _risks(source, additional_properties=False):
    return find_passthrough_schema_risks(
        {"f": {"source": source, "additional_properties": additional_properties}}
    )


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


def test_two_flagged_actions_yield_exactly_two_findings():
    actions = {
        "flatten": {"source": _PASSTHROUGH, "additional_properties": False},
        "build": {"source": _CONSTRUCTED, "additional_properties": False},
        "extend": {"source": _EXTEND, "additional_properties": False},
    }
    findings = find_passthrough_schema_risks(actions)
    assert len(findings) == 2
    flagged = {name for name in ("flatten", "build", "extend") if any(name in f for f in findings)}
    assert flagged == {"flatten", "extend"}


def test_two_level_namespace_flatten_is_flagged():
    assert _risks(_TWO_LEVEL) != []


def test_subscript_bus_read_is_flagged():
    assert _risks(_SUBSCRIPT) != []


def test_non_data_param_name_is_flagged():
    assert _risks(_NONDATA_PARAM) != []


def test_binop_assign_bus_read_is_flagged():
    assert _risks(_BINOP_ASSIGN) != []


def test_return_whole_input_not_flagged():
    assert _risks(_RETURN_INPUT) == []


def test_mutate_and_return_input_not_flagged():
    assert _risks(_MUTATE_RETURN_INPUT) == []


def test_subkey_read_into_dict_literal_not_flagged():
    assert _risks(_SUBKEY_CONSTRUCT) == []


def test_string_index_not_flagged():
    assert _risks(_STR_INDEX) == []


def test_string_slice_not_flagged():
    assert _risks(_STR_SLICE) == []


def test_negative_index_not_flagged():
    assert _risks(_NEG_INDEX) == []


def test_variable_key_subscript_is_flagged():
    assert _risks(_VAR_KEY) != []


def test_missing_source_is_ignored():
    assert find_passthrough_schema_risks({"f": {"additional_properties": False}}) == []


def test_syntactically_invalid_source_is_ignored():
    assert _risks("def f(data):\n    this is not python\n") == []
