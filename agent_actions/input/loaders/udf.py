"""UDF discovery and validation."""

import ast
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from agent_actions.errors import DuplicateFunctionError, UDFLoadError
from agent_actions.utils.udf_management.registry import UDF_REGISTRY, get_udf

logger = logging.getLogger(__name__)

# Decorators that register user tool code via import side effect.
_TOOL_DECORATORS = frozenset({"udf_tool", "reprompt_validation"})


def _declares_tool_decorator(py_file: Path) -> bool:
    """True if the file declares a tool-registering decorated function, without executing it."""
    try:
        source = py_file.read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        logger.debug("Skipping unreadable file %s: %s", py_file, e)
        return False
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        # Unparseable: can't prove intent structurally. A decorator-name mention
        # keeps the file on the import path so its syntax error surfaces loudly.
        return any(name in source for name in _TOOL_DECORATORS)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                name = (
                    target.attr
                    if isinstance(target, ast.Attribute)
                    else getattr(target, "id", None)
                )
                if name in _TOOL_DECORATORS:
                    return True
    return False


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

    Only files that declare a tool-registering decorator (``udf_tool`` or
    ``reprompt_validation``) are imported; other ``.py`` files under the tree
    (helper scripts, notes) are skipped so a broken non-UDF file cannot block
    discovery.

    Raises:
        UDFLoadError: If the user-code directory is missing or invalid
            (``module == UDFLoadError.DISCOVERY_SENTINEL``), if path-to-module
            derivation fails for a discovered file (also routed through the
            sentinel), or if a UDF-declaring file fails to import (module set
            to the failing dotted import name).
        DuplicateFunctionError: If duplicate function names are detected.
    """
    user_code_path = Path(user_code_path)
    if not user_code_path.exists():
        error_context = {"user_code_path": str(user_code_path), "operation": "discover_udfs"}
        raise UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file=str(user_code_path),
            error="User code directory not found",
            context=error_context,
        )
    if not user_code_path.is_dir():
        error_context = {"user_code_path": str(user_code_path), "operation": "discover_udfs"}
        raise UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file=str(user_code_path),
            error="User code path is not a directory",
            context=error_context,
        )

    python_files = discover_tool_files(user_code_path)

    for py_file in python_files:
        # Own try so relative_to() ValueError doesn't leave module_name
        # unbound for the import-time except block below.
        try:
            relative_path = py_file.relative_to(user_code_path)
            module_name = str(relative_path.with_suffix("")).replace("/", ".").replace("\\", ".")
        except ValueError as e:
            # Discovery-level failure — sentinel, not a per-module import.
            raise UDFLoadError(
                module=UDFLoadError.DISCOVERY_SENTINEL,
                file=str(py_file),
                error=f"Could not derive module name from path: {e}",
                context={"error_type": type(e).__name__},
                cause=e,
            ) from e

        if not _declares_tool_decorator(py_file):
            logger.debug("Skipping %s: no tool-registering decorator declared", py_file)
            continue

        if f"agent_actions._udfs.{module_name}" in sys.modules:
            continue

        try:
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
