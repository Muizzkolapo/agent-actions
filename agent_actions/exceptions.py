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

class SourceContentError(StagingContentError):
    def __init__(self, source_path: str, error_msg: str):
        msg = f"Error loading source content from {source_path}: {error_msg}"
        super().__init__(msg)

class FewShotSampleError(StagingContentError):
    def __init__(self, sample_count: Any):
        msg = f"Invalid few-shot sample count: {sample_count}. Must be an integer."
        super().__init__(msg)

class PromptError(StagingContentError):
    def __init__(self):
        msg = "No prompt found in agent_config"
        super().__init__(msg)

class ContentProcessingError(StagingContentError):
    def __init__(self, content_type: str, error_msg: str):
        msg = f"Error processing {content_type} content: {error_msg}"
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

class SchemaValidationError(SchemaError):
    def __init__(self, schema_name: str, error_msg: str):
        msg = f"Schema validation failed for {schema_name}: {error_msg}"
        super().__init__(msg)

class SchemaLoadError(SchemaError):
    def __init__(self, schema_path: str, error_msg: str):
        msg = f"Failed to load schema from {schema_path}: {error_msg}"
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

def raise_few_shot_sample_error(sample_count: Any) -> NoReturn:
    raise FewShotSampleError(sample_count)

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
