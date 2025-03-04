
from typing import NoReturn, Optional, Any, Dict, List
import functools
from agent_actions.logging_setup import setup_logging
from agent_actions.exceptions import (
    PromptProcessingError,
    FewShotSampleError,
    SourceContentError,
    DynamicAgentError,
    FileTypeError,
    AgentBuilderImportError,
    SourceDataLoadError,
    FewShotSampleParseError,
    FewShotSamplePathError,
    ContentTypeError,
    ItemProcessingError,
    ContentProcessingError,
    SideOutputProcessingError,
    UnexpectedFormatError,
    AgentCreationError,
    TargetProcessingError,
    TargetSaveError,
    SideOutputError,
)

logger = setup_logging()



def raise_prompt_processing_error(error_msg: str) -> NoReturn:
    raise PromptProcessingError(error_msg)
def raise_few_shot_sample_error(error_msg: str) -> NoReturn:
    raise FewShotSampleError(error_msg)
def raise_source_content_error(source_path: str, error_msg: str) -> NoReturn:
    raise SourceContentError(source_path, error_msg)
def raise_dynamic_agent_error(agent_name: str, error_msg: str) -> NoReturn:
    raise DynamicAgentError(agent_name, error_msg)
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
def raise_item_processing_error(guid: str, error_msg: str) -> NoReturn:
    raise ItemProcessingError(guid, error_msg)
def raise_content_processing_error(error_msg: str) -> NoReturn:
    raise ContentProcessingError(error_msg)
def raise_side_output_processing_error(error_msg: str) -> NoReturn:
    raise SideOutputProcessingError(error_msg)

def raise_unexpected_format_error(item_format: str) -> NoReturn:
    raise UnexpectedFormatError(item_format)
def raise_agent_creation_error(error_msg: str) -> NoReturn:
    raise AgentCreationError(error_msg)

def raise_target_processing_error(file_path: str, error_msg: str) -> NoReturn:
    raise TargetProcessingError(file_path, error_msg)
def raise_target_save_error(file_path: str, error_msg: str) -> NoReturn:
    raise TargetSaveError(file_path, error_msg)
def raise_side_output_error(file_path: str, error_msg: str) -> NoReturn:
    raise SideOutputError(file_path, error_msg)


# Export context functions
CONTEXT_EXPORTS = {
    fn.__name__: fn
    for fn in [
        raise_prompt_processing_error,
        raise_few_shot_sample_error,
        raise_source_content_error,
        raise_dynamic_agent_error,
        raise_file_type_error,
        raise_agent_builder_import_error,
        raise_source_data_load_error,
        raise_few_shot_sample_parse_error,
        raise_few_shot_sample_path_error,
        raise_content_type_error,
        raise_item_processing_error,
        raise_content_processing_error,
        raise_side_output_processing_error,
        raise_unexpected_format_error,
        raise_agent_creation_error,
        raise_target_processing_error,
        raise_target_save_error,
        raise_side_output_error
    ]
}