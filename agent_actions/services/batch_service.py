import json
from pathlib import Path
from openai import OpenAI
from agent_actions.handlers.config_handler import ConfigManager
from agent_actions.processors.data_loaders.batch_data_loader import BatchDataLoader
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.processors.prompt_processor.prompt_utils import PromptUtils
from agent_actions.handlers.schema_handler import SchemaLoader
from agent_actions.models.schema_change import compile_unified_schema
from agent_actions.handlers.file_writer import FileWriter
from agent_actions.transformers.data_transformer import DataTransformer
from agent_actions.constants import PROMPT_KEY, SCHEMA_NAME_KEY

class BatchService:
    # Class variable to control force batch behavior
    force_batch = False
    
    def __init__(self):
        self.data_loader = BatchDataLoader()
        self.client = OpenAI()

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

        tasks = []
        for row in data:
            # In batch mode, the 'id' is the guid.
            uuid = row.get("guid")
            if not uuid:
                print(f"Warning: Skipping row in batch data due to missing 'guid'.")
                continue

            formatted_prompt, cleaned_row = PromptUtils.replace_placeholders(raw_prompt, row)
            
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

    def retrieve_results(self, batch_id: str, output_dir: str):
        try:
            batch_job = self.client.batches.retrieve(batch_id)
            if batch_job.status == 'completed':
                result_file_id = batch_job.output_file_id
                result = self.client.files.content(result_file_id).content
                
                output_path = Path(output_dir)
                output_path.mkdir(exist_ok=True)
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
            result_content = self.client.files.content(result_file_id).content
            
            # Parse batch results
            batch_results = []
            for line in result_content.decode('utf-8').strip().split('\n'):
                if line.strip():
                    batch_results.append(json.loads(line))
            
            # Process results into workflow format
            processed_data = self._convert_batch_results_to_workflow_format(batch_results)
            
            # Save to workflow output directory structure
            relative_path = Path(file_path).relative_to(base_directory)
            output_file_path = Path(output_directory) / relative_path.with_suffix('.json')
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_writer = FileWriter(str(output_file_path))
            file_writer.write_target(processed_data)
            
            return str(output_file_path)
            
        except Exception as e:
            raise RuntimeError(f"Error processing batch results to workflow output: {e}")

    def _convert_batch_results_to_workflow_format(self, batch_results):
        """
        Convert batch API results to the workflow's expected format.
        Extracts content and preserves metadata, matching non-batch agent output format.
        
        Args:
            batch_results: List of batch API result objects
            
        Returns:
            List of processed data in workflow format
        """
        processed_data = []
        
        for result in batch_results:
            if result.get('body'):
                response_body = result['body']
                custom_id = result['custom_id']  # This is the GUID
                
                # Extract the generated content
                if 'choices' in response_body and response_body['choices']:
                    choice = response_body['choices'][0]
                    if 'message' in choice and 'content' in choice['message']:
                        content = choice['message']['content']
                        
                        try:
                            # Parse JSON content from the response
                            generated_data = json.loads(content)
                            
                            # Create workflow format: extract content and preserve metadata
                            workflow_item = {
                                "guid": custom_id,
                                "content": generated_data,  # This is the actual content extracted
                                "metadata": {
                                    "model": response_body.get('model'),
                                    "usage": response_body.get('usage'),
                                    "finish_reason": choice.get('finish_reason'),
                                    "created": response_body.get('created'),
                                    "system_fingerprint": response_body.get('system_fingerprint')
                                }
                            }
                            processed_data.append(workflow_item)
                            
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
                # Handle error cases
                custom_id = result.get('custom_id', 'unknown')
                error_item = {
                    "guid": custom_id,
                    "error": "Batch processing failed",
                    "raw_result": result
                }
                processed_data.append(error_item)
        
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
        """
        try:
            # Retrieve batch results
            batch_job = self.client.batches.retrieve(batch_id)
            if batch_job.status != 'completed':
                raise ValueError(f"Batch job {batch_id} is not completed. Status: {batch_job.status}")
                
            result_file_id = batch_job.output_file_id
            result_content = self.client.files.content(result_file_id).content
            
            # Parse batch results
            batch_results = []
            for line in result_content.decode('utf-8').strip().split('\n'):
                if line.strip():
                    batch_results.append(json.loads(line))
            
            # Process results into workflow format
            processed_data = self._convert_batch_results_to_workflow_format(batch_results)
            
            # Save to a generic file in the workflow output directory
            output_file_path = Path(output_directory) / f"{batch_id}_processed_output.json"
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_writer = FileWriter(str(output_file_path))
            file_writer.write_target(processed_data)
            
            return str(output_file_path)
            
        except Exception as e:
            raise RuntimeError(f"Error processing batch results to workflow output: {e}")