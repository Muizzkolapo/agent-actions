"""Validation module import for batch processing."""

import logging

from agent_actions.utils.module_loader import load_module_from_path

logger = logging.getLogger(__name__)


def import_validation_module(validation_module: str, validation_path: str | None) -> None:
    """Import validation module to register UDFs via decorators.

    Args:
        validation_module: Name of the Python module (without .py extension)
        validation_path: Path where the module is located (or None for PYTHONPATH)
    """
    try:
        module = load_module_from_path(
            module_name=validation_module,
            module_path=validation_path,
            execute=True,
            fallback_import=True,
            cache=True,
        )

        if module:
            logger.debug("Successfully imported validation module: %s", validation_module)
        else:
            logger.warning(
                "Could not import validation module '%s'. "
                "Ensure the module exists and validation_path is configured correctly.",
                validation_module,
            )
    except ImportError as e:
        from agent_actions.errors import ConfigurationError

        raise ConfigurationError(
            f"Cannot import validation module '{validation_module}': {e}",
            context={"validation_module": validation_module, "validation_path": validation_path},
            cause=e,
        ) from e
    except Exception as e:
        logger.warning("Failed to import validation module '%s': %s", validation_module, e)
