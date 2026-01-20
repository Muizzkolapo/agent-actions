"""
Operator registry for managing and evaluating operators.

This module provides the central registry that manages all operators,
with automatic discovery and registration of built-in operators.
"""

from typing import Dict, List, Optional
import inspect
import logging

from .base import BaseOperator, OperatorInfo, OperatorType
from . import comparison, logical, functions

logger = logging.getLogger(__name__)


class OperatorRegistry:
    """Registry for managing operators and functions."""

    def __init__(self):
        """Initialize the registry with built-in operators."""
        self._operators: Dict[str, BaseOperator] = {}
        self._symbols_to_names: Dict[str, str] = {}
        self._discover_and_register_builtin_operators()

    def _discover_and_register_builtin_operators(self):
        """
        Automatically discover and register all built-in operators.

        This uses reflection to find all operator classes in the comparison,
        logical, and functions modules, eliminating the need for manual
        registration calls.
        """
        # Modules containing built-in operators
        operator_modules = [comparison, logical, functions]

        for module in operator_modules:
            # Get all classes from the module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # Skip abstract base classes and check if it's a concrete operator
                if (
                    issubclass(obj, BaseOperator)
                    and obj is not BaseOperator
                    and not inspect.isabstract(obj)
                    and not name.startswith("_")
                ):
                    try:
                        # Instantiate and register the operator
                        operator_instance = obj()
                        self.register_operator(operator_instance)
                    except ValueError as e:
                        logger.debug(
                            "Skipping operator %s that can't be instantiated: %s",
                            name,
                            e,
                            extra={
                                "operator_class": name,
                                "module_name": (
                                    module.__name__ if hasattr(module, "__name__") else "unknown"
                                ),
                                "operation": "operator_discovery",
                            },
                        )

    def register_operator(self, operator: BaseOperator):
        """
        Register a new operator.

        Args:
            operator: The operator to register

        Raises:
            Warning if operator name or symbol already exists (logged, not raised)
        """
        info = operator.get_info()

        # Check for conflicts (could add logging here)
        if info.name in self._operators:
            # Existing operator will be overwritten
            pass

        if info.symbol in self._symbols_to_names:
            # Existing symbol mapping will be overwritten
            pass

        self._operators[info.name] = operator
        self._symbols_to_names[info.symbol] = info.name

    def get_operator(self, name_or_symbol: str) -> Optional[BaseOperator]:
        """
        Get an operator by name or symbol.

        Args:
            name_or_symbol: Operator name or symbol

        Returns:
            The operator instance or None if not found
        """
        # Try by name first
        if name_or_symbol in self._operators:
            return self._operators[name_or_symbol]

        # Try by symbol
        if name_or_symbol in self._symbols_to_names:
            name = self._symbols_to_names[name_or_symbol]
            return self._operators[name]

        return None

    def get_operator_info(self, name_or_symbol: str) -> Optional[OperatorInfo]:
        """
        Get operator information.

        Args:
            name_or_symbol: Operator name or symbol

        Returns:
            Operator information or None if not found
        """
        operator = self.get_operator(name_or_symbol)
        return operator.get_info() if operator else None

    def list_operators(self, operator_type: Optional[OperatorType] = None) -> List[OperatorInfo]:
        """
        List all registered operators.

        Args:
            operator_type: Optional filter by operator type

        Returns:
            List of operator information
        """
        operators = []
        for operator in self._operators.values():
            info = operator.get_info()
            if operator_type is None or info.operator_type == operator_type:
                operators.append(info)

        return sorted(operators, key=lambda x: (x.operator_type.value, x.precedence, x.name))


# Global registry instance
_global_registry = OperatorRegistry()


def get_global_registry() -> OperatorRegistry:
    """Get the global operator registry."""
    return _global_registry
