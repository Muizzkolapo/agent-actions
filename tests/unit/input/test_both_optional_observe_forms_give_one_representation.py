"""An optional observe entry is written two ways and read one way.

`review.rejected_text?` and `{field: review.rejected_text, optional: true}` both
leave the plain reference in `observe` and name it under `optional`, with the value a
missing field takes. Nothing downstream meets a `?` or a mapping in the observe list.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, DefaultsConfig
from agent_actions.errors import ConfigurationError
from agent_actions.input.context.normalizer import (
    normalize_all_agent_configs,
    normalize_context_scope,
    observe_entry_reference,
    split_optional_observe,
)
from agent_actions.output.response.expander_merge import deep_merge_context_scope

SUFFIX = {"observe": ["spec.text", "review.rejected_text?"]}
MAPPING = {"observe": ["spec.text", {"field": "review.rejected_text", "optional": True}]}
PLAIN = {
    "observe": ["spec.text", "review.rejected_text"],
    "optional": {"review.rejected_text": None},
}


class TestTheTwoFormsAreEquivalent:
    def test_the_suffix_form_leaves_a_plain_reference_and_names_it_optional(self):
        assert split_optional_observe(SUFFIX) == PLAIN

    def test_the_mapping_form_gives_the_same(self):
        assert split_optional_observe(MAPPING) == split_optional_observe(SUFFIX)

    def test_the_normaliser_the_run_and_preflight_share_gives_the_same(self):
        assert normalize_context_scope(SUFFIX, {}) == PLAIN
        assert normalize_context_scope(MAPPING, {}) == PLAIN

    def test_what_is_already_plain_is_left_as_it_is(self):
        assert normalize_context_scope(PLAIN, {}) == PLAIN
        assert split_optional_observe(PLAIN) is PLAIN

    def test_a_scope_with_no_optional_entry_gains_no_key(self):
        scope = {"observe": ["spec.text", "review.*"], "drop": ["spec.secret"]}

        assert split_optional_observe(scope) is scope
        assert "optional" not in normalize_context_scope(scope, {})

    def test_a_suffix_inside_the_mapping_form_means_the_same(self):
        scope = {"observe": [{"field": "review.rejected_text?"}]}

        assert split_optional_observe(scope)["optional"] == {"review.rejected_text": None}


class TestTheMappingFormStatesADefault:
    def test_a_default_is_kept_for_the_reference(self):
        scope = {"observe": [{"field": "review.rejected_text", "optional": True, "default": ""}]}

        assert split_optional_observe(scope) == {
            "observe": ["review.rejected_text"],
            "optional": {"review.rejected_text": ""},
        }

    def test_a_default_alone_makes_the_field_optional(self):
        scope = {"observe": [{"field": "review.reasons", "default": []}]}

        assert split_optional_observe(scope)["optional"] == {"review.reasons": []}

    def test_a_mapping_that_is_not_optional_is_a_plain_reference(self):
        scope = {"observe": [{"field": "review.score", "optional": False}]}

        assert split_optional_observe(scope) == {"observe": ["review.score"]}

    def test_a_field_named_twice_is_listed_once_and_keeps_the_stated_default(self):
        scope = {"observe": ["review.text?", {"field": "review.text", "default": "none"}]}

        assert split_optional_observe(scope) == {
            "observe": ["review.text"],
            "optional": {"review.text": "none"},
        }


class TestWhatIsRefusedAtLoad:
    @pytest.mark.parametrize(
        "entry",
        ["source.*?", {"field": "source.*", "optional": True}, {"field": "source.*?"}],
        ids=["suffix", "mapping", "suffix-in-mapping"],
    )
    def test_an_optional_wildcard_is_refused(self, entry):
        with pytest.raises(ConfigurationError, match="wildcard"):
            split_optional_observe({"observe": [entry]})

    @pytest.mark.parametrize("entry", ["review?.text", "review.text??", "review.body?.text"])
    def test_a_question_mark_anywhere_but_the_end_is_refused(self, entry):
        with pytest.raises(ConfigurationError, match="at the end"):
            split_optional_observe({"observe": [entry]})

    @pytest.mark.parametrize(
        "entry, problem",
        [
            ({"optional": True}, "'field'"),
            ({"field": 3, "optional": True}, "'field'"),
            ({"field": "review.text", "optional": "yes"}, "true or false"),
            ({"field": "review.text", "fallback": ""}, "fallback"),
            ({"field": "review.text?", "optional": False}, "optional: false"),
            ({"field": "review.text", "optional": False, "default": ""}, "optional: false"),
        ],
    )
    def test_a_malformed_mapping_names_its_problem(self, entry, problem):
        with pytest.raises(ConfigurationError, match=problem):
            split_optional_observe({"observe": [entry]})

    @pytest.mark.parametrize("directive", ["passthrough", "drop"])
    @pytest.mark.parametrize(
        "entry",
        ["review.text?", {"field": "review.text", "optional": True}],
        ids=["suffix", "map"],
    )
    def test_passthrough_and_drop_have_no_optional_form(self, directive, entry):
        with pytest.raises(ConfigurationError, match=f"context_scope.{directive}"):
            split_optional_observe({"observe": ["review.*"], directive: [entry]})

    def test_the_normaliser_refuses_what_the_split_refuses(self):
        with pytest.raises(ConfigurationError, match="wildcard"):
            normalize_context_scope({"observe": ["source.*?"]}, {})


class TestTheWorkflowFileIsReadAtItsBoundary:
    def _action(self, scope: dict) -> ActionConfig:
        return ActionConfig.model_validate({"name": "a", "intent": "i", "context_scope": scope})

    def test_an_action_holds_plain_references_once_validated(self):
        assert self._action(SUFFIX).context_scope == PLAIN
        assert self._action(MAPPING).context_scope == PLAIN

    def test_defaults_hold_plain_references_once_validated(self):
        assert DefaultsConfig.model_validate({"context_scope": MAPPING}).context_scope == PLAIN

    def test_an_optional_wildcard_fails_the_load_naming_the_entry(self):
        with pytest.raises(ValidationError) as raised:
            self._action({"observe": ["source.*?"]})

        message = str(raised.value)
        assert "source.*?" in message
        assert "wildcard" in message

    def test_an_optional_passthrough_fails_the_load(self):
        with pytest.raises(ValidationError, match="context_scope.passthrough"):
            self._action({"observe": ["source.*"], "passthrough": ["source.title?"]})


class TestDefaultsAndActionMerge:
    def test_an_optional_entry_of_the_defaults_reaches_the_action(self):
        merged = deep_merge_context_scope(
            {"observe": ["review.rejected_text?"]}, {"observe": ["spec.text"]}
        )

        assert merged == {
            "observe": ["review.rejected_text", "spec.text"],
            "optional": {"review.rejected_text": None},
        }

    def test_the_mapping_form_merges_over_a_defaults_list(self):
        """A mapping is not hashable, so the unsplit list could not be merged at all."""
        merged = deep_merge_context_scope(
            {"observe": ["spec.text"]},
            {"observe": [{"field": "review.rejected_text", "optional": True, "default": ""}]},
        )

        assert merged == {
            "observe": ["spec.text", "review.rejected_text"],
            "optional": {"review.rejected_text": ""},
        }

    def test_the_same_field_written_both_ways_is_observed_once(self):
        merged = deep_merge_context_scope(
            {"observe": ["review.rejected_text"]}, {"observe": ["review.rejected_text?"]}
        )

        assert merged["observe"] == ["review.rejected_text"]
        assert merged["optional"] == {"review.rejected_text": None}


class TestAVersionedUpstream:
    def test_an_optional_field_of_a_version_base_is_optional_on_every_version(self):
        scope = {"observe": [{"field": "vote.reason", "optional": True, "default": "-"}]}

        assert normalize_context_scope(scope, {"vote": ["vote_1", "vote_2"]}) == {
            "observe": ["vote_1.reason", "vote_2.reason"],
            "optional": {"vote_1.reason": "-", "vote_2.reason": "-"},
        }

    def test_every_agent_config_is_normalised_in_place(self):
        configs = {
            "vote_1": {"is_versioned_agent": True, "version_base_name": "vote"},
            "vote_2": {"is_versioned_agent": True, "version_base_name": "vote"},
            "tally": {"context_scope": {"observe": ["vote.reason?"]}},
        }

        normalize_all_agent_configs(configs)

        assert configs["tally"]["context_scope"] == {
            "observe": ["vote_1.reason", "vote_2.reason"],
            "optional": {"vote_1.reason": None, "vote_2.reason": None},
        }


class TestOneEntryReadLeniently:
    """What an editor needs of a file that is still being written."""

    @pytest.mark.parametrize(
        "entry, reference",
        [
            ("review.text", "review.text"),
            ("review.text?", "review.text"),
            ({"field": "review.text", "optional": True}, "review.text"),
            ({"field": "review.text?"}, "review.text"),
            ({"optional": True}, None),
            (None, None),
            (3, None),
        ],
    )
    def test_the_reference_an_entry_names(self, entry, reference):
        assert observe_entry_reference(entry) == reference
