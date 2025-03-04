from typing import NoReturn, List
from agent_actions.logging_setup import setup_logging
from agent_actions.exceptions import (
    FileProcessingError,
    NoFilesFoundError,
    DirectoryError,
    DuplicateConfigError,
    MissingConfigError,
    MissingSchemaError,
    InvalidConfigFormatError,
    WorkflowNameMismatchError,
    ProjectInitError,
    DocsServerError,
    WorkflowError,
    CleanupError,
    TemplateRenderError,
    UDFNotFoundError,
    UDFExecutionError
)
logger = setup_logging()

# Raise helper functions
def raise_file_processing_error(file: str, error_msg: str) -> NoReturn:
    raise FileProcessingError(file, error_msg)

def raise_no_files_found_error(directory: str) -> NoReturn:
    raise NoFilesFoundError(directory)

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

def raise_workflow_name_mismatch_error(agent_name: str, available_names: List[str]) -> NoReturn:
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

def raise_udf_not_found(function_name: str, module_name: str) -> NoReturn:
    raise UDFNotFoundError(function_name, module_name)

def raise_udf_execution_error(function_name: str, error_msg: str) -> NoReturn:
    raise UDFExecutionError(function_name, error_msg)
# Export context functions
CONTEXT_EXPORTS = {
    fn.__name__: fn
    for fn in [
        raise_file_processing_error,
        raise_no_files_found_error,
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
