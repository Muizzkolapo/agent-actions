"""Built-in deterministic expectation types."""

import pytest

from agent_actions.expectations.registry import get, known_types


def run(type_name, value, **params):
    etype = get(type_name)
    assert etype is not None, f"{type_name} is not registered"
    return etype.check(value, params)


def test_known_types_contains_every_builtin():
    assert set(known_types()) == {
        "not_null",
        "item_count",
        "word_count_between",
        "word_count_ratio",
        "accepted_values",
        "matches_regex",
        "no_forbidden_phrases",
        "contains_terms_from",
    }


def test_get_returns_none_for_unregistered_type():
    assert get("no_such_type") is None


@pytest.mark.parametrize("value", [None, "", [], {}])
def test_not_null_fails_on_null_and_empty(value):
    passed, detail = run("not_null", value)
    assert passed is False
    assert detail


def test_not_null_passes_on_zero_because_zero_is_a_value():
    assert run("not_null", 0)[0] is True


def test_item_count_equals_passes_on_exact_length():
    assert run("item_count", [1, 2, 3, 4], equals=4)[0] is True


def test_item_count_equals_fails_and_reports_both_numbers():
    passed, detail = run("item_count", [1, 2, 3], equals=4)
    assert passed is False
    assert "4" in detail and "3" in detail


def test_item_count_min_fails_below_bound():
    assert run("item_count", [1], min=2)[0] is False


def test_item_count_max_fails_above_bound():
    assert run("item_count", [1, 2, 3], max=2)[0] is False


def test_item_count_on_a_non_list_fails_rather_than_raising():
    passed, detail = run("item_count", "not a list", equals=4)
    assert passed is False
    assert "str" in detail


def test_word_count_between_passes_inside_bounds():
    assert run("word_count_between", "one two three", min=2, max=5)[0] is True


def test_word_count_between_fails_below_min():
    assert run("word_count_between", "one", min=2)[0] is False


def test_word_count_between_fails_above_max():
    assert run("word_count_between", "one two three", max=2)[0] is False


def test_word_count_ratio_passes_when_options_are_balanced():
    assert run("word_count_ratio", ["a b", "c d"], max_ratio=2.0)[0] is True


def test_word_count_ratio_fails_when_one_option_dwarfs_another():
    passed, detail = run("word_count_ratio", ["a", "b c d e f"], max_ratio=2.0)
    assert passed is False
    assert "2.0" in detail


def test_word_count_ratio_fails_when_an_item_is_empty_rather_than_dividing_by_zero():
    passed, detail = run("word_count_ratio", ["", "a b"], max_ratio=2.0)
    assert passed is False
    assert "empty" in detail


def test_accepted_values_passes_for_a_member():
    assert run("accepted_values", "placed", values=["placed", "shipped"])[0] is True


def test_accepted_values_fails_for_a_non_member_and_names_it():
    passed, detail = run("accepted_values", "returned", values=["placed", "shipped"])
    assert passed is False
    assert "returned" in detail


def test_matches_regex_passes_on_a_match():
    assert run("matches_regex", "AB-123", pattern=r"^[A-Z]{2}-\d+$")[0] is True


def test_matches_regex_fails_when_the_pattern_is_absent():
    assert run("matches_regex", "nope", pattern=r"^[A-Z]{2}-\d+$")[0] is False


def test_matches_regex_negate_inverts_the_verdict():
    assert run("matches_regex", "nope", pattern=r"\d", negate=True)[0] is True
    assert run("matches_regex", "has 1 digit", pattern=r"\d", negate=True)[0] is False


def test_no_forbidden_phrases_passes_when_none_present():
    assert run("no_forbidden_phrases", "per the documentation", phrases=["the source"])[0] is True


def test_no_forbidden_phrases_fails_and_names_the_phrase_found():
    passed, detail = run("no_forbidden_phrases", "per the source", phrases=["the source"])
    assert passed is False
    assert "the source" in detail


def test_no_forbidden_phrases_is_case_insensitive_by_default():
    assert run("no_forbidden_phrases", "per The Source", phrases=["the source"])[0] is False


def test_no_forbidden_phrases_respects_case_sensitive_flag():
    assert (
        run("no_forbidden_phrases", "per The Source", phrases=["the source"], case_sensitive=True)[
            0
        ]
        is True
    )


def test_contains_terms_from_passes_on_a_single_match_by_default():
    assert run("contains_terms_from", "uses TLS handshake", terms=["TLS", "mTLS"])[0] is True


def test_contains_terms_from_fails_when_min_matches_not_reached():
    passed, detail = run("contains_terms_from", "uses TLS", terms=["TLS", "mTLS"], min_matches=2)
    assert passed is False
    assert "1" in detail


def test_item_count_max_passes_on_the_exact_bound():
    assert run("item_count", [1, 2], max=2)[0] is True


def test_item_count_min_passes_on_the_exact_bound():
    assert run("item_count", [1, 2], min=2)[0] is True


def test_word_count_between_min_passes_on_the_exact_bound():
    assert run("word_count_between", "one two", min=2)[0] is True


def test_word_count_between_max_passes_on_the_exact_bound():
    assert run("word_count_between", "one two", max=2)[0] is True


def test_word_count_ratio_empty_item_detail_names_the_index():
    passed, detail = run("word_count_ratio", ["a b", "", "c"], max_ratio=2.0)
    assert passed is False
    assert "1" in detail


def test_word_count_ratio_passes_on_the_exact_max_ratio_boundary():
    assert run("word_count_ratio", ["a", "a b"], max_ratio=2.0)[0] is True


def test_matches_regex_detail_names_the_observed_value():
    passed, detail = run("matches_regex", "nope", pattern=r"^[A-Z]{2}-\d+$")
    assert passed is False
    assert "nope" in detail


def test_no_forbidden_phrases_handles_a_non_string_phrase_under_case_sensitive():
    passed, detail = run("no_forbidden_phrases", "the value is 5", phrases=[5], case_sensitive=True)
    assert passed is False
    assert "5" in detail
