from typing import NoReturn, Optional, Any, Dict, List
import functools
from agent_actions.logging_setup import setup_logging
from agent_actions.exceptions import (
    DataExtractionError,
    SchemaUpdateError,
    GUIDNotFoundError,
    DataTypeError,
    InvalidInputError,
    FunctionCallError,
    TokenizationError,
    UserFunctionError,
)

logger = setup_logging()

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
def raise_function_call_error(function_name: str, loader: str) -> NoReturn:
    raise FunctionCallError(function_name, loader)
def raise_tokenization_error(text: str, error_msg: str) -> NoReturn:
    raise TokenizationError(text, error_msg)

def raise_user_function_error(function_name: str, error_msg: str) -> NoReturn:
    raise UserFunctionError(function_name, error_msg)
# Export context functions
CONTEXT_EXPORTS = {
    fn.__name__: fn
    for fn in [
        raise_data_extraction_error,
        raise_schema_update_error,
        raise_guid_not_found_error,
        raise_data_type_error,
        raise_invalid_input_error,
        raise_function_call_error,
        raise_tokenization_error,
        raise_user_function_error
    ]
}
