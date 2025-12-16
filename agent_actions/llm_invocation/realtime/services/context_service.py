"""Context preparation service for agent builder."""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union

from agent_actions.utilities.context_scope.static_data_loader import (
    StaticDataLoader,
    StaticDataLoadError,
)

logger = logging.getLogger(__name__)


class ContextService:
    """Handles context preparation and transformation for agents."""

    @staticmethod
    def build_field_context(
        context_data: Union[str, Dict], agent_config: Dict[str, Any]
    ) -> Optional[Dict]:
        """
        Build field_context dict from context_data for field reference replacement.

        **DEPRECATED**: This method is deprecated and should not be used directly.
        Use PromptPreparationService.prepare_prompt_with_context() instead to ensure
        consistent prompt preparation with static data loading, context_scope transformations,
        and field reference replacement.

        See: agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService

        This method is kept only for backward compatibility and testing purposes.

        Args:
            context_data: The context data (str or dict)
            agent_config: Agent configuration

        Returns:
            field_context dict with 'source' and optionally 'static' keys
        """
        import warnings

        warnings.warn(
            "ContextService.build_field_context() is deprecated. "
            "Use PromptPreparationService.prepare_prompt_with_context() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if isinstance(context_data, str):
            try:
                parsed = json.loads(context_data)
            except (json.JSONDecodeError, TypeError):
                return None
        elif isinstance(context_data, dict):
            parsed = context_data
        else:
            return None

        field_context = {"source": parsed}

        # Load seed data if configured
        context_scope = agent_config.get("context_scope", {})

        if context_scope and context_scope.get("seed_data"):
            try:
                # Determine seed_data directory
                static_data_dir = ContextService._determine_static_data_dir(
                    agent_config.get("workflow_config_path")
                )
                logger.debug("[SEED_DATA] Seed data directory: %s", static_data_dir)

                # Load seed data
                static_data_loader = StaticDataLoader(static_data_dir=static_data_dir)
                static_data = static_data_loader.load_static_data(
                    context_scope.get("seed_data", {})
                )

                # Add under 'seed' namespace for {seed.field_name} references
                field_context["seed"] = static_data

                logger.info(
                    f"[SEED_DATA] Loaded {len(static_data)} seed data files: "
                    f"{list(static_data.keys())}"
                )
            except StaticDataLoadError as e:
                logger.error("Failed to load static data in online mode: %s", e)
                # Don't raise - allow workflow to continue without static data
            except Exception as e:
                logger.error("Unexpected error loading static data in online mode: %s", e)
                # Don't raise - allow workflow to continue without static data

        return field_context

    @staticmethod
    def _determine_static_data_dir(workflow_config_path: Optional[str]) -> Path:
        """
        Determine seed_data/ directory for loading static data files.

        Args:
            workflow_config_path: Path to workflow config file

        Returns:
            Path to seed_data/ directory

        Raises:
            StaticDataLoadError: If seed_data/ folder doesn't exist
        """
        # Determine workflow root directory
        if not workflow_config_path:
            base_dir = Path.cwd()
        else:
            file_path_obj = Path(workflow_config_path).resolve()

            # Traverse up to find the directory containing agent_config/
            # This ensures we're at workflow root regardless of nesting
            current = file_path_obj.parent
            while current != current.parent:  # Stop at filesystem root
                if (current / "agent_config").exists():
                    base_dir = current
                    break
                # Also check if current directory name is 'agent_config'
                if current.name == "agent_config" and current.parent != current:
                    base_dir = current.parent
                    break
                current = current.parent
            else:
                # Fallback: use parent directory of config file
                base_dir = file_path_obj.parent

        logger.debug("Determined workflow base directory: %s", base_dir)

        # Check for seed_data/ folder at workflow root
        seed_data_dir = base_dir / "seed_data"
        if seed_data_dir.exists() and seed_data_dir.is_dir():
            logger.debug("Found seed_data/ folder: %s", seed_data_dir)
            return seed_data_dir

        # Not found - raise error
        logger.error("Seed data directory not found. Checked: %s", seed_data_dir)
        raise StaticDataLoadError(
            f"Seed data directory not found. Create '{seed_data_dir}' folder "
            f"at workflow root (same level as agent_config/, schema/, prompt_store/) "
            f"to store static reference data files.",
            context={
                "workflow_dir": str(base_dir),
                "checked_path": str(seed_data_dir),
                "error_type": "missing_seed_data_directory",
            },
        )

    @staticmethod
    def prepare_context_data(
        context_data_str: Union[str, Dict],
        original_context: Optional[Union[str, Dict]],
        is_tool: bool,
    ) -> Union[str, Dict]:
        """
        Prepare context data for LLM/tool invocation.

        CRITICAL: For tool actions, use original_context (not transformed llm_data).
        Tools need access to ALL fields from previous actions, even those dropped
        by context_scope.drop for the LLM.

        Args:
            context_data_str: Context data for LLM (may have context_scope.drop applied)
            original_context: Original untransformed context for tools (optional)
            is_tool: Whether this is a tool vendor invocation

        Returns:
            Prepared context data (str or dict depending on vendor needs)
        """
        # CRITICAL FIX (Issue #487 - Phase 2):
        # For tool actions, use original_context (not transformed llm_data)
        if is_tool and original_context is not None:
            return original_context

        # For tool vendor, return context as-is (dict or str)
        # For LLM vendors, convert to JSON string if dict
        if is_tool:
            return context_data_str
        else:
            if isinstance(context_data_str, str):
                return context_data_str
            else:
                return json.dumps(context_data_str, ensure_ascii=False)

    @staticmethod
    def prepare_tool_context(
        context_data_str: Union[str, Dict], original_context: Optional[Union[str, Dict]]
    ) -> str:
        """
        Prepare tool context as JSON string for tool injection.

        CRITICAL: Use original_context for tool injection (has all fields from previous actions).
        Use context_data (transformed) for LLM only.

        Args:
            context_data_str: Transformed context data (with context_scope.drop applied)
            original_context: Original untransformed context for tools (optional)

        Returns:
            JSON string of tool context
        """
        # Use original context if available, otherwise use context_data_str
        tool_context = original_context if original_context is not None else context_data_str

        # Convert to JSON string if needed
        if isinstance(tool_context, str):
            return tool_context
        else:
            return json.dumps(tool_context, ensure_ascii=False)
