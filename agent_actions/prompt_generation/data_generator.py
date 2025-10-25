"""Module for generating data using agents."""
from typing import Dict, Any, List, Optional, Tuple
from agent_actions.response_processing.config_types import AgentEntryDict
from agent_actions.prompt_generation.prompt_handler import PromptLoader
from agent_actions.preprocessing.prompt_utils import PromptUtils
from agent_actions.utilities.constants import PROMPT_KEY
from agent_actions.preprocessing.sample_enricher import SampleEnricher
from agent_actions.utilities.utils_processor_helpers import apply_drops, run_dynamic_agent
from agent_actions.configuration.interfaces import IGenerator, ProcessingMode
from agent_actions.orchestration.dependency_injection import registry

@registry.register_generator('data_generator')
class DataGenerator(IGenerator):
    """Handles agent creation and data generation (Single Responsibility)."""

    def __init__(self, agent_config: AgentEntryDict, agent_name: str, dependency_configs: Optional[Dict[str, AgentEntryDict]]=None):
        """
        Initialize the data generator.

        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
            dependency_configs: Optional dict mapping dependency names to their configs.
                              Used to build namespaced field_context for {agent.field} references.
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.dependency_configs = dependency_configs or {}

    def supports_async(self) -> bool:
        """Return True as this generator supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def create_agent_with_data(self, contents: Any, source_content: Optional[Any]=None, loop_context: Optional[Dict]=None, workflow_metadata: Optional[Dict]=None) -> Tuple[List[Dict], bool]:
        """
        Create an agent with the provided data and generate results.
        
        Args:
            contents: Content to process
            source_content: Optional source content for prompt formatting
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references

        Returns:
            Tuple containing the generated data and a flag indicating if the
            agent was executed
            
        Raises:
            RuntimeError: If agent creation or data generation fails
        """
        try:
            formatted_prompt, contents = self._format_prompt(contents, source_content, loop_context, workflow_metadata)
            formatted_prompt = SampleEnricher.append_few_shot_samples(formatted_prompt, self.agent_config, self.agent_name)
            tool_args = self.agent_config.get('tool_args', {})
            response, executed = run_dynamic_agent(self.agent_config, self.agent_name, contents, formatted_prompt, tools_path=self.agent_config.get('tools', {}).get('path'), tool_args=tool_args, source_content=source_content)
            return (response, executed)
        except Exception as e:
            from agent_actions.shared.exceptions import GenerationError
            raise GenerationError(f'Failed to create agent with data: {str(e)}', cause=e)

    def _apply_drops(self, contents: Dict) -> Dict:
        """
        Apply drops transformation to contents.

        Args:
            contents: Content to transform

        Returns:
            Transformed content
        """
        return apply_drops(contents, self.agent_config)

    def _build_namespaced_field_context(self, contents: Dict, source_content: Optional[Any]=None, loop_context: Optional[Dict]=None, workflow_metadata: Optional[Dict]=None) -> Dict:
        """
        Build field context with agent namespaces from flat contents.

        Uses dependency output signatures to reconstruct which fields belong to which agent.
        Data remains flat in the pipeline; namespacing is only for field_context.

        Args:
            contents: Flat dict containing all fields from dependencies
            source_content: Optional source content for {source.field} references
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references

        Returns:
            Namespaced field_context dict for replace_field_references()

        Example:
            Input contents (flat):
                {'bloom_details': '...', 'cluster_id': '...', 'page_content': '...'}

            Output field_context (namespaced):
                {
                    'source': {...},
                    'create_new_clusters': {
                        'bloom_details': '...',
                        'cluster_id': '...',
                        'page_content': '...'
                    },
                    'loop': {...},
                    'workflow': {...}
                }
        """
        from agent_actions.validation.llm_context_utils import LLMContextUtils
        field_context = {}
        if source_content:
            field_context['source'] = source_content
        dependencies = self.agent_config.get('dependencies', [])
        for dep_name in dependencies:
            dep_config = self.dependency_configs.get(dep_name)
            if not dep_config:
                continue
            dep_output_fields = LLMContextUtils.compute_llm_context(dep_config)
            dep_fields = {}
            for field in dep_output_fields:
                if field in contents:
                    dep_fields[field] = contents[field]
            if dep_fields:
                field_context[dep_name] = dep_fields
        if loop_context:
            field_context['loop'] = loop_context
        if workflow_metadata:
            field_context['workflow'] = workflow_metadata
        return field_context

    def _format_prompt(self, contents: Dict, source_content: Optional[Any]=None, loop_context: Optional[Dict]=None, workflow_metadata: Optional[Dict]=None) -> Tuple[str, Dict]:
        """
        Format the prompt using {reference.field} pattern.

        Args:
            contents: Content for prompt formatting
            source_content: Optional source content for prompt formatting
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references

        Returns:
            Tuple of the formatted prompt and contents (unchanged)
        """
        raw_prompt = self.agent_config.get(PROMPT_KEY, '')
        if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
            raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
        if not raw_prompt:
            raw_prompt = 'Process the following content: {content}'
        field_context = self._build_namespaced_field_context(contents if isinstance(contents, dict) else {}, source_content, loop_context, workflow_metadata)
        if field_context:
            formatted_prompt = PromptUtils.replace_field_references(raw_prompt, field_context)
        else:
            formatted_prompt = raw_prompt
        return (formatted_prompt, contents)