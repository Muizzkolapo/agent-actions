"""find_unknown_bus_namespaces: flag literal UDF reads of an unknown bus namespace."""

import pytest

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


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("def f(data):\n    k = 'x'\n    return data.get(k)\n", id="dynamic-key"),
        # Only reads off the `data` bus count; a regex over source text would over-match.
        pytest.param(
            "def f(data):\n    other = {}\n    return other.get('typo_name')\n",
            id="non-data-var",
        ),
        # AST anchors on real reads; literals in comments/strings are invisible.
        pytest.param(
            "def f(data):\n    # data.get('ghost')\n    s = \"data['phantom']\"\n    return data.get('author')\n",
            id="literal-in-comment-or-string",
        ),
        pytest.param("def f(data)\n    return data.get('bad')\n", id="syntax-error"),
    ],
)
def test_source_without_a_literal_unknown_read_is_not_flagged(src):
    assert find_unknown_bus_namespaces({"f": src}, {"author"}) == []


@pytest.mark.parametrize(
    ("src", "key"),
    [
        pytest.param("def f(data):\n    return data['nope']\n", "nope", id="subscript"),
        # data.get("X", default) keeps the optional read unbroken but still surfaces the typo.
        pytest.param("def f(data):\n    return data.get('maybe', {})\n", "maybe", id="get-default"),
    ],
)
def test_unknown_literal_read_is_flagged(src, key):
    assert any(key in f for f in find_unknown_bus_namespaces({"f": src}, {"author"}))


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


def test_multiple_unknown_keys_all_reported():
    src = "def f(data):\n    return data.get('one'), data['two']\n"
    findings = find_unknown_bus_namespaces({"f": src}, {"author"})
    assert any("one" in f for f in findings)
    assert any("two" in f for f in findings)


def test_identical_nested_helper_across_sources_not_deduped():
    # Two distinct UDFs each define a nested helper of the same name reading the same
    # unknown key. These are two independent bugs and must both be reported — dedup is
    # per-source, so the second must not be swallowed.
    src_a = "def udf_a(data):\n    def _inner(data):\n        return data.get('bad')\n    return _inner(data)\n"
    src_b = "def udf_b(data):\n    def _inner(data):\n        return data.get('bad')\n    return _inner(data)\n"
    findings = find_unknown_bus_namespaces({"a": src_a, "b": src_b}, {"author"})
    assert len(findings) == 2


def test_same_key_repeated_within_one_function_still_deduped():
    # Per-source dedup must still collapse a repeat within the same function.
    src = "def f(data):\n    return data.get('bad'), data['bad'], data.get('bad')\n"
    assert len(find_unknown_bus_namespaces({"f": src}, {"author"})) == 1
