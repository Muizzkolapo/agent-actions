"""
Tests for deep merging of context_scope directives between defaults and actions.

This test suite verifies that when an action defines its own context_scope,
it properly merges with (instead of replacing) the defaults.context_scope.

Key scenarios tested:
1. seed from defaults + drop from action
2. seed from defaults + observe from action
3. observe from both defaults and action (should combine)
4. All directive combinations
5. Empty/missing directives
"""

import pytest

from agent_actions.output.response.expander import ActionExpander
from agent_actions.output.response.expander_merge import deep_merge_context_scope


class TestContextScopeDeepMerge:
    """Test deep merge helper function for context_scope directives."""

    @pytest.mark.parametrize(
        ("defaults_scope", "action_scope", "expected"),
        [
            pytest.param(
                {"seed": {"exam_syllabus": "$file:azure_ds_associate_syllabus.json"}},
                {"drop": ["source.syllabus", "source.url"]},
                {
                    "seed": {"exam_syllabus": "$file:azure_ds_associate_syllabus.json"},
                    "drop": ["source.syllabus", "source.url"],
                },
                id="drop",
            ),
            pytest.param(
                {"seed": {"knowledge_base": "$file:kb.json"}},
                {"observe": ["previous_agent.field1", "previous_agent.field2"]},
                {
                    "seed": {"knowledge_base": "$file:kb.json"},
                    "observe": ["previous_agent.field1", "previous_agent.field2"],
                },
                id="observe",
            ),
        ],
    )
    def test_seed_from_defaults_plus_directive_from_action(
        self, defaults_scope, action_scope, expected
    ):
        """Action can define a directive while inheriting seed from defaults."""
        assert deep_merge_context_scope(defaults_scope, action_scope) == expected

    @pytest.mark.parametrize(
        ("directive", "defaults_list", "action_list"),
        [
            pytest.param(
                "observe", ["agent1.field1"], ["agent2.field2", "agent3.field3"], id="observe"
            ),
            pytest.param(
                "drop",
                ["source.internal_id"],
                ["source.api_key", "source.credentials"],
                id="drop",
            ),
            pytest.param(
                "passthrough",
                ["source.id", "source.timestamp"],
                ["source.metadata"],
                id="passthrough",
            ),
        ],
    )
    def test_directive_lists_combine_from_both_levels(self, directive, defaults_list, action_list):
        """When both defaults and action have the same list directive, lists combine."""
        result = deep_merge_context_scope({directive: defaults_list}, {directive: action_list})

        assert result == {directive: defaults_list + action_list}

    def test_list_deduplication(self):
        """When same field appears in both defaults and action, deduplicate."""
        defaults_scope = {"observe": ["agent1.field1", "agent2.field2"]}
        action_scope = {
            "observe": ["agent2.field2", "agent3.field3"]  # agent2.field2 is duplicate
        }

        result = deep_merge_context_scope(defaults_scope, action_scope)

        # Should preserve order and remove duplicates
        assert result == {"observe": ["agent1.field1", "agent2.field2", "agent3.field3"]}

    def test_seed_dicts_merge(self):
        """When both have seed, merge the dict contents."""
        defaults_scope = {"seed": {"exam_syllabus": "$file:exam.json"}}
        action_scope = {"seed": {"grading_rubric": "$file:rubric.yaml"}}

        result = deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {
            "seed": {"exam_syllabus": "$file:exam.json", "grading_rubric": "$file:rubric.yaml"}
        }

    def test_seed_action_overrides_same_key(self):
        """When both have same seed key, action overrides defaults."""
        defaults_scope = {"seed": {"exam_syllabus": "$file:default_exam.json"}}
        action_scope = {
            "seed": {
                "exam_syllabus": "$file:custom_exam.json"  # Override
            }
        }

        result = deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {"seed": {"exam_syllabus": "$file:custom_exam.json"}}

    def test_all_directives_combined(self):
        """Complex scenario with all directive types."""
        defaults_scope = {"seed": {"exam": "$file:exam.json"}, "observe": ["agent1.field1"]}
        action_scope = {
            "observe": ["agent2.field2"],
            "drop": ["source.api_key"],
            "passthrough": ["source.metadata"],
        }

        result = deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {
            "seed": {"exam": "$file:exam.json"},
            "observe": ["agent1.field1", "agent2.field2"],
            "drop": ["source.api_key"],
            "passthrough": ["source.metadata"],
        }


class TestContextScopeMergeInActionExpander:
    """Integration tests for context_scope merging in action expansion."""

    @pytest.mark.parametrize(
        ("name", "seed", "action_scope"),
        [
            pytest.param(
                "fact_extractor",
                {"exam_syllabus": "$file:azure_ds_associate_syllabus.json"},
                {"drop": ["source.syllabus", "source.url"]},
                id="drop",
            ),
            pytest.param(
                "review_summaries",
                {"exam": "$file:exam.json"},
                {"observe": ["generate_summary.summary_content", "score_quality.quality_score"]},
                id="observe",
            ),
        ],
    )
    def test_action_with_directive_inherits_seed_from_defaults(self, name, seed, action_scope):
        """An action that defines drop or observe keeps the seed from defaults."""
        defaults = {
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "api_key": "test_key",
            "context_scope": {"seed": seed},
        }
        action = {"name": name, "context_scope": action_scope}
        agent = {"agent_type": "generic", "name": name}

        def template_replacer(value):
            return value

        result = ActionExpander._create_agent_from_action(
            action=action,
            defaults=defaults,
            agent=agent,
            template_replacer=template_replacer,
        )

        assert "context_scope" in result
        assert result["context_scope"] == {"seed": seed, **action_scope}

    def test_action_without_context_scope_inherits_from_defaults(self):
        """When action has no context_scope, it should inherit from defaults."""
        defaults = {
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "api_key": "test_key",
            "context_scope": {"seed": {"knowledge_base": "$file:kb.json"}},
        }

        action = {
            "name": "processor"
            # No context_scope defined
        }

        agent = {"agent_type": "generic", "name": "processor"}

        def template_replacer(value):
            return value

        result = ActionExpander._create_agent_from_action(
            action=action,
            defaults=defaults,
            agent=agent,
            template_replacer=template_replacer,
        )

        # Should inherit defaults context_scope
        assert "context_scope" in result
        assert result["context_scope"] == {"seed": {"knowledge_base": "$file:kb.json"}}

    def test_no_context_scope_in_either(self):
        """When neither defaults nor action have context_scope, agent should not have it."""
        defaults = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "test_key"}

        action = {"name": "simple_agent"}

        agent = {"agent_type": "generic", "name": "simple_agent"}

        def template_replacer(value):
            return value

        result = ActionExpander._create_agent_from_action(
            action=action,
            defaults=defaults,
            agent=agent,
            template_replacer=template_replacer,
        )

        # Should not have context_scope
        assert "context_scope" not in result


class TestASelectedSeedSurvivesTheMerge:
    def test_an_action_replaces_one_selected_key_and_keeps_the_rest(self):
        """A seed entry that picks its file by a record field merges as one whole value."""
        defaults_scope = {
            "seed": {
                "rules": "$file:rules.json",
                "syllabus": {
                    "select_by": "source.exam",
                    "files": {"dbt": "$file:dbt.json", "snowflake": "$file:snowflake.json"},
                },
            }
        }
        action_scope = {
            "seed": {"syllabus": {"select_by": "source.track", "files": {"a": "$file:a.json"}}}
        }

        result = deep_merge_context_scope(defaults_scope, action_scope)

        assert result["seed"] == {
            "rules": "$file:rules.json",
            "syllabus": {"select_by": "source.track", "files": {"a": "$file:a.json"}},
        }
