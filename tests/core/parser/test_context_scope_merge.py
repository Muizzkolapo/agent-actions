"""
Tests for deep merging of context_scope directives between defaults and actions.

This test suite verifies that when an action defines its own context_scope,
it properly merges with (instead of replacing) the defaults.context_scope.

Key scenarios tested:
1. seed_data from defaults + drop from action
2. seed_data from defaults + observe from action
3. observe from both defaults and action (should combine)
4. All directive combinations
5. Empty/missing directives
"""

from agent_actions.output.response.expander import ActionExpander


class TestContextScopeDeepMerge:
    """Test deep merge helper function for context_scope directives."""

    def test_seed_data_from_defaults_plus_drop_from_action(self):
        """Action can define drop while inheriting seed_data from defaults."""
        defaults_scope = {"seed_data": {"exam_syllabus": "$file:azure_ds_associate_syllabus.json"}}
        action_scope = {"drop": ["source.syllabus", "source.url"]}

        result = ActionExpander._deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {
            "seed_data": {"exam_syllabus": "$file:azure_ds_associate_syllabus.json"},
            "drop": ["source.syllabus", "source.url"],
        }

    def test_seed_data_from_defaults_plus_observe_from_action(self):
        """Action can define observe while inheriting seed_data from defaults."""
        defaults_scope = {"seed_data": {"knowledge_base": "$file:kb.json"}}
        action_scope = {"observe": ["previous_agent.field1", "previous_agent.field2"]}

        result = ActionExpander._deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {
            "seed_data": {"knowledge_base": "$file:kb.json"},
            "observe": ["previous_agent.field1", "previous_agent.field2"],
        }

    def test_observe_lists_combine_from_both_levels(self):
        """When both defaults and action have observe, lists should combine."""
        defaults_scope = {"observe": ["agent1.field1"]}
        action_scope = {"observe": ["agent2.field2", "agent3.field3"]}

        result = ActionExpander._deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {"observe": ["agent1.field1", "agent2.field2", "agent3.field3"]}

    def test_drop_lists_combine_from_both_levels(self):
        """When both defaults and action have drop, lists should combine."""
        defaults_scope = {"drop": ["source.internal_id"]}
        action_scope = {"drop": ["source.api_key", "source.credentials"]}

        result = ActionExpander._deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {"drop": ["source.internal_id", "source.api_key", "source.credentials"]}

    def test_list_deduplication(self):
        """When same field appears in both defaults and action, deduplicate."""
        defaults_scope = {"observe": ["agent1.field1", "agent2.field2"]}
        action_scope = {
            "observe": ["agent2.field2", "agent3.field3"]  # agent2.field2 is duplicate
        }

        result = ActionExpander._deep_merge_context_scope(defaults_scope, action_scope)

        # Should preserve order and remove duplicates
        assert result == {"observe": ["agent1.field1", "agent2.field2", "agent3.field3"]}

    def test_seed_data_dicts_merge(self):
        """When both have seed_data, merge the dict contents."""
        defaults_scope = {"seed_data": {"exam_syllabus": "$file:exam.json"}}
        action_scope = {"seed_data": {"grading_rubric": "$file:rubric.yaml"}}

        result = ActionExpander._deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {
            "seed_data": {"exam_syllabus": "$file:exam.json", "grading_rubric": "$file:rubric.yaml"}
        }

    def test_seed_data_action_overrides_same_key(self):
        """When both have same seed_data key, action overrides defaults."""
        defaults_scope = {"seed_data": {"exam_syllabus": "$file:default_exam.json"}}
        action_scope = {
            "seed_data": {
                "exam_syllabus": "$file:custom_exam.json"  # Override
            }
        }

        result = ActionExpander._deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {"seed_data": {"exam_syllabus": "$file:custom_exam.json"}}

    def test_all_directives_combined(self):
        """Complex scenario with all directive types."""
        defaults_scope = {"seed_data": {"exam": "$file:exam.json"}, "observe": ["agent1.field1"]}
        action_scope = {
            "observe": ["agent2.field2"],
            "drop": ["source.api_key"],
            "passthrough": ["source.metadata"],
        }

        result = ActionExpander._deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {
            "seed_data": {"exam": "$file:exam.json"},
            "observe": ["agent1.field1", "agent2.field2"],
            "drop": ["source.api_key"],
            "passthrough": ["source.metadata"],
        }

    def test_passthrough_lists_combine(self):
        """Passthrough directives from both levels should combine."""
        defaults_scope = {"passthrough": ["source.id", "source.timestamp"]}
        action_scope = {"passthrough": ["source.metadata"]}

        result = ActionExpander._deep_merge_context_scope(defaults_scope, action_scope)

        assert result == {"passthrough": ["source.id", "source.timestamp", "source.metadata"]}


class TestContextScopeMergeInActionExpander:
    """Integration tests for context_scope merging in action expansion."""

    def test_action_with_drop_inherits_seed_data_from_defaults(self):
        """Real-world scenario: action defines drop, inherits seed_data from defaults."""
        defaults = {
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "api_key": "test_key",
            "context_scope": {
                "seed_data": {"exam_syllabus": "$file:azure_ds_associate_syllabus.json"}
            },
        }

        action = {
            "name": "fact_extractor",
            "context_scope": {"drop": ["source.syllabus", "source.url"]},
        }

        agent = {"agent_type": "generic", "name": "fact_extractor"}

        # Mock template replacer
        def template_replacer(value):
            return value

        result = ActionExpander._create_agent_from_action(
            action=action,
            defaults=defaults,
            agent=agent,
            template_replacer=template_replacer,
            is_operational=True,
        )

        # Should have both seed_data from defaults AND drop from action
        assert "context_scope" in result
        assert result["context_scope"] == {
            "seed_data": {"exam_syllabus": "$file:azure_ds_associate_syllabus.json"},
            "drop": ["source.syllabus", "source.url"],
        }

    def test_action_without_context_scope_inherits_from_defaults(self):
        """When action has no context_scope, it should inherit from defaults."""
        defaults = {
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "api_key": "test_key",
            "context_scope": {"seed_data": {"knowledge_base": "$file:kb.json"}},
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
            is_operational=True,
        )

        # Should inherit defaults context_scope
        assert "context_scope" in result
        assert result["context_scope"] == {"seed_data": {"knowledge_base": "$file:kb.json"}}

    def test_action_with_observe_inherits_seed_data(self):
        """Action with observe should still inherit seed_data from defaults."""
        defaults = {
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "api_key": "test_key",
            "context_scope": {"seed_data": {"exam": "$file:exam.json"}},
        }

        action = {
            "name": "review_summaries",
            "context_scope": {
                "observe": ["generate_summary.summary_content", "score_quality.quality_score"]
            },
        }

        agent = {"agent_type": "generic", "name": "review_summaries"}

        def template_replacer(value):
            return value

        result = ActionExpander._create_agent_from_action(
            action=action,
            defaults=defaults,
            agent=agent,
            template_replacer=template_replacer,
            is_operational=True,
        )

        # Should have both
        assert "context_scope" in result
        assert result["context_scope"] == {
            "seed_data": {"exam": "$file:exam.json"},
            "observe": ["generate_summary.summary_content", "score_quality.quality_score"],
        }

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
            is_operational=True,
        )

        # Should not have context_scope
        assert "context_scope" not in result
