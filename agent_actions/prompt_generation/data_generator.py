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

    def __init__(self, agent_config: AgentEntryDict, agent_name: str, dependency_configs: Optional[Dict[str, AgentEntryDict]]=None, agent_indices: Optional[Dict[str, int]]=None):
        """
        Initialize the data generator.

        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
            dependency_configs: Optional dict mapping dependency names to their configs.
                              Used to build namespaced field_context for {agent.field} references.
            agent_indices: Optional dict mapping agent names to their node indices.
                         Used for loading historical node data via {action_name.field} references.
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.dependency_configs = dependency_configs or {}
        self.agent_indices = agent_indices or {}

    def supports_async(self) -> bool:
        """Return True as this generator supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def create_agent_with_data(self, contents: Any, source_content: Optional[Any]=None, loop_context: Optional[Dict]=None, workflow_metadata: Optional[Dict]=None, current_item: Optional[Dict]=None, file_path: Optional[str]=None) -> Tuple[List[Dict], bool]:
        """
        Create an agent with the provided data and generate results.

        Args:
            contents: Content to process
            source_content: Optional source content for prompt formatting
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references
            current_item: Optional current item dict containing lineage and source_guid for historical node loading
            file_path: Optional file path for constructing historical node paths

        Returns:
            Tuple containing the generated data and a flag indicating if the
            agent was executed

        Raises:
            RuntimeError: If agent creation or data generation fails
        """
        try:
            formatted_prompt, contents, llm_context, passthrough_fields = self._format_prompt(contents, source_content, loop_context, workflow_metadata, current_item, file_path)
            formatted_prompt = SampleEnricher.append_few_shot_samples(formatted_prompt, self.agent_config, self.agent_name)
            tool_args = self.agent_config.get('tool_args', {})
            # Note: passthrough_fields not passed here - handled later in transform_with_observe()
            response, executed = run_dynamic_agent(self.agent_config, self.agent_name, contents, formatted_prompt, tools_path=self.agent_config.get('tools', {}).get('path'), tool_args=tool_args, source_content=source_content, llm_additional_context=llm_context)
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

    def _build_namespaced_field_context(self, contents: Dict, source_content: Optional[Any]=None, loop_context: Optional[Dict]=None, workflow_metadata: Optional[Dict]=None, current_item: Optional[Dict]=None, file_path: Optional[str]=None) -> Dict:
        """
        Build field context with agent namespaces from flat contents.

        Automatically loads ALL previous actions from lineage, making them available
        for field references. No manual dependencies declaration needed.

        Args:
            contents: Flat dict containing all fields from dependencies
            source_content: Optional source content for {source.field} references
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references
            current_item: Optional current item dict containing lineage and source_guid
            file_path: Optional file path for constructing historical node paths

        Returns:
            Namespaced field_context dict for replace_field_references()

        Example:
            Input contents (flat):
                {'bloom_details': '...', 'cluster_id': '...', 'page_content': '...'}

            Output field_context (namespaced):
                {
                    'source': {...},
                    'fact_extractor': {...},        # Auto-loaded from lineage
                    'flatten_facts': {...},         # Auto-loaded from lineage
                    'cluster_list': {...},          # Auto-loaded from lineage
                    'combine_by_cluster': {...},    # Auto-loaded from lineage
                    'loop': {...},
                    'workflow': {...}
                }
        """
        from agent_actions.validation.llm_context_utils import LLMContextUtils
        from agent_actions.preprocessing.historical_node_loader import HistoricalNodeDataLoader

        field_context = {}

        # Add source content
        if source_content:
            field_context['source'] = source_content

        # Auto-load ALL previous actions from lineage
        if current_item and file_path and self.agent_indices:
            lineage = current_item.get('lineage', [])
            source_guid = current_item.get('source_guid')
            current_idx = self.agent_indices.get(self.agent_name, 999)

            if lineage and source_guid:
                # Iterate through ALL agents in agent_indices
                for action_name, action_idx in self.agent_indices.items():
                    # Only load actions that come BEFORE the current agent
                    if action_idx >= current_idx:
                        continue

                    # Load historical data for this action
                    historical_data = HistoricalNodeDataLoader.load_historical_node_data(
                        action_name=action_name,
                        lineage=lineage,
                        source_guid=source_guid,
                        file_path=file_path,
                        agent_indices=self.agent_indices
                    )

                    if historical_data:
                        field_context[action_name] = historical_data

        # Fallback: Also check declared dependencies for flat contents
        # (Backward compatibility for immediate predecessor data in contents)
        dependencies = self.agent_config.get('dependencies', [])
        for dep_name in dependencies:
            # Skip if already loaded from historical data
            if dep_name in field_context:
                continue

            dep_config = self.dependency_configs.get(dep_name)
            if not dep_config:
                continue

            # Load from flat contents (immediate predecessor)
            dep_output_fields = LLMContextUtils.compute_llm_context(dep_config)
            dep_fields = {}
            for field in dep_output_fields:
                if field in contents:
                    dep_fields[field] = contents[field]

            if dep_fields:
                field_context[dep_name] = dep_fields

        # Add loop and workflow contexts
        if loop_context:
            field_context['loop'] = loop_context
        if workflow_metadata:
            field_context['workflow'] = workflow_metadata

        return field_context

    def _format_prompt(self, contents: Dict, source_content: Optional[Any]=None, loop_context: Optional[Dict]=None, workflow_metadata: Optional[Dict]=None, current_item: Optional[Dict]=None, file_path: Optional[str]=None) -> Tuple[str, Dict, Dict, Dict]:
        """
        Format the prompt using {reference.field} pattern.

        Args:
            contents: Content for prompt formatting
            source_content: Optional source content for prompt formatting
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references
            current_item: Optional current item dict containing lineage and source_guid
            file_path: Optional file path for constructing historical node paths

        Returns:
            Tuple of:
            - formatted_prompt: Rendered prompt string
            - contents: Original contents (unchanged)
            - llm_context: Fields for LLM additional context (from context_scope.include)
            - passthrough_fields: Fields to merge into output (from context_scope.passthrough)
        """
        raw_prompt = self.agent_config.get(PROMPT_KEY, '')
        if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
            raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
        if not raw_prompt:
            raw_prompt = 'Process the following content: {content}'
        field_context = self._build_namespaced_field_context(
            contents if isinstance(contents, dict) else {},
            source_content,
            loop_context,
            workflow_metadata,
            current_item,
            file_path
        )

        # Apply context_scope if configured
        context_scope = self.agent_config.get('context_scope', {})
        if context_scope:
            from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
            print(f"\n[DEBUG _format_prompt] Applying context_scope for {self.agent_name}")
            print(f"  context_scope config: {context_scope}")
            print(f"  field_context keys: {list(field_context.keys())}")

            prompt_context, llm_context, passthrough_fields = ContextScopeProcessor.apply_context_scope(
                field_context, context_scope
            )

            print(f"  AFTER apply_context_scope:")
            print(f"    llm_context keys: {list(llm_context.keys())}")
            print(f"    llm_context has data: {bool(llm_context)}")
        else:
            # No context_scope: use field_context as-is for backward compatibility
            prompt_context = field_context
            llm_context = {}
            passthrough_fields = {}

        # Render prompt with prompt_context (may have fields removed by include/exclude/passthrough)
        if prompt_context:
            formatted_prompt = PromptUtils.replace_field_references(raw_prompt, prompt_context)
        else:
            formatted_prompt = raw_prompt
        return (formatted_prompt, contents, llm_context, passthrough_fields)