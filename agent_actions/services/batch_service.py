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

class BatchService:
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
            with open(file_path, 'r', encoding='utf-8') as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError:
                    existing = []
        if not isinstance(existing, list):
            existing = [existing]
        existing.extend(data)
        with open(file_path, 'w', encoding='utf-8') as f:
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
        for row in data:
            # In batch mode, the 'id' is the guid.
            uuid = row.get("guid")
            if not uuid:
                print(f"Warning: Skipping row in batch data due to missing 'guid'.")
                continue

            self.context_map[uuid] = row

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
                    "custom_id": uuid,
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









    def submit_batch_job_from_data(self, agent_config, agent_type, data, output_directory=None, force=False):
        # Check for existing in-flight batch job unless forced
        force_submission = force or BatchService.force_batch
        if not force_submission:
            existing_batch_id = self._check_for_existing_batch_job(output_directory)
            if existing_batch_id:
                print(f"Found existing in-flight batch job: {existing_batch_id}")
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
        
        file_name = f"{agent_type}_batch_input.jsonl"
        file_path = batch_dir / file_name

        with open(file_path, 'w') as file:
            for obj in tasks:
                file.write(json.dumps(obj) + '\n')

        print(f"Batch file created at: {file_path}")
        self._save_context_map(self.context_map, agent_config, output_directory, agent_type)

        try:
            batch_file = self.client.files.create(file=open(file_path, "rb"), purpose="batch")
            batch_job = self.client.batches.create(
                input_file_id=batch_file.id,
                endpoint="/v1/chat/completions",
                completion_window="24h"
            )
            print(f"Batch job created with ID: {batch_job.id}")
            self._save_batch_job_id(batch_job.id, output_directory)
            return batch_job.id
        except Exception as e:
            raise RuntimeError(f"Error submitting batch job: {e}")

    def _save_batch_job_id(self, batch_id: str, output_directory: str = None):
        """Save batch job ID to both global and local directories."""
        # Save to global batch directory (for backward compatibility)
        global_batch_dir = Path.cwd() / "batch"
        global_batch_dir.mkdir(exist_ok=True)
        global_job_id_file = global_batch_dir / ".last_batch_id"
        with open(global_job_id_file, 'w') as f:
            f.write(batch_id)
        
        # Also save to output directory if provided
        if output_directory:
            local_batch_dir = Path(output_directory) / "batch"
            local_batch_dir.mkdir(parents=True, exist_ok=True)
            local_job_id_file = local_batch_dir / ".last_batch_id"
            with open(local_job_id_file, 'w') as f:
                f.write(batch_id)

    def _save_context_map(self, context_map: dict, agent_config: dict, output_directory: str, agent_type: str):
        """Persist original context data for side_collection processing."""
        if output_directory:
            batch_dir = Path(output_directory) / "batch"
        else:
            batch_dir = Path.cwd() / "batch"
        batch_dir.mkdir(parents=True, exist_ok=True)
        path = batch_dir / f"{agent_type}_context_map.json"
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
            return payload.get("data", {}), payload.get("side_collection", [])
        except Exception:
            return {}, []

    def _get_last_batch_job_id(self, output_directory: str = None):
        """Get the last batch job ID, checking local directory first if provided."""
        # Check local directory first if provided
        if output_directory:
            local_job_id_file = Path(output_directory) / "batch" / ".last_batch_id"
            if local_job_id_file.exists():
                with open(local_job_id_file, 'r') as f:
                    return f.read().strip()
        
        # Fall back to global directory
        global_job_id_file = Path.cwd() / "batch" / ".last_batch_id"
        if global_job_id_file.exists():
            with open(global_job_id_file, 'r') as f:
                return f.read().strip()
        return None
    
    def _check_for_existing_batch_job(self, output_directory: str = None):
        """Check if there's already an in-flight batch job for this output directory."""
        batch_id = self._get_last_batch_job_id(output_directory)
        if not batch_id:
            return None
        
        try:
            status = self.check_status(batch_id)
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
                result = self.client.files.content(result_file_id).content
                
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
            result_content = self.client.files.content(result_file_id).content
            
            # Parse batch results
            batch_results = []
            for line in result_content.decode('utf-8').strip().split('\n'):
                if line.strip():
                    batch_results.append(json.loads(line))
            
            batch_dir = Path(output_directory) / "batch"
            context_map, side_collection = self._load_context_map(batch_dir)

            # Process results into workflow format
            processed_data = self._convert_batch_results_to_workflow_format(
                batch_results,
                side_collection=side_collection,
                context_map=context_map,
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

    def _convert_batch_results_to_workflow_format(self, batch_results, *, side_collection=None, context_map=None):
        """
        Convert batch API results to the workflow's expected format.
        Extracts content and preserves metadata, matching non-batch agent output format.
        
        Args:
            batch_results: List of batch API result objects
            
        Returns:
            List of processed data in workflow format
        """
        processed_data = []
        context_map = context_map or {}
        side_collection = side_collection or []
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
                            generated_data = json.loads(content)

                            if side_collection and custom_id in context_map:
                                original = context_map.get(custom_id, {})
                                if isinstance(generated_data, list):
                                    generated_data = [
                                        DataTransformer.update_schema_objects(original, item, side_collection)
                                        if isinstance(item, dict) else item
                                        for item in generated_data
                                    ]
                                elif isinstance(generated_data, dict):
                                    generated_data = DataTransformer.update_schema_objects(
                                        original,
                                        generated_data,
                                        side_collection,
                                    )

                            structured_items = DataTransformer.transform_structure(
                                [{custom_id: generated_data}]
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
                            processed_data.extend(structured_items)
                            
                        except json.JSONDecodeError:
                            # If not valid JSON, wrap in error structure
                            error_item = {
                                "guid": custom_id,
                                "error": "Invalid JSON response",
                                "raw_content": content,
                                "metadata": {
                                    "model": response_body.get('model'),
                                    "finish_reason": choice.get('finish_reason', 'error')
                                }
                            }
                            processed_data.append(error_item)
            else:
                # Handle error cases where 'response' or 'body' is missing
                error_item = {
                    "guid": custom_id or 'unknown',
                    "error": "Batch processing failed or missing response body",
                    "raw_result": result
                }
                processed_data.append(error_item)
        #===end here===#
        
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
                
            
            # Parse batch results
            #muizz change this is where we get the outcpme of the run like the result from the model
            batch_results = []
            for line in result_content.strip().split('\n'):
                if line.strip():
                    batch_results.append(json.loads(line))
            
            print(f"Parsed {len(batch_results)} batch results")
            
            context_map, side_collection = self._load_context_map(batch_dir)

            # Process results into workflow format
            processed_data = self._convert_batch_results_to_workflow_format(
                batch_results,
                side_collection=side_collection,
                context_map=context_map,
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