import json 
import traceback
import importlib
import os 
from agent_actions.handlers.file_handler import FileHandler
import shutil
import random
import logging
import re
import yaml

logger = logging.getLogger(__name__)



# Agent Management Functions

class AgentManager:
    """
    A class for managing agent directories and configurations.
    """

    @staticmethod
    def clean_agent_directories(agent_name):
        """
        Deletes all files under the staging, source, and target folders for the specified agent.
        """
        current_dir = os.getcwd()
        agent_folder = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')

        if agent_folder is None:
            print(f"Agent folder not found for agent: {agent_name}")
            return

        staging_dir = os.path.join(agent_folder, 'staging')
        source_dir = os.path.join(agent_folder, 'source')
        target_dir = os.path.join(agent_folder, 'target')

        for directory in [staging_dir, source_dir, target_dir]:
            if os.path.exists(directory):
                shutil.rmtree(directory)
                print(f"Deleted directory: {directory}")
            else:
                print(f"Directory not found: {directory}")

    @staticmethod
    def clean_agent_output(agent_name, agent_type, function_name):
        """
        Cleans the agent output by applying a specified function to each JSON file
        in the target directory of the agent.

        :param agent_name: Name of the agent
        :param agent_type: Type of the agent
        :param function_name: Name of the function to apply to the JSON data
        """
        project_root = os.getcwd()  # Get current working directory
        input_directory = os.path.join(project_root, 'agent_io', agent_name, 'target', agent_type)
        function_call = globals().get(function_name)
        if function_call and callable(function_call):
            for root, _, files in os.walk(input_directory):
                for file_name in files:
                    if file_name.endswith('.json'):
                        file_path = os.path.join(root, file_name)
                        with open(file_path, 'r', encoding='utf-8') as file:
                            data = json.load(file)
                        flattened_data = function_call(data)
                        with open(file_path, 'w', encoding='utf-8') as file:
                            json.dump(flattened_data, file, indent=4)

    @staticmethod
    def process_and_generate_for_agent(agent_config,
                                       agent_name,
                                       previous_agent_type,
                                       loader,
                                       function_name):
        """
        Processes and generates data for an agent by applying a specified function
        to each file in the input directory and saving the output in the target directory.

        :param agent_config: Configuration dictionary for the agent.
        :param agent_name: Name of the agent.
        :param previous_agent_type: Type of the previous agent, if applicable.
        :param loader: Name of the loader module.
        :param function_name: Name of the function to apply to the data.
        """
        try:
            current_dir = os.getcwd()
            agent_folder = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')

            if agent_folder is None:
                raise FileNotFoundError(f"Agent folder not found for agent: {agent_name}")

            input_directory = os.path.join(
                agent_folder,
                'target',
                previous_agent_type
            ) if previous_agent_type else os.path.join(
                agent_folder,
                'staging'
            )

            output_directory = os.path.join(
                agent_folder,
                'target',
                agent_config["agent_type"]
            )

            try:
                module = importlib.import_module(f"agent_actions.processors.{loader}")
                function_call = getattr(module, function_name)
            except (ImportError, AttributeError) as e:
                print(f"Failed to import {function_name} from module {loader}: {e}")
                traceback.print_exc()
                return

            if function_call and callable(function_call):
                files_processed = False
                for root, _, files in os.walk(input_directory):
                    if files:
                        files_processed = True
                    for file in files:
                        file_path = os.path.join(root, file)
                        print(f"Processing {file_path}")
                        try:
                            function_call(agent_config,
                                          agent_name,
                                          file_path,
                                          input_directory,
                                          output_directory)
                        except (IOError, OSError, json.JSONDecodeError) as e:
                            print(f"Failed to process {file}: {e}")
                        except ValueError as e:
                            print(f"Invalid data encountered while processing {file}: {e}")
                        except KeyError as e:
                            print(f"Missing key encountered while processing {file}: {e}")

                if not files_processed:
                    print(f"No files found in the input directory: {input_directory}")
            else:
                print(f"Function {function_name} not found in module {loader}.")
                traceback.print_exc()
            return output_directory  # Return the output directory path
        except FileNotFoundError as fnf_error:
            print(f"File not found error: {fnf_error}")
        except Exception as e:
            print(f"An error occurred in process_and_generate_for_agent: {e}")
            traceback.print_exc()

    @staticmethod
    def load_few_shot_samples(few_shot_samples_path, agent_type, sample_count=3):
        """
        Load random sample objects from the JSON files in the sample output directory for a specific agent type.

        Parameters:
            few_shot_samples_path (str): Base path to the sample output directory.
            agent_type (str): The type of the agent to load samples for.
            sample_count (int): Number of random sample objects to load.

        Returns:
            list: List of randomly selected sample objects.
        """

        agent_samples_path = os.path.join(few_shot_samples_path, agent_type)
        if not os.path.exists(agent_samples_path):
            return []

        sample_files = [f for f in os.listdir(agent_samples_path) if f.endswith('.json')]
        all_samples = []

        for sample_file in sample_files:
            with open(os.path.join(agent_samples_path, sample_file), 'r') as file:
                data = json.load(file)
                if isinstance(data, list):
                    all_samples.extend(data)
                elif isinstance(data, dict):
                    all_samples.append(data)

        if sample_count > 0 and all_samples:
            selected_samples = random.sample(all_samples, min(sample_count, len(all_samples)))
        else:
            selected_samples = []
        return selected_samples



# Schema and Prompt Loading

class SchemaLoader:
    """
    A class for loading schemas.
    """

    @staticmethod
    def load_schema(schema_name):
        """
        Retrieve and generate a JSON schema based on the schema name provided.

        Parameters:
            schema_name (str): The name of the schema to load.

        Returns:
            dict: The loaded schema as a dictionary.
        """
        try:
            current_dir = os.getcwd()
            schema_dir = os.path.join(current_dir, "schema")

            if not os.path.exists(schema_dir):
                raise FileNotFoundError("Schema directory not found.")

            schema_file_path = FileHandler.find_file_in_directory(schema_dir, f"{schema_name}.yml")

            if not schema_file_path:
                raise FileNotFoundError(f"Schema file not found: {schema_name}.yml")

            with open(schema_file_path, 'r', encoding='utf-8') as file:
                documents = yaml.safe_load(file)

            return documents

        except Exception as e:
            print(f"An error occurred in load_schema: {e}")
            traceback.print_exc()
            return None


class PromptLoader:
    """
    A class for loading prompts.
    """

    @staticmethod
    def extract_prompt(content, prompt_name):
        """
        Extracts a prompt from the content using the prompt_name.

        Parameters:
            content (str): The content containing the prompt.
            prompt_name (str): The name of the prompt to extract.

        Returns:
            str: The extracted prompt or "Prompt not found."
        """
        # Regular expression to match the prompt block
        pattern = re.compile(rf"\{{prompt {prompt_name}\}}(.*?)\{{end_prompt\}}", re.DOTALL)

        # Search for the prompt using the pattern
        match = pattern.search(content)

        if match:
            return match.group(1).strip()
        else:
            return "Prompt not found."

    @staticmethod
    def load_prompt(prompt_name):
        """
        Retrieve and generate a prompt based on the prompt name provided.

        Parameters:
            prompt_name (str): The name of the prompt to load, in the format 'filename.prompt_key'.

        Returns:
            str: The loaded prompt as a string.
        """
        try:
            current_dir = os.getcwd()
            prompt_dir = os.path.join(current_dir, "prompt_store")

            if not os.path.exists(prompt_dir):
                raise FileNotFoundError("Prompt directory not found.")

            # Extract the prompt file name and the prompt key
            prompt_file_name, prompt_key = prompt_name.split('.', 1)

            # Search for the file in the prompt directory
            prompt_file_path = FileHandler.find_file_in_directory(prompt_dir, f"{prompt_file_name}.md")

            if not prompt_file_path:
                raise FileNotFoundError(f"Prompt file not found: {prompt_file_name}.md")

            # Read the content of the prompt file
            with open(prompt_file_path, 'r', encoding='utf-8') as file:
                content = file.read()

            prompt_data = PromptLoader.extract_prompt(content, prompt_key)

            return prompt_data

        except Exception as e:
            print(f"An error occurred in load_prompt: {e}")
            traceback.print_exc()
            return None

