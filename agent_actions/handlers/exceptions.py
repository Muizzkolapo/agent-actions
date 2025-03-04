from typing import NoReturn, Optional, Any, Dict, List
import functools
from agent_actions.logging_setup import setup_logging
from agent_actions.exceptions import (
    AgentActionsError,
    NoFilesFoundError,
    ConfigLoadError,
    DefaultConfigLoadError,
    FileTypeError,
    FileReadError,
    FileWriteError,
    AgentFolderError,
    ConfigFileError,
    DuplicatePromptError,
    PromptNotFoundError,
    PromptDirectoryError,
    PromptFileNotFoundError,
    SchemaNotFoundError,
    SchemaRenderError,
    MultipleSchemaMissingError,
    SingleSchemaMissingError,
    FileProcessingError
)



logger = setup_logging()



def raise_file_processing_error(file: str, error_msg: str) -> NoReturn:
    raise FileProcessingError(file, error_msg)

def raise_no_files_found_error(directory: str) -> NoReturn:
    raise NoFilesFoundError(directory)

def raise_config_load_error(config_path: str, error_msg: str) -> NoReturn:
    raise ConfigLoadError(config_path, error_msg)

def raise_default_config_load_error(config_path: str, error_msg: str) -> NoReturn:
    raise DefaultConfigLoadError(config_path, error_msg)

def raise_file_type_error(file_type: str) -> NoReturn:
    raise FileTypeError(file_type)

def raise_file_read_error(file_path: str, error_msg: str) -> NoReturn:
    raise FileReadError(file_path, error_msg)

def raise_file_write_error(file_path: str, error_msg: str) -> NoReturn:
    raise FileWriteError(file_path, error_msg)

def raise_agent_folder_error(agent_name: str) -> NoReturn:
    raise AgentFolderError(agent_name)

def raise_config_file_error(filename: str, error_msg: str) -> NoReturn:
    raise ConfigFileError(filename, error_msg)

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
        raise_file_type_error,
        raise_file_processing_error,
        raise_no_files_found_error,
        raise_duplicate_prompt_error,
        raise_prompt_not_found_error,
        raise_prompt_directory_error,
        raise_prompt_file_not_found_error,
        raise_schema_not_found_error,
        raise_schema_render_error,
        raise_multiple_schema_missing_error,
        raise_single_schema_missing_error,
        raise_file_read_error,
        raise_file_write_error,
        raise_agent_folder_error,
        raise_config_file_error,
        raise_config_load_error,
        raise_default_config_load_error
    ]
}