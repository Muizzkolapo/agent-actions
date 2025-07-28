import json
import sys
from pathlib import Path
import yaml
from agent_actions.handlers.agent_handlers import AgentManager
from openai import OpenAI
from agent_actions.handlers.config_handler import ConfigManager
from agent_actions.processors.data_loaders.batch_data_loader import BatchDataLoader
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.processors.prompt_processor.prompt_utils import PromptUtils
from agent_actions.handlers.schema_handler import SchemaLoader
from agent_actions.models.schema_change import compile_unified_schema
from agent_actions.handlers.file_writer import FileWriter
from agent_actions.transformers.data_transformer import DataTransformer
from agent_actions.constants import PROMPT_KEY, SCHEMA_NAME_KEY, SIDE_COLLECTION_KEY
from agent_actions.processors.common.utils import apply_remove_collection
from agent_actions.core.tooling import execute_user_defined_function
import uuid

class BatchService:
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
        output_src_path.parent.mkdir(parents=True, exist_ok=True)
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
    
    def __init__(self):
        self.data_loader = BatchDataLoader()
        self.client = OpenAI()
        self.context_map = {}
        self.side_collection = []

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
        file_path.parent.mkdir(parents=True, exist_ok=True)

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
            return str(Path(path).resolve())

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
                return str(Path(project_root / tool_path[0]).resolve()) if tool_path else None
            if tool_path:
                return str(Path(project_root / tool_path).resolve())
        except Exception:
            return None

        return None

    def _prepare_schema(self, agent_config):
        """Load and prepare schema from config"""
        schema_name = agent_config.get(SCHEMA_NAME_KEY)
        if not schema_name:
            return None
        
        base_schema = SchemaLoader.load_schema(schema_name)
        return compile_unified_schema(base_schema, 'openai')

    def prepare_batch_tasks_from_data(self, agent_config, data):
        schema = self._prepare_schema(agent_config)
        if not schema:
            raise ValueError("Schema is required for batch processing")
            
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
        tasks = []
        
        # Check for conditional clause
        conditional_clause = agent_config.get("conditional_clause", "").lower()
        
        for row in data:
            # Always use target_id as the custom_id; if missing, generate a new UUID and assign it
            custom_id = row.get("target_id")
            if not custom_id:
                custom_id = str(uuid.uuid4())
                row["target_id"] = custom_id

            # Store the full row to preserve source_guid and other metadata
            self.context_map[custom_id] = row

            # Skip processing if conditional clause is present and evaluates to False
            if conditional_clause and not execute_user_defined_function(
                conditional_clause, row
            ):
                # Store the original row without processing for conditional failures
                continue

            # Apply remove_collection only for rows that pass the conditional check
            processed_row = apply_remove_collection(row, agent_config)

            formatted_prompt, cleaned_row = PromptUtils.replace_placeholders(raw_prompt, processed_row)
            formatted_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
                formatted_prompt,
                tools_path,
                json.dumps(processed_row, ensure_ascii=False),
                agent_config=agent_config
            )
            
            task = {
                    # Unique ID to match results back to the original input
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": agent_config.get('model_name', 'gpt-4.1-mini'),
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": schema
                        },
                        "messages": [
                            {"role": "system", "content": formatted_prompt},
                            {"role": "user", "content":  json.dumps(cleaned_row)}
                        ],
                    }
                }
            tasks.append(task)
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
            print("No batch tasks to submit.")
            return None

        # Create batch directory in the node-specific output directory if provided
        if output_directory:
            batch_dir = Path(output_directory) / "batch"
        else:
            # Fallback to global batch directory
            batch_dir = Path.cwd() / "batch"
        
        batch_dir.mkdir(parents=True, exist_ok=True)
        
        file_name = f"{Path(batch_name).stem}_batch_input.jsonl"
        file_path = batch_dir / file_name

        with open(file_path, 'w') as file:
            for obj in tasks:
                file.write(json.dumps(obj) + '\n')

        print(f"Batch file created at: {file_path}")
        self._save_context_map(self.context_map, agent_config, output_directory, batch_name)

        try:
            batch_file = self.client.files.create(file=open(file_path, "rb"), purpose="batch")
            batch_job = self.client.batches.create(
                input_file_id=batch_file.id,
                endpoint="/v1/chat/completions",
                completion_window="24h"
            )
            print(f"Batch job created with ID: {batch_job.id}")
            self._save_batch_job_id(batch_job.id, output_directory, batch_name)
            return batch_job.id
        except Exception as e:
            raise RuntimeError(f"Error submitting batch job: {e}")

    def _save_batch_job_id(self, batch_id: str, output_directory: str = None, file_name: str = None):
        """Save batch job ID to batch registry."""
        if output_directory:
            local_batch_dir = Path(output_directory) / "batch"
            local_batch_dir.mkdir(parents=True, exist_ok=True)
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
                'timestamp': datetime.now().isoformat()
            }
            
            # Save updated registry
            with open(registry_file, 'w') as f:
                json.dump(registry, f, indent=2)
        
        # Save to global batch directory (for backward compatibility)
        global_batch_dir = Path.cwd() / "batch"
        global_batch_dir.mkdir(exist_ok=True)
        global_job_id_file = global_batch_dir / ".last_batch_id"
        with open(global_job_id_file, 'w') as f:
            f.write(batch_id)

    def _save_context_map(self, context_map: dict, agent_config: dict, output_directory: str, batch_name: str):
        """Persist original context data for side_collection processing."""
        if output_directory:
            batch_dir = Path(output_directory) / "batch"
        else:
            batch_dir = Path.cwd() / "batch"
        batch_dir.mkdir(parents=True, exist_ok=True)
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
        
        # Fall back to global directory for backward compatibility
        global_job_id_file = Path.cwd() / "batch" / ".last_batch_id"
        if global_job_id_file.exists():
            with open(global_job_id_file, 'r') as f:
                return f.read().strip()
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
                    actual_status = self.check_status(batch_id)
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
                    actual_status = self.check_status(batch_id)
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
        
        # Fall back to global directory
        global_job_id_file = Path.cwd() / "batch" / ".last_batch_id"
        if global_job_id_file.exists():
            with open(global_job_id_file, 'r') as f:
                return f.read().strip()
        return None
    
    def _check_for_existing_batch_job(self, output_directory: str = None, file_name: str = None):
        """Check if there's already an in-flight batch job for this specific file."""
        batch_id = self._get_batch_job_id_for_file(output_directory, file_name)
        if not batch_id:
            return None
        
        try:
            status = self.check_status(batch_id)
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

    def check_status(self, batch_id: str):
        try:
            batch_job = self.client.batches.retrieve(batch_id)
            return batch_job.status
        except Exception as e:
            raise RuntimeError(f"Error checking batch status: {e}")

    # This is the function that retrieves the job 
    # Muizzchange
    def retrieve_results(self, batch_id: str, output_dir: str, file_path: str = None):
        try:
            batch_job = self.client.batches.retrieve(batch_id)
            if batch_job.status == 'completed':
                result_file_id = batch_job.output_file_id
                
                # Add retry logic for file retrieval
                max_retries = 3
                retry_delay = 2  # seconds
                last_error = None
                
                for attempt in range(max_retries):
                    try:
                        result = self.client.files.content(result_file_id).content
                        # Validate that we got content
                        if not result or len(result) == 0:
                            raise ValueError("Retrieved empty content from batch results")
                        break
                    except Exception as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            print(f"Retry {attempt + 1}/{max_retries}: Failed to retrieve batch results: {e}")
                            import time
                            time.sleep(retry_delay)
                        else:
                            raise RuntimeError(f"Failed to retrieve batch results after {max_retries} attempts: {last_error}")
                
                output_path = Path(output_dir)
                output_path.mkdir(exist_ok=True)
                
                # Use original file name if provided (like batch1.json -> batch1_results.jsonl)
                if file_path:
                    original_file_name = Path(file_path).stem  # Gets 'batch1' from 'batch1.json'
                    result_file_name = output_path / f"{original_file_name}_results.jsonl"
                else:
                    # Fallback to batch_id naming
                    result_file_name = output_path / f"{batch_id}_results.jsonl"
                
                with open(result_file_name, 'wb') as file:
                    file.write(result)
                return result_file_name
            else:
                return f"Batch job is not completed yet. Status: {batch_job.status}"
        except Exception as e:
            raise RuntimeError(f"Error retrieving batch results: {e}")

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
            # Retrieve batch results
            batch_job = self.client.batches.retrieve(batch_id)
            if batch_job.status != 'completed':
                raise ValueError(f"Batch job {batch_id} is not completed. Status: {batch_job.status}")
                
            result_file_id = batch_job.output_file_id
            #this is where we load the file for the processng
            
            # Add retry logic for file retrieval
            max_retries = 3
            retry_delay = 2
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    result_content = self.client.files.content(result_file_id).content
                    if not result_content or len(result_content) == 0:
                        raise ValueError("Retrieved empty content from batch results")
                    break
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        print(f"Retry {attempt + 1}/{max_retries}: Failed to retrieve batch results: {e}")
                        import time
                        time.sleep(retry_delay)
                    else:
                        raise RuntimeError(f"Failed to retrieve batch results after {max_retries} attempts: {last_error}")
            
            # Parse batch results with error handling
            batch_results = []
            lines = result_content.decode('utf-8').strip().split('\n')
            for line_num, line in enumerate(lines, 1):
                if line.strip():
                    try:
                        batch_results.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"[ERROR] JSON parsing error on line {line_num}: {e}")
                        print(f"[DEBUG] Line position: character {e.pos if hasattr(e, 'pos') else 'unknown'}")
                        print(f"[DEBUG] Problematic content (first 500 chars): {line[:500]}...")
                        if len(line) > 500:
                            print(f"[DEBUG] Line length: {len(line)} characters")
                        # Continue processing other lines instead of failing completely
                        continue
            
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
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_writer = FileWriter(str(output_file_path))
            file_writer.write_target(main_output)

            if side_output_data:
                side_output_dir = Path(output_directory).parent / 'side_output'
                side_output_file_path = side_output_dir / relative_path.name
                self._save_side_output(side_output_data, side_output_file_path)

            return str(output_file_path)
            
        except Exception as e:
            raise RuntimeError(f"Error processing batch results to workflow output: {e}")

    def _convert_batch_results_to_workflow_format(self, batch_results, *, side_collection=None, context_map=None, output_directory=None):
        """
        Convert batch API results to the workflow's expected format.
        Extracts content and preserves metadata, matching non-batch agent output format.
        
        Args:
            batch_results: List of batch API result objects
            side_collection: List of side collection fields
            context_map: Map of custom_id to original row data
            output_directory: Output directory path to extract node information
            
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
        for result in batch_results:
            # The 'response' key contains the main data, including the body
            response_data = result.get('response')
            custom_id = result.get('custom_id')

            if response_data and response_data.get('body'):
                response_body = response_data['body']
                
                # Extract the generated content
                if 'choices' in response_body and response_body['choices']:
                    choice = response_body['choices'][0]
                    if 'message' in choice and 'content' in choice['message']:
                        content = choice['message']['content']
                        
                        try:
                            # Parse JSON content from the response
                            generated_obj = json.loads(content)

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

                            for itm in structured_items:
                                itm["metadata"] = {
                                    "model": response_body.get("model"),
                                    "usage": response_body.get("usage"),
                                    "finish_reason": choice.get("finish_reason"),
                                    "created": response_body.get("created"),
                                    "system_fingerprint": response_body.get(
                                        "system_fingerprint"
                                    ),
                                }
                                
                                # Add node_id and lineage tracking
                                if node_idx is not None:
                                    # Generate a unique node_id for each item
                                    item_node_id = f"node_{node_idx}_{uuid.uuid4()}"
                                    itm["node_id"] = item_node_id
                                    
                                    # Get lineage from original row
                                    original_lineage = original_row.get("lineage", [])
                                    if isinstance(original_lineage, list):
                                        # Filter to keep only node_* entries and add current node
                                        filtered_lineage = [nid for nid in original_lineage if isinstance(nid, str) and nid.startswith('node_')]
                                        itm["lineage"] = filtered_lineage + [item_node_id]
                                    else:
                                        itm["lineage"] = [item_node_id]
                                
                                # Ensure target_id and source_guid are set
                                if 'target_id' not in itm or not itm['target_id']:
                                    itm['target_id'] = original_row.get('target_id', str(uuid.uuid4()))
                                if 'source_guid' not in itm or not itm['source_guid']:
                                    itm['source_guid'] = original_source_guid
                                    
                            processed_data.extend(structured_items)
                            processed_custom_ids.add(custom_id)
                            
                        except json.JSONDecodeError:
                            # Get the original source_guid for error cases too
                            original_row = context_map.get(custom_id, {})
                            original_source_guid = original_row.get("source_guid", custom_id)
                            
                            # If not valid JSON, wrap in error structure
                            error_item = {
                                "source_guid": original_source_guid,
                                "error": "Invalid JSON response",
                                "raw_content": content,
                                "metadata": {
                                    "model": response_body.get('model'),
                                    "finish_reason": choice.get('finish_reason', 'error')
                                }
                            }
                            processed_data.append(error_item)
                            processed_custom_ids.add(custom_id)
            else:
                # Handle error cases where 'response' or 'body' is missing
                original_row = context_map.get(custom_id, {})
                original_source_guid = original_row.get("source_guid", custom_id or 'unknown')
                
                error_item = {
                    "source_guid": original_source_guid,
                    "error": "Batch processing failed or missing response body",
                    "raw_result": result
                }
                processed_data.append(error_item)
                processed_custom_ids.add(custom_id)
        #===end here===#
        
        # Process records that were filtered out by conditional clause
        # These are in context_map but not in batch_results
        for custom_id, original_row in context_map.items():
            if custom_id not in processed_custom_ids:
                # This record was skipped due to conditional clause
                # Pass it through unmodified to maintain the full data flow
                original_source_guid = original_row.get("source_guid", custom_id)
                
                # Create a passthrough item that preserves all original data
                passthrough_item = original_row.copy()
                
                # Ensure required fields are set
                if 'target_id' not in passthrough_item or not passthrough_item['target_id']:
                    passthrough_item['target_id'] = custom_id
                if 'source_guid' not in passthrough_item or not passthrough_item['source_guid']:
                    passthrough_item['source_guid'] = original_source_guid
                
                # Add node_id and lineage tracking for consistency
                if node_idx is not None:
                    item_node_id = f"node_{node_idx}_{uuid.uuid4()}"
                    passthrough_item["node_id"] = item_node_id
                    
                    # Get lineage from original row
                    original_lineage = original_row.get("lineage", [])
                    if isinstance(original_lineage, list):
                        filtered_lineage = [nid for nid in original_lineage if isinstance(nid, str) and nid.startswith('node_')]
                        passthrough_item["lineage"] = filtered_lineage + [item_node_id]
                    else:
                        passthrough_item["lineage"] = [item_node_id]
                
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
                    if self.check_status(batch_id) == 'completed':
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
            # First, check if results were already saved locally by retrieve_results
            batch_dir = Path(output_directory) / "batch"
            local_results_file = batch_dir / f"{batch_id}_results.jsonl"
            
            if local_results_file.exists():
                # Use the locally saved results
                print(f"Using locally saved results from: {local_results_file}")
                with open(local_results_file, 'r') as f:
                    result_content = f.read()
            else:
                # Fallback to API retrieval if local file doesn't exist
                print(f"Local results file not found, retrieving from API...")
                batch_job = self.client.batches.retrieve(batch_id)
                if batch_job.status != 'completed':
                    raise ValueError(f"Batch job {batch_id} is not completed. Status: {batch_job.status}")
                    
                result_file_id = batch_job.output_file_id
                result_content = self.client.files.content(result_file_id).content.decode('utf-8')
                
            
            # Parse batch results with error handling
            #muizz change this is where we get the outcpme of the run like the result from the model
            batch_results = []
            lines = result_content.strip().split('\n')
            for line_num, line in enumerate(lines, 1):
                if line.strip():
                    try:
                        batch_results.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"[ERROR] JSON parsing error on line {line_num}: {e}")
                        print(f"[DEBUG] Line position: character {e.pos if hasattr(e, 'pos') else 'unknown'}")
                        print(f"[DEBUG] Problematic content (first 500 chars): {line[:500]}...")
                        if len(line) > 500:
                            print(f"[DEBUG] Line length: {len(line)} characters")
                        # Continue processing other lines instead of failing completely
                        continue
            
            print(f"Parsed {len(batch_results)} batch results")
            
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
            
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_writer = FileWriter(str(output_file_path))
            file_writer.write_target(main_output)

            if side_output_data:
                side_output_dir = Path(output_directory).parent / "side_output"
                if original_file_name:
                    side_output_file = side_output_dir / f"{original_file_name}.json"
                else:
                    side_output_file = side_output_dir / f"{batch_id}_processed_output.json"
                self._save_side_output(side_output_data, side_output_file)

            return str(output_file_path)
            
        except Exception as e:
            raise RuntimeError(f"Error processing batch results to workflow output: {e}")

    def process_all_batch_results_to_workflow_output(self, output_directory: str):
        """
        Process all completed batch jobs in the registry, maintaining file-to-file mapping.
        Each input file produces its own corresponding output file.
        """
        try:
            batch_dir = Path(output_directory) / "batch"
            registry_file = batch_dir / ".batch_registry.json"
            
            if not registry_file.exists():
                raise ValueError(f"No batch registry found at {registry_file}")
            
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
                    batch_status = self.check_status(batch_id)
                    if batch_status != 'completed':
                        print(f"Batch {batch_id} for {file_name} is not completed: {batch_status}")
                        continue
                except Exception as e:
                    print(f"Could not check status for batch {batch_id}: {e}")
                    continue
                
                # Get batch results for this specific file
                try:
                    local_results_file = batch_dir / f"{batch_id}_results.jsonl"
                    
                    if local_results_file.exists():
                        with open(local_results_file, 'r') as f:
                            result_content = f.read()
                    else:
                        # Fallback to API retrieval
                        batch_job = self.client.batches.retrieve(batch_id)
                        result_file_id = batch_job.output_file_id
                        result_content = self.client.files.content(result_file_id).content.decode('utf-8')
                    
                    # Parse batch results for this specific file
                    batch_results = []
                    lines = result_content.strip().split('\n')
                    for line_num, line in enumerate(lines, 1):
                        if line.strip():
                            try:
                                batch_results.append(json.loads(line))
                            except json.JSONDecodeError as e:
                                print(f"[ERROR] JSON parsing error on line {line_num} for {file_name}: {e}")
                                print(f"[DEBUG] Line position: character {e.pos if hasattr(e, 'pos') else 'unknown'}")
                                print(f"[DEBUG] File: {file_name}")
                                print(f"[DEBUG] Batch ID: {batch_id}")
                                print(f"[DEBUG] Problematic content (first 500 chars): {line[:500]}...")
                                if len(line) > 500:
                                    print(f"[DEBUG] Line length: {len(line)} characters")
                                # Continue processing other lines instead of failing completely
                                continue
                    
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
                    )

                    main_output, side_output_data = self._separate_side_output(processed_data)

                    # Create output filename based on original file name
                    if file_name and file_name != 'default':
                        # Use the original file name from registry
                        output_file_path = Path(output_directory) / f"{Path(file_name).stem}.json"
                    else:
                        # Fallback to batch_id naming
                        output_file_path = Path(output_directory) / f"{batch_id}_processed_output.json"
                    
                    output_file_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Write results for this specific file
                    file_writer = FileWriter(str(output_file_path))
                    file_writer.write_target(main_output)

                    if side_output_data:
                        side_output_dir = Path(output_directory).parent / "side_output"
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
                raise ValueError("No batch results were successfully processed")
            
            print(f"Successfully processed {len(processed_files)} files")
            return processed_files
            
        except Exception as e:
            raise RuntimeError(f"Error processing all batch results to workflow output: {e}")