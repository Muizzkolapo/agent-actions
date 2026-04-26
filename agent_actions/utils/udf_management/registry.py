"""UDF (User-Defined Function) registry for Agent Actions."""

import inspect
import sys
import threading
from collections.abc import Callable
from typing import Any, cast

from agent_actions.config.types import Granularity
from agent_actions.errors import DuplicateFunctionError, FunctionNotFoundError


class FileUDFResult:
    """Explicit provenance for N→M FILE tools.

    Tools return business data only.  The framework handles all metadata
    propagation (``source_guid``, lineage, ``node_id``) automatically —
    tools never need to think about it.

    Each output must declare ``source_index`` (which input produced it)
    and ``data`` (the business fields).
    """

    def __init__(self, outputs: list[dict[str, Any]]):
        for i, out in enumerate(outputs):
            if not isinstance(out, dict):
                raise ValueError(f"FileUDFResult output[{i}] must be a dict")
            if "source_index" not in out:
                raise ValueError(
                    f"FileUDFResult output[{i}] missing 'source_index'. "
                    f"Every output must declare which input produced it. "
                    f"Use None for synthetic records (aggregations, dedup results)."
                )
            src = out["source_index"]
            if src is not None and not isinstance(src, (int, list)):
                raise ValueError(
                    f"FileUDFResult output[{i}] source_index must be int, list[int], or None. "
                    f"Got {type(src).__name__}."
                )
            if "data" not in out or not isinstance(out["data"], dict):
                raise ValueError(
                    f"FileUDFResult output[{i}] missing 'data' dict. "
                    f"Every output must have a 'data' dict with business fields."
                )
        self.outputs = outputs


# Thread safety
_registry_lock = threading.RLock()

# Process-wide registry with cached compiled schemas.
# Assumes one workflow per process; concurrent workflows would share state.
UDF_REGISTRY: dict[str, dict[str, Any]] = {}

# Track which module names contributed UDFs (for sys.modules cleanup on clear)
_registered_modules: set[str] = set()


def udf_tool(
    func: Callable | None = None,
    *,
    granularity: Granularity = Granularity.RECORD,
) -> Callable:
    """Decorator to register a UDF with optional granularity (RECORD or FILE)."""

    def decorator(f: Callable) -> Callable:
        with _registry_lock:
            func_name_lower = f.__name__.lower()

            if func_name_lower in UDF_REGISTRY:
                existing = UDF_REGISTRY[func_name_lower]
                new_file = inspect.getfile(f)
                # Allow if it's the same file being imported via different module paths
                # This happens when tools_path subdirectories are added to sys.path
                if existing["file"] == new_file:
                    # Same file, different import path - return existing function
                    return cast(Callable, existing["function"])
                raise DuplicateFunctionError(
                    function_name=f.__name__,
                    existing_location=f"{existing['module']}.{existing['name']}",
                    existing_file=existing["file"],
                    new_location=f"{f.__module__}.{f.__name__}",
                    new_file=new_file,
                )

            UDF_REGISTRY[func_name_lower] = {
                "function": f,
                "module": f.__module__,
                "name": f.__name__,
                "file": inspect.getfile(f),
                "docstring": f.__doc__,
                "signature": inspect.signature(f),
                "granularity": granularity,
            }
            _registered_modules.add(f.__module__)

        return f

    # Support @udf_tool() with no arguments
    if func is not None:
        # Called as @udf_tool without parentheses
        return decorator(func)
    return decorator


def get_udf(func_name: str) -> Callable:
    """Retrieve a registered UDF by name (case-insensitive).

    Raises:
        FunctionNotFoundError: If function not found in registry.
    """
    with _registry_lock:
        func_name_lower = func_name.lower()
        if func_name_lower not in UDF_REGISTRY:
            available = sorted([meta["name"] for meta in UDF_REGISTRY.values()])
            raise FunctionNotFoundError(
                f"Function '{func_name}' not found",
                context={"function_name": func_name, "available_functions": available},
            )
        return cast(Callable, UDF_REGISTRY[func_name_lower]["function"])


def get_udf_metadata(func_name: str) -> dict[str, Any]:
    """Get complete UDF metadata (shallow copy to prevent registry mutation).

    Raises:
        FunctionNotFoundError: If function not found.
    """
    with _registry_lock:
        func_name_lower = func_name.lower()
        if func_name_lower not in UDF_REGISTRY:
            available = sorted([meta["name"] for meta in UDF_REGISTRY.values()])
            raise FunctionNotFoundError(
                f"Function '{func_name}' not found",
                context={"function_name": func_name, "available_functions": available},
            )
        return UDF_REGISTRY[func_name_lower].copy()


def list_udfs() -> list[dict[str, Any]]:
    """List all registered UDFs with their metadata."""
    with _registry_lock:
        return [
            {
                "name": meta["name"],
                "module": meta["module"],
                "file": meta["file"],
                "docstring": meta["docstring"],
                "signature": str(meta["signature"]),
            }
            for meta in sorted(UDF_REGISTRY.values(), key=lambda x: x["name"].lower())
        ]


def clear_registry() -> None:
    """Clear the UDF registry (testing only, thread-safe)."""
    with _registry_lock:
        UDF_REGISTRY.clear()
        for module_name in _registered_modules:
            sys.modules.pop(module_name, None)
        _registered_modules.clear()
