"""Tests for the reference extractor."""

from agent_actions.validation.static_analyzer import ReferenceExtractor


class TestReferenceExtractor:
    """Tests for ReferenceExtractor class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = ReferenceExtractor()

    def test_extract_jinja2_basic(self):
        """Test extracting basic Jinja2 references."""
        config = {
            "name": "test_agent",
            "prompt": "The result is {{ action.extractor.summary }}",
        }
        refs = self.extractor.extract_from_agent(config)

        assert len(refs) == 1
        assert refs[0].source_agent == "extractor"
        assert refs[0].field_path == "summary"

    def test_extract_jinja2_nested_field(self):
        """Test extracting nested field references."""
        config = {
            "name": "test_agent",
            "prompt": "Score: {{ action.analyzer.metadata.score }}",
        }
        refs = self.extractor.extract_from_agent(config)

        assert len(refs) == 1
        assert refs[0].source_agent == "analyzer"
        assert refs[0].field_path == "metadata.score"

    def test_extract_multiple_references(self):
        """Test extracting multiple references from prompt."""
        config = {
            "name": "test_agent",
            "prompt": """
            Name: {{ action.user_info.name }}
            Age: {{ action.user_info.age }}
            City: {{ action.location.city }}
            """,
        }
        refs = self.extractor.extract_from_agent(config)

        assert len(refs) == 3
        agents = {r.source_agent for r in refs}
        assert agents == {"user_info", "location"}

    def test_extract_simple_braces(self):
        """Test extracting simple {action.agent.field} references."""
        config = {
            "name": "test_agent",
            "prompt": "The value is {action.extractor.result}",
        }
        refs = self.extractor.extract_from_agent(config)

        assert len(refs) == 1
        assert refs[0].source_agent == "extractor"
        assert refs[0].field_path == "result"

    def test_skip_source_namespace_in_guards(self):
        """Test that source namespace references don't cause errors."""
        config = {
            "name": "test_agent",
            "prompt": "Process this",
            "guard": "source.data.length > 0",
        }
        refs = self.extractor.extract_from_agent(config)

        # source is in guard, will be extracted but filtered at type check time
        source_refs = [r for r in refs if r.source_agent == "source"]
        assert len(source_refs) >= 1

    def test_extract_from_agent_config_prompt(self):
        """Test extracting references from agent config prompt."""
        config = {
            "name": "summarizer",
            "prompt": "Summarize: {{ action.extractor.text }}",
        }
        refs = self.extractor.extract_from_agent(config)

        assert len(refs) == 1
        assert refs[0].source_agent == "extractor"
        assert refs[0].location == "prompt"

    def test_extract_from_guard_expression(self):
        """Test extracting references from guard expressions."""
        config = {
            "name": "conditional_agent",
            "prompt": "Process",
            "guard": "analyzer.confidence > 0.8",
        }
        refs = self.extractor.extract_from_agent(config)

        # Should find analyzer reference in guard
        guard_refs = [r for r in refs if r.location == "guard"]
        assert len(guard_refs) == 1
        assert guard_refs[0].source_agent == "analyzer"
        assert guard_refs[0].field_path == "confidence"

    def test_extract_from_guard_with_action_prefix(self):
        """Test extracting references from guard expressions with action prefix."""
        config = {
            "name": "conditional_agent",
            "prompt": "Process",
            "guard": "action.analyzer.confidence > 0.8",
        }
        refs = self.extractor.extract_from_agent(config)

        guard_refs = [r for r in refs if r.location == "guard"]
        assert len(guard_refs) == 1
        assert guard_refs[0].source_agent == "analyzer"
        assert guard_refs[0].field_path == "confidence"

    def test_extract_from_dict_guard_with_action_prefix(self):
        """Test extracting references from dict guard with action prefix."""
        config = {
            "name": "conditional_agent",
            "prompt": "Process",
            "guard": {
                "field": "action.analyzer.confidence",
                "operator": ">",
                "value": 0.8,
            },
        }
        refs = self.extractor.extract_from_agent(config)

        guard_refs = [r for r in refs if r.location == "guard.field"]
        assert len(guard_refs) == 1
        assert guard_refs[0].source_agent == "analyzer"
        assert guard_refs[0].field_path == "confidence"

    def test_extract_from_context_scope_observe(self):
        """Test extracting references from context_scope observe."""
        config = {
            "name": "agent",
            "prompt": "Process",
            "context_scope": {
                "observe": ["extractor.field1", "classifier.category"],
            },
        }
        refs = self.extractor.extract_from_agent(config)

        context_refs = [r for r in refs if r.location == "context_scope.observe"]
        assert len(context_refs) == 2

    def test_extract_from_context_scope_with_action_prefix(self):
        """Test extracting references from context_scope with action prefix."""
        config = {
            "name": "agent",
            "prompt": "Process",
            "context_scope": {
                "observe": ["action.extractor.field1", "action.classifier.category"],
            },
        }
        refs = self.extractor.extract_from_agent(config)

        context_refs = [r for r in refs if r.location == "context_scope.observe"]
        assert len(context_refs) == 2
        agents = {r.source_agent for r in context_refs}
        assert agents == {"extractor", "classifier"}

    def test_extract_from_context_scope_drop(self):
        """Test extracting references from context_scope drop."""
        config = {
            "name": "agent",
            "prompt": "Process",
            "context_scope": {
                "drop": ["upstream.unwanted_field"],
            },
        }
        refs = self.extractor.extract_from_agent(config)

        drop_refs = [r for r in refs if r.location == "context_scope.drop"]
        assert len(drop_refs) == 1

    def test_mixed_reference_styles_in_prompt(self):
        """Test prompt with both Jinja2 and simple reference styles."""
        config = {
            "name": "test_agent",
            "prompt": """
            Jinja2: {{ action.agent1.field }}
            Simple: {action.agent2.result}
            """,
        }
        refs = self.extractor.extract_from_agent(config)

        assert len(refs) == 2
        agents = {r.source_agent for r in refs}
        assert agents == {"agent1", "agent2"}

    def test_empty_config(self):
        """Test agent config with no references returns empty list."""
        config = {
            "name": "agent",
            "prompt": "This is plain text with no references",
        }
        refs = self.extractor.extract_from_agent(config)
        assert len(refs) == 0

    def test_no_prompt(self):
        """Test agent config without prompt."""
        config = {
            "name": "agent",
        }
        refs = self.extractor.extract_from_agent(config)
        assert len(refs) == 0

    def test_extract_from_versions_items_from(self):
        """Test extracting from versions.items_from."""
        config = {
            "name": "version_agent",
            "prompt": "Process item",
            "versions": {
                "items_from": "{{ action.data_source.items }}",
            },
        }
        refs = self.extractor.extract_from_agent(config)

        version_refs = [r for r in refs if r.location == "versions.items_from"]
        assert len(version_refs) == 1
        assert version_refs[0].source_agent == "data_source"

    def test_extract_from_conditional_clause(self):
        """Test extracting from conditional_clause."""
        config = {
            "name": "agent",
            "prompt": "Process",
            "conditional_clause": "status_checker.ready == True",
        }
        refs = self.extractor.extract_from_agent(config)

        cond_refs = [r for r in refs if r.location == "conditional_clause"]
        assert len(cond_refs) >= 1
        assert any(r.source_agent == "status_checker" for r in cond_refs)

    def test_get_referenced_agents(self):
        """Test getting unique agent names from requirements."""
        config = {
            "name": "consumer",
            "prompt": """
            {{ action.agent1.field1 }}
            {{ action.agent1.field2 }}
            {{ action.agent2.data }}
            """,
        }
        refs = self.extractor.extract_from_agent(config)
        agents = self.extractor.get_referenced_agents(refs)

        assert agents == {"agent1", "agent2"}

    def test_get_referenced_agents_excludes_special(self):
        """Test get_referenced_agents excludes special namespaces."""
        config = {
            "name": "agent",
            "prompt": "{{ action.extractor.data }}",
            "guard": "source.field > 0",  # source is special
        }
        refs = self.extractor.extract_from_agent(config)
        agents = self.extractor.get_referenced_agents(refs)

        assert "extractor" in agents
        assert "source" not in agents

    def test_extract_from_workflow(self):
        """Test extracting from entire workflow."""
        workflow_config = {
            "actions": [
                {
                    "name": "agent1",
                    "prompt": "Start",
                },
                {
                    "name": "agent2",
                    "prompt": "Use: {{ action.agent1.data }}",
                },
            ]
        }

        result = self.extractor.extract_from_workflow(workflow_config)

        assert "agent1" in result
        assert "agent2" in result
        assert len(result["agent1"]) == 0
        assert len(result["agent2"]) == 1

    def test_dict_guard(self):
        """Test extracting from dict-style guard."""
        config = {
            "name": "agent",
            "prompt": "Process",
            "guard": {
                "field": "scorer.confidence",
                "operator": ">",
                "value": 0.5,
            },
        }
        refs = self.extractor.extract_from_agent(config)

        guard_refs = [r for r in refs if "guard" in r.location]
        assert len(guard_refs) == 1
        assert guard_refs[0].source_agent == "scorer"
        assert guard_refs[0].field_path == "confidence"

    def test_direct_jinja2_pattern(self):
        """Test direct Jinja2 pattern without 'action.' prefix."""
        config = {
            "name": "agent",
            "prompt": "Data: {{ extractor.summary }}",
        }
        refs = self.extractor.extract_from_agent(config)

        assert len(refs) == 1
        assert refs[0].source_agent == "extractor"

    def test_jinja_keywords_skipped(self):
        """Test Jinja2 control keywords are not treated as agents."""
        config = {
            "name": "agent",
            "prompt": "{% if condition %}{{ action.real_agent.data }}{% endif %}",
        }
        refs = self.extractor.extract_from_agent(config)

        # Should only have reference to real_agent, not 'if'
        agent_names = {r.source_agent for r in refs}
        assert "if" not in agent_names
        assert "real_agent" in agent_names

    def test_jinja_loop_variables_skipped(self):
        """Test Jinja2 for-loop variables are not treated as external references."""
        config = {
            "name": "agent",
            "prompt": """
            {% for ref in source.referenced_in %}
            Section: {{ ref.section_name }}
            Objective: {{ ref.objective }}
            {% endfor %}

            External: {{ action.extractor.data }}
            """,
        }
        refs = self.extractor.extract_from_agent(config)

        # Should not include 'ref' as it's a loop variable
        agent_names = {r.source_agent for r in refs}
        assert "ref" not in agent_names
        # Should include 'extractor' (external reference)
        assert "extractor" in agent_names

    def test_multiple_loop_variables_skipped(self):
        """Test multiple for-loop variables are all skipped."""
        config = {
            "name": "agent",
            "prompt": """
            {% for item in items_list %}
            Item: {{ item.name }}
            {% endfor %}
            {% for resp in responsibilities %}
            Resp: {{ resp.description }}
            {% endfor %}
            Real ref: {{ action.extractor.summary }}
            """,
        }
        refs = self.extractor.extract_from_agent(config)

        agent_names = {r.source_agent for r in refs}
        # Loop variables should not be treated as external references
        assert "item" not in agent_names
        assert "resp" not in agent_names
        # Real external references should be present
        assert "extractor" in agent_names
