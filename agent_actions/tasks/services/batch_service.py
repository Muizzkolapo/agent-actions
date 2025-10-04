import json
import sys
import logging
from pathlib import Path
import yaml
from typing import Optional, Dict, Any, List
from agent_actions.agents.handlers.agent_handlers import AgentManager
from agent_actions.agents.handlers.config_handler import ConfigManager
from agent_actions.integrations.loaders.batch_data_loader import BatchDataLoader
from agent_actions.agents.handlers.prompt_handler import PromptLoader
from agent_actions.agents.transformers.prompt_utils import PromptUtils
from agent_actions.agents.handlers.schema_handler import SchemaLoader
from agent_actions.core.parser.schema_change import compile_unified_schema
from agent_actions.agents.handlers.file_writer import FileWriter
from agent_actions.agents.transformers.data_transformer import DataTransformer
from agent_actions.core.constants import PROMPT_KEY, SCHEMA_NAME_KEY, SCHEMA_KEY, SIDE_COLLECTION_KEY
from agent_actions.core.utils.processor_helpers import apply_remove_collection
from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.core.parser.where_parser import get_global_filter, evaluate_safe_skip_condition
from agent_actions.core.utils.path_utils import (
    ensure_directory_exists,
    create_side_output_directory,
    resolve_absolute_path
)
from agent_actions.core.utils.processor_utils import ProcessorUtils
from agent_actions.core.parser.where_parser import WhereClauseParser

from agent_actions.core.graph.dependency_injection import registry
from agent_actions.integrations.providers.base import BatchProvider, BatchTask, BatchResult
from agent_actions.integrations.providers.openai.provider import OpenAIBatchProvider
from agent_actions.integrations.providers.factory import BatchProviderFactory


logger = logging.getLogger(__name__)


@registry.register_service("batch_service")
class BatchService:
    def _create_passthrough_data(self, data, agent_config, output_directory):
        """
        Create passthrough data structure when no batch tasks are submitted.
        This preserves all original data with appropriate metadata.
        """
        
        # Extract node index from output directory (e.g., "node_0_summary")
        node_idx = None
        if output_directory:
            import re
            match = re.search(r'node_(\d+)_(\w+)', str(output_directory))
            if match:
                node_idx = int(match.group(1))
        
        processed_data = []
        
        for row in data:
            # Always use target_id as the identifier; if missing, generate a new UUID and assign it
            target_id = row.get("target_id")
            if not target_id:
                target_id = ProcessorUtils.generate_target_id()
                row["target_id"] = target_id
            
            # Create a passthrough item that preserves all original data
            passthrough_item = row.copy()
            original_source_guid = row.get("source_guid", target_id)
            
            # Ensure required fields are set
            if 'target_id' not in passthrough_item or not passthrough_item['target_id']:
                passthrough_item['target_id'] = target_id
            if 'source_guid' not in passthrough_item or not passthrough_item['source_guid']:
                passthrough_item['source_guid'] = original_source_guid
            
            # Add node_id and lineage tracking for consistency
            if node_idx is not None:
                item_node_id = ProcessorUtils.generate_node_id(node_idx)
                passthrough_item["node_id"] = item_node_id
                
                # Use ProcessorUtils for lineage tracking
                passthrough_item["lineage"] = ProcessorUtils.build_lineage(row, item_node_id)
            
            # Add metadata to indicate this was skipped by conditional
            passthrough_item["metadata"] = {
                "skipped_by_conditional": True,
                "agent_type": "passthrough",
                "reason": "conditional_clause_failed"
            }
            
            processed_data.append(passthrough_item)
        
        # Return a special marker indicating this is passthrough data
        return {"type": "passthrough", "data": processed_data, "output_directory": output_directory}

    def _create_passthrough_data_from_context(self, agent_config, output_directory):
        """
        Create passthrough data from context map, respecting filter statuses.
        Only items marked as 'skipped' will be included as passthrough.
        """
        # Extract node index from output directory (e.g., "node_0_summary")
        node_idx = None
        if output_directory:
            import re
            match = re.search(r'node_(\d+)_(\w+)', str(output_directory))
            if match:
                node_idx = int(match.group(1))

        processed_data = []

        for custom_id, original_row in self.context_map.items():
            filter_status = original_row.get("_batch_filter_status", "included")

            if filter_status == "skipped":
                # Only pass through items that were skipped (not filtered)
                target_id = original_row.get("target_id", custom_id)
                original_source_guid = original_row.get("source_guid", target_id)

                # Create a passthrough item that preserves all original data
                passthrough_item = original_row.copy()

                # Remove internal metadata before output
                passthrough_item.pop("_batch_filter_status", None)

                # Ensure required fields are set
                if 'target_id' not in passthrough_item or not passthrough_item['target_id']:
                    passthrough_item['target_id'] = target_id
                if 'source_guid' not in passthrough_item or not passthrough_item['source_guid']:
                    passthrough_item['source_guid'] = original_source_guid

                # Add node_id and lineage tracking for consistency
                if node_idx is not None:
                    item_node_id = ProcessorUtils.generate_node_id(node_idx)
                    passthrough_item["node_id"] = item_node_id

                    # Use ProcessorUtils for lineage tracking
                    passthrough_item["lineage"] = ProcessorUtils.build_lineage(original_row, item_node_id)

                # Add metadata to indicate this was skipped by WHERE clause
                passthrough_item["metadata"] = {
                    "skipped_by_where_clause": True,
                    "agent_type": "passthrough",
                    "reason": "where_clause_not_matched"
                }

                processed_data.append(passthrough_item)

        # Return the same format as regular passthrough data (workflow expects this)
        return {"type": "passthrough", "data": processed_data, "output_directory": output_directory}

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
        source_path = base_path / "source"
        output_src_path = source_path / relative_path.with_suffix('.json')
        ensure_directory_exists(output_src_path, is_file=True)
        print(f"[DEBUG] Saving source for file_path: {file_path}")
        print(f"[DEBUG] Output source path: {output_src_path}")
        print(f"[DEBUG] Custom ID: {list(src_text.keys())[0]}")
        
        if output_src_path.exists():
            with open(output_src_path, 'r') as existing_file:
                try:
                    existing_source = json.load(existing_file)
                except Exception:
                    existing_source = []
            # Only add if GUID is new
            task_guid = list(src_text.keys())[0]
            if task_guid not in [list(item.keys())[0] for item in existing_source]:
                existing_source.append(src_text)
                with open(output_src_path, 'w') as f:
                    json.dump(existing_source, f, indent=2)
        else:
            with open(output_src_path, 'w') as f:
                json.dump([src_text], f, indent=2)

    # Class variable to control force batch behavior
    force_batch = False
    
    def __init__(self, provider: Optional[BatchProvider] = None):
        self.data_loader = BatchDataLoader()
        self.provider = provider
        self.context_map = {}
        self.side_collection = []
        # Cache providers by type to avoid recreating them
        self._provider_cache = {}
        self.where_parser = WhereClauseParser()


    def _get_provider_for_config(self, agent_config: Dict[str, Any]) -> BatchProvider:
        """
        Get the appropriate provider based on agent configuration.

        Args:
            agent_config: Agent configuration dictionary (must be resolved via hierarchy)

        Returns:
            BatchProvider instance for the specified provider type
        """
        # Validate that config is complete (was resolved by caller via ActionExpander)
        # Batch service expects fully resolved config, not raw action/workflow config
        required_fields = ['model_vendor', 'model_name', 'api_key']
        missing = [f for f in required_fields if not agent_config.get(f)]

        if missing:
            from agent_actions.core.exceptions import ConfigurationError
            raise ConfigurationError(
                f"Batch service received incomplete config (missing: {', '.join(missing)})",
                context={
                    'missing_fields': missing,
                    'agent_type': agent_config.get('agent_type', 'unknown'),
                    'hint': 'Caller must resolve config hierarchy (project → workflow → action) before calling batch service'
                }
            )

        # Get provider type from config - prioritize model_vendor, fallback to batch_provider for backward compatibility
        provider_type = (agent_config.get('model_vendor') or agent_config.get('batch_provider') or 'openai').lower()
        
        # Log deprecation warning if using batch_provider without model_vendor
        if agent_config.get('batch_provider') and not agent_config.get('model_vendor'):
            print(f"⚠️ DEPRECATION WARNING: 'batch_provider' is deprecated. Use 'model_vendor' instead. Found: batch_provider='{agent_config.get('batch_provider')}'")
        
        # Handle special case: 'tool' vendor doesn't support batch processing
        if provider_type == 'tool':
            from agent_actions.core.exceptions import ConfigurationError
            raise ConfigurationError(
                "'tool' vendor does not support batch processing",
                context={'provider_type': provider_type, 'supported_vendors': ['openai', 'gemini', 'anthropic']}
            )
        
        # Check cache first
        if provider_type in self._provider_cache:
            return self._provider_cache[provider_type]
        
        # Create new provider instance
        try:
            # Extract provider-specific config if needed
            provider_config = {}
            if provider_type == 'gemini' and agent_config.get('google_api_key'):
                provider_config['api_key'] = agent_config['google_api_key']
            elif provider_type == 'openai' and agent_config.get('openai_api_key'):
                provider_config['api_key'] = agent_config['openai_api_key']
            
            provider = BatchProviderFactory.create_provider(provider_type, provider_config)
            
            # Validate that the provider supports the requested model
            is_valid, error_msg = provider.validate_config(agent_config)
            if not is_valid:
                from agent_actions.core.exceptions import ConfigurationError
                raise ConfigurationError(
                    "Provider configuration validation failed",
                    context={'provider_type': provider_type, 'error_message': error_msg}
                )
            
            # Cache the provider
            self._provider_cache[provider_type] = provider
            
            return provider
            
        except Exception as e:
            from agent_actions.core.exceptions import ConfigurationError
            raise ConfigurationError(
                f"Failed to create provider for batch_provider_{provider_type}: {e}",
                context={"provider_type": provider_type},
                cause=e
            )

    def _process_batch(self, *args, **kwargs):
        """Placeholder batch processing method for testing/mocking."""
        return None

    def _should_process_item(self, item_data: dict, agent_config: dict) -> bool:
        """Enhanced item filtering with WHERE clause support"""

        if agent_config.get("conditional_clause"):
            try:
                if not execute_user_defined_function(
                    agent_config["conditional_clause"], item_data
                ):
                    return False
            except Exception as e:
                logger.warning(f"Error in conditional_clause: {e}")

        where_config = agent_config.get("where_clause")
        if where_config and where_config.get("scope") == "item":
            try:
                conditions = self.where_parser.parse(where_config["clause"])
                return self.where_parser.evaluate(item_data, conditions)
            except Exception as e:
                logger.warning(f"Error in WHERE clause evaluation: {e}")
                return where_config.get("passthrough_on_empty", True)

        return True
    
    @staticmethod
    def _separate_side_output(items):
        """Split processed items into main and side output collections."""
        main_output, side_output = [], []
        for item in items:
            content = item.get('content', {})
            if isinstance(content, dict) and content.get('side_output', False):
                side_output.append(item)
            else:
                main_output.append(item)
        return main_output, side_output

    @staticmethod
    def _save_side_output(data, file_path):
        """Persist side output data, merging with existing content if present."""
        ensure_directory_exists(file_path, is_file=True)

        existing = []
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError:
                    existing = []

        if not isinstance(existing, list):
            existing = [existing]

        # Ensure the incoming data is a list for consistent appends
        if not isinstance(data, list):
            data = [data]

        existing.extend(data)

        with open(file_path, "w", encoding="utf-8") as f:
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
        from agent_actions.core.parser.schema_change import prepare_schema_unified
        from agent_actions.core.constants import MODEL_VENDOR_KEY

        if provider is None:
            provider = self.provider

        # Get vendor name from agent config
        # This is more reliable than extracting from provider class name
        vendor = agent_config.get(MODEL_VENDOR_KEY, '').lower()

        # Fallback: extract from provider type if not in config
        if not vendor:
            # E.g., "OpenAIBatchProvider" -> "openai"
            vendor = type(provider).__name__.replace('BatchProvider', '').lower()

        return prepare_schema_unified(agent_config, vendor)

    def prepare_batch_tasks_from_data(self, agent_config, data):
        # Get the appropriate provider for this agent configuration
        provider = self._get_provider_for_config(agent_config)
        
        schema = self._prepare_schema(agent_config, provider)
        if not schema:
            from agent_actions.core.exceptions import ConfigurationError
            raise ConfigurationError(
                "Schema is required for batch processing",
                context={'agent_config': agent_config.get('agent_type', 'unknown')}
            )
            
        raw_prompt = agent_config.get(PROMPT_KEY, '')
        if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
            raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
        if not raw_prompt:
            raw_prompt = "Process the following content: {content}"

        tools_path = self._resolve_tools_path(agent_config)
        if tools_path and tools_path not in sys.path:
            sys.path.insert(0, tools_path)

        self.context_map = {}
        self.side_collection = agent_config.get(SIDE_COLLECTION_KEY, [])
        
        # Check for conditional clause (legacy support)
        conditional_clause = agent_config.get("conditional_clause", "")
        
        # Check for new WHERE clause (secure)
        where_clause_config = agent_config.get("where_clause")
        
        # WHERE clause validation is handled by the filter service itself
        if where_clause_config:
            scope = where_clause_config.get("scope", "item")
            if scope != "item":
                # For non-item scope, we skip processing at agent level
                # This is handled in the workflow, not here
                where_clause_config = None
        
        # Prepare data for the provider
        prepared_data = []

        for row in data:
            # Always use target_id as the custom_id; if missing, generate a new UUID and assign it
            custom_id = row.get("target_id")
            if not custom_id:
                custom_id = ProcessorUtils.generate_target_id()
                row["target_id"] = custom_id

            # Store the full row to preserve source_guid and other metadata
            # Add metadata to track filtering behavior
            row_with_meta = row.copy()
            row_with_meta["_batch_filter_status"] = "included"  # Default status
            self.context_map[custom_id] = row_with_meta

            # Extract the actual content from wrapped structure for processing
            # This ensures dispatch functions receive the same data structure as online mode
            if 'source_guid' in row and 'content' in row:
                # Wrapped structure - extract the content
                row_content = row['content']
            else:
                # Already unwrapped or different structure
                row_content = row

            # Check for WHERE clause filtering (new secure method)
            where_clause_config = agent_config.get("where_clause")
            should_skip = False

            if where_clause_config and where_clause_config.get("scope") == "item":
                # Check behavior - only process filter behavior at batch level
                behavior = where_clause_config.get("behavior", "filter")

                if behavior == "filter":
                    # Process filter behavior at batch level (remove records)
                    try:
                        filter_service = get_global_filter()

                        # Debug logging
                        logger.info(f"WHERE clause filtering: '{where_clause_config['clause']}'")
                        logger.info(f"Row content keys: {list(row_content.keys()) if isinstance(row_content, dict) else 'Not a dict'}")
                        if isinstance(row_content, dict) and 'questionable' in row_content:
                            logger.info(f"Row questionable value: {row_content['questionable']}")

                        filter_result = filter_service.filter_item(
                            row_content,
                            where_clause_config["clause"]
                        )

                        # Handle both FilterResult objects and boolean returns
                        if hasattr(filter_result, 'success'):
                            # FilterResult object
                            logger.info(f"Filter result - success: {filter_result.success}, matched: {filter_result.matched}")
                            if filter_result.error:
                                logger.warning(f"Filter error: {filter_result.error}")

                            if not filter_result.success:
                                # Handle filter error based on configuration
                                passthrough_on_error = where_clause_config.get("passthrough_on_error", True)
                                if not passthrough_on_error:
                                    should_skip = True
                                    # Mark as filtered on error when passthrough_on_error=False
                                    if custom_id in self.context_map:
                                        self.context_map[custom_id]["_batch_filter_status"] = "filtered"
                                    logger.info("Filtering item due to filter error and passthrough_on_error=False")
                                # If passthrough_on_error is True, continue processing
                            elif not filter_result.matched:
                                # Item doesn't match WHERE clause - filter it out
                                should_skip = True
                                # Mark this item as filtered in context map
                                if custom_id in self.context_map:
                                    self.context_map[custom_id]["_batch_filter_status"] = "filtered"
                                logger.info(f"Filtering item - WHERE clause not matched")
                        else:
                            # Boolean result (legacy or simplified filter)
                            matched = bool(filter_result)
                            logger.info(f"Filter result (boolean): {matched}")

                            if not matched:
                                # Item doesn't match WHERE clause - filter it out
                                should_skip = True
                                # Mark this item as filtered in context map
                                if custom_id in self.context_map:
                                    self.context_map[custom_id]["_batch_filter_status"] = "filtered"
                                logger.info(f"Filtering item - WHERE clause not matched (boolean result)")

                    except Exception as e:
                        logger.warning(f"Error in WHERE clause evaluation: {e}")
                        passthrough_on_error = where_clause_config.get("passthrough_on_error", True)
                        if not passthrough_on_error:
                            should_skip = True
                            # Mark as filtered on error when passthrough_on_error=False
                            if custom_id in self.context_map:
                                self.context_map[custom_id]["_batch_filter_status"] = "filtered"
                elif behavior == "skip":
                    # Process skip behavior at batch level (same filtering as filter behavior)
                    try:
                        filter_service = get_global_filter()

                        # Debug logging
                        logger.info(f"WHERE clause skipping: '{where_clause_config['clause']}'")
                        logger.info(f"Row content keys: {list(row_content.keys()) if isinstance(row_content, dict) else 'Not a dict'}")
                        if isinstance(row_content, dict) and 'questionable' in row_content:
                            logger.info(f"Row questionable value: {row_content['questionable']}")

                        filter_result = filter_service.filter_item(
                            row_content,
                            where_clause_config["clause"]
                        )

                        # Handle both FilterResult objects and boolean returns
                        if hasattr(filter_result, 'success'):
                            # FilterResult object
                            logger.info(f"Skip filter result - success: {filter_result.success}, matched: {filter_result.matched}")
                            if filter_result.error:
                                logger.warning(f"Skip filter error: {filter_result.error}")

                            if not filter_result.success:
                                # Handle filter error based on configuration
                                passthrough_on_error = where_clause_config.get("passthrough_on_error", True)
                                if not passthrough_on_error:
                                    should_skip = True
                                    # Mark as skipped on error when passthrough_on_error=False
                                    if custom_id in self.context_map:
                                        self.context_map[custom_id]["_batch_filter_status"] = "skipped"
                                    logger.info("Skipping item due to filter error and passthrough_on_error=False")
                                # If passthrough_on_error is True, continue processing
                            elif not filter_result.matched:
                                # Item doesn't match WHERE clause - skip it (don't send to batch)
                                should_skip = True
                                # Mark this item as skipped in context map
                                if custom_id in self.context_map:
                                    self.context_map[custom_id]["_batch_filter_status"] = "skipped"
                                logger.info(f"Skipping item - WHERE clause not matched")
                        else:
                            # Boolean result (legacy or simplified filter)
                            matched = bool(filter_result)
                            logger.info(f"Skip filter result (boolean): {matched}")

                            if not matched:
                                # Item doesn't match WHERE clause - skip it (don't send to batch)
                                should_skip = True
                                # Mark this item as skipped in context map
                                if custom_id in self.context_map:
                                    self.context_map[custom_id]["_batch_filter_status"] = "skipped"
                                logger.info(f"Skipping item - WHERE clause not matched (boolean result)")

                    except Exception as e:
                        logger.warning(f"Error in WHERE clause evaluation: {e}")
                        passthrough_on_error = where_clause_config.get("passthrough_on_error", True)
                        if not passthrough_on_error:
                            should_skip = True
                            # Mark as skipped on error when passthrough_on_error=False
                            if custom_id in self.context_map:
                                self.context_map[custom_id]["_batch_filter_status"] = "skipped"
            
            # Legacy conditional clause support (deprecated but maintained for backwards compatibility)
            elif conditional_clause and not execute_user_defined_function(
                conditional_clause, row_content
            ):
                should_skip = True
                # Mark as skipped (not filtered) for legacy conditional clause
                if custom_id in self.context_map:
                    self.context_map[custom_id]["_batch_filter_status"] = "skipped"
            
            # Handle filtering behavior
            if should_skip:
                # should_skip is only set for filter behavior now
                # (skip behavior is handled at agent level)
                continue

            # Apply remove_collection only for rows that pass the conditional check
            processed_row = apply_remove_collection(row_content, agent_config)

            formatted_prompt, cleaned_row = PromptUtils.replace_placeholders(raw_prompt, processed_row)
            formatted_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
                formatted_prompt,
                tools_path,
                json.dumps(processed_row, ensure_ascii=False),
                agent_config=agent_config
            )
            
            # Create a prepared data item with all necessary info
            prepared_item = {
                "target_id": custom_id,
                "content": cleaned_row,
                "prompt": formatted_prompt
            }
            prepared_data.append(prepared_item)
        
        # Let the provider handle its own task format
        # Update agent_config to include the formatted prompt and compiled schema
        provider_config = agent_config.copy()
        provider_config["compiled_schema"] = schema
        
        # Use provider to prepare tasks
        tasks = provider.prepare_tasks(prepared_data, provider_config)

        return tasks

    def submit_batch_job_from_data(self, agent_config, batch_name, data, output_directory=None, force=False):
        # Check for existing in-flight batch job unless forced
        force_submission = force or BatchService.force_batch
        if not force_submission:
            existing_batch_id = self._check_for_existing_batch_job(output_directory, batch_name)
            if existing_batch_id:
                print(f"Found existing in-flight batch job for {batch_name}: {existing_batch_id}")
                print("Skipping new batch submission. Use --batch_continue to process completed batches.")
                return existing_batch_id

        tasks = self.prepare_batch_tasks_from_data(agent_config, data)
        if not tasks:
            print("No batch tasks to submit. All items filtered out by WHERE clause or conditional clause.")

            # Check behavior type - but always return the same format the workflow expects
            where_clause_config = agent_config.get("where_clause")
            if where_clause_config:
                behavior = where_clause_config.get("behavior", "filter")
                if behavior == "filter":
                    # For filter behavior, return empty passthrough data
                    print("Filter behavior detected - returning empty result set.")
                    return {"type": "passthrough", "data": [], "output_directory": output_directory}
                elif behavior == "skip":
                    # For skip behavior, return skipped items as passthrough
                    print("Skip behavior detected - returning skipped items as passthrough.")
                    return self._create_passthrough_data_from_context(agent_config, output_directory)
                else:
                    # Unknown behavior, default to passthrough
                    return self._create_passthrough_data(data, agent_config, output_directory)
            else:
                # Legacy conditional clause - return passthrough data
                return self._create_passthrough_data(data, agent_config, output_directory)

        # Save context map before submitting
        self._save_context_map(self.context_map, agent_config, output_directory, batch_name)

        try:
            # Get the appropriate provider for this agent configuration
            provider = self._get_provider_for_config(agent_config)
            provider_type = (agent_config.get('model_vendor') or agent_config.get('batch_provider') or 'openai').lower()
            
            # Use provider to submit the batch
            batch_id = provider.submit_batch(tasks, batch_name, output_directory)
            self._save_batch_job_id(batch_id, output_directory, batch_name, provider_type)
            return batch_id
        except Exception as e:
            from agent_actions.core.exceptions import ExternalServiceError
            raise ExternalServiceError(provider_type, f"Failed to submit batch job: {e}", cause=e)

    def _save_batch_job_id(self, batch_id: str, output_directory: str = None, file_name: str = None, provider_type: str = None):
        """Save batch job ID to batch registry."""
        if output_directory:
            local_batch_dir = Path(output_directory) / "batch"
            ensure_directory_exists(local_batch_dir)
            registry_file = local_batch_dir / ".batch_registry.json"
            
            # Load existing registry
            registry = {}
            if registry_file.exists():
                try:
                    with open(registry_file, 'r') as f:
                        registry = json.load(f)
                except json.JSONDecodeError:
                    registry = {}
            
            # Add new batch job
            from datetime import datetime
            registry[file_name or 'default'] = {
                'batch_id': batch_id,
                'status': 'submitted',
                'timestamp': datetime.now().isoformat(),
                'provider': provider_type or 'openai'  # Store provider type
            }
            
            # Save updated registry
            with open(registry_file, 'w') as f:
                json.dump(registry, f, indent=2)
        

    def _save_context_map(self, context_map: dict, agent_config: dict, output_directory: str, batch_name: str):
        """Persist original context data for side_collection processing."""
        if output_directory:
            batch_dir = Path(output_directory) / "batch"
        else:
            batch_dir = Path.cwd() / "batch"
        ensure_directory_exists(batch_dir)
        path = batch_dir / f"{Path(batch_name).stem}_context_map.json"
        payload = {
            "side_collection": agent_config.get(SIDE_COLLECTION_KEY, []),
            "data": context_map,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return path

    def _load_context_map(self, batch_dir: Path):
        context_files = list(batch_dir.glob("*_context_map.json"))
        if not context_files:
            return {}, []
        try:
            with open(context_files[0], "r", encoding="utf-8") as f:
                payload = json.load(f)

            raw_map = payload.get("data", {})
            # Keep the full row data to preserve source_guid and other metadata
            # The key is target_id (custom_id), the value should be the full row
            return raw_map, payload.get("side_collection", [])
        except Exception:
            return {}, []

    def _get_batch_job_id_for_file(self, output_directory: str = None, file_name: str = None):
        """Get the batch job ID for a specific file from the registry."""
        if output_directory:
            registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
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
            
        registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
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
            
        registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
        if not registry_file.exists():
            return True
            
        try:
            with open(registry_file, 'r') as f:
                registry = json.load(f)
            
            if not registry:
                return True
                
            # Check each batch job's actual status from the API
            for file_name, entry in registry.items():
                batch_id = entry.get('batch_id')
                if not batch_id:
                    continue
                    
                try:
                    actual_status = self.check_status(batch_id, str(output_directory))
                    # Update registry with actual status
                    if actual_status != entry.get('status'):
                        entry['status'] = actual_status
                        
                    # If any job is not completed, return False
                    if actual_status not in ['completed', 'failed', 'cancelled']:
                        return False
                        
                except Exception:
                    # If we can't check status, consider it not completed
                    return False
            
            # Save updated registry
            with open(registry_file, 'w') as f:
                json.dump(registry, f, indent=2)
                
            return True
            
        except (json.JSONDecodeError, KeyError):
            return True

    def _get_batch_registry_status(self, output_directory: str) -> str:
        """Get the overall status of all batch jobs in the registry."""
        if not output_directory:
            return 'no_batches'
            
        registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
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

    def _get_last_batch_job_id(self, output_directory: str = None):
        """Backward compatibility method - gets the most recent batch job ID."""
        if output_directory:
            registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
            if registry_file.exists():
                try:
                    with open(registry_file, 'r') as f:
                        registry = json.load(f)
                    # Return the most recent batch job ID
                    if registry:
                        latest_entry = max(registry.values(), key=lambda x: x.get('timestamp', ''))
                        return latest_entry.get('batch_id')
                except json.JSONDecodeError:
                    pass
        
        return None
    
    def _check_for_existing_batch_job(self, output_directory: str = None, file_name: str = None):
        """Check if there's already an in-flight batch job for this specific file."""
        batch_id = self._get_batch_job_id_for_file(output_directory, file_name)
        if not batch_id:
            return None
        
        try:
            status = self.check_status(batch_id, output_directory)
            # Update registry with current status
            if output_directory and file_name:
                self._update_batch_registry_status(output_directory, file_name, batch_id, status)
            
            # If batch is still processing, return the batch ID
            if status in ['validating', 'in_progress', 'finalizing']:
                return batch_id
            # If completed or failed, we can proceed with a new batch
            return None
        except Exception:
            # If we can't check status, assume we can proceed
            return None

    def _get_provider_for_batch_id(self, batch_id: str, output_directory: str = None) -> BatchProvider:
        """
        Get the provider that was used for a specific batch ID.
        
        Args:
            batch_id: The batch job ID
            output_directory: Output directory to look for registry
            
        Returns:
            BatchProvider instance
        """
        # First check the registry if we have output directory
        if output_directory:
            registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
            if registry_file.exists():
                try:
                    with open(registry_file, 'r') as f:
                        registry = json.load(f)
                    
                    # Look for the batch ID in registry entries
                    for entry in registry.values():
                        if entry.get('batch_id') == batch_id:
                            provider_type = entry.get('provider', 'openai')
                            if provider_type in self._provider_cache:
                                return self._provider_cache[provider_type]
                            else:
                                # Create provider if not cached
                                return BatchProviderFactory.create_provider(provider_type)
                except Exception:
                    pass
        
        # Fallback to default provider
        return self.provider
    
    def check_status(self, batch_id: str, output_directory: str = None):
        try:
            provider = self._get_provider_for_batch_id(batch_id, output_directory)
            return provider.check_status(batch_id)
        except Exception as e:
            from agent_actions.core.exceptions import ExternalServiceError
            raise ExternalServiceError(self.vendor_type or 'unknown', f"Failed to check batch status: {e}", cause=e)

    # This is the function that retrieves the job 
    # Muizzchange
    def retrieve_results(self, batch_id: str, output_dir: str, file_path: str = None):
        try:
            # Get the appropriate provider for this batch ID
            provider = self._get_provider_for_batch_id(batch_id, output_dir)
            
            # Use provider to get results
            batch_results = provider.retrieve_results(batch_id, output_dir)
            
            # The provider already saves raw results, but we need to maintain
            # compatibility with the existing interface that returns a file path
            output_path = Path(output_dir)
            
            # Use original file name if provided (like batch1.json -> batch1_results.jsonl)
            if file_path:
                original_file_name = Path(file_path).stem  # Gets 'batch1' from 'batch1.json'
                result_file_name = output_path / f"{original_file_name}_results.jsonl"
            else:
                # Fallback to batch_id naming
                result_file_name = output_path / f"{batch_id}_results.jsonl"
            
            # Check if provider already saved the file
            if result_file_name.exists():
                return result_file_name
            else:
                # If not, we can save the transformed results for compatibility
                ensure_directory_exists(output_path)
                with open(result_file_name, 'w') as f:
                    for result in batch_results:
                        # Convert BatchResult back to a format similar to OpenAI's raw format
                        # for backward compatibility
                        raw_format = {
                            "custom_id": result.custom_id,
                            "response": {
                                "body": {
                                    "choices": [{"message": {"content": json.dumps(result.content)}}],
                                    "usage": result.usage
                                }
                            }
                        }
                        f.write(json.dumps(raw_format) + '\n')
                return result_file_name
        except Exception as e:
            from agent_actions.core.exceptions import ExternalServiceError
            raise ExternalServiceError(self.vendor_type or 'unknown', f"Failed to retrieve batch results: {e}", cause=e)

    def process_batch_results_to_workflow_output(self, batch_id: str, output_directory: str, base_directory: str, file_path: str):
        """
        Process batch results and integrate them into the workflow output system.
        
        Args:
            batch_id: The batch job ID
            output_directory: The target output directory (e.g., node_X_agenttype)
            base_directory: The base directory for relative path calculation
            file_path: The original file path being processed
        """
        try:
            # Get the appropriate provider for this batch ID
            provider = self._get_provider_for_batch_id(batch_id, output_directory)
            
            # Check status first
            status = provider.check_status(batch_id)
            if status != 'completed':
                from agent_actions.core.exceptions import ProcessingError
                raise ProcessingError(
                    "Batch job is not completed",
                    context={'batch_id': batch_id, 'status': status}
                )
            
            # Use provider to get results - already transformed to BatchResult format
            batch_results = provider.retrieve_results(batch_id, output_directory)
            
            batch_dir = Path(output_directory) / "batch"
            context_map, side_collection = self._load_context_map(batch_dir)

            # Process results into workflow format
            processed_data = self._convert_batch_results_to_workflow_format(
                batch_results,
                side_collection=side_collection,
                context_map=context_map,
                output_directory=output_directory,
            )

            main_output, side_output_data = self._separate_side_output(processed_data)
            
            # Save to workflow output directory structure
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
            from agent_actions.core.exceptions import ProcessingError
            raise ProcessingError(f"Failed to process batch results to workflow output: {e}", cause=e)

    def _convert_batch_results_to_workflow_format(self, batch_results, *, side_collection=None, context_map=None, output_directory=None, agent_config=None):
        """
        Convert batch provider results to the workflow's expected format.
        Works with standardized BatchResult objects from any provider.

        Args:
            batch_results: List of BatchResult objects from provider
            side_collection: List of side collection fields
            context_map: Map of custom_id to original row data
            output_directory: Output directory path to extract node information
            agent_config: Agent configuration (needed for loop correlation ID)

        Returns:
            List of processed data in workflow format
        """
        processed_data = []
        context_map = context_map or {}
        side_collection = side_collection or []
        
        # Extract node index from output directory (e.g., "node_0_summary")
        node_idx = None
        if output_directory:
            import re
            match = re.search(r'node_(\d+)_(\w+)', str(output_directory))
            if match:
                node_idx = int(match.group(1))
        
        # Track which custom_ids were processed by the batch API
        processed_custom_ids = set()
        
        #muizzchange this is the transformed data we use for the output
        # This is where we transform the data to what we want which matches usual agent actions flow 
        
        #===start here===#
        for batch_result in batch_results:
            # Now working with standardized BatchResult objects from any provider
            custom_id = batch_result.custom_id
            
            if batch_result.success and batch_result.content is not None:
                try:
                    # Content is already parsed by the provider
                    generated_obj = batch_result.content
                    
                    # Normalize to a list for consistent processing
                    generated_list = DataTransformer.ensure_list(generated_obj)

                    # Get the original source_guid from the stored row
                    original_row = context_map.get(custom_id, {})
                    original_source_guid = original_row.get("source_guid", custom_id)

                    if side_collection and custom_id in context_map:
                        original_content = original_row.get("content", original_row)
                        generated_list = [
                            DataTransformer.update_schema_objects(original_content, item, side_collection)
                            if isinstance(item, dict) else item
                            for item in generated_list
                        ]

                    # Use the original source_guid instead of custom_id
                    structured_items = DataTransformer.transform_structure(
                        [{original_source_guid: generated_list}]
                    )

                    for idx, itm in enumerate(structured_items):
                        # Use metadata from BatchResult
                        itm["metadata"] = batch_result.metadata or {}

                        # Add node_id and lineage tracking
                        if node_idx is not None:
                            # Generate a unique node_id for each item
                            item_node_id = ProcessorUtils.generate_node_id(node_idx)
                            itm["node_id"] = item_node_id

                            # Use ProcessorUtils for lineage tracking
                            itm["lineage"] = ProcessorUtils.build_lineage(original_row, item_node_id)

                        # Ensure target_id and source_guid are set
                        if 'target_id' not in itm or not itm['target_id']:
                            itm['target_id'] = original_row.get('target_id', ProcessorUtils.generate_target_id())
                        if 'source_guid' not in itm or not itm['source_guid']:
                            itm['source_guid'] = original_source_guid

                        # Add loop correlation ID if agent is part of a loop
                        if agent_config:
                            # Get the record index from context_map (position in original batch)
                            record_index = None
                            if custom_id and context_map:
                                # Find the position of this record in the context_map
                                context_keys = list(context_map.keys())
                                if custom_id in context_keys:
                                    record_index = context_keys.index(custom_id)

                            # add_loop_correlation_id returns a new dict, so update the list
                            structured_items[idx] = ProcessorUtils.add_loop_correlation_id(itm, agent_config, record_index=record_index)

                    processed_data.extend(structured_items)
                    processed_custom_ids.add(custom_id)
                    
                except Exception as e:
                    # Get the original source_guid for error cases too
                    original_row = context_map.get(custom_id, {})
                    original_source_guid = original_row.get("source_guid", custom_id)
                    
                    # If processing fails, wrap in error structure
                    error_item = {
                        "source_guid": original_source_guid,
                        "error": f"Processing error: {str(e)}",
                        "raw_content": batch_result.content,
                        "metadata": batch_result.metadata or {}
                    }
                    processed_data.append(error_item)
                    processed_custom_ids.add(custom_id)
            else:
                # Handle error cases from BatchResult
                original_row = context_map.get(custom_id, {})
                original_source_guid = original_row.get("source_guid", custom_id or 'unknown')
                
                error_item = {
                    "source_guid": original_source_guid,
                    "error": batch_result.error or "Batch processing failed",
                    "metadata": batch_result.metadata or {}
                }
                processed_data.append(error_item)
                processed_custom_ids.add(custom_id)
        #===end here===#
        
        # Process records that were skipped (not filtered) by conditional clause
        # These are in context_map but not in batch_results
        for custom_id, original_row in context_map.items():
            if custom_id not in processed_custom_ids:
                # Check filter status to determine if we should include this item
                filter_status = original_row.get("_batch_filter_status", "included")

                if filter_status == "filtered":
                    # Items with filter behavior should be completely excluded from output
                    continue
                elif filter_status in ["skipped", "included"]:
                    # This record was skipped (not filtered) due to conditional clause
                    # Pass it through unmodified to maintain the full data flow
                    original_source_guid = original_row.get("source_guid", custom_id)

                    # Create a passthrough item that preserves all original data
                    passthrough_item = original_row.copy()

                    # Remove internal metadata before output
                    passthrough_item.pop("_batch_filter_status", None)

                    # Ensure required fields are set
                    if 'target_id' not in passthrough_item or not passthrough_item['target_id']:
                        passthrough_item['target_id'] = custom_id
                    if 'source_guid' not in passthrough_item or not passthrough_item['source_guid']:
                        passthrough_item['source_guid'] = original_source_guid

                    # Add node_id and lineage tracking for consistency
                    if node_idx is not None:
                        item_node_id = ProcessorUtils.generate_node_id(node_idx)
                        passthrough_item["node_id"] = item_node_id

                        # Use ProcessorUtils for lineage tracking
                        passthrough_item["lineage"] = ProcessorUtils.build_lineage(original_row, item_node_id)

                    # Add metadata to indicate this was skipped by conditional
                    passthrough_item["metadata"] = {
                        "skipped_by_conditional": True,
                        "agent_type": "passthrough"
                    }

                    processed_data.append(passthrough_item)
        
        return processed_data

    def check_and_process_completed_batches(self, output_directory: str, base_directory: str):
        """
        Check for completed batch jobs and process their results into workflow output.
        
        Args:
            output_directory: The target output directory
            base_directory: The base directory for relative paths
            
        Returns:
            List of processed file paths
        """
        processed_files = []
        
        # Look for batch placeholder files in the output directory
        placeholder_files = list(Path(output_directory).rglob("*.json"))
        
        for placeholder_file in placeholder_files:
            try:
                with open(placeholder_file, 'r') as f:
                    placeholder_data = json.load(f)
                
                # Check if this is a batch placeholder
                if (isinstance(placeholder_data, dict) and 
                    placeholder_data.get('status') == 'submitted' and
                    'batch_job_id' in placeholder_data):
                    
                    batch_id = placeholder_data['batch_job_id']
                    
                    # Check if batch is completed
                    if self.check_status(batch_id, str(output_directory)) == 'completed':
                        # Process the batch results
                        original_file_path = placeholder_file
                        processed_file = self.process_batch_results_to_workflow_output(
                            batch_id, 
                            output_directory, 
                            base_directory, 
                            str(original_file_path)
                        )
                        processed_files.append(processed_file)
                        
            except Exception as e:
                print(f"Warning: Failed to process batch placeholder {placeholder_file}: {e}")
                continue
        
        return processed_files

    def process_batch_results_to_workflow_output_direct(self, batch_id: str, output_directory: str):
        """
        Retrieves, processes, and saves batch results directly without a placeholder.
        Uses the locally saved results file from retrieve_results.
        """
        try:
            # Get the appropriate provider for this batch ID
            provider = self._get_provider_for_batch_id(batch_id, output_directory)
            
            # Use provider to get results - already transformed to BatchResult format
            batch_results = provider.retrieve_results(batch_id, output_directory)
            
            print(f"Retrieved {len(batch_results)} batch results")
            
            batch_dir = Path(output_directory) / "batch"
            context_map, side_collection = self._load_context_map(batch_dir)

            # Process results into workflow format
            processed_data = self._convert_batch_results_to_workflow_format(
                batch_results,
                side_collection=side_collection,
                context_map=context_map,
                output_directory=output_directory,
            )

            print(f"Processed {len(processed_data)} items into workflow format")

            main_output, side_output_data = self._separate_side_output(processed_data)

            # Find the original staging file to use its name (like batch_15.json)
            staging_dir = Path(output_directory).parent.parent / "staging"
            original_file_name = None
            
            if staging_dir.exists():
                # Look for .json files in staging directory
                json_files = list(staging_dir.glob("*.json"))
                if json_files:
                    # Use the first json file found (or you could match by some other criteria)
                    original_file_name = json_files[0].stem  # Gets 'batch_15' from 'batch_15.json'
            
            # Create output filename based on original file name or fallback to batch_id
            if original_file_name:
                output_file_path = Path(output_directory) / f"{original_file_name}.json"
            else:
                output_file_path = Path(output_directory) / f"{batch_id}_processed_output.json"
            
            ensure_directory_exists(output_file_path, is_file=True)
            
            file_writer = FileWriter(str(output_file_path))
            file_writer.write_target(main_output)

            if side_output_data:
                side_output_dir = create_side_output_directory(output_directory)
                if original_file_name:
                    side_output_file = side_output_dir / f"{original_file_name}.json"
                else:
                    side_output_file = side_output_dir / f"{batch_id}_processed_output.json"
                self._save_side_output(side_output_data, side_output_file)

            return str(output_file_path)
            
        except Exception as e:
            from agent_actions.core.exceptions import ProcessingError
            raise ProcessingError(f"Failed to process batch results to workflow output: {e}", cause=e)

    def process_all_batch_results_to_workflow_output(self, output_directory: str, agent_config: Dict[str, Any] = None):
        """
        Process all completed batch jobs in the registry, maintaining file-to-file mapping.
        Each input file produces its own corresponding output file.

        Args:
            output_directory: Path to the agent's output directory
            agent_config: Agent configuration (needed for loop correlation ID)
        """
        try:
            batch_dir = Path(output_directory) / "batch"
            registry_file = batch_dir / ".batch_registry.json"

            if not registry_file.exists():
                from agent_actions.core.exceptions import ProcessingError
                raise ProcessingError(
                    "No batch registry found",
                    context={'registry_file': str(registry_file), 'output_directory': output_directory}
                )
            
            # Load registry
            with open(registry_file, 'r') as f:
                registry = json.load(f)
            
            # Load context map and side collection once
            context_map, side_collection = self._load_context_map(batch_dir)
            
            processed_files = []
            
            # Process each batch job separately to maintain file mapping
            for file_name, entry in registry.items():
                batch_id = entry.get('batch_id')
                if not batch_id:
                    continue
                    
                # Check if batch is completed
                try:
                    batch_status = self.check_status(batch_id, str(output_directory))
                    if batch_status != 'completed':
                        print(f"Batch {batch_id} for {file_name} is not completed: {batch_status}")
                        continue
                except Exception as e:
                    print(f"Could not check status for batch {batch_id}: {e}")
                    continue
                
                # Get batch results for this specific file
                try:
                    # Get the appropriate provider for this batch ID
                    provider = self._get_provider_for_batch_id(batch_id, output_directory)
                    
                    # Use provider to get results - already transformed to BatchResult format
                    batch_results = provider.retrieve_results(batch_id, output_directory)
                    
                    if not batch_results:
                        print(f"No results found for batch {batch_id} ({file_name})")
                        continue
                    
                    print(f"Processing {len(batch_results)} batch results for {file_name}")
                    
                    # Process results for this file into workflow format
                    processed_data = self._convert_batch_results_to_workflow_format(
                        batch_results,
                        side_collection=side_collection,
                        context_map=context_map,
                        output_directory=output_directory,
                        agent_config=agent_config,
                    )

                    main_output, side_output_data = self._separate_side_output(processed_data)

                    # Create output filename based on original file name
                    if file_name and file_name != 'default':
                        # Use the original file name from registry
                        output_file_path = Path(output_directory) / f"{Path(file_name).stem}.json"
                    else:
                        # Fallback to batch_id naming
                        output_file_path = Path(output_directory) / f"{batch_id}_processed_output.json"
                    
                    ensure_directory_exists(output_file_path, is_file=True)
                    
                    # Write results for this specific file
                    file_writer = FileWriter(str(output_file_path))
                    file_writer.write_target(main_output)

                    if side_output_data:
                        side_output_dir = create_side_output_directory(output_directory)
                        if file_name and file_name != 'default':
                            side_output_file = side_output_dir / f"{Path(file_name).stem}.json"
                        else:
                            side_output_file = side_output_dir / f"{batch_id}_processed_output.json"
                        self._save_side_output(side_output_data, side_output_file)
                    
                    processed_files.append(str(output_file_path))
                    print(f"✅ Processed {file_name} → {output_file_path}")
                    
                except Exception as e:
                    error_msg = f"Could not process batch results for {file_name} (batch {batch_id}): {e}"
                    print(f"[ERROR] {error_msg}")
                    print(f"[DEBUG] Batch ID: {batch_id}")
                    print(f"[DEBUG] File name: {file_name}")
                    print(f"[DEBUG] Output directory: {output_directory}")
                    if 'json.JSONDecodeError' in str(type(e)):
                        print(f"[DEBUG] This appears to be a JSON parsing error. Check the batch results file for malformed JSON.")
                    continue
            
            if not processed_files:
                from agent_actions.core.exceptions import ProcessingError
                raise ProcessingError(
                    "No batch results were successfully processed",
                    context={'output_directory': output_directory, 'registry_entries': len(registry)}
                )
            
            print(f"Successfully processed {len(processed_files)} files")
            return processed_files
            
        except Exception as e:
            from agent_actions.core.exceptions import ProcessingError
            raise ProcessingError(f"Failed to process all batch results to workflow output: {e}", cause=e)