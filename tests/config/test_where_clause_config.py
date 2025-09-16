import pytest
import yaml
from pydantic import ValidationError
from agent_actions.core.parser.config_schema import EnhancedAgentConfig, WhereClauseConfig


class TestWhereClauseConfiguration:
    """Test WHERE clause configuration validation and schema"""

    def test_where_clause_config_validation(self):
        valid_config = WhereClauseConfig(
            clause='field == "value"',
            scope='item',
            passthrough_on_empty=True
        )
        assert valid_config.clause == 'field == "value"'
        assert valid_config.scope == 'item'
        assert valid_config.passthrough_on_empty is True

    def test_where_clause_config_defaults(self):
        config = WhereClauseConfig(clause='field == "value"')
        assert config.scope == 'item'
        assert config.passthrough_on_empty is True

    def test_invalid_scope_validation(self):
        with pytest.raises(ValidationError):
            WhereClauseConfig(clause='field == "value"', scope='invalid_scope')

    def test_enhanced_agent_config_validation(self):
        valid_config_data = {
            'agent_type': 'TestAgent',
            'model_vendor': 'openai',
            'model_name': 'gpt-3.5-turbo',
            'where_clause': {
                'clause': 'questionable != "Low Value"',
                'scope': 'item',
                'passthrough_on_empty': True
            }
        }
        config = EnhancedAgentConfig(**valid_config_data)
        assert config.where_clause.clause == 'questionable != "Low Value"'
        assert config.where_clause.scope == 'item'

    def test_backwards_compatibility_config(self):
        config_data = {
            'agent_type': 'TestAgent',
            'model_vendor': 'openai',
            'model_name': 'gpt-3.5-turbo',
            'conditional_clause': 'row_content.get("status") == "active"'
        }
        config = EnhancedAgentConfig(**config_data)
        assert config.conditional_clause == 'row_content.get("status") == "active"'
        assert config.where_clause is None

    def test_mixed_filtering_config(self):
        config_data = {
            'agent_type': 'TestAgent',
            'model_vendor': 'openai',
            'model_name': 'gpt-3.5-turbo',
            'conditional_clause': 'row_content.get("status") == "active"',
            'where_clause': {
                'clause': 'score > 50',
                'scope': 'item'
            }
        }
        config = EnhancedAgentConfig(**config_data)
        assert config.conditional_clause is not None
        assert config.where_clause is not None

    def test_yaml_config_parsing(self):
        yaml_content = """
        agents:
          - agent_type: FilterAgent
            model_vendor: openai
            model_name: gpt-3.5-turbo
            where_clause:
              clause: 'questionable != "Low Value" AND score >= 70'
              scope: item
              passthrough_on_empty: true

          - agent_type: ProcessAgent
            dependencies: [FilterAgent]
            skip_if: 'len(previous_outputs.get("FilterAgent", [])) == 0'
            where_clause:
              clause: 'metadata.quality_score > 80'
              scope: agent
        """
        config_data = yaml.safe_load(yaml_content)
        agent1_config = EnhancedAgentConfig(**config_data['agents'][0])
        assert agent1_config.where_clause.clause == 'questionable != "Low Value" AND score >= 70'
        assert agent1_config.where_clause.scope == 'item'
        agent2_config = EnhancedAgentConfig(**config_data['agents'][1])
        assert agent2_config.where_clause.scope == 'agent'

    def test_config_edge_cases(self):
        with pytest.raises(ValidationError):
            WhereClauseConfig(clause='')
        with pytest.raises(ValidationError):
            WhereClauseConfig(clause=None)
        long_clause = ' AND '.join([f'field{i} == "value{i}"' for i in range(100)])
        config = WhereClauseConfig(clause=long_clause)
        assert len(config.clause) > 1000

    def test_skip_if_validation(self):
        config_data = {
            'agent_type': 'TestAgent',
            'model_vendor': 'openai',
            'model_name': 'gpt-3.5-turbo',
            'skip_if': 'len(previous_outputs.get("ExtractionAgent", [])) == 0'
        }
        config = EnhancedAgentConfig(**config_data)
        assert config.skip_if == 'len(previous_outputs.get("ExtractionAgent", [])) == 0'


class TestConfigurationExamples:
    """Test real-world configuration examples"""

    def test_content_quality_filtering_config(self):
        config_yaml = """
        agents:
          - agent_type: QualityFilter
            model_vendor: openai
            model_name: gpt-4
            where_clause:
              clause: 'questionable NOT IN ["Low Value", "Spam"] AND metadata.word_count >= 100'
              scope: item
              passthrough_on_empty: false

          - agent_type: ContentProcessor
            dependencies: [QualityFilter]
            where_clause:
              clause: 'content IS NOT NULL AND url CONTAINS "trusted-domain.com"'
              scope: item
        """
        config_data = yaml.safe_load(config_yaml)
        for agent_data in config_data['agents']:
            config = EnhancedAgentConfig(**agent_data)
            assert config.where_clause is not None
            assert len(config.where_clause.clause) > 0

    def test_conditional_workflow_config(self):
        config_yaml = """
        agents:
          - agent_type: ExtractionAgent
            model_vendor: openai
            model_name: gpt-3.5-turbo
            where_clause:
              clause: 'page_content IS NOT NULL AND title != ""'
              scope: item

          - agent_type: SummaryAgent
            dependencies: [ExtractionAgent]
            skip_if: 'len(previous_outputs.get("ExtractionAgent", [])) < 5'

          - agent_type: AnalysisAgent
            dependencies: [ExtractionAgent]
            where_clause:
              clause: 'previous_outputs["ExtractionAgent"]["avg_quality_score"] >= 70'
              scope: agent
        """
        config_data = yaml.safe_load(config_yaml)
        extraction_config = EnhancedAgentConfig(**config_data['agents'][0])
        assert extraction_config.where_clause.scope == 'item'
        summary_config = EnhancedAgentConfig(**config_data['agents'][1])
        assert summary_config.skip_if is not None
        analysis_config = EnhancedAgentConfig(**config_data['agents'][2])
        assert analysis_config.where_clause.scope == 'agent'

    def test_migration_from_conditional_clause(self):
        old_config_yaml = """
        agents:
          - agent_type: ProcessorAgent
            model_vendor: openai
            model_name: gpt-3.5-turbo
            conditional_clause: 'row_content.get("questionable") != "Low Value"'
        """
        new_config_yaml = """
        agents:
          - agent_type: ProcessorAgent
            model_vendor: openai
            model_name: gpt-3.5-turbo
            where_clause:
              clause: 'questionable != "Low Value"'
              scope: item
              passthrough_on_empty: true
        """
        old_config = yaml.safe_load(old_config_yaml)
        new_config = yaml.safe_load(new_config_yaml)
        old_agent = EnhancedAgentConfig(**old_config['agents'][0])
        new_agent = EnhancedAgentConfig(**new_config['agents'][0])
        assert old_agent.conditional_clause is not None
        assert new_agent.where_clause is not None
        assert new_agent.where_clause.scope == 'item'
