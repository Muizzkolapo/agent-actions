"""UDF discovery and validation."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

from agent_actions.errors import DuplicateFunctionError, UDFLoadError
from agent_actions.utils.udf_management.registry import UDF_REGISTRY, get_udf


def discover_tool_files(tool_dir: Path) -> list[Path]:
    """Discover Python files eligible for UDF registration.

    Searches *tool_dir* recursively for ``*.py`` files, excluding private
    (``_``-prefixed) and test (``test_``-prefixed) modules.  Returns a
    sorted list of paths.
    """
    if not tool_dir.exists() or not tool_dir.is_dir():
        return []
    return sorted(
        f
        for f in tool_dir.rglob("*.py")
        if not f.name.startswith("_") and not f.name.startswith("test_")
    )


def discover_udfs(user_code_path: Path) -> dict[str, dict[str, Any]]:
    """Discover and register all UDFs in the user code directory.

    Raises:
        UDFLoadError: If a Python file fails to import.
        DuplicateFunctionError: If duplicate function names are detected.
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

    python_files = discover_tool_files(user_code_path)

    for py_file in python_files:
        try:
            relative_path = py_file.relative_to(user_code_path)
            module_name = str(relative_path.with_suffix("")).replace("/", ".").replace("\\", ".")

            if f"agent_actions._udfs.{module_name}" in sys.modules:
                continue

            # Keep original module loading logic to preserve exception behavior
            # (DuplicateFunctionError must bubble up directly)
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[f"agent_actions._udfs.{module_name}"] = module
                spec.loader.exec_module(module)

        except DuplicateFunctionError:
            raise
        except Exception as e:
            error_context = {"error_type": type(e).__name__}
            raise UDFLoadError(
                module=module_name, file=str(py_file), error=str(e), context=error_context, cause=e
            ) from e

    return UDF_REGISTRY


def validate_udf_references(config: dict[str, Any]) -> None:
    """Validate that all 'impl' references in config exist in the UDF registry.

    Raises:
        FunctionNotFoundError: If a referenced function is not in the registry.
    """
    impl_references: list[str] = []

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
