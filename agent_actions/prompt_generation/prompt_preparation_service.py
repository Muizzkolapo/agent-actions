"""
Prompt Preparation Service - Unified prompt preparation for batch and realtime modes.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError

from agent_actions.prompt_generation.prompt_formatter import PromptFormatter
from agent_actions.prompt_generation.prompt_utils import PromptUtils
from agent_actions.prompt_generation.sample_enricher import SampleEnricher
from agent_actions.utilities.context_scope.context_scope_processor import ContextScopeProcessor
from agent_actions.utilities.context_scope.llm_context_builder import LLMContextBuilder
from agent_actions.utilities.context_scope.static_data_loader import (
    StaticDataLoader,
    StaticDataLoadError,
)
from agent_actions.validation.preflight import PreFlightValidator
from agent_actions.errors.preflight import TemplateVariableError

logger = logging.getLogger(__name__)


@dataclass
class PromptPreparationRequest:
    """
    Request parameters for prompt preparation.

    This dataclass groups all parameters for prepare_prompt_with_context()
    to reduce method signature complexity. This is a legitimate use case
    for having multiple attributes.

    Attributes:
        agent_config: Agent configuration dict
        agent_name: Name of the agent
        contents: Content dict to process
        mode: Processing mode ('batch' or 'realtime')
        agent_indices: Optional dict mapping agent names to node indices
        dependency_configs: Optional dict mapping dependency names to configs
        source_content: Optional source content for references
        loop_context: Optional loop context for references
        workflow_metadata: Optional workflow metadata for references
        current_item: Optional current item dict
        file_path: Optional file path for history
        tools_path: Optional path to tools directory
    """

    agent_config: Dict[str, Any]
    agent_name: str
    contents: Dict[str, Any]
    mode: Literal["batch", "realtime"] = "realtime"
    agent_indices: Optional[Dict[str, int]] = None
    dependency_configs: Optional[Dict[str, Dict]] = None
    source_content: Optional[Any] = None
    loop_context: Optional[Dict] = None
    workflow_metadata: Optional[Dict] = None
    current_item: Optional[Dict] = None
    file_path: Optional[str] = None
    tools_path: Optional[str] = None


@dataclass
class PromptPreparationResult:
    """
    Result of prompt preparation.

    Attributes:
        formatted_prompt: Fully rendered prompt ready for LLM (with field references replaced,
                         function outputs injected, and few-shot samples appended)
        llm_context: Full context dict for LLM (JSON serializable), includes:
                    - Base content (row_content in batch, processed_context in realtime)
                    - Fields from context_scope.observe
                    - Minus fields from context_scope.drop
        passthrough_fields: Fields to merge into output (from context_scope.passthrough)
        metadata: Debug information including:
                 - field_context_keys: Keys in field_context before context_scope
                 - observe_fields: Fields added from context_scope.observe
                 - drop_fields: Fields removed from context_scope.drop
                 - passthrough_fields: Fields marked for passthrough
                 - mode: Processing mode used (batch or realtime)
        prompt_context: Full context dict used for template rendering (includes all
                       upstream action data, source, seed, etc.)
    """

    formatted_prompt: str
    llm_context: Dict[str, Any]
    passthrough_fields: Dict[str, Any]
    metadata: Dict[str, Any]
    prompt_context: Dict[str, Any] = None  # Optional for backward compat


class PromptPreparationService:
    """
    Unified service for preparing prompts across batch and realtime modes.

    This service orchestrates all prompt preparation steps to ensure consistent
    behavior between online (DataGenerator) and batch (BatchService) modes.

    The service is the SINGLE POINT OF TRUTH for prompt preparation. Both modes
    MUST use this service to prevent divergent behavior.
    """

    @staticmethod
    def is_valid_mode(mode: str) -> bool:
        """
        Validate if the given mode is supported.

        Args:
            mode: The mode to validate ('batch' or 'realtime')

        Returns:
            True if mode is valid, False otherwise
        """
        return mode in ("batch", "realtime")

    @staticmethod
    def prepare_prompt_with_context(
        agent_config: Dict[str, Any],
        agent_name: str,
        contents: Dict[str, Any],
        *,
        mode: Literal["batch", "realtime"] = "realtime",
        agent_indices: Optional[Dict[str, int]] = None,
        dependency_configs: Optional[Dict[str, Dict]] = None,
        source_content: Optional[Any] = None,
        loop_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None,
        current_item: Optional[Dict] = None,
        file_path: Optional[str] = None,
        tools_path: Optional[str] = None,
    ) -> PromptPreparationResult:
        """
        Unified entry point for prompt preparation (batch AND realtime).

        ARCHITECTURE INVARIANT: This is the SINGLE SOURCE OF TRUTH for context
        building. Both batch (via BatchTaskPreparator) and realtime (via
        DataGenerator) MUST use this method to ensure context parity.

        Mode-specific behavior is limited to LLMContextBuilder, which has
        legitimate differences in dict manipulation strategies. The resulting
        prompt_context, formatted_prompt, and passthrough_fields are identical
        across modes.

        DO NOT add mode-specific context building logic here or in callers.
        If you need different context for batch vs realtime, you're likely
        breaking the invariant that templates work identically in both modes.

        See: https://github.com/Muizzkolapo/agent-actions/issues/640

        Args:
            agent_config: Agent configuration dict with prompt, context_scope, etc.
            agent_name: Name of the agent being prepared.
            contents: Content dict to process (row content in batch, processed in realtime).
            mode: Processing mode - 'batch' or 'realtime'.
            agent_indices: Optional dict mapping agent names to node indices.
            dependency_configs: Optional dict mapping dependency names to configs.
            source_content: Optional source content for references.
            loop_context: Optional loop context for references.
            workflow_metadata: Optional workflow metadata for references.
            current_item: Optional current item dict with source_guid, lineage, etc.
            file_path: Optional file path for historical data loading.
            tools_path: Optional path to tools directory for UDF injection.

        Returns:
            PromptPreparationResult containing:
            - formatted_prompt: Fully rendered prompt (identical across modes)
            - llm_context: Context for LLM (mode-specific implementation)
            - passthrough_fields: Fields to merge into output (identical across modes)
            - prompt_context: Full context for template rendering (identical across modes)
            - metadata: Debug information including mode used
        """
        request = PromptPreparationRequest(
            agent_config=agent_config,
            agent_name=agent_name,
            contents=contents,
            mode=mode,
            agent_indices=agent_indices,
            dependency_configs=dependency_configs,
            source_content=source_content,
            loop_context=loop_context,
            workflow_metadata=workflow_metadata,
            current_item=current_item,
            file_path=file_path,
            tools_path=tools_path,
        )
        return PromptPreparationService._prepare_prompt_internal(request)

    @staticmethod
    def _prepare_prompt_internal(request: PromptPreparationRequest) -> PromptPreparationResult:
        """
        Prepare prompt with all transformations applied.

        This method orchestrates the complete prompt preparation pipeline:
        1. Load raw prompt template
        2. Build field context with historical node loading
        3. Apply context_scope transformations (observe/drop/passthrough)
        4. Build LLM context (mode-specific)
        5. Replace field references ({action.field})
        6. Inject function outputs (batch mode only)
        7. Append few-shot samples

        Args:
            request: PromptPreparationRequest with all parameters

        Returns:
            PromptPreparationResult containing:
            - formatted_prompt: Fully rendered prompt
            - llm_context: Full context for LLM
            - passthrough_fields: Fields to merge into output
            - metadata: Debug information
        """
        # Validate required parameters
        if request.agent_config is None:
            from agent_actions.errors.preflight import ContextStructureError

            raise ContextStructureError(
                "agent_config is required and cannot be None",
                expected_fields=["agent_config"],
                actual_fields=[],
                agent_name=request.agent_name,
                mode=request.mode,
            )

        logger.debug("Preparing prompt for agent '%s' in %s mode", request.agent_name, request.mode)

        # Initialize defaults
        agent_indices = request.agent_indices or {}
        dependency_configs = request.dependency_configs or {}

        # Step 1: Load raw prompt template
        raw_prompt = PromptFormatter.get_raw_prompt(request.agent_config)
        logger.debug("Loaded raw prompt (length: %d)", len(raw_prompt))

        # Step 2: Build field context with historical node loading
        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents=request.contents if isinstance(request.contents, dict) else {},
            agent_name=request.agent_name,
            agent_config=request.agent_config,
            agent_indices=agent_indices,
            dependency_configs=dependency_configs,
            source_content=request.source_content,
            loop_context=request.loop_context,
            workflow_metadata=request.workflow_metadata,
            current_item=request.current_item,
            file_path=request.file_path,
        )
        logger.debug("Built field context with %d top-level keys", len(field_context))

        # Step 2.5: Load seed data files if configured
        context_scope = request.agent_config.get("context_scope", {})
        static_data = PromptPreparationService._load_seed_data(
            request.agent_config, context_scope, request.agent_name
        )

        # Step 3: Apply context_scope transformations (observe/drop/passthrough)
        if context_scope:
            prompt_context, llm_additional_context, passthrough_fields = (
                ContextScopeProcessor.apply_context_scope(
                    field_context,
                    context_scope,
                    static_data=static_data,  # Pass static data to processor
                )
            )
            logger.debug(
                "Applied context_scope: observe=%d, passthrough=%d, static_data=%d",
                len(llm_additional_context),
                len(passthrough_fields),
                len(static_data),
            )
        else:
            # No context_scope: use field_context as-is for backward compatibility
            prompt_context = field_context
            llm_additional_context = {}
            passthrough_fields = {}
            logger.debug("No context_scope configured, using field_context as-is")

        # Step 4: Build LLM context (mode-specific)
        llm_context = PromptPreparationService._build_llm_context(
            mode=request.mode,
            contents=request.contents,
            llm_additional_context=llm_additional_context,
            context_scope=context_scope,
        )
        logger.debug("Built LLM context for %s mode with %d keys", request.mode, len(llm_context))

        # Step 4.5: Pre-flight validation - check template variables before rendering
        PromptPreparationService._run_preflight_validation(
            raw_prompt=raw_prompt,
            prompt_context=prompt_context,
            agent_name=request.agent_name,
            mode=request.mode,
            agent_config=request.agent_config,
        )

        # Step 5: Render template with Jinja2 ({{ action.field }})
        formatted_prompt = PromptPreparationService._render_prompt_template(
            raw_prompt, prompt_context
        )

        # Step 6: Inject function outputs (all modes)
        if request.tools_path:
            # Inject llm_context as JSON for dispatch_task() functions
            formatted_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
                formatted_prompt,
                request.tools_path,
                json.dumps(llm_context, ensure_ascii=False),
                agent_config=request.agent_config,
            )
            logger.debug("Injected function outputs for dispatch_task()")

        # Step 7: Append few-shot samples
        formatted_prompt = SampleEnricher.append_few_shot_samples(
            formatted_prompt, request.agent_config, request.agent_name
        )
        logger.debug("Appended few-shot samples")

        # Build metadata for debugging
        metadata = {
            "mode": request.mode,
            "field_context_keys": list(field_context.keys()),
            "observe_fields": list(llm_additional_context.keys()),
            "passthrough_fields": list(passthrough_fields.keys()),
            "drop_fields": context_scope.get("drop", []) if context_scope else [],
            "prompt_length": len(formatted_prompt),
            "llm_context_keys": list(llm_context.keys()) if isinstance(llm_context, dict) else [],
        }

        logger.debug(
            "Prompt preparation complete for '%s': prompt_length=%d, llm_context_keys=%d",
            request.agent_name,
            metadata["prompt_length"],
            len(metadata["llm_context_keys"]),
        )

        return PromptPreparationResult(
            formatted_prompt=formatted_prompt,
            llm_context=llm_context,
            passthrough_fields=passthrough_fields,
            metadata=metadata,
            prompt_context=prompt_context,
        )

    @staticmethod
    def _render_prompt_template(raw_prompt: str, prompt_context: Dict[str, Any]) -> str:
        """
        Render Jinja2 template with the given context.

        Args:
            raw_prompt: Raw prompt template string
            prompt_context: Context dict for template rendering

        Returns:
            Rendered prompt string

        Raises:
            TemplateVariableError: If template syntax is invalid or rendering fails
        """
        if not prompt_context:
            logger.debug("No prompt_context, using raw prompt")
            return raw_prompt

        try:
            # Create Jinja2 environment with strict undefined checking
            jinja_env = Environment(
                undefined=StrictUndefined,
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=True,
            )

            # Parse and render template
            template = jinja_env.from_string(raw_prompt)
            formatted_prompt = template.render(**prompt_context)
            logger.debug("Rendered prompt template with Jinja2")
            return formatted_prompt

        except TemplateSyntaxError as e:
            logger.debug("Jinja2 template syntax error: %s", e)
            raise TemplateVariableError(
                missing_variables=[],
                available_variables=list(prompt_context.keys()),
                template_line=e.lineno,
                cause=e,
            ) from e
        except Exception as e:
            logger.debug("Error rendering prompt template: %s", e)
            # Build available refs including nested fields from source/seed
            available_refs = list(prompt_context.keys())
            # Add nested fields from 'source' to show what's in staged data
            source_data = prompt_context.get("source")
            if isinstance(source_data, dict):
                for key in source_data.keys():
                    available_refs.append(f"source.{key}")
            # Add nested fields from 'seed' if present
            seed_data = prompt_context.get("seed")
            if isinstance(seed_data, dict):
                for key in seed_data.keys():
                    available_refs.append(f"seed.{key}")

            # Extract missing variable from error message if possible
            error_str = str(e)
            missing = []
            if "has no attribute" in error_str or "is undefined" in error_str:
                # Try to extract the missing variable name
                import re

                match = re.search(r"'(\w+)'", error_str)
                if match:
                    missing.append(match.group(1))
            raise TemplateVariableError(
                missing_variables=missing,
                available_variables=available_refs,
                cause=e,
            ) from e

    @staticmethod
    def _load_seed_data(
        agent_config: Dict[str, Any], context_scope: Dict[str, Any], agent_name: str
    ) -> Dict[str, Any]:
        """
        Load seed data files if configured.

        Args:
            agent_config: Agent configuration dict
            context_scope: Context scope configuration
            agent_name: Name of the agent (for error reporting)

        Returns:
            Dictionary of loaded static data, or empty dict if not configured
        """
        if not context_scope or not context_scope.get("seed_data"):
            return {}

        try:
            logger.debug("[SEED_DATA_LOAD] Starting seed data loading...")
            # Determine seed_data directory from workflow config path
            static_data_dir = PromptPreparationService._determine_static_data_dir(
                agent_config.get("workflow_config_path")
            )
            logger.debug("[SEED_DATA_LOAD] Seed data directory: %s", static_data_dir)

            # Load seed data
            static_data_loader = StaticDataLoader(static_data_dir=static_data_dir)
            static_data = static_data_loader.load_static_data(context_scope.get("seed_data", {}))

            logger.debug(
                "[SEED_DATA_LOAD] Loaded %d seed data files: %s",
                len(static_data),
                list(static_data.keys()),
            )
            logger.debug("[SEED_DATA_LOAD] Seed data keys: %s", list(static_data.keys()))
            return static_data
        except StaticDataLoadError as e:
            logger.error("Failed to load static data: %s", e)
            raise
        except Exception as e:
            logger.error("Unexpected error loading static data: %s", e)
            raise StaticDataLoadError(
                f"Failed to load static data: {str(e)}",
                context={
                    "agent_name": agent_name,
                    "error": str(e),
                    "error_type": "unexpected_static_data_error",
                },
                cause=e,
            ) from e

    @staticmethod
    def _build_llm_context(
        mode: str,
        contents: Dict[str, Any],
        llm_additional_context: Dict[str, Any],
        context_scope: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build the complete LLM context (mode-specific).

        This method delegates to the appropriate LLMContextBuilder method based on mode.

        Args:
            mode: Processing mode ('batch' or 'realtime')
            contents: Base content dict (row_content in batch, processed_context in realtime)
            llm_additional_context: Fields from context_scope.observe
            context_scope: Optional context scope configuration

        Returns:
            Dict ready for JSON serialization and LLM invocation

        Raises:
            ValueError: If mode is invalid
        """
        # Ensure contents is a dict (handle None or non-dict gracefully)
        safe_contents = contents if isinstance(contents, dict) else {}

        if mode == "batch":
            # Batch mode: Start with row_content, remove drops, add observes
            return LLMContextBuilder.build_llm_context_for_batch(
                row_content=safe_contents,
                llm_context=llm_additional_context,
                context_scope=context_scope,
            )
        if mode == "realtime":
            # Realtime mode: Start with processed_context, use DataTransformer for drops
            result = LLMContextBuilder.build_llm_context_for_realtime(
                processed_context=safe_contents,
                llm_additional_context=llm_additional_context,
                context_scope=context_scope,
            )
            # Ensure result is always a dict (DataTransformer might return non-dict)
            return result if isinstance(result, dict) else {}
        raise ValueError(f"Invalid mode '{mode}'. Must be 'batch' or 'realtime'.")

    @staticmethod
    def _run_preflight_validation(
        raw_prompt: str,
        prompt_context: Dict[str, Any],
        agent_name: str,
        mode: str,
        agent_config: Dict[str, Any],
    ) -> None:
        """
        Run pre-flight validation on template and context before rendering.

        Validates template variables are available in context before rendering.
        This catches configuration errors early with unified error messages
        across batch and online modes.

        Args:
            raw_prompt: The raw prompt template
            prompt_context: The context dictionary for template rendering
            agent_name: Name of the agent being processed
            mode: Processing mode ('batch' or 'realtime')
            agent_config: Agent configuration dictionary

        Raises:
            PreFlightValidationError: If validation fails
        """
        if not raw_prompt or not prompt_context:
            return  # Nothing to validate

        validator = PreFlightValidator()
        result = validator.validate(
            template=raw_prompt,
            context=prompt_context,
            agent_name=agent_name,
            mode=mode,
            agent_config=agent_config,
        )

        # Raise unified error if validation fails
        result.raise_if_invalid()

    @staticmethod
    def _determine_static_data_dir(workflow_config_path: Optional[str]) -> Path:
        """
        Determine seed_data/ directory for loading static data files.

        Args:
            workflow_config_path: Path to workflow config file
                (from agent_config['workflow_config_path'])

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


# Note: PromptPreparationService is stateless - call methods directly via the class
# or create instances as needed. No global singleton is required.
