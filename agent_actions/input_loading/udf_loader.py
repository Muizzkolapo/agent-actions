"""
UDF Discovery and Validation Module.
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List

from agent_actions.errors import DuplicateFunctionError, UDFLoadError
from agent_actions.utilities.module_loader import ensure_path_importable
from agent_actions.utilities.udf_management.udf_registry import UDF_REGISTRY, get_udf


def discover_udfs(user_code_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Discover and register all UDFs in the user code directory.

    Recursively scans the directory for Python files, imports them to trigger
    @udf_tool decorator registration, and returns the populated registry.

    Args:
        user_code_path: Path to the directory containing user-defined functions

    Returns:
        The populated UDF_REGISTRY dictionary

    Raises:
        UDFLoadError: If a Python file fails to import
        DuplicateFunctionError: If duplicate function names are detected

    Example:
        registry = discover_udfs(Path('./user_code'))
        print(f"Discovered {len(registry)} UDF(s)")
    """
    user_code_path = Path(user_code_path)
    if not user_code_path.exists():
        error_context = {"user_code_path": str(user_code_path), "operation": "discover_udfs"}
        raise UDFLoadError(
            module="<discovery>",
            file=str(user_code_path),
            error="User code directory not found",
            context=error_context,
        )
    if not user_code_path.is_dir():
        error_context = {"user_code_path": str(user_code_path), "operation": "discover_udfs"}
        raise UDFLoadError(
            module="<discovery>",
            file=str(user_code_path),
            error="User code path is not a directory",
            context=error_context,
        )

    # Use centralized path management (thread-safe, cached)
    ensure_path_importable(user_code_path)

    python_files = list(user_code_path.rglob("*.py"))
    python_files = [
        f for f in python_files if not f.name.startswith("_") and not f.name.startswith("test_")
    ]

    for py_file in python_files:
        try:
            relative_path = py_file.relative_to(user_code_path)
            module_name = str(relative_path.with_suffix("")).replace("/", ".").replace("\\", ".")

            if module_name in sys.modules:
                continue

            # Keep original module loading logic to preserve exception behavior
            # (DuplicateFunctionError must bubble up directly)
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

        except DuplicateFunctionError:
            raise
        except Exception as e:
            error_context = {"error_type": type(e).__name__}
            raise UDFLoadError(
                module=module_name, file=str(py_file), error=str(e), context=error_context, cause=e
            ) from e

    return UDF_REGISTRY


def validate_udf_references(config: Dict[str, Any]) -> None:
    """
    Validate that all 'impl' references in config exist in the UDF registry.

    Recursively walks the configuration structure to find all 'impl' fields
    and verifies that the referenced functions are registered.

    Args:
        config: Configuration dictionary to validate

    Raises:
        FunctionNotFoundError: If a referenced function is not in the registry

    Example:
        config = {'actions': [{'impl': 'my_function'}]}
        validate_udf_references(config)  # Will raise if 'my_function' not found
    """
    impl_references: List[str] = []

    def extract_impl_refs(obj: Any, path: str = "") -> None:
        """Recursively extract all 'impl' field values."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key
                if key == "impl" and isinstance(value, str):
                    impl_references.append(value)
                else:
                    extract_impl_refs(value, current_path)
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                current_path = f"{path}[{idx}]"
                extract_impl_refs(item, current_path)

    extract_impl_refs(config)
    for impl_ref in impl_references:
        get_udf(impl_ref)
