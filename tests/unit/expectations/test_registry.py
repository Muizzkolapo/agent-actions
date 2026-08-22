"""Built-in deterministic expectation types."""

import pytest

from agent_actions.expectations.registry import get, known_types


def run(type_name, value, **params):
    etype = get(type_name)
    assert etype is not None, f"{type_name} is not registered"
    return etype.check(value, params)


def test_known_types_contains_every_builtin():
    assert set(known_types()) >= {
        "not_null",
        "item_count",
        "word_count_between",
        "word_count_ratio",
        "accepted_values",
        "matches_regex",
        "match_like_pattern",
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


def test_match_like_pattern_treats_percent_as_any_run():
    passed, _ = run("match_like_pattern", "intro <b>bold</b> outro", like_pattern="%<%>%")
    assert passed is True


def test_match_like_pattern_fails_a_value_without_the_pattern():
    passed, detail = run("match_like_pattern", "plain prose with no markup", like_pattern="%<%>%")
    assert passed is False
    assert "%<%>%" in detail


def test_match_like_pattern_treats_underscore_as_exactly_one_character():
    assert run("match_like_pattern", "ab", like_pattern="a_")[0] is True
    assert run("match_like_pattern", "abc", like_pattern="a_")[0] is False


def test_match_like_pattern_is_anchored_across_the_whole_value():
    assert run("match_like_pattern", "prefix ab", like_pattern="a_")[0] is False


def test_match_like_pattern_treats_regex_metacharacters_as_literal_text():
    assert run("match_like_pattern", "axb", like_pattern="a.b")[0] is False
    assert run("match_like_pattern", "a.b", like_pattern="a.b")[0] is True


def test_match_like_pattern_negate_forbids_the_pattern():
    assert run("match_like_pattern", "plain prose", like_pattern="%<%>%", negate=True)[0] is True
    passed, detail = run(
        "match_like_pattern", "has <b>markup</b>", like_pattern="%<%>%", negate=True
    )
    assert passed is False
    assert "%<%>%" in detail


def test_match_like_pattern_requires_its_pattern():
    assert "like_pattern" in get("match_like_pattern").required


def test_every_registered_type_accepts_row_condition():
    missing = [name for name in known_types() if "row_condition" not in get(name).params]
    assert missing == []


def test_match_like_pattern_spans_newlines_the_way_sql_like_does():
    multiline = "line one\n<b>bold</b>\nline three"
    assert run("match_like_pattern", multiline, like_pattern="%<%>%")[0] is True
    assert run("match_like_pattern", "a\nb", like_pattern="a_b")[0] is True


def test_no_registered_argument_name_is_mistaken_for_a_rule_key():
    from agent_actions.expectations.types import _nearest_rule_key

    confused = {
        name: _nearest_rule_key(name)
        for etype in (get(t) for t in known_types())
        for name in etype.params
        if _nearest_rule_key(name) is not None
    }
    assert confused == {}


def test_expectation_check_registers_a_usable_type(preserve_registry):
    from agent_actions import expectation_check

    @expectation_check("ends_with_period")
    def ends_with_period(value, params):
        text = str(value)
        if text.endswith("."):
            return True, ""
        return False, f"value {text!r} does not end with a period"

    etype = get("ends_with_period")
    assert etype is not None
    assert etype.check("Done.", {}) == (True, "")
    assert etype.check("Done", {})[0] is False
    assert "ends_with_period" in known_types()


def test_expectation_check_declares_params_for_preflight(preserve_registry):
    from agent_actions import expectation_check

    @expectation_check("min_sentences", params=("min",), required=("min",))
    def min_sentences(value, params):
        count = str(value).count(".")
        if count >= params["min"]:
            return True, ""
        return False, f"{count} sentences, expected at least {params['min']}"

    etype = get("min_sentences")
    assert etype.params == frozenset({"min", "row_condition"})
    assert etype.required == frozenset({"min"})


def test_shadowing_a_builtin_raises(preserve_registry):
    from agent_actions import expectation_check

    with pytest.raises(ValueError, match="built-in"):

        @expectation_check("not_null")
        def not_null(value, params):
            return True, ""


def test_same_file_reregistration_is_idempotent(preserve_registry):
    from agent_actions import expectation_check

    def original(value, params):
        return True, "original"

    registered_first = expectation_check("idempotent_check")(original)
    registered_second = expectation_check("idempotent_check")(original)
    assert registered_second is registered_first
    assert get("idempotent_check").check(None, {}) == (True, "original")


def test_same_name_from_a_different_file_raises(preserve_registry, monkeypatch):
    from agent_actions import expectation_check
    from agent_actions.errors import DuplicateFunctionError
    from agent_actions.expectations import registry as registry_module

    @expectation_check("collision_check")
    def first(value, params):
        return True, ""

    monkeypatch.setattr(registry_module.inspect, "getfile", lambda fn: "/somewhere/else/checks.py")
    with pytest.raises(DuplicateFunctionError):

        @expectation_check("collision_check")
        def second(value, params):
            return True, ""


def test_user_check_flows_through_the_preflight_validator(preserve_registry):
    from agent_actions import expectation_check
    from agent_actions.validation.expectations_validator import find_expectation_defects

    @expectation_check("has_emoji", params=("at_least",))
    def has_emoji(value, params):
        return True, ""

    configs = {
        "a": {
            "expect": {
                "expectations": [
                    {"id": "e", "type": "has_emoji", "field": "title", "params": {"at_most": 3}}
                ]
            }
        }
    }
    defects = find_expectation_defects(configs, {"a": {"title"}})["a"]
    assert any("takes no parameter 'at_most'" in d for d in defects)
