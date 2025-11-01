import json
import sys
import logging
from pathlib import Path
import yaml
from typing import Optional, Dict, Any, List, Set
from agent_actions.llm_invocation.realtime.agent_handlers import AgentManager
from agent_actions.llm_invocation.batch.loaders_batch_data_loader import BatchDataLoader
from agent_actions.prompt_generation.prompt_handler import PromptLoader
from agent_actions.preprocessing.prompt_utils import PromptUtils
from agent_actions.llm_invocation.realtime.file_writer import FileWriter
from agent_actions.preprocessing.data_transformer import DataTransformer
from agent_actions.utilities.constants import PROMPT_KEY, JSON_MODE_KEY
from agent_actions.utilities.tooling import execute_user_defined_function
from agent_actions.response_processing.where_parser import get_global_filter
from agent_actions.utilities.utils_path_utils import ensure_directory_exists, create_side_output_directory, resolve_absolute_path
from agent_actions.utilities.utils_processor_utils import ProcessorUtils
from agent_actions.response_processing.where_parser import WhereClauseParser
from agent_actions.orchestration.dependency_injection import registry
from agent_actions.llm_invocation.realtime.providers.base import BatchProvider, BatchResult
from agent_actions.llm_invocation.realtime.providers.factory import BatchProviderFactory
logger = logging.getLogger(__name__)

@registry.register_service('batch_service')
class BatchService:
    """
    Service for managing batch processing operations with validation and retry.

    Configuration:
    -------------
    Users can configure batch retry behavior via action config:

    ```yaml
    actions:
      - name: process_data
        model: gpt-4o-mini
        vendor: openai
        run_mode: batch
        batch_retry:
          max_retry_depth: 2  # Optional, default 2 (total 3 attempts per record)
    ```

    **max_retry_depth**: Maximum number of retry attempts for failed records
    - Default: 2 (total 3 attempts: initial + 2 retries)
    - Range: 0-10 (0 disables automatic retry)
    - Records exceeding max depth are written to Dead Letter Queue (DLQ)

    Example workflow:
    1. Submit batch with 100 records
    2. 95 succeed, 5 fail → Automatic retry batch created (attempt 1/3)
    3. 4 succeed on retry, 1 fails → Second retry batch created (attempt 2/3)
    4. If max_retry_depth exceeded → Record written to DLQ file

    Audit files:
    - `{batch_name}_retry_manifest.json`: Complete audit trail
    - `dead_letter_queue.jsonl`: Permanently failed records
    """

    def _create_passthrough_data(self, data, agent_config, output_directory):
        """
        Create passthrough data structure when no batch tasks are submitted.
        This preserves all original data with appropriate metadata.
        """
        node_idx = None
        if output_directory:
            import re
            match = re.search('node_(\\d+)_(\\w+)', str(output_directory))
            if match:
                node_idx = int(match.group(1))
        processed_data = []
        for row in data:
            target_id = row.get('target_id')
            if not target_id:
                target_id = ProcessorUtils.generate_target_id()
                row['target_id'] = target_id
            passthrough_item = row.copy()
            original_source_guid = row.get('source_guid', target_id)
            if 'target_id' not in passthrough_item or not passthrough_item['target_id']:
                passthrough_item['target_id'] = target_id
            if 'source_guid' not in passthrough_item or not passthrough_item['source_guid']:
                passthrough_item['source_guid'] = original_source_guid
            if node_idx is not None:
                item_node_id = ProcessorUtils.generate_node_id(node_idx)
                passthrough_item['node_id'] = item_node_id
                passthrough_item['lineage'] = ProcessorUtils.build_lineage(row, item_node_id)
            passthrough_item['metadata'] = {'skipped_by_conditional': True, 'agent_type': 'passthrough', 'reason': 'conditional_clause_failed'}
            processed_data.append(passthrough_item)
        return {'type': 'passthrough', 'data': processed_data, 'output_directory': output_directory}

    def _create_passthrough_data_from_context(self, agent_config, output_directory):
        """
        Create passthrough data from context map, respecting filter statuses.
        Only items marked as 'skipped' will be included as passthrough.
        """
        node_idx = None
        if output_directory:
            import re
            match = re.search('node_(\\d+)_(\\w+)', str(output_directory))
            if match:
                node_idx = int(match.group(1))
        processed_data = []
        for custom_id, original_row in self.context_map.items():
            filter_status = original_row.get('_batch_filter_status', 'included')
            if filter_status == 'skipped':
                target_id = original_row.get('target_id', custom_id)
                original_source_guid = original_row.get('source_guid', target_id)
                passthrough_item = original_row.copy()
                passthrough_item.pop('_batch_filter_status', None)
                if 'target_id' not in passthrough_item or not passthrough_item['target_id']:
                    passthrough_item['target_id'] = target_id
                if 'source_guid' not in passthrough_item or not passthrough_item['source_guid']:
                    passthrough_item['source_guid'] = original_source_guid
                if node_idx is not None:
                    item_node_id = ProcessorUtils.generate_node_id(node_idx)
                    passthrough_item['node_id'] = item_node_id
                    passthrough_item['lineage'] = ProcessorUtils.build_lineage(original_row, item_node_id)
                passthrough_item['metadata'] = {'skipped_by_where_clause': True, 'agent_type': 'passthrough', 'reason': 'where_clause_not_matched'}
                processed_data.append(passthrough_item)
        return {'type': 'passthrough', 'data': processed_data, 'output_directory': output_directory}

    def _save_task_source(self, src_text, file_path, base_directory, output_directory):
        """
        Save or merge a single task's source data into the appropriate file in the source directory.
        src_text: dict, e.g. {guid: row}
        file_path: str or Path to the original file
        base_directory: str or Path to the base directory
        output_directory: str or Path to the output directory (for structure)
        """
        from pathlib import Path
        import json
        relative_path = Path(file_path).relative_to(base_directory)
        base_path = Path(base_directory).parent
        source_path = base_path / 'source'
        output_src_path = source_path / relative_path.with_suffix('.json')
        ensure_directory_exists(output_src_path, is_file=True)
        if output_src_path.exists():
            with open(output_src_path, 'r') as existing_file:
                try:
                    existing_source = json.load(existing_file)
                except Exception:
                    existing_source = []
            task_guid = list(src_text.keys())[0]
            if task_guid not in [list(item.keys())[0] for item in existing_source]:
                existing_source.append(src_text)
                with open(output_src_path, 'w') as f:
                    json.dump(existing_source, f, indent=2)
        else:
            with open(output_src_path, 'w') as f:
                json.dump([src_text], f, indent=2)
    force_batch = False
    _MAX_RETRY_DEPTH = 2

    def __init__(self, provider: Optional[BatchProvider]=None, agent_indices: Optional[Dict[str, int]]=None, dependency_configs: Optional[Dict[str, Dict]]=None):
        """
        Initialize batch service.

        Args:
            provider: Optional batch provider instance
            agent_indices: Dict mapping agent names to node indices (for historical data loading)
            dependency_configs: Dict mapping dependency names to their configs (for field context)
        """
        self.data_loader = BatchDataLoader()
        self.provider = provider
        self.context_map = {}
        self._provider_cache = {}
        self.where_parser = WhereClauseParser()
        self.agent_indices = agent_indices or {}
        self.dependency_configs = dependency_configs or {}

    def _get_provider_for_config(self, agent_config: Dict[str, Any]) -> BatchProvider:
        """
        Get the appropriate provider based on agent configuration.

        Args:
            agent_config: Agent configuration dictionary (must be resolved via hierarchy)

        Returns:
            BatchProvider instance for the specified provider type
        """
        required_fields = ['model_vendor', 'model_name', 'api_key']
        missing = [f for f in required_fields if not agent_config.get(f)]
        if missing:
            from agent_actions.shared.exceptions import ConfigurationError
            raise ConfigurationError(f"Batch service received incomplete config (missing: {', '.join(missing)})", context={'missing_fields': missing, 'agent_type': agent_config.get('agent_type', 'unknown'), 'hint': 'Caller must resolve config hierarchy (project → workflow → action) before calling batch service'})
        provider_type = agent_config.get('model_vendor')
        if not provider_type:
            from agent_actions.shared.exceptions import ConfigValidationError
            raise ConfigValidationError('model_vendor', "Missing required field 'model_vendor' for batch processing. Specify the LLM provider (e.g., openai, anthropic, gemini).")
        provider_type = provider_type.lower()
        if provider_type == 'tool':
            from agent_actions.shared.exceptions import ConfigurationError
            raise ConfigurationError("'tool' vendor does not support batch processing", context={'provider_type': provider_type, 'supported_vendors': ['openai', 'gemini', 'anthropic']})
        if provider_type in self._provider_cache:
            return self._provider_cache[provider_type]
        try:
            provider_config = {}
            if provider_type == 'gemini' and agent_config.get('google_api_key'):
                provider_config['api_key'] = agent_config['google_api_key']
            elif provider_type == 'openai' and agent_config.get('openai_api_key'):
                provider_config['api_key'] = agent_config['openai_api_key']
            provider = BatchProviderFactory.create_provider(provider_type, provider_config)
            is_valid, error_msg = provider.validate_config(agent_config)
            if not is_valid:
                from agent_actions.shared.exceptions import ConfigurationError
                raise ConfigurationError('Provider configuration validation failed', context={'provider_type': provider_type, 'error_message': error_msg})
            self._provider_cache[provider_type] = provider
            return provider
        except Exception as e:
            from agent_actions.shared.exceptions import ConfigurationError
            raise ConfigurationError(f'Failed to create provider for batch_provider_{provider_type}: {e}', context={'provider_type': provider_type}, cause=e)

    def _load_retry_config(self, agent_config: Optional[Dict[str, Any]]) -> int:
        """
        Load retry configuration from agent config.

        Allows users to configure max retry depth via agent_config:
        {
            "batch_retry": {
                "max_retry_depth": 2  # Default: 2 (total 3 attempts)
            }
        }

        Args:
            agent_config: Agent configuration dict

        Returns:
            max_retry_depth (int): Maximum retry attempts (0-10)
        """
        max_retry_depth = self._MAX_RETRY_DEPTH
        if not agent_config:
            return max_retry_depth
        batch_retry_config = agent_config.get('batch_retry', {})
        if 'max_retry_depth' in batch_retry_config:
            depth = batch_retry_config['max_retry_depth']
            if isinstance(depth, int) and 0 <= depth <= 10:
                max_retry_depth = depth
            else:
                print(f'[WARN] Invalid max_retry_depth: {depth}. Must be integer 0-10. Using default {self._MAX_RETRY_DEPTH}')
        return max_retry_depth

    @staticmethod
    def _separate_side_output(items):
        """Split processed items into main and side output collections."""
        main_output, side_output = ([], [])
        for item in items:
            content = item.get('content', {})
            if isinstance(content, dict) and content.get('side_output', False):
                side_output.append(item)
            else:
                main_output.append(item)
        return (main_output, side_output)

    @staticmethod
    def _save_side_output(data, file_path):
        """Persist side output data, merging with existing content if present."""
        ensure_directory_exists(file_path, is_file=True)
        existing = []
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError:
                    existing = []
        if not isinstance(existing, list):
            existing = [existing]
        if not isinstance(data, list):
            data = [data]
        existing.extend(data)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=4)

    def _resolve_tools_path(self, agent_config):
        path = agent_config.get('tools', {}).get('path')
        if path:
            return str(resolve_absolute_path(path))
        project_root = AgentManager.find_project_root(Path.cwd())
        if not project_root:
            return None
        config_file = project_root / 'agent_actions.yml'
        if not config_file.exists():
            return None
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                default_cfg = yaml.safe_load(f)
            tool_path = default_cfg.get('tool_path')
            if isinstance(tool_path, list):
                return str(resolve_absolute_path(project_root / tool_path[0])) if tool_path else None
            if tool_path:
                return str(resolve_absolute_path(project_root / tool_path))
        except Exception:
            return None
        return None

    def _prepare_schema(self, agent_config, provider=None):
        """
        Load and prepare schema from config.

        Uses the unified prepare_schema_unified() function to ensure consistent
        schema handling across online and batch modes.
        """
        from agent_actions.response_processing.schema_change import prepare_schema_unified
        from agent_actions.utilities.constants import MODEL_VENDOR_KEY
        if provider is None:
            provider = self.provider
        vendor = agent_config.get(MODEL_VENDOR_KEY, '').lower()
        if not vendor:
            vendor = type(provider).__name__.replace('BatchProvider', '').lower()
        return prepare_schema_unified(agent_config, vendor)

    def prepare_batch_tasks_from_data(self, agent_config, data, output_directory=None, batch_name=None):
        provider = self._get_provider_for_config(agent_config)
        schema = self._prepare_schema(agent_config, provider)
        json_mode = agent_config.get(JSON_MODE_KEY, True)
        if not schema and json_mode:
            from agent_actions.shared.exceptions import ConfigurationError
            raise ConfigurationError('Schema is required for batch processing when json_mode is enabled', context={'agent_config': agent_config.get('agent_type', 'unknown'), 'json_mode': json_mode, 'hint': 'Either provide a schema or set json_mode: false'})
        raw_prompt = agent_config.get(PROMPT_KEY, '')
        if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
            raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
        if not raw_prompt:
            raw_prompt = 'Process the following content: {content}'
        tools_path = self._resolve_tools_path(agent_config)
        if tools_path and tools_path not in sys.path:
            sys.path.insert(0, tools_path)
        self.context_map = {}
        conditional_clause = agent_config.get('conditional_clause', '')
        where_clause_config = agent_config.get('where_clause')
        if where_clause_config:
            scope = where_clause_config.get('scope', 'item')
            if scope != 'item':
                where_clause_config = None
        prepared_data = []
        for row in data:
            custom_id = row.get('target_id')
            if not custom_id:
                custom_id = ProcessorUtils.generate_target_id()
                row['target_id'] = custom_id
            row_with_meta = row.copy()
            row_with_meta['_batch_filter_status'] = 'included'
            self.context_map[custom_id] = row_with_meta
            if 'source_guid' in row and 'content' in row:
                row_content = row['content']
            else:
                row_content = row
            where_clause_config = agent_config.get('where_clause')
            should_skip = False
            if where_clause_config and where_clause_config.get('scope') == 'item':
                behavior = where_clause_config.get('behavior', 'filter')
                if behavior == 'filter':
                    try:
                        filter_service = get_global_filter()
                        logger.info(f"WHERE clause filtering: '{where_clause_config['clause']}'")
                        logger.info(f"Row content keys: {(list(row_content.keys()) if isinstance(row_content, dict) else 'Not a dict')}")
                        if isinstance(row_content, dict) and 'questionable' in row_content:
                            logger.info(f"Row questionable value: {row_content['questionable']}")
                        filter_result = filter_service.filter_item(row_content, where_clause_config['clause'])
                        if hasattr(filter_result, 'success'):
                            logger.info(f'Filter result - success: {filter_result.success}, matched: {filter_result.matched}')
                            if filter_result.error:
                                logger.warning(f'Filter error: {filter_result.error}')
                            if not filter_result.success:
                                passthrough_on_error = where_clause_config.get('passthrough_on_error', True)
                                if not passthrough_on_error:
                                    should_skip = True
                                    if custom_id in self.context_map:
                                        self.context_map[custom_id]['_batch_filter_status'] = 'filtered'
                                    logger.info('Filtering item due to filter error and passthrough_on_error=False')
                            elif not filter_result.matched:
                                should_skip = True
                                if custom_id in self.context_map:
                                    self.context_map[custom_id]['_batch_filter_status'] = 'filtered'
                                logger.info(f'Filtering item - WHERE clause not matched')
                        else:
                            matched = bool(filter_result)
                            logger.info(f'Filter result (boolean): {matched}')
                            if not matched:
                                should_skip = True
                                if custom_id in self.context_map:
                                    self.context_map[custom_id]['_batch_filter_status'] = 'filtered'
                                logger.info(f'Filtering item - WHERE clause not matched (boolean result)')
                    except Exception as e:
                        logger.warning(f'Error in WHERE clause evaluation: {e}')
                        passthrough_on_error = where_clause_config.get('passthrough_on_error', True)
                        if not passthrough_on_error:
                            should_skip = True
                            if custom_id in self.context_map:
                                self.context_map[custom_id]['_batch_filter_status'] = 'filtered'
                elif behavior == 'skip':
                    try:
                        filter_service = get_global_filter()
                        logger.info(f"WHERE clause skipping: '{where_clause_config['clause']}'")
                        logger.info(f"Row content keys: {(list(row_content.keys()) if isinstance(row_content, dict) else 'Not a dict')}")
                        if isinstance(row_content, dict) and 'questionable' in row_content:
                            logger.info(f"Row questionable value: {row_content['questionable']}")
                        filter_result = filter_service.filter_item(row_content, where_clause_config['clause'])
                        if hasattr(filter_result, 'success'):
                            logger.info(f'Skip filter result - success: {filter_result.success}, matched: {filter_result.matched}')
                            if filter_result.error:
                                logger.warning(f'Skip filter error: {filter_result.error}')
                            if not filter_result.success:
                                passthrough_on_error = where_clause_config.get('passthrough_on_error', True)
                                if not passthrough_on_error:
                                    should_skip = True
                                    if custom_id in self.context_map:
                                        self.context_map[custom_id]['_batch_filter_status'] = 'skipped'
                                    logger.info('Skipping item due to filter error and passthrough_on_error=False')
                            elif not filter_result.matched:
                                should_skip = True
                                if custom_id in self.context_map:
                                    self.context_map[custom_id]['_batch_filter_status'] = 'skipped'
                                logger.info(f'Skipping item - WHERE clause not matched')
                        else:
                            matched = bool(filter_result)
                            logger.info(f'Skip filter result (boolean): {matched}')
                            if not matched:
                                should_skip = True
                                if custom_id in self.context_map:
                                    self.context_map[custom_id]['_batch_filter_status'] = 'skipped'
                                logger.info(f'Skipping item - WHERE clause not matched (boolean result)')
                    except Exception as e:
                        logger.warning(f'Error in WHERE clause evaluation: {e}')
                        passthrough_on_error = where_clause_config.get('passthrough_on_error', True)
                        if not passthrough_on_error:
                            should_skip = True
                            if custom_id in self.context_map:
                                self.context_map[custom_id]['_batch_filter_status'] = 'skipped'
            elif conditional_clause and (not execute_user_defined_function(conditional_clause, row_content)):
                should_skip = True
                if custom_id in self.context_map:
                    self.context_map[custom_id]['_batch_filter_status'] = 'skipped'
            if should_skip:
                continue

            # Build field context with historical data (same as online mode)
            from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
            agent_name = agent_config.get('agent_type', agent_config.get('name', 'unknown'))

            # Build namespaced field context with historical node loading
            # In batch mode, construct a file path from output_directory + batch_name
            # output_directory is like: .../target/node_4_Cluster_Validation_Agent
            # batch_name is like: Designing_and_Implementing_a_Data_Science_Solution_on_Azure.json
            # We need: .../target/node_4_Cluster_Validation_Agent/Designing_and_Implementing_a_Data_Science_Solution_on_Azure.json
            file_path_for_history = None
            if output_directory and batch_name:
                from pathlib import Path
                file_path_for_history = str(Path(output_directory) / batch_name)

            field_context = ContextScopeProcessor.build_field_context_with_history(
                contents=row_content if isinstance(row_content, dict) else {},
                agent_name=agent_name,
                agent_config=agent_config,
                agent_indices=self.agent_indices,
                dependency_configs=self.dependency_configs,
                source_content=row_content,  # Source is the current row in batch mode
                current_item=self.context_map.get(custom_id),
                file_path=file_path_for_history
            )

            # Apply context_scope to split field_context into prompt/llm/passthrough contexts
            context_scope = agent_config.get('context_scope', {})
            if context_scope:
                prompt_context, llm_context, passthrough_fields = ContextScopeProcessor.apply_context_scope(
                    field_context, context_scope
                )

                # Store passthrough_fields for later merging into results
                if passthrough_fields and custom_id in self.context_map:
                    self.context_map[custom_id]['_passthrough_fields'] = passthrough_fields
            else:
                prompt_context = field_context
                llm_context = {}

            # Build LLM context: start with current row, then add included fields
            # Start with current row content (source in batch mode)
            llm_full_context = row_content.copy() if isinstance(row_content, dict) else {}

            # Remove dropped fields (they were removed from prompt_context['source'])
            if context_scope and context_scope.get('drop'):
                for field_ref in context_scope.get('drop', []):
                    try:
                        _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                        llm_full_context.pop(field_name, None)
                    except ValueError:
                        continue

            # Add observed fields from llm_context (fields from previous actions)
            if llm_context:
                llm_full_context.update(llm_context)

            # Render prompt with prompt_context (fields not dropped)
            formatted_prompt = PromptUtils.replace_field_references(raw_prompt, prompt_context)
            # Use llm_full_context for LLM (includes fields from context_scope.observe)
            formatted_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
                formatted_prompt, tools_path, json.dumps(llm_full_context, ensure_ascii=False), agent_config=agent_config
            )
            cleaned_row = llm_full_context
            prepared_item = {'target_id': custom_id, 'content': cleaned_row, 'prompt': formatted_prompt}
            prepared_data.append(prepared_item)
        provider_config = agent_config.copy()
        provider_config['compiled_schema'] = schema
        tasks = provider.prepare_tasks(prepared_data, provider_config)
        return tasks

    def submit_batch_job_from_data(self, agent_config, batch_name, data, output_directory=None, force=False):
        force_submission = force or BatchService.force_batch
        if not force_submission:
            existing_batch_id = self._check_for_existing_batch_job(output_directory, batch_name)
            if existing_batch_id:
                print(f'Found existing in-flight batch job for {batch_name}: {existing_batch_id}')
                print('Skipping new batch submission. Use --batch_continue to process completed batches.')
                return existing_batch_id
        tasks = self.prepare_batch_tasks_from_data(agent_config, data, output_directory, batch_name)
        if not tasks:
            print('No batch tasks to submit. All items filtered out by WHERE clause or conditional clause.')
            where_clause_config = agent_config.get('where_clause')
            if where_clause_config:
                behavior = where_clause_config.get('behavior', 'filter')
                if behavior == 'filter':
                    print('Filter behavior detected - returning empty result set.')
                    return {'type': 'passthrough', 'data': [], 'output_directory': output_directory}
                elif behavior == 'skip':
                    print('Skip behavior detected - returning skipped items as passthrough.')
                    return self._create_passthrough_data_from_context(agent_config, output_directory)
                else:
                    return self._create_passthrough_data(data, agent_config, output_directory)
            else:
                return self._create_passthrough_data(data, agent_config, output_directory)
        self._save_context_map(self.context_map, agent_config, output_directory, batch_name)
        try:
            provider = self._get_provider_for_config(agent_config)
            provider_type = agent_config.get('model_vendor')
            if not provider_type:
                from agent_actions.shared.exceptions import ConfigValidationError
                raise ConfigValidationError('model_vendor', "Missing required field 'model_vendor' for batch processing.")
            provider_type = provider_type.lower()
            batch_id = provider.submit_batch(tasks, batch_name, output_directory)
            self._save_batch_job_id(batch_id=batch_id, output_directory=output_directory, file_name=batch_name, provider_type=provider_type, record_count=len(tasks))
            return batch_id
        except Exception as e:
            from agent_actions.shared.exceptions import ExternalServiceError
            raise ExternalServiceError(provider_type, f'Failed to submit batch job: {e}', cause=e)

    def _save_batch_job_id(self, batch_id: str, output_directory: str=None, file_name: str=None, provider_type: str=None, parent_batch_id: Optional[str]=None, retry_attempt: int=0, record_count: Optional[int]=None, retry_for_records: Optional[List[str]]=None):
        """
        Save batch job ID to batch registry with parent tracking for retries.

        Args:
            batch_id: The batch job ID to save
            output_directory: Output directory for the batch registry
            file_name: Name of the file being processed
            provider_type: Type of provider (openai, gemini, etc.)
            parent_batch_id: ID of the parent batch (for retry batches)
            retry_attempt: Current retry attempt number (0 = original, 1 = first retry, etc.)
            record_count: Number of tasks submitted in this batch (for validation)
            retry_for_records: List of custom_ids being retried (for retry batches only)
        """
        if output_directory:
            local_batch_dir = Path(output_directory) / 'batch'
            ensure_directory_exists(local_batch_dir)
            registry_file = local_batch_dir / '.batch_registry.json'
            registry = {}
            if registry_file.exists():
                try:
                    with open(registry_file, 'r') as f:
                        registry = json.load(f)
                except json.JSONDecodeError:
                    registry = {}
            from datetime import datetime
            registry_entry = {'batch_id': batch_id, 'status': 'submitted', 'timestamp': datetime.now().isoformat(), 'provider': provider_type, 'parent_batch_id': parent_batch_id, 'retry_attempt': retry_attempt, 'has_retry_batch': False}
            if record_count is not None:
                registry_entry['record_count'] = record_count
            if retry_for_records is not None:
                registry_entry['retry_for_records'] = retry_for_records
            registry[file_name or 'default'] = registry_entry
            with open(registry_file, 'w') as f:
                json.dump(registry, f, indent=2)

    def _save_context_map(self, context_map: dict, agent_config: dict, output_directory: str, batch_name: str):
        """Persist original context data for batch processing."""
        if output_directory:
            batch_dir = Path(output_directory) / 'batch'
        else:
            batch_dir = Path.cwd() / 'batch'
        ensure_directory_exists(batch_dir)
        path = batch_dir / f'{Path(batch_name).stem}_context_map.json'
        payload = {'data': context_map}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        return path

    def _load_context_map(self, batch_dir: Path):
        context_files = list(batch_dir.glob('*_context_map.json'))
        if not context_files:
            return {}
        try:
            with open(context_files[0], 'r', encoding='utf-8') as f:
                payload = json.load(f)
            raw_map = payload.get('data', {})
            return raw_map
        except Exception:
            return {}

    def _get_batch_job_id_for_file(self, output_directory: str=None, file_name: str=None):
        """Get the batch job ID for a specific file from the registry."""
        if output_directory:
            registry_file = Path(output_directory) / 'batch' / '.batch_registry.json'
            if registry_file.exists():
                try:
                    with open(registry_file, 'r') as f:
                        registry = json.load(f)
                    file_entry = registry.get(file_name or 'default', {})
                    return file_entry.get('batch_id')
                except json.JSONDecodeError:
                    pass
        return None

    def _update_batch_registry_status(self, output_directory: str, file_name: str, batch_id: str, status: str):
        """Update the status of a batch job in the registry."""
        if not output_directory:
            return
        registry_file = Path(output_directory) / 'batch' / '.batch_registry.json'
        if not registry_file.exists():
            return
        try:
            with open(registry_file, 'r') as f:
                registry = json.load(f)
            if file_name in registry and registry[file_name].get('batch_id') == batch_id:
                registry[file_name]['status'] = status
                with open(registry_file, 'w') as f:
                    json.dump(registry, f, indent=2)
        except (json.JSONDecodeError, KeyError):
            pass

    def _are_all_batch_jobs_completed(self, output_directory: str) -> bool:
        """Check if all batch jobs in the registry are completed."""
        if not output_directory:
            return True
        registry_file = Path(output_directory) / 'batch' / '.batch_registry.json'
        if not registry_file.exists():
            return True
        try:
            with open(registry_file, 'r') as f:
                registry = json.load(f)
            if not registry:
                return True
            for file_name, entry in registry.items():
                batch_id = entry.get('batch_id')
                if not batch_id:
                    continue
                try:
                    actual_status = self.check_status(batch_id, str(output_directory))
                    if actual_status != entry.get('status'):
                        entry['status'] = actual_status
                    if actual_status not in ['completed', 'failed', 'cancelled']:
                        return False
                except Exception:
                    return False
            with open(registry_file, 'w') as f:
                json.dump(registry, f, indent=2)
            return True
        except (json.JSONDecodeError, KeyError):
            return True

    def _get_batch_registry_status(self, output_directory: str) -> str:
        """Get the overall status of all batch jobs in the registry."""
        if not output_directory:
            return 'no_batches'
        registry_file = Path(output_directory) / 'batch' / '.batch_registry.json'
        if not registry_file.exists():
            return 'no_batches'
        try:
            with open(registry_file, 'r') as f:
                registry = json.load(f)
            if not registry:
                return 'no_batches'
            completed_count = 0
            failed_count = 0
            in_progress_count = 0
            for file_name, entry in registry.items():
                batch_id = entry.get('batch_id')
                if not batch_id:
                    continue
                try:
                    actual_status = self.check_status(batch_id, str(output_directory))
                    if actual_status == 'completed':
                        completed_count += 1
                    elif actual_status in ['failed', 'cancelled']:
                        failed_count += 1
                    else:
                        in_progress_count += 1
                except Exception:
                    in_progress_count += 1
            total_jobs = len(registry)
            if completed_count == total_jobs:
                return 'completed'
            elif failed_count > 0:
                return 'partial_failed'
            elif in_progress_count > 0:
                return 'in_progress'
            else:
                return 'unknown'
        except (json.JSONDecodeError, KeyError):
            return 'error'

    def _get_last_batch_job_id(self, output_directory: str=None):
        """Backward compatibility method - gets the most recent batch job ID."""
        if output_directory:
            registry_file = Path(output_directory) / 'batch' / '.batch_registry.json'
            if registry_file.exists():
                try:
                    with open(registry_file, 'r') as f:
                        registry = json.load(f)
                    if registry:
                        latest_entry = max(registry.values(), key=lambda x: x.get('timestamp', ''))
                        return latest_entry.get('batch_id')
                except json.JSONDecodeError:
                    pass
        return None

    def _check_for_existing_batch_job(self, output_directory: str=None, file_name: str=None):
        """Check if there's already an in-flight batch job for this specific file."""
        batch_id = self._get_batch_job_id_for_file(output_directory, file_name)
        if not batch_id:
            return None
        try:
            status = self.check_status(batch_id, output_directory)
            if output_directory and file_name:
                self._update_batch_registry_status(output_directory, file_name, batch_id, status)
            if status in ['validating', 'in_progress', 'finalizing']:
                return batch_id
            return None
        except Exception:
            return None

    def _get_provider_for_batch_id(self, batch_id: str, output_directory: str=None) -> BatchProvider:
        """
        Get the provider that was used for a specific batch ID.
        
        Args:
            batch_id: The batch job ID
            output_directory: Output directory to look for registry
            
        Returns:
            BatchProvider instance
        """
        if output_directory:
            registry_file = Path(output_directory) / 'batch' / '.batch_registry.json'
            if registry_file.exists():
                try:
                    with open(registry_file, 'r') as f:
                        registry = json.load(f)
                    for entry in registry.values():
                        if entry.get('batch_id') == batch_id:
                            provider_type = entry.get('provider', 'openai')
                            if provider_type in self._provider_cache:
                                return self._provider_cache[provider_type]
                            else:
                                return BatchProviderFactory.create_provider(provider_type)
                except Exception:
                    pass
        return self.provider

    def check_status(self, batch_id: str, output_directory: str=None):
        try:
            provider = self._get_provider_for_batch_id(batch_id, output_directory)
            return provider.check_status(batch_id)
        except Exception as e:
            from agent_actions.shared.exceptions import ExternalServiceError
            raise ExternalServiceError(self.vendor_type or 'unknown', f'Failed to check batch status: {e}', cause=e)

    def retrieve_results(self, batch_id: str, output_dir: str, file_path: str=None):
        try:
            provider = self._get_provider_for_batch_id(batch_id, output_dir)
            batch_dir = Path(output_dir) / 'batch'
            context_map = self._load_context_map(batch_dir)
            registry_entry = None
            file_name = None
            registry_file = batch_dir / '.batch_registry.json'
            if registry_file.exists():
                with open(registry_file, 'r') as f:
                    registry = json.load(f)
                for key, entry in registry.items():
                    if entry.get('batch_id') == batch_id:
                        registry_entry = entry
                        file_name = key
                        break
            batch_results = self._retrieve_results_with_validation_and_retry(provider, batch_id, output_dir, context_map=context_map, agent_config=None, record_count=registry_entry.get('record_count') if registry_entry else None, file_name=file_name)
            output_path = Path(output_dir)
            if file_path:
                original_file_name = Path(file_path).stem
                result_file_name = output_path / f'{original_file_name}_results.jsonl'
            else:
                result_file_name = output_path / f'{batch_id}_results.jsonl'
            if result_file_name.exists():
                return result_file_name
            else:
                ensure_directory_exists(output_path)
                with open(result_file_name, 'w') as f:
                    for result in batch_results:
                        raw_format = {'custom_id': result.custom_id, 'response': {'body': {'choices': [{'message': {'content': json.dumps(result.content)}}], 'usage': result.usage}}}
                        f.write(json.dumps(raw_format) + '\n')
                return result_file_name
        except Exception as e:
            from agent_actions.shared.exceptions import ExternalServiceError
            raise ExternalServiceError(self.vendor_type or 'unknown', f'Failed to retrieve batch results: {e}', cause=e)

    def process_batch_results_to_workflow_output(self, batch_id: str, output_directory: str, base_directory: str, file_path: str, agent_config: Optional[Dict[str, Any]]=None):
        """
        Process batch results and integrate them into the workflow output system.

        Args:
            batch_id: The batch job ID
            output_directory: The target output directory (e.g., node_X_agenttype)
            base_directory: The base directory for relative path calculation
            file_path: The original file path being processed
            agent_config: Agent configuration (optional, enables automatic retry on missing records)
        """
        try:
            provider = self._get_provider_for_batch_id(batch_id, output_directory)
            status = provider.check_status(batch_id)
            if status != 'completed':
                from agent_actions.shared.exceptions import ProcessingError
                raise ProcessingError('Batch job is not completed', context={'batch_id': batch_id, 'status': status})
            batch_dir = Path(output_directory) / 'batch'
            context_map = self._load_context_map(batch_dir)
            registry_entry = None
            file_name = None
            registry_file = batch_dir / '.batch_registry.json'
            if registry_file.exists():
                with open(registry_file, 'r') as f:
                    registry = json.load(f)
                for key, entry in registry.items():
                    if entry.get('batch_id') == batch_id:
                        registry_entry = entry
                        file_name = key
                        break
            batch_results = self._retrieve_results_with_validation_and_retry(provider, batch_id, output_directory, context_map=context_map, agent_config=agent_config, record_count=registry_entry.get('record_count') if registry_entry else None, file_name=file_name)
            processed_data = self._convert_batch_results_to_workflow_format(batch_results, context_map=context_map, output_directory=output_directory, agent_config=agent_config)
            main_output, side_output_data = self._separate_side_output(processed_data)
            relative_path = Path(file_path).relative_to(base_directory)
            output_file_path = Path(output_directory) / relative_path.with_suffix('.json')
            ensure_directory_exists(output_file_path, is_file=True)
            file_writer = FileWriter(str(output_file_path))
            file_writer.write_target(main_output)
            if side_output_data:
                side_output_dir = create_side_output_directory(output_directory)
                side_output_file_path = side_output_dir / relative_path.name
                self._save_side_output(side_output_data, side_output_file_path)
            return str(output_file_path)
        except Exception as e:
            from agent_actions.shared.exceptions import ProcessingError
            raise ProcessingError(f'Failed to process batch results to workflow output: {e}', cause=e)

    def _convert_batch_results_to_workflow_format(self, batch_results, *, context_map=None, output_directory=None, agent_config=None):
        """
        Convert batch provider results to the workflow's expected format.
        Works with standardized BatchResult objects from any provider.

        Args:
            batch_results: List of BatchResult objects from provider
            context_map: Map of custom_id to original row data
            output_directory: Output directory path to extract node information
            agent_config: Agent configuration (needed for loop correlation ID)

        Returns:
            List of processed data in workflow format
        """
        processed_data = []
        context_map = context_map or {}
        node_idx = None
        if output_directory:
            import re
            match = re.search('node_(\\d+)_(\\w+)', str(output_directory))
            if match:
                node_idx = int(match.group(1))
        processed_custom_ids = set()
        for batch_result in batch_results:
            custom_id = batch_result.custom_id
            if batch_result.success and batch_result.content is not None:
                try:
                    generated_obj = batch_result.content
                    json_mode = agent_config.get('json_mode', True)
                    if not json_mode and isinstance(generated_obj, str):
                        output_field = agent_config.get('output_field', 'content')
                        generated_obj = {output_field: generated_obj}
                    generated_list = DataTransformer.ensure_list(generated_obj)
                    original_row = context_map.get(custom_id, {})
                    original_source_guid = original_row.get('source_guid', custom_id)

                    # Apply context_scope.passthrough using pre-computed values
                    if agent_config and custom_id in context_map:
                        # Use the pre-computed passthrough_fields stored during task creation
                        stored_passthrough = context_map[custom_id].get('_passthrough_fields', {})

                        if stored_passthrough:
                            # Merge passthrough fields into generated items using ContextScopeProcessor
                            from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
                            generated_list = ContextScopeProcessor.merge_passthrough_fields(
                                generated_list, stored_passthrough
                            )
                        elif agent_config.get('context_scope', {}).get('passthrough'):
                            # Fallback: old behavior for backward compatibility
                            # (when _passthrough_fields not available)
                            passthrough_refs = agent_config.get('context_scope', {}).get('passthrough', [])
                            passthrough_fields = []
                            for field_ref in passthrough_refs:
                                try:
                                    from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
                                    _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                                    passthrough_fields.append(field_name)
                                except ValueError:
                                    # If parsing fails, use the whole string as field name
                                    passthrough_fields.append(field_ref)

                            # Get original content (same as old observe logic)
                            original_content = original_row.get('content', original_row)

                            # Merge passthrough fields from original into generated items
                            generated_list = [
                                DataTransformer.update_schema_objects(original_content, item, passthrough_fields)
                                if isinstance(item, dict) else item
                                for item in generated_list
                            ]

                    structured_items = DataTransformer.transform_structure([{original_source_guid: generated_list}])
                    for idx, itm in enumerate(structured_items):
                        itm['metadata'] = batch_result.metadata or {}
                        if node_idx is not None:
                            item_node_id = ProcessorUtils.generate_node_id(node_idx)
                            itm['node_id'] = item_node_id
                            itm['lineage'] = ProcessorUtils.build_lineage(original_row, item_node_id)
                        if 'target_id' not in itm or not itm['target_id']:
                            itm['target_id'] = original_row.get('target_id', ProcessorUtils.generate_target_id())
                        if 'source_guid' not in itm or not itm['source_guid']:
                            itm['source_guid'] = original_source_guid
                        if agent_config:
                            record_index = None
                            if custom_id and context_map:
                                context_keys = list(context_map.keys())
                                if custom_id in context_keys:
                                    record_index = context_keys.index(custom_id)
                            structured_items[idx] = ProcessorUtils.add_loop_correlation_id(itm, agent_config, record_index=record_index)
                    processed_data.extend(structured_items)
                    processed_custom_ids.add(str(custom_id))
                except Exception as e:
                    original_row = context_map.get(custom_id, {})
                    original_source_guid = original_row.get('source_guid', custom_id)
                    error_item = {'source_guid': original_source_guid, 'error': f'Processing error: {str(e)}', 'raw_content': batch_result.content, 'metadata': batch_result.metadata or {}}
                    processed_data.append(error_item)
                    processed_custom_ids.add(str(custom_id))
            else:
                original_row = context_map.get(custom_id, {})
                original_source_guid = original_row.get('source_guid', custom_id or 'unknown')
                error_item = {'source_guid': original_source_guid, 'error': batch_result.error or 'Batch processing failed', 'metadata': batch_result.metadata or {}}
                processed_data.append(error_item)
                processed_custom_ids.add(str(custom_id))
        expected_included_ids = {str(custom_id) for custom_id, original_row in (context_map or {}).items() if original_row.get('_batch_filter_status', 'included') == 'included'}
        missing_included_ids = expected_included_ids - processed_custom_ids
        if missing_included_ids:
            print(f"[INFO] Missing {len(missing_included_ids)} records in batch results. Continuing with available data.")
        for custom_id, original_row in context_map.items():
            if custom_id not in processed_custom_ids:
                filter_status = original_row.get('_batch_filter_status', 'included')
                if filter_status == 'filtered':
                    continue
                elif filter_status in ['skipped', 'included']:
                    original_source_guid = original_row.get('source_guid', custom_id)
                    passthrough_item = original_row.copy()
                    passthrough_item.pop('_batch_filter_status', None)
                    if 'target_id' not in passthrough_item or not passthrough_item['target_id']:
                        passthrough_item['target_id'] = custom_id
                    if 'source_guid' not in passthrough_item or not passthrough_item['source_guid']:
                        passthrough_item['source_guid'] = original_source_guid
                    if node_idx is not None:
                        item_node_id = ProcessorUtils.generate_node_id(node_idx)
                        passthrough_item['node_id'] = item_node_id
                        passthrough_item['lineage'] = ProcessorUtils.build_lineage(original_row, item_node_id)
                    passthrough_item['metadata'] = {'skipped_by_conditional': True, 'agent_type': 'passthrough'}
                    processed_data.append(passthrough_item)
        return processed_data

    def process_all_batch_results_to_workflow_output(self, output_directory: str, agent_config: Dict[str, Any]=None):
        """
        Process all completed batch jobs in the registry, maintaining file-to-file mapping.
        Each input file produces its own corresponding output file.

        Args:
            output_directory: Path to the agent's output directory
            agent_config: Agent configuration (needed for loop correlation ID)
        """
        try:
            batch_dir = Path(output_directory) / 'batch'
            registry_file = batch_dir / '.batch_registry.json'
            if not registry_file.exists():
                from agent_actions.shared.exceptions import ProcessingError
                raise ProcessingError('No batch registry found', context={'registry_file': str(registry_file), 'output_directory': output_directory})
            with open(registry_file, 'r') as f:
                registry = json.load(f)
            context_map = self._load_context_map(batch_dir)
            processed_files = []
            for file_name, entry in registry.items():
                batch_id = entry.get('batch_id')
                if not batch_id:
                    continue
                try:
                    batch_status = self.check_status(batch_id, str(output_directory))
                    if batch_status != 'completed':
                        print(f'Batch {batch_id} for {file_name} is not completed: {batch_status}')
                        continue
                except Exception as e:
                    print(f'Could not check status for batch {batch_id}: {e}')
                    continue
                try:
                    provider = self._get_provider_for_batch_id(batch_id, output_directory)
                    batch_results = self._retrieve_results_with_validation_and_retry(provider, batch_id, output_directory, context_map=context_map, agent_config=agent_config, record_count=entry.get('record_count'), file_name=file_name)
                    if not batch_results:
                        print(f'No results found for batch {batch_id} ({file_name})')
                        continue
                    print(f'Processing {len(batch_results)} batch results for {file_name}')
                    processed_data = self._convert_batch_results_to_workflow_format(batch_results, context_map=context_map, output_directory=output_directory, agent_config=agent_config)
                    main_output, side_output_data = self._separate_side_output(processed_data)
                    if file_name and file_name != 'default':
                        output_file_path = Path(output_directory) / f'{Path(file_name).stem}.json'
                    else:
                        output_file_path = Path(output_directory) / f'{batch_id}_processed_output.json'
                    ensure_directory_exists(output_file_path, is_file=True)
                    file_writer = FileWriter(str(output_file_path))
                    file_writer.write_target(main_output)
                    if side_output_data:
                        side_output_dir = create_side_output_directory(output_directory)
                        if file_name and file_name != 'default':
                            side_output_file = side_output_dir / f'{Path(file_name).stem}.json'
                        else:
                            side_output_file = side_output_dir / f'{batch_id}_processed_output.json'
                        self._save_side_output(side_output_data, side_output_file)
                    processed_files.append(str(output_file_path))
                    print(f'✅ Processed {file_name} → {output_file_path}')
                except Exception as e:
                    error_msg = f'Could not process batch results for {file_name} (batch {batch_id}): {e}'
                    print(f'[ERROR] {error_msg}')
                    continue
            if not processed_files:
                from agent_actions.shared.exceptions import ProcessingError
                raise ProcessingError('No batch results were successfully processed', context={'output_directory': output_directory, 'registry_entries': len(registry)})
            print(f'Successfully processed {len(processed_files)} files')
            return processed_files
        except Exception as e:
            from agent_actions.shared.exceptions import ProcessingError
            raise ProcessingError(f'Failed to process all batch results to workflow output: {e}', cause=e)

    def _collect_expected_custom_ids(self, context_map: Dict[str, Any]) -> set:
        """
        Collect custom_ids of records that were submitted to batch API.

        Only counts records with _batch_filter_status='included' since filtered/skipped
        records were never submitted to the batch API.

        Args:
            context_map: Dictionary mapping custom_id to original record data

        Returns:
            Set of custom_ids that were actually submitted to batch API
        """
        return {str(custom_id) for custom_id, original_row in (context_map or {}).items() if original_row.get('_batch_filter_status', 'included') == 'included'}

    def _collect_result_custom_ids(self, batch_results: List[BatchResult]) -> set:
        """
        Collect custom_ids from batch results.

        Ignores internal error placeholders (error_line_*) which are not real missing
        records, just provider-side errors that need to be filtered out.

        Args:
            batch_results: List of BatchResult objects from provider

        Returns:
            Set of custom_ids that were returned in batch results
        """
        result_ids: set = set()
        for batch_result in batch_results or []:
            custom_id = getattr(batch_result, 'custom_id', None)
            if not custom_id:
                continue
            custom_id_str = str(custom_id)
            if custom_id_str.startswith('error_line_'):
                continue
            result_ids.add(custom_id_str)
        return result_ids

    def _log_batch_reconciliation(self, *, batch_id: str, expected_count: int, received_count: int, file_name: Optional[str]=None) -> None:
        """
        Log batch reconciliation status with visual indicators.

        Provides transparency into whether all expected results were received.
        Uses visual indicators (✅/⚠️) for quick scanning of batch health.

        Args:
            batch_id: Batch ID for context
            expected_count: Number of records submitted to batch API
            received_count: Number of results received from batch API
            file_name: Optional file name for better labeling (preferred over batch_id)
        """
        if expected_count == 0:
            return
        prefix = '✅' if expected_count == received_count else '⚠️'
        label = file_name or batch_id
        print(f'{prefix} Batch reconciliation for {label}: expected {expected_count} result(s), received {received_count}')

    def _reconstruct_tasks_for_retry(self, *, missing_custom_ids: Set[str], context_map: Dict[str, Any], agent_config: Dict[str, Any], output_directory: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Reconstruct batch tasks for missing records from context map.

        Rebuilds the full task structure (prompt + content + schema) for records
        that were submitted to the batch API but never received a result.

        Args:
            missing_custom_ids: Set of custom_ids that need to be retried
            context_map: Original context map with full row data
            agent_config: Agent configuration (for prompt, schema, etc.)
            output_directory: Optional output directory for historical node loading

        Returns:
            List of reconstructed tasks ready for resubmission
        """
        provider = self._get_provider_for_config(agent_config)
        schema = self._prepare_schema(agent_config, provider)
        raw_prompt = agent_config.get(PROMPT_KEY, '')
        if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
            raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
        if not raw_prompt:
            raw_prompt = 'Process the following content: {content}'
        tools_path = self._resolve_tools_path(agent_config)
        if tools_path and tools_path not in sys.path:
            sys.path.insert(0, tools_path)
        prepared_data = []
        for custom_id in missing_custom_ids:
            if custom_id not in context_map:
                continue
            original_row = context_map[custom_id]
            if 'source_guid' in original_row and 'content' in original_row:
                row_content = original_row['content']
            else:
                row_content = original_row

            # Build field context with historical data (same as online mode)
            from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
            agent_name = agent_config.get('agent_type', agent_config.get('name', 'unknown'))

            # Build namespaced field context with historical node loading
            field_context = ContextScopeProcessor.build_field_context_with_history(
                contents=row_content if isinstance(row_content, dict) else {},
                agent_name=agent_name,
                agent_config=agent_config,
                agent_indices=self.agent_indices,
                dependency_configs=self.dependency_configs,
                source_content=row_content,  # Source is the current row in batch mode
                current_item=context_map.get(custom_id),
                file_path=output_directory  # Use output_directory as base for historical node loading
            )

            # Apply context_scope to split field_context into prompt/llm/passthrough contexts
            context_scope = agent_config.get('context_scope', {})
            if context_scope:
                prompt_context, llm_context, passthrough_fields = ContextScopeProcessor.apply_context_scope(
                    field_context, context_scope
                )

                # Note: passthrough_fields not stored here since retry uses existing context_map
            else:
                prompt_context = field_context
                llm_context = {}

            # Build LLM context: start with current row, then add included fields
            # Start with current row content (source in batch mode)
            llm_full_context = row_content.copy() if isinstance(row_content, dict) else {}

            # Remove dropped fields
            if context_scope and context_scope.get('drop'):
                for field_ref in context_scope.get('drop', []):
                    try:
                        _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                        llm_full_context.pop(field_name, None)
                    except ValueError:
                        continue

            # Add observed fields from llm_context (fields from previous actions)
            if llm_context:
                llm_full_context.update(llm_context)

            # Render prompt with prompt_context (fields not dropped)
            formatted_prompt = PromptUtils.replace_field_references(raw_prompt, prompt_context)
            # Use llm_full_context for LLM (includes fields from context_scope.observe)
            formatted_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
                formatted_prompt, tools_path, json.dumps(llm_full_context, ensure_ascii=False), agent_config=agent_config
            )
            cleaned_row = llm_full_context
            prepared_item = {'target_id': custom_id, 'content': cleaned_row, 'prompt': formatted_prompt}
            prepared_data.append(prepared_item)
        provider_config = agent_config.copy()
        provider_config['compiled_schema'] = schema
        tasks = provider.prepare_tasks(prepared_data, provider_config)
        return tasks

    def _resubmit_missing_records_as_batch(self, *, parent_batch_id: str, missing_custom_ids: Set[str], context_map: Dict[str, Any], agent_config: Dict[str, Any], output_directory: str, file_name: str) -> Optional[str]:
        """
        Resubmit missing records as a new batch job (main orchestration method).

        Implements the Dead Letter Queue (DLQ) pattern for handling batch failures.
        Creates audit files and tracks retry attempts to prevent infinite loops.

        Flow:
        1. Check if retry is allowed (depth limit + duplicate prevention)
        2. Read parent batch retry attempt from registry
        3. Check retry depth against _MAX_RETRY_DEPTH
        4. Reconstruct tasks for missing records
        5. Submit retry batch with incremented attempt number
        6. Mark parent batch as having retry
        7. Create/update retry manifest for audit trail
        8. Archive permanently failed records to DLQ if max retries exceeded

        Args:
            parent_batch_id: ID of the original/parent batch
            missing_custom_ids: Set of custom_ids that need retry
            context_map: Original context map
            agent_config: Agent configuration
            output_directory: Output directory for batch files
            file_name: Name of the original file

        Returns:
            Retry batch ID if resubmitted, None if retry not allowed or no records to retry
        """
        if not missing_custom_ids:
            return None
        max_retry_depth = self._load_retry_config(agent_config)
        batch_dir = Path(output_directory) / 'batch'
        registry_file = batch_dir / '.batch_registry.json'
        if not registry_file.exists():
            logger.warning(f'Registry not found, cannot retry: {registry_file}')
            return None
        with open(registry_file, 'r') as f:
            registry = json.load(f)
        parent_entry = None
        for entry_file_name, entry in registry.items():
            if entry.get('batch_id') == parent_batch_id:
                parent_entry = entry
                break
        if not parent_entry:
            logger.warning(f'Parent batch {parent_batch_id} not found in registry')
            return None
        if parent_entry.get('has_retry_batch', False):
            print(f'⚠️ Parent batch {parent_batch_id} already has a retry batch, skipping duplicate retry')
            return None
        current_retry_attempt = parent_entry.get('retry_attempt', 0)
        next_retry_attempt = current_retry_attempt + 1
        if next_retry_attempt > max_retry_depth:
            print(f'⚠️ Max retry depth ({max_retry_depth}) exceeded for {file_name}')
            print(f'   Archiving {len(missing_custom_ids)} permanently failed record(s) to DLQ')
            self._append_to_dlq(missing_custom_ids=missing_custom_ids, context_map=context_map, output_directory=output_directory, parent_batch_id=parent_batch_id, retry_attempt=current_retry_attempt)
            return None
        print(f'🔄 Retrying {len(missing_custom_ids)} missing record(s) from {file_name} (attempt {next_retry_attempt}/{max_retry_depth + 1})')
        retry_tasks = self._reconstruct_tasks_for_retry(missing_custom_ids=missing_custom_ids, context_map=context_map, agent_config=agent_config, output_directory=output_directory)
        if not retry_tasks:
            print('⚠️ Failed to reconstruct tasks for retry')
            return None
        try:
            provider = self._get_provider_for_config(agent_config)
            provider_type = agent_config.get('model_vendor')
            if not provider_type:
                from agent_actions.shared.exceptions import ConfigValidationError
                raise ConfigValidationError('model_vendor', "Missing required field 'model_vendor' for batch retry processing.")
            provider_type = provider_type.lower()
            retry_batch_name = f'{Path(file_name).stem}_retry_{next_retry_attempt}'
            retry_batch_id = provider.submit_batch(retry_tasks, retry_batch_name, output_directory)
            self._save_batch_job_id(batch_id=retry_batch_id, output_directory=output_directory, file_name=f'{retry_batch_name}.json', provider_type=provider_type, parent_batch_id=parent_batch_id, retry_attempt=next_retry_attempt, record_count=len(retry_tasks), retry_for_records=sorted(list(missing_custom_ids)))
            self._mark_parent_batch_has_retry(parent_batch_id=parent_batch_id, output_directory=output_directory)
            self._update_retry_manifest(parent_batch_id=parent_batch_id, retry_batch_id=retry_batch_id, missing_custom_ids=missing_custom_ids, retry_attempt=next_retry_attempt, output_directory=output_directory)
            print(f'✅ Retry batch submitted: {retry_batch_id}')
            return retry_batch_id
        except Exception as e:
            from agent_actions.shared.exceptions import ExternalServiceError
            logger.error(f'Failed to submit retry batch: {e}')
            raise ExternalServiceError(provider_type, f'Failed to submit retry batch: {e}', cause=e)

    def _mark_parent_batch_has_retry(self, *, parent_batch_id: str, output_directory: str) -> None:
        """
        Mark parent batch as having a retry batch to prevent duplicate retries.

        Updates the registry to set has_retry_batch=True for the parent batch.

        Args:
            parent_batch_id: ID of the parent batch
            output_directory: Output directory for registry
        """
        batch_dir = Path(output_directory) / 'batch'
        registry_file = batch_dir / '.batch_registry.json'
        if not registry_file.exists():
            return
        try:
            with open(registry_file, 'r') as f:
                registry = json.load(f)
            for entry_file_name, entry in registry.items():
                if entry.get('batch_id') == parent_batch_id:
                    entry['has_retry_batch'] = True
                    break
            with open(registry_file, 'w') as f:
                json.dump(registry, f, indent=2)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f'Failed to mark parent batch as having retry: {e}')

    def _create_retry_manifest(self, *, parent_batch_id: str, retry_batch_id: str, missing_custom_ids: Set[str], retry_attempt: int, output_directory: str) -> None:
        """
        Create comprehensive retry manifest file for audit trail.

        Creates a JSON file documenting all retry attempts for compliance and debugging.
        Includes timestamps, custom_ids, batch IDs, and attempt numbers.

        Args:
            parent_batch_id: ID of the original batch
            retry_batch_id: ID of the retry batch
            missing_custom_ids: Set of custom_ids being retried
            retry_attempt: Current retry attempt number
            output_directory: Output directory for manifest file
        """
        from datetime import datetime
        batch_dir = Path(output_directory) / 'batch'
        ensure_directory_exists(batch_dir)
        manifest_file = batch_dir / f'{parent_batch_id}_retry_manifest.json'
        manifest = {'parent_batch_id': parent_batch_id, 'created_at': datetime.now().isoformat(), 'total_retries': 1, 'retry_attempts': [{'attempt_number': retry_attempt, 'retry_batch_id': retry_batch_id, 'timestamp': datetime.now().isoformat(), 'missing_custom_ids': list(missing_custom_ids), 'record_count': len(missing_custom_ids)}]}
        with open(manifest_file, 'w') as f:
            json.dump(manifest, f, indent=2)

    def _update_retry_manifest(self, *, parent_batch_id: str, retry_batch_id: str, missing_custom_ids: Set[str], retry_attempt: int, output_directory: str) -> None:
        """
        Update existing retry manifest or create new one.

        Appends new retry attempt to manifest file, tracking all retry history.

        Args:
            parent_batch_id: ID of the original batch
            retry_batch_id: ID of the retry batch
            missing_custom_ids: Set of custom_ids being retried
            retry_attempt: Current retry attempt number
            output_directory: Output directory for manifest file
        """
        from datetime import datetime
        batch_dir = Path(output_directory) / 'batch'
        ensure_directory_exists(batch_dir)
        manifest_file = batch_dir / f'{parent_batch_id}_retry_manifest.json'
        if manifest_file.exists():
            try:
                with open(manifest_file, 'r') as f:
                    manifest = json.load(f)
                manifest['total_retries'] += 1
                manifest['retry_attempts'].append({'attempt_number': retry_attempt, 'retry_batch_id': retry_batch_id, 'timestamp': datetime.now().isoformat(), 'missing_custom_ids': list(missing_custom_ids), 'record_count': len(missing_custom_ids)})
                with open(manifest_file, 'w') as f:
                    json.dump(manifest, f, indent=2)
            except (json.JSONDecodeError, KeyError):
                self._create_retry_manifest(parent_batch_id=parent_batch_id, retry_batch_id=retry_batch_id, missing_custom_ids=missing_custom_ids, retry_attempt=retry_attempt, output_directory=output_directory)
        else:
            self._create_retry_manifest(parent_batch_id=parent_batch_id, retry_batch_id=retry_batch_id, missing_custom_ids=missing_custom_ids, retry_attempt=retry_attempt, output_directory=output_directory)

    def _append_to_dlq(self, *, missing_custom_ids: Set[str], context_map: Dict[str, Any], output_directory: str, parent_batch_id: str, retry_attempt: int) -> None:
        """
        Append permanently failed records to Dead Letter Queue (DLQ) file.

        Archives records that exceeded max retry attempts to JSONL file for manual review.
        Uses JSONL format (one JSON object per line) for easy parsing and streaming.

        Args:
            missing_custom_ids: Set of custom_ids that permanently failed
            context_map: Original context map with full record data
            output_directory: Output directory for DLQ file
            parent_batch_id: ID of the original batch
            retry_attempt: Final retry attempt number
        """
        from datetime import datetime
        batch_dir = Path(output_directory) / 'batch'
        ensure_directory_exists(batch_dir)
        dlq_file = batch_dir / 'dead_letter_queue.jsonl'
        with open(dlq_file, 'a') as f:
            for custom_id in missing_custom_ids:
                if custom_id not in context_map:
                    continue
                original_row = context_map[custom_id]
                dlq_entry = {'custom_id': custom_id, 'parent_batch_id': parent_batch_id, 'retry_attempt': retry_attempt, 'archived_at': datetime.now().isoformat(), 'reason': 'max_retry_exceeded', 'original_data': original_row}
                f.write(json.dumps(dlq_entry) + '\n')
        print(f'📝 Archived {len(missing_custom_ids)} record(s) to DLQ: {dlq_file}')

    def _is_retry_batch(self, file_name: Optional[str], output_directory: str) -> bool:
        """
        Check if a batch is a retry batch.

        Retry batches have a parent_batch_id field in the registry, linking them
        to their original parent batch. This check prevents recursive retries
        (retry batches don't trigger more retries).

        Args:
            file_name: Batch file name to check
            output_directory: Output directory

        Returns:
            True if this is a retry batch, False otherwise
        """
        if not file_name:
            return False
        batch_dir = Path(output_directory) / 'batch'
        registry_file = batch_dir / '.batch_registry.json'
        if not registry_file.exists():
            return False
        try:
            with open(registry_file, 'r') as f:
                registry = json.load(f)
            entry = registry.get(file_name, {})
            return entry.get('parent_batch_id') is not None
        except Exception:
            return False

    def _get_retry_attempt_from_registry(self, file_name: Optional[str], output_directory: str) -> int:
        """
        Get the current retry_attempt number for a batch.

        Reads the batch registry to determine which retry attempt this batch
        represents (0 = original, 1 = first retry, 2 = second retry, etc.).

        Args:
            file_name: Batch file name
            output_directory: Output directory

        Returns:
            Current retry_attempt number (0 for parent batches, 1+ for retry batches)
        """
        if not file_name:
            return 0
        batch_dir = Path(output_directory) / 'batch'
        registry_file = batch_dir / '.batch_registry.json'
        if not registry_file.exists():
            return 0
        try:
            with open(registry_file, 'r') as f:
                registry = json.load(f)
            entry = registry.get(file_name, {})
            return entry.get('retry_attempt', 0)
        except Exception:
            return 0

    def _retrieve_results_with_validation_and_retry(self, provider: BatchProvider, batch_id: str, output_directory: Optional[str], *, context_map: Optional[Dict[str, Any]]=None, agent_config: Optional[Dict[str, Any]]=None, record_count: Optional[int]=None, file_name: Optional[str]=None) -> List[BatchResult]:
        """
        Retrieve batch results without validation or retry.

        Simply downloads whatever results are available from the batch provider.
        No validation, no retry logic - just take what you get.

        Args:
            provider: Batch provider instance
            batch_id: Batch ID to retrieve
            output_directory: Output directory
            context_map: Context map for logging (optional)
            agent_config: Agent config (unused, kept for compatibility)
            record_count: Fallback record count for logging (optional)
            file_name: Batch file name for logging (optional)

        Returns:
            List of BatchResult objects (whatever the provider returns)
        """
        batch_results = provider.retrieve_results(batch_id, output_directory)
        expected_custom_ids = self._collect_expected_custom_ids(context_map or {})
        expected_count = len(expected_custom_ids)
        if expected_count == 0 and record_count:
            expected_count = record_count
        if expected_count == 0:
            return batch_results
        result_custom_ids = self._collect_result_custom_ids(batch_results)
        received_count = len(result_custom_ids) if expected_custom_ids else len(batch_results)
        if expected_custom_ids:
            missing_ids = expected_custom_ids - result_custom_ids
        else:
            missing_ids = set() if received_count >= expected_count else set()
        if not missing_ids and received_count >= expected_count:
            self._log_batch_reconciliation(batch_id=batch_id, expected_count=expected_count, received_count=received_count, file_name=file_name)
        else:
            print(f"[INFO] Batch {batch_id}: expected {expected_count} result(s) but received {received_count}. Missing: {', '.join(sorted(missing_ids)[:5])}{('...' if len(missing_ids) > 5 else '')}")
            print(f"[INFO] Continuing with {received_count} available result(s). No retry will be attempted.")
        return batch_results