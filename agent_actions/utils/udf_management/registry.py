"""
UDF (User-Defined Function) Registry for Agent Actions.
"""

import inspect
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

from agent_actions.config.schema import Granularity
from agent_actions.errors import DuplicateFunctionError, FunctionNotFoundError


@dataclass
class FileUDFResult:
    """
    Result type for FILE-level UDFs with explicit source mapping.

    Enables UDFs to declare exactly which input record(s) produced each output,
    supporting proper lineage tracking for filter, dedup, and merge operations.

    Attributes:
        outputs: List of output records
        source_mapping: Maps output_idx -> input_idx(es)
            - int: one-to-one (output[i] from input[j])
            - List[int]: many-to-one (output[i] from inputs[j,k,...])
        input_count: Number of input records (optional, for validation)

    Examples:
        # Dedup: output 0 from input 0, output 1 from input 2 (skipped input 1)
        FileUDFResult(
            outputs=[{"a": 1}, {"c": 3}],
            source_mapping={0: 0, 1: 2},
            input_count=3
        )

        # Merge: output 0 aggregates inputs 0, 1, 2
        FileUDFResult(
            outputs=[{"merged": "abc"}],
            source_mapping={0: [0, 1, 2]},
            input_count=3
        )

        # Without mapping: falls back to legacy lineage behavior
        FileUDFResult(outputs=[{"result": "x"}])
    """

    outputs: List[Dict]
    source_mapping: Optional[Dict[int, Union[int, List[int]]]] = None
    input_count: Optional[int] = None

    def __post_init__(self):
        """Validate source_mapping bounds at creation time."""
        if self.source_mapping is None:
            return

        for output_idx, source_idx in self.source_mapping.items():
            # Validate output index is within bounds
            if output_idx < 0 or output_idx >= len(self.outputs):
                raise ValueError(
                    f"source_mapping key {output_idx} out of bounds "
                    f"for outputs (length {len(self.outputs)})"
                )

            # Validate input indices if input_count is provided
            if self.input_count is not None:
                indices = source_idx if isinstance(source_idx, list) else [source_idx]
                for idx in indices:
                    if idx < 0 or idx >= self.input_count:
                        raise ValueError(
                            f"source_mapping value {idx} out of bounds "
                            f"for inputs (count {self.input_count})"
                        )


# Thread safety
_registry_lock = threading.RLock()

# Registry with cached compiled schemas
UDF_REGISTRY: Dict[str, Dict[str, Any]] = {}


def udf_tool(
    func: Optional[Callable] = None,
    *,
    granularity: Granularity = Granularity.RECORD,
) -> Callable:
    """
    Decorator to register a UDF.

    Output schema is defined via YAML ``schema:`` in the workflow config
    (the single source of truth). Runtime output validation is fed from
    the compiled ``json_output_schema`` in agent config.

    Args:
        func: The function to register
        granularity: RECORD (default) or FILE processing

    Examples:
        @udf_tool()
        def process_user(data, **kwargs):
            return {'status': 'processed'}

        @udf_tool(granularity=Granularity.FILE)
        def process_users_batch(data, **kwargs):
            return [{'status': 'processed'} for _ in data]
    """

    def decorator(f: Callable) -> Callable:
        # Thread-safe registration
        with _registry_lock:
            func_name_lower = f.__name__.lower()

            # Check for duplicates (atomic check-and-register)
            if func_name_lower in UDF_REGISTRY:
                existing = UDF_REGISTRY[func_name_lower]
                new_file = inspect.getfile(f)
                # Allow if it's the same file being imported via different module paths
                # This happens when tools_path subdirectories are added to sys.path
                if existing["file"] == new_file:
                    # Same file, different import path - return existing function
                    return existing["function"]
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

        return f

    # Support @udf_tool() with no arguments
    if func is not None:
        # Called as @udf_tool without parentheses
        return decorator(func)
    return decorator


def get_udf(func_name: str) -> Callable:
    """
    Retrieve a registered UDF by name (case-insensitive).

    Args:
        func_name: Name of the function to retrieve

    Returns:
        The registered function

    Raises:
        FunctionNotFoundError: If function not found in registry

    Example:
        func = get_udf('process_user')
        result = func(data)
    """
    with _registry_lock:
        func_name_lower = func_name.lower()
        if func_name_lower not in UDF_REGISTRY:
            available = sorted([meta["name"] for meta in UDF_REGISTRY.values()])
            raise FunctionNotFoundError(
                f"Function '{func_name}' not found",
                context={"function_name": func_name, "available_functions": available},
            )
        return UDF_REGISTRY[func_name_lower]["function"]


def get_udf_metadata(func_name: str) -> Dict[str, Any]:
    """
    Get complete UDF metadata including schema and granularity.
    Thread-safe. Returns direct reference - callers should not mutate.

    Args:
        func_name: Name of the function

    Returns:
        Dictionary containing all metadata (read-only reference)

    Raises:
        FunctionNotFoundError: If function not found
    """
    with _registry_lock:
        func_name_lower = func_name.lower()
        if func_name_lower not in UDF_REGISTRY:
            available = sorted([meta["name"] for meta in UDF_REGISTRY.values()])
            raise FunctionNotFoundError(
                f"Function '{func_name}' not found",
                context={"function_name": func_name, "available_functions": available},
            )
        return UDF_REGISTRY[func_name_lower]


def list_udfs() -> List[Dict[str, Any]]:
    """
    List all registered UDFs with their metadata.

    Returns:
        List of dicts containing function metadata

    Example:
        udfs = list_udfs()
        for udf in udfs:
            print(f"{udf['name']} - {udf['file']}")
    """
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
    """
    Clear the UDF registry. Thread-safe.

    This function should only be called in test cleanup.

    Example:
        @pytest.fixture(autouse=True)
        def cleanup():
            clear_registry()
    """
    with _registry_lock:
        UDF_REGISTRY.clear()
