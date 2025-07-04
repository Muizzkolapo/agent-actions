import json
from pathlib import Path
from openai import OpenAI
from agent_actions.handlers.config_handler import ConfigManager
from agent_actions.processors.data_loaders.batch_data_loader import BatchDataLoader
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.processors.prompt_processor.prompt_utils import PromptUtils
from agent_actions.handlers.schema_handler import SchemaLoader
from agent_actions.models.schema_change import compile_unified_schema
from agent_actions.constants import PROMPT_KEY, SCHEMA_NAME_KEY

class BatchService:
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









    def submit_batch_job_from_data(self, agent_config, agent_type, data):
        tasks = self.prepare_batch_tasks_from_data(agent_config, data)
        if not tasks:
            print("No batch tasks to submit.")
            return None

        batch_dir = Path.cwd() / "batch"
        batch_dir.mkdir(exist_ok=True)
        
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
            self._save_batch_job_id(batch_job.id)
            return batch_job.id
        except Exception as e:
            raise RuntimeError(f"Error submitting batch job: {e}")

    def _save_batch_job_id(self, batch_id: str):
        job_id_file = Path.cwd() / "batch" / ".last_batch_id"
        with open(job_id_file, 'w') as f:
            f.write(batch_id)

    def _get_last_batch_job_id(self):
        job_id_file = Path.cwd() / "batch" / ".last_batch_id"
        if job_id_file.exists():
            with open(job_id_file, 'r') as f:
                return f.read().strip()
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