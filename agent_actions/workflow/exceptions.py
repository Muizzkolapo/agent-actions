from typing import NoReturn, Optional, Any, Dict, List
import functools
from agent_actions.logging_setup import setup_logging
from agent_actions.exceptions import (
    TemplateLoadError,
    YAMLRenderError,
)

logger = setup_logging()



def raise_template_load_error(template_file: str, error_msg: str) -> NoReturn:
    raise TemplateLoadError(template_file, error_msg)
def raise_yaml_render_error(yaml_path: str, error_msg: str) -> NoReturn:
    raise YAMLRenderError(yaml_path, error_msg)


# Export context functions
CONTEXT_EXPORTS = {
    fn.__name__: fn
    for fn in [
        raise_template_load_error, 
        raise_yaml_render_error

    ]
}

