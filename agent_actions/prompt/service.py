"""
Prompt Preparation Service - Unified prompt preparation for batch and realtime modes.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Literal, TYPE_CHECKING
from dataclasses import dataclass
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

from agent_actions.errors import TemplateVariableError
from agent_actions.logging import fire_event
from agent_actions.logging.events.types import ContextFieldNotFoundEvent
from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.prompt.prompt_utils import PromptUtils
from agent_actions.prompt.context.scope import ContextScopeProcessor
from agent_actions.prompt.context.builder import LLMContextBuilder
from agent_actions.prompt.context.static_loader import (
    StaticDataLoader,
    StaticDataLoadError,
)

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
        version_context: Optional loop context for references
        workflow_metadata: Optional workflow metadata for references
        current_item: Optional current item dict
        file_path: Optional file path for history
        tools_path: Optional path to tools directory
        output_directory: Optional output directory path for storage backend lookup
        storage_backend: Optional storage backend for loading historical data from SQLite/TinyDB
    """

    agent_config: Dict[str, Any]
    agent_name: str
    contents: Dict[str, Any]
    mode: Literal["batch", "realtime"] = "realtime"
    agent_indices: Optional[Dict[str, int]] = None
    dependency_configs: Optional[Dict[str, Dict]] = None
    source_content: Optional[Any] = None
    version_context: Optional[Dict] = None
    workflow_metadata: Optional[Dict] = None
    current_item: Optional[Dict] = None
    file_path: Optional[str] = None
    tools_path: Optional[str] = None
    output_directory: Optional[str] = None
    storage_backend: Optional["StorageBackend"] = None


@dataclass
class PromptPreparationResult:
    """
    Result of prompt preparation.

    Attributes:
        formatted_prompt: Fully rendered prompt ready for LLM (with field references replaced,
                         function outputs injected)
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
        version_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None,
        current_item: Optional[Dict] = None,
        file_path: Optional[str] = None,
        tools_path: Optional[str] = None,
        output_directory: Optional[str] = None,
        storage_backend: Optional["StorageBackend"] = None,
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
            version_context: Optional loop context for references.
            workflow_metadata: Optional workflow metadata for references.
            current_item: Optional current item dict with source_guid, lineage, etc.
            file_path: Optional file path for historical data loading.
            tools_path: Optional path to tools directory for UDF injection.
            output_directory: Optional output directory path for storage backend lookup.
            storage_backend: Optional storage backend for loading historical data from SQLite/TinyDB.

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
            version_context=version_context,
            workflow_metadata=workflow_metadata,
            current_item=current_item,
            file_path=file_path,
            tools_path=tools_path,
            output_directory=output_directory,
            storage_backend=storage_backend,
        )
        return PromptPreparationService._prepare_prompt_internal(request)

    @staticmethod
    def prepare_prompt_with_field_context(
        agent_config: Dict[str, Any],
        agent_name: str,
        contents: Dict[str, Any],
        *,
        mode: Literal["batch", "realtime"] = "realtime",
        field_context: Dict[str, Any],
        tools_path: Optional[str] = None,
    ) -> PromptPreparationResult:
        """
        Prepare prompt using pre-loaded field_context.

        This method is used when field_context has already been loaded
        (e.g., for guard evaluation). It skips the context loading step
        and proceeds directly to context_scope transformations and rendering.

        Args:
            agent_config: Agent configuration dict
            agent_name: Name of the agent
            contents: Content dict to process
            mode: Processing mode - 'batch' or 'realtime'
            field_context: Pre-loaded field context (from build_field_context_with_history)
            tools_path: Optional path to tools directory for UDF injection

        Returns:
            PromptPreparationResult with formatted_prompt, llm_context, etc.
        """
        logger.debug(
            "Preparing prompt with pre-loaded context for '%s' in %s mode",
            agent_name, mode
        )

        # Step 1: Load raw prompt template
        raw_prompt = PromptFormatter.get_raw_prompt(agent_config)

        # Step 2: Extract context_scope (already normalized by config pipeline)
        context_scope = agent_config.get("context_scope", {})

        # Step 3: Load seed data if configured
        static_data = PromptPreparationService._load_seed_data(
            agent_config, context_scope, agent_name
        )

        # Step 4: Apply context_scope transformations
        if context_scope:
            prompt_context, llm_additional_context, passthrough_fields = (
                ContextScopeProcessor.apply_context_scope(
                    field_context,
                    context_scope,
                    static_data=static_data,
                    action_name=agent_name,
                )
            )
        else:
            prompt_context = field_context
            llm_additional_context = {}
            passthrough_fields = {}

        # Step 5: Build LLM context
        llm_context = PromptPreparationService._build_llm_context(
            mode=mode,
            contents=contents,
            llm_additional_context=llm_additional_context,
            context_scope=context_scope,
        )

        # Step 6: Render template
        formatted_prompt = PromptPreparationService._render_prompt_template(
            raw_prompt,
            prompt_context,
            agent_name=agent_name,
            mode=mode,
        )

        # Step 7: Inject function outputs
        if tools_path:
            formatted_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
                formatted_prompt,
                tools_path,
                json.dumps(llm_context, ensure_ascii=False),
                agent_config=agent_config,
            )

        # Build metadata
        metadata = {
            "mode": mode,
            "field_context_keys": list(field_context.keys()),
            "observe_fields": list(llm_additional_context.keys()),
            "passthrough_fields": list(passthrough_fields.keys()),
            "prompt_length": len(formatted_prompt),
            "llm_context_keys": list(llm_context.keys()) if isinstance(llm_context, dict) else [],
            "preloaded_context": True,
        }

        return PromptPreparationResult(
            formatted_prompt=formatted_prompt,
            llm_context=llm_context,
            passthrough_fields=passthrough_fields,
            metadata=metadata,
            prompt_context=prompt_context,
        )

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
        7. Finalize formatted prompt

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

        # Step 1.5: Extract context_scope for progressive data exposure
        # Already normalized by config pipeline (version references expanded)
        context_scope = request.agent_config.get("context_scope", {})

        # Step 2: Build field context with historical node loading
        # Pass context_scope to control which fields are loaded (progressive data exposure)
        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents=request.contents if isinstance(request.contents, dict) else {},
            agent_name=request.agent_name,
            agent_config=request.agent_config,
            agent_indices=agent_indices,
            dependency_configs=dependency_configs,
            source_content=request.source_content,
            version_context=request.version_context,
            workflow_metadata=request.workflow_metadata,
            current_item=request.current_item,
            file_path=request.file_path,
            context_scope=context_scope,  # NEW: Controls which fields to load
            output_directory=request.output_directory,  # For storage backend lookup
            storage_backend=request.storage_backend,  # For loading historical data from SQLite/TinyDB
        )
        logger.debug("Built field context with %d top-level keys", len(field_context))

        # Step 2.5: Load seed data files if configured
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
                    action_name=request.agent_name,
                )
            )
            logger.debug(
                "Applied context_scope: observe=%d, passthrough=%d, static_data=%d",
                len(llm_additional_context),
                len(passthrough_fields),
                len(static_data),
            )
            logger.debug(
                "DEBUG: prompt_context namespaces after apply_context_scope: %s",
                list(prompt_context.keys()),
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

        # Step 5: Render template with Jinja2 ({{ action.field }})
        formatted_prompt = PromptPreparationService._render_prompt_template(
            raw_prompt,
            prompt_context,
            agent_name=request.agent_name,
            mode=request.mode,
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

        # Step 7: Finalize formatted prompt

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
    def _render_prompt_template(
        raw_prompt: str,
        prompt_context: Dict[str, Any],
        *,
        agent_name: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> str:
        """
        Render Jinja2 template with the given context.

        Args:
            raw_prompt: Raw prompt template string
            prompt_context: Context dict for template rendering
            agent_name: Optional agent name for error context
            mode: Optional execution mode for error context

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
                agent_name=agent_name,
                mode=mode,
                cause=e,
            ) from e
        except Exception as e:
            logger.debug("Error rendering prompt template: %s", e)

            # Build namespace-aware context (grouped by namespace)
            namespace_context = {}
            available_refs = []

            def _collect_refs_with_namespace(prefix: str, value: Any) -> None:
                if prefix:
                    available_refs.append(prefix)
                    # Track by namespace (top-level key)
                    parts = prefix.split(".", 1)
                    ns = parts[0]
                    if ns not in namespace_context:
                        namespace_context[ns] = []
                    if len(parts) > 1:
                        namespace_context[ns].append(parts[1])
                if isinstance(value, dict):
                    for child_key, child_value in value.items():
                        child_prefix = f"{prefix}.{child_key}" if prefix else child_key
                        _collect_refs_with_namespace(child_prefix, child_value)

            _collect_refs_with_namespace("", prompt_context)

            error_str = str(e)
            missing = []
            if "has no attribute" in error_str or "is undefined" in error_str:
                import re

                attribute_match = re.search(r"has no attribute '([^']+)'", error_str)
                if attribute_match:
                    missing.append(attribute_match.group(1))
                else:
                    undefined_match = re.search(r"'([^']+)' is undefined", error_str)
                    if undefined_match:
                        missing.append(undefined_match.group(1))

            # Fire event for each missing field to help with debugging
            for var in missing:
                if "." in var:
                    ns, field = var.split(".", 1)
                    available = namespace_context.get(ns, [])
                    fire_event(
                        ContextFieldNotFoundEvent(
                            action_name=agent_name,
                            field_ref=var,
                            namespace=ns,
                            available_fields=available,
                        )
                    )
                else:
                    # Top-level variable not in a namespace
                    fire_event(
                        ContextFieldNotFoundEvent(
                            action_name=agent_name,
                            field_ref=var,
                            namespace="",
                            available_fields=list(namespace_context.keys()),
                        )
                    )

            raise TemplateVariableError(
                missing_variables=missing,
                available_variables=available_refs,
                agent_name=agent_name,
                mode=mode,
                cause=e,
                namespace_context=namespace_context,
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
    def _determine_static_data_dir(workflow_config_path: Optional[str]) -> Path:
        """
        Determine seed_data/ directory using unified PathManager.

        Args:
            workflow_config_path: Path to workflow config file
                (used as a hint for project root discovery)

        Returns:
            Path to seed_data/ directory

        Raises:
            StaticDataLoadError: If seed_data/ folder doesn't exist
        """
        from agent_actions.config.paths import (
            PathManager,
            PathType,
            ProjectRootNotFoundError,
        )

        try:
            # LEVEL 1: Workflow-specific seed data (Priority)
            if workflow_config_path:
                file_path_obj = Path(workflow_config_path).resolve()
                # Heuristic: Find workflow root by looking for 'agent_config'
                current = file_path_obj.parent
                workflow_root = None

                # Traverse up to find directory containing agent_config
                search_up = current
                while search_up != search_up.parent:
                    if (search_up / "agent_config").exists():
                        workflow_root = search_up
                        break
                    if search_up.name == "agent_config":  # In case we are inside it
                        workflow_root = search_up.parent
                        break
                    search_up = search_up.parent

                # Fallback to config file's parent if heuristic fails
                if not workflow_root:
                    workflow_root = current

                workflow_seed_dir = workflow_root / "seed_data"
                if workflow_seed_dir.exists() and workflow_seed_dir.is_dir():
                    logger.debug("Found workflow-level seed_data: %s", workflow_seed_dir)
                    return workflow_seed_dir

            # LEVEL 2: Project-level seed data (Fallback via PathManager)
            pm = PathManager()

            # Hint PathManager with workflow path if available
            start_path = Path(workflow_config_path).parent if workflow_config_path else None
            if start_path:
                try:
                    pm.get_project_root(start_path=start_path)
                except ProjectRootNotFoundError:
                    pass

            project_seed_dir = pm.get_standard_path(PathType.SEED_DATA)

            if project_seed_dir.exists() and project_seed_dir.is_dir():
                logger.debug("Found project-level seed_data via PathManager: %s", project_seed_dir)
                return project_seed_dir

            logger.warning(
                "Could not find seed_data at workflow level (%s) or project level (%s)",
                workflow_seed_dir if "workflow_seed_dir" in locals() else "unknown",
                project_seed_dir,
            )

        except Exception as e:
            logger.debug("Error during seed data resolution: %s", e)
            # Fall through to error raising

        # Not found - raise error
        raise StaticDataLoadError(
            f"Seed data directory not found. Create 'seed_data' folder "
            f"at workflow root (same level as agent_config/, schema/, prompt_store/) "
            f"to store static reference data files.",
            context={
                "workflow_config_path": str(workflow_config_path),
                "error_type": "missing_seed_data_directory",
            },
        )


# Note: PromptPreparationService is stateless - call methods directly via the class
# or create instances as needed. No global singleton is required.
