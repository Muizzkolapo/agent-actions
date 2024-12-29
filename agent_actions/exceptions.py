from typing import NoReturn, Optional, Any, Dict, List
import functools
from agent_actions.logging_setup import setup_logging

logger = setup_logging()

# Base Exceptions
class AgentActionsError(Exception):
    """Base exception for all agent-actions errors"""
    def __init__(self, msg: str, node: Optional[Any] = None):
        super().__init__(msg)
        self.msg = msg
        self.node = node

    def add_node(self, node: Any):
        self.node = node

# Configuration Exceptions
class ConfigurationError(AgentActionsError):
    """Base class for configuration-related errors"""
    pass

class MissingConfigError(ConfigurationError):
    def __init__(self, config_name: str):
        msg = f"Configuration '{config_name}' is required but was not provided"
        super().__init__(msg)

class DuplicateAgentError(ConfigurationError):
    def __init__(self, agent_name: str):
        msg = f"Duplicate agent name found: {agent_name}"
        super().__init__(msg)

# Tool/UDF Exceptions
class ToolingError(AgentActionsError):
    """Base class for tooling-related errors"""
    pass

class UDFNotFoundError(ToolingError):
    def __init__(self, function_name: str, module_name: str):
        msg = f"Function '{function_name}' not found in module '{module_name}'"
        super().__init__(msg)

class UDFExecutionError(ToolingError):
    def __init__(self, function_name: str, error_msg: str):
        msg = f"Error executing UDF '{function_name}': {error_msg}"
        super().__init__(msg)

# Staging Content Exceptions
class StagingContentError(AgentActionsError):
    """Base class for staging content-related errors"""
    pass

class PromptProcessingError(StagingContentError):
    def __init__(self, error_msg: str):
        msg = f"Error processing prompt: {error_msg}"
        super().__init__(msg)

class FewShotSampleError(StagingContentError):
    def __init__(self, error_msg: str):
        msg = f"Error loading few shot samples: {error_msg}"
        super().__init__(msg)

class SourceContentError(StagingContentError):
    def __init__(self, source_path: str, error_msg: str):
        msg = f"Error loading source content from {source_path}: {error_msg}"
        super().__init__(msg)

class DynamicAgentError(StagingContentError):
    def __init__(self, agent_name: str, error_msg: str):
        msg = f"Error creating dynamic agent '{agent_name}': {error_msg}"
        super().__init__(msg)

class DataTransformError(StagingContentError):
    def __init__(self, error_msg: str):
        msg = f"Error transforming data: {error_msg}"
        super().__init__(msg)

# Template Rendering Exceptions
class TemplateError(AgentActionsError):
    """Base class for template-related errors"""
    pass

class TemplateLoadError(TemplateError):
    def __init__(self, template_file: str, error_msg: str):
        msg = f"Error loading template {template_file}: {error_msg}"
        super().__init__(msg)

class YAMLRenderError(TemplateError):
    def __init__(self, yaml_path: str, error_msg: str):
        msg = f"Error rendering YAML file {yaml_path}: {error_msg}"
        super().__init__(msg)

# Staging Loader Exceptions
class StagingLoaderError(AgentActionsError):
    """Base class for staging loader-related errors"""
    pass

class FileTypeError(StagingLoaderError):
    def __init__(self, file_type: str):
        msg = f"Unsupported file type: {file_type}"
        super().__init__(msg)

class AgentBuilderImportError(StagingLoaderError):
    def __init__(self):
        msg = "Unable to import 'agent_actions.agent_utils.agent_builder'"
        super().__init__(msg)

# Target Content Exceptions
class TargetContentError(AgentActionsError):
    """Base class for target content-related errors"""
    pass

class SourceDataLoadError(TargetContentError):
    def __init__(self, file_path: str, error_msg: str):
        msg = f"Error loading source data from {file_path}: {error_msg}"
        super().__init__(msg)

class FewShotSampleParseError(TargetContentError):
    def __init__(self, value: Any):
        msg = f"Invalid value for 'use_few_shot_samples': {value}. Defaulting to 0."
        super().__init__(msg)

class FewShotSamplePathError(TargetContentError):
    def __init__(self, error_msg: str):
        msg = f"Few-shot samples path not found: {error_msg}"
        super().__init__(msg)

class ContentTypeError(TargetContentError):
    def __init__(self):
        msg = "Contents is not a dictionary. Cannot add samples."
        super().__init__(msg)

class ItemProcessingError(TargetContentError):
    def __init__(self, guid: str, error_msg: str):
        msg = f"Error processing item with GUID {guid}: {error_msg}"
        super().__init__(msg)

class ContentProcessingError(TargetContentError):
    def __init__(self, error_msg: str):
        msg = f"Error in content processing: {error_msg}"
        super().__init__(msg)

class SideOutputProcessingError(TargetContentError):
    def __init__(self, error_msg: str):
        msg = f"Error processing side output: {error_msg}"
        super().__init__(msg)

class UnexpectedFormatError(TargetContentError):
    def __init__(self, item_format: str):
        msg = f"Unexpected item format: {item_format}"
        super().__init__(msg)

# Agent Handler Exceptions
class AgentHandlerError(AgentActionsError):
    """Base class for agent handler-related errors"""
    pass

class ModuleImportError(AgentHandlerError):
    def __init__(self, function_name: str, loader: str, error_msg: str):
        msg = f"Failed to import {function_name} from module {loader}: {error_msg}"
        super().__init__(msg)

class FunctionCallError(AgentHandlerError):
    def __init__(self, function_name: str, loader: str):
        msg = f"Function {function_name} not found in module {loader}"
        super().__init__(msg)

class FileProcessingError(AgentHandlerError):
    def __init__(self, file: str, error_msg: str):
        msg = f"Error processing {file}: {error_msg}"
        super().__init__(msg)

class NoFilesFoundError(AgentHandlerError):
    def __init__(self, directory: str):
        msg = f"No files found in: {directory}"
        super().__init__(msg)

# Schema Handler Exceptions
class SchemaError(AgentActionsError):
    """Base class for schema-related errors"""
    pass

class SchemaNotFoundError(SchemaError):
    def __init__(self, schema_name: str):
        msg = f"Schema file not found: {schema_name}.yml"
        super().__init__(msg)

class SchemaRenderError(SchemaError):
    def __init__(self, agent_name: str, error_msg: str):
        msg = f"Failed to render template for agent '{agent_name}': {error_msg}"
        super().__init__(msg)

class MultipleSchemaMissingError(SchemaError):
    def __init__(self, missing_files: List[str]):
        msg = f"The following schema files are missing: {', '.join(missing_files)}"
        super().__init__(msg)

class SingleSchemaMissingError(SchemaError):
    def __init__(self, schema_file: str):
        msg = f"The schema file '{schema_file}' is missing."
        super().__init__(msg)

# Prompt Handler Exceptions
class PromptError(AgentActionsError):
    """Base class for prompt-related errors"""
    pass

class DuplicatePromptError(PromptError):
    def __init__(self, filename: str, duplicates: List[str]):
        msg = f"Duplicate prompt names found in {filename}: {', '.join(duplicates)}"
        super().__init__(msg)

class PromptNotFoundError(PromptError):
    def __init__(self, prompt_name: str):
        msg = f"Prompt '{prompt_name}' not found"
        super().__init__(msg)

class PromptDirectoryError(PromptError):
    def __init__(self):
        msg = "Prompt directory not found"
        super().__init__(msg)

class PromptFileNotFoundError(PromptError):
    def __init__(self, filename: str):
        msg = f"Prompt file not found: {filename}"
        super().__init__(msg)

# Target Loader Exceptions
class TargetLoaderError(AgentActionsError):
    """Base class for target loader-related errors"""
    pass

class TargetProcessingError(TargetLoaderError):
    def __init__(self, file_path: str, error_msg: str):
        msg = f"Error processing target file {file_path}: {error_msg}"
        super().__init__(msg)

class TargetSaveError(TargetLoaderError):
    def __init__(self, file_path: str, error_msg: str):
        msg = f"Error saving target file {file_path}: {error_msg}"
        super().__init__(msg)

class SideOutputError(TargetLoaderError):
    def __init__(self, file_path: str, error_msg: str):
        msg = f"Error processing side output for {file_path}: {error_msg}"
        super().__init__(msg)

# Data Transformer Exceptions
class DataTransformerError(AgentActionsError):
    """Base class for data transformer-related errors"""
    pass

class DataExtractionError(DataTransformerError):
    def __init__(self, error_msg: str):
        msg = f"An error occurred while extracting data: {error_msg}"
        super().__init__(msg)

class SchemaUpdateError(DataTransformerError):
    def __init__(self, key: str, error_msg: str):
        msg = f"Error updating schema for key '{key}': {error_msg}"
        super().__init__(msg)

class GUIDNotFoundError(DataTransformerError):
    def __init__(self, guid: str):
        msg = f"GUID '{guid}' not found in data"
        super().__init__(msg)

class DataTypeError(DataTransformerError):
    def __init__(self, expected_type: str, received_type: str):
        msg = f"Invalid data type. Expected {expected_type}, received {received_type}"
        super().__init__(msg)

# String Transformer Exceptions
class StringTransformerError(AgentActionsError):
    """Base class for string transformer-related errors"""
    pass

class InvalidInputError(StringTransformerError):
    def __init__(self, input_type: str):
        msg = f"Input must be a string, got {input_type}"
        super().__init__(msg)

class FunctionCallError(StringTransformerError):
    def __init__(self, function_name: str, error_msg: str):
        msg = f"Error calling function {function_name}: {error_msg}"
        super().__init__(msg)

class TokenizationError(StringTransformerError):
    def __init__(self, text: str, error_msg: str):
        msg = f"Error tokenizing text: {error_msg}"
        super().__init__(msg)

class UserFunctionError(StringTransformerError):
    def __init__(self, function_name: str, error_msg: str):
        msg = f"Error in call_user_function for {function_name}: {error_msg}"
        super().__init__(msg)

# File Handler Exceptions
class FileHandlerError(AgentActionsError):
    """Base class for file handler-related errors"""
    pass

class FileTypeError(FileHandlerError):
    def __init__(self, file_type: str):
        msg = f"Unsupported file type: {file_type}"
        super().__init__(msg)

class FileReadError(FileHandlerError):
    def __init__(self, file_path: str, error_msg: str):
        msg = f"Error reading file {file_path}: {error_msg}"
        super().__init__(msg)

class FileWriteError(FileHandlerError):
    def __init__(self, file_path: str, error_msg: str):
        msg = f"Error writing to file {file_path}: {error_msg}"
        super().__init__(msg)

class AgentFolderError(FileHandlerError):
    def __init__(self, agent_name: str):
        msg = f"Agent folder not found for agent: {agent_name}"
        super().__init__(msg)

class ConfigFileError(FileHandlerError):
    def __init__(self, filename: str, error_msg: str):
        msg = f"Error with config file {filename}: {error_msg}"
        super().__init__(msg)

# Config Handler Exceptions
class ConfigHandlerError(AgentActionsError):
    """Base class for configuration handler-related errors"""
    pass

class ConfigLoadError(ConfigHandlerError):
    def __init__(self, config_path: str, error_msg: str):
        msg = f"Error loading constructor config: {config_path}, Error: {error_msg}"
        super().__init__(msg)

class DefaultConfigLoadError(ConfigHandlerError):
    def __init__(self, config_path: str, error_msg: str):
        msg = f"Error loading default config: {config_path}, Error: {error_msg}"
        super().__init__(msg)

# CLI Exceptions
class CLIError(AgentActionsError):
    """Base class for CLI-related errors"""
    pass

class DirectoryError(CLIError):
    def __init__(self, directory: str):
        msg = f"Missing directory: {directory}"
        super().__init__(msg)

class DuplicateConfigError(CLIError):
    def __init__(self, config_path: str):
        msg = f"Duplicate configuration file: {config_path}"
        super().__init__(msg)

class MissingConfigError(CLIError):
    def __init__(self, filename: str):
        msg = f"Missing configuration file: {filename}"
        super().__init__(msg)

class MissingSchemaError(CLIError):
    def __init__(self, agent_name: str):
        msg = f"Missing schema for agent '{agent_name}'"
        super().__init__(msg)

class InvalidConfigFormatError(CLIError):
    def __init__(self):
        msg = "Invalid configuration format for the agent"
        super().__init__(msg)

class WorkflowNameMismatchError(CLIError):
    def __init__(self, agent_name: str, available_names: list):
        msg = f"The config file name '{agent_name}' does not match any workflow names {available_names}"
        super().__init__(msg)

class ProjectInitError(CLIError):
    def __init__(self, project_name: str, error_msg: str):
        msg = f"Failed to initialize project '{project_name}': {error_msg}"
        super().__init__(msg)

class DocsServerError(CLIError):
    def __init__(self, error_msg: str):
        msg = f"Failed to start documentation server: {error_msg}"
        super().__init__(msg)

class WorkflowError(CLIError):
    def __init__(self, error_msg: str):
        msg = f"Failed to run agent workflow: {error_msg}"
        super().__init__(msg)

class CleanupError(CLIError):
    def __init__(self, agent_name: str, error_msg: str):
        msg = f"Failed to clean agent directories for '{agent_name}': {error_msg}"
        super().__init__(msg)

class TemplateRenderError(CLIError):
    def __init__(self, agent_name: str, error_msg: str):
        msg = f"Failed to render template for agent '{agent_name}': {error_msg}"
        super().__init__(msg)

# Helper Functions
def raise_config_error(msg: str, node: Optional[Any] = None) -> NoReturn:
    raise ConfigurationError(msg, node)

def raise_udf_not_found(function_name: str, module_name: str) -> NoReturn:
    raise UDFNotFoundError(function_name, module_name)

def raise_udf_execution_error(function_name: str, error_msg: str) -> NoReturn:
    raise UDFExecutionError(function_name, error_msg)

def raise_source_content_error(source_path: str, error_msg: str) -> NoReturn:
    raise SourceContentError(source_path, error_msg)

def raise_few_shot_sample_error(error_msg: str) -> NoReturn:
    raise FewShotSampleError(error_msg)

def raise_prompt_error() -> NoReturn:
    raise PromptError()

def raise_content_processing_error(content_type: str, error_msg: str) -> NoReturn:
    raise ContentProcessingError(content_type, error_msg)

def raise_template_load_error(template_file: str, error_msg: str) -> NoReturn:
    raise TemplateLoadError(template_file, error_msg)

def raise_yaml_render_error(yaml_path: str, error_msg: str) -> NoReturn:
    raise YAMLRenderError(yaml_path, error_msg)

def raise_file_type_error(file_type: str) -> NoReturn:
    raise FileTypeError(file_type)

def raise_agent_builder_import_error() -> NoReturn:
    raise AgentBuilderImportError()

def raise_source_data_load_error(file_path: str, error_msg: str) -> NoReturn:
    raise SourceDataLoadError(file_path, error_msg)

def raise_few_shot_sample_parse_error(value: Any) -> NoReturn:
    raise FewShotSampleParseError(value)

def raise_few_shot_sample_path_error(error_msg: str) -> NoReturn:
    raise FewShotSamplePathError(error_msg)

def raise_content_type_error() -> NoReturn:
    raise ContentTypeError()

def raise_module_import_error(function_name: str, loader: str, error_msg: str) -> NoReturn:
    raise ModuleImportError(function_name, loader, error_msg)

def raise_function_call_error(function_name: str, loader: str) -> NoReturn:
    raise FunctionCallError(function_name, loader)

def raise_file_processing_error(file: str, error_msg: str) -> NoReturn:
    raise FileProcessingError(file, error_msg)

def raise_no_files_found_error(directory: str) -> NoReturn:
    raise NoFilesFoundError(directory)

def raise_schema_validation_error(schema_name: str, error_msg: str) -> NoReturn:
    raise SchemaValidationError(schema_name, error_msg)

def raise_schema_load_error(schema_path: str, error_msg: str) -> NoReturn:
    raise SchemaLoadError(schema_path, error_msg)

def raise_duplicate_prompt_error(filename: str, duplicates: List[str]) -> NoReturn:
    raise DuplicatePromptError(filename, duplicates)

def raise_prompt_not_found_error(prompt_name: str) -> NoReturn:
    raise PromptNotFoundError(prompt_name)

def raise_prompt_directory_error() -> NoReturn:
    raise PromptDirectoryError()

def raise_prompt_file_not_found_error(filename: str) -> NoReturn:
    raise PromptFileNotFoundError(filename)

def raise_schema_not_found_error(schema_name: str) -> NoReturn:
    raise SchemaNotFoundError(schema_name)

def raise_schema_render_error(agent_name: str, error_msg: str) -> NoReturn:
    raise SchemaRenderError(agent_name, error_msg)

def raise_multiple_schema_missing_error(missing_files: List[str]) -> NoReturn:
    raise MultipleSchemaMissingError(missing_files)

def raise_single_schema_missing_error(schema_file: str) -> NoReturn:
    raise SingleSchemaMissingError(schema_file)

def raise_target_processing_error(file_path: str, error_msg: str) -> NoReturn:
    raise TargetProcessingError(file_path, error_msg)

def raise_target_save_error(file_path: str, error_msg: str) -> NoReturn:
    raise TargetSaveError(file_path, error_msg)

def raise_side_output_error(file_path: str, error_msg: str) -> NoReturn:
    raise SideOutputError(file_path, error_msg)

def raise_data_extraction_error(error_msg: str) -> NoReturn:
    raise DataExtractionError(error_msg)

def raise_schema_update_error(key: str, error_msg: str) -> NoReturn:
    raise SchemaUpdateError(key, error_msg)

def raise_guid_not_found_error(guid: str) -> NoReturn:
    raise GUIDNotFoundError(guid)

def raise_data_type_error(expected_type: str, received_type: str) -> NoReturn:
    raise DataTypeError(expected_type, received_type)

def raise_invalid_input_error(input_type: str) -> NoReturn:
    raise InvalidInputError(input_type)

def raise_tokenization_error(text: str, error_msg: str) -> NoReturn:
    raise TokenizationError(text, error_msg)

def raise_user_function_error(function_name: str, error_msg: str) -> NoReturn:
    raise UserFunctionError(function_name, error_msg)

def raise_file_read_error(file_path: str, error_msg: str) -> NoReturn:
    raise FileReadError(file_path, error_msg)

def raise_file_write_error(file_path: str, error_msg: str) -> NoReturn:
    raise FileWriteError(file_path, error_msg)

def raise_agent_folder_error(agent_name: str) -> NoReturn:
    raise AgentFolderError(agent_name)

def raise_config_file_error(filename: str, error_msg: str) -> NoReturn:
    raise ConfigFileError(filename, error_msg)

def raise_prompt_processing_error(error_msg: str) -> NoReturn:
    raise PromptProcessingError(error_msg)

def raise_dynamic_agent_error(agent_name: str, error_msg: str) -> NoReturn:
    raise DynamicAgentError(agent_name, error_msg)

def raise_data_transform_error(error_msg: str) -> NoReturn:
    raise DataTransformError(error_msg)

def raise_item_processing_error(guid: str, error_msg: str) -> NoReturn:
    raise ItemProcessingError(guid, error_msg)

def raise_content_processing_error(error_msg: str) -> NoReturn:
    raise ContentProcessingError(error_msg)

def raise_side_output_processing_error(error_msg: str) -> NoReturn:
    raise SideOutputProcessingError(error_msg)

def raise_unexpected_format_error(item_format: str) -> NoReturn:
    raise UnexpectedFormatError(item_format)

def raise_config_load_error(config_path: str, error_msg: str) -> NoReturn:
    raise ConfigLoadError(config_path, error_msg)

def raise_default_config_load_error(config_path: str, error_msg: str) -> NoReturn:
    raise DefaultConfigLoadError(config_path, error_msg)

def raise_directory_error(directory: str) -> NoReturn:
    raise DirectoryError(directory)

def raise_duplicate_config_error(config_path: str) -> NoReturn:
    raise DuplicateConfigError(config_path)

def raise_missing_config_error(filename: str) -> NoReturn:
    raise MissingConfigError(filename)

def raise_missing_schema_error(agent_name: str) -> NoReturn:
    raise MissingSchemaError(agent_name)

def raise_invalid_config_format_error() -> NoReturn:
    raise InvalidConfigFormatError()

def raise_workflow_name_mismatch_error(agent_name: str, available_names: list) -> NoReturn:
    raise WorkflowNameMismatchError(agent_name, available_names)

def raise_project_init_error(project_name: str, error_msg: str) -> NoReturn:
    raise ProjectInitError(project_name, error_msg)

def raise_docs_server_error(error_msg: str) -> NoReturn:
    raise DocsServerError(error_msg)

def raise_workflow_error(error_msg: str) -> NoReturn:
    raise WorkflowError(error_msg)

def raise_cleanup_error(agent_name: str, error_msg: str) -> NoReturn:
    raise CleanupError(agent_name, error_msg)

def raise_template_render_error(agent_name: str, error_msg: str) -> NoReturn:
    raise TemplateRenderError(agent_name, error_msg)

# Context wrapper
def wrapper(agent_config):
    def wrap(func):
        @functools.wraps(func)
        def inner(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except AgentActionsError as exc:
                exc.add_node(agent_config)
                raise exc
        return inner
    return wrap

# Export context functions
CONTEXT_EXPORTS = {
    fn.__name__: fn
    for fn in [
        raise_config_error,
        raise_udf_not_found,
        raise_udf_execution_error,
        raise_template_load_error,
        raise_yaml_render_error,
        raise_file_type_error,
        raise_agent_builder_import_error,
        raise_source_data_load_error,
        raise_few_shot_sample_parse_error,
        raise_few_shot_sample_path_error,
        raise_content_type_error,
        raise_module_import_error,
        raise_function_call_error,
        raise_file_processing_error,
        raise_no_files_found_error,
        raise_schema_validation_error,
        raise_schema_load_error,
        raise_duplicate_prompt_error,
        raise_prompt_not_found_error,
        raise_prompt_directory_error,
        raise_prompt_file_not_found_error,
        raise_schema_not_found_error,
        raise_schema_render_error,
        raise_multiple_schema_missing_error,
        raise_single_schema_missing_error,
        raise_target_processing_error,
        raise_target_save_error,
        raise_side_output_error,
        raise_data_extraction_error,
        raise_schema_update_error,
        raise_guid_not_found_error,
        raise_data_type_error,
        raise_invalid_input_error,
        raise_tokenization_error,
        raise_user_function_error,
        raise_file_read_error,
        raise_file_write_error,
        raise_agent_folder_error,
        raise_config_file_error,
        raise_prompt_processing_error,
        raise_few_shot_sample_error,
        raise_source_content_error,
        raise_dynamic_agent_error,
        raise_data_transform_error,
        raise_item_processing_error,
        raise_content_processing_error,
        raise_side_output_processing_error,
        raise_unexpected_format_error,
        raise_config_load_error,
        raise_default_config_load_error,
        raise_directory_error,
        raise_duplicate_config_error,
        raise_missing_config_error,
        raise_missing_schema_error,
        raise_invalid_config_format_error,
        raise_workflow_name_mismatch_error,
        raise_project_init_error,
        raise_docs_server_error,
        raise_workflow_error,
        raise_cleanup_error,
        raise_template_render_error,
    ]
}

def wrapped_exports(agent_config):
    wrap = wrapper(agent_config)
    return {name: wrap(export) for name, export in CONTEXT_EXPORTS.items()}

# Context Exports
STAGING_CONTEXT_EXPORTS = {
    fn.__name__: fn
    for fn in [
        raise_source_content_error,
        raise_few_shot_sample_error,
        raise_prompt_error,
        raise_content_processing_error,
    ]
}

class AgentCreationError(AgentActionsError):
    """Exception raised when there's an error creating an agent with data"""
    def __init__(self, error_msg: str):
        msg = f"Error in create_agent_with_data: {error_msg}"
        super().__init__(msg)

def raise_agent_creation_error(error_msg: str) -> NoReturn:
    raise AgentCreationError(error_msg)

# Update Context Exports
CONTEXT_EXPORTS.update({
    'raise_agent_creation_error': raise_agent_creation_error,
})
