"""find_unknown_bus_namespaces: flag literal UDF reads of an unknown bus namespace."""

from agent_actions.validation.bus_namespace_validator import find_unknown_bus_namespaces

_SRC = (
    "def agg(data):\n"
    "    a = data.get('compile_verify_input')\n"
    "    b = data['author']\n"
    "    c = data.get('fb_compile_verify_input')\n"
    "    return {}\n"
)

_VALID = {"compile_verify_input", "author", "seed"}


def test_unknown_literal_is_flagged():
    findings = find_unknown_bus_namespaces({"agg": _SRC}, _VALID)
    assert any("fb_compile_verify_input" in f and "agg" in f for f in findings)


def test_known_literals_not_flagged():
    src = "def agg(data):\n    a = data.get('compile_verify_input')\n    b = data['author']\n    return {}\n"
    assert find_unknown_bus_namespaces({"agg": src}, _VALID) == []


def test_dynamic_key_is_ignored():
    src = "def f(data):\n    k = 'x'\n    return data.get(k)\n"
    assert find_unknown_bus_namespaces({"f": src}, {"author"}) == []


def test_subscript_literal_flagged():
    src = "def f(data):\n    return data['nope']\n"
    assert any("nope" in f for f in find_unknown_bus_namespaces({"f": src}, {"author"}))


def test_default_arg_get_is_still_flagged():
    # data.get("X", default) is a warning, not an error — the optional read stays
    # unbroken but the typo is still surfaced (FAILURE MODE #3).
    src = "def f(data):\n    return data.get('maybe', {})\n"
    assert any("maybe" in f for f in find_unknown_bus_namespaces({"f": src}, {"author"}))


def test_non_data_variable_not_flagged():
    # Only reads off the `data` bus count — a regex over source text would over-match.
    src = "def f(data):\n    other = {}\n    return other.get('typo_name')\n"
    assert find_unknown_bus_namespaces({"f": src}, {"author"}) == []


def test_literal_in_comment_or_string_not_flagged():
    # AST anchors on real reads — literals in comments/strings must be invisible.
    src = "def f(data):\n    # data.get('ghost')\n    s = \"data['phantom']\"\n    return data.get('author')\n"
    assert find_unknown_bus_namespaces({"f": src}, {"author"}) == []


def test_finding_attributed_to_enclosing_function_not_siblings():
    # Two UDFs in one source: only the offender is named, never its sibling.
    src = (
        "def reader_a(data):\n"
        "    return data.get('bad_key')\n"
        "def reader_b(data):\n"
        "    return data.get('author')\n"
    )
    findings = find_unknown_bus_namespaces({"tools.py": src}, {"author"})
    assert any(f.startswith("reader_a:") and "bad_key" in f for f in findings)
    assert not any(f.startswith("reader_b:") for f in findings)


def test_same_key_read_twice_in_one_udf_is_deduped():
    src = "def f(data):\n    x = data.get('bad')\n    y = data['bad']\n    return x or y\n"
    assert len(find_unknown_bus_namespaces({"f": src}, {"author"})) == 1


def test_syntax_error_source_is_skipped():
    src = "def f(data)\n    return data.get('bad')\n"  # missing colon
    assert find_unknown_bus_namespaces({"f": src}, {"author"}) == []


def test_multiple_unknown_keys_all_reported():
    src = "def f(data):\n    return data.get('one'), data['two']\n"
    findings = find_unknown_bus_namespaces({"f": src}, {"author"})
    assert any("one" in f for f in findings)
    assert any("two" in f for f in findings)
