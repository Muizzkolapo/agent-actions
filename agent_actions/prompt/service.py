"""Unified prompt preparation service for batch and online modes."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError, TemplateVariableError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import ContextFieldNotFoundEvent
from agent_actions.prompt.context.builder import LLMContextBuilder
from agent_actions.prompt.context.scope_application import apply_context_scope
from agent_actions.prompt.context.scope_builder import build_field_context_with_history
from agent_actions.prompt.context.static_loader import (
    StaticDataLoader,
    StaticDataLoadError,
)
from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.prompt.prompt_utils import PromptUtils

logger = logging.getLogger(__name__)


@dataclass
class PromptPreparationRequest:
    """Groups all parameters for prepare_prompt_with_context() to reduce signature complexity."""

    agent_config: dict[str, Any]
    agent_name: str
    contents: dict[str, Any]
    mode: RunMode = RunMode.ONLINE
    agent_indices: dict[str, int] | None = None
    dependency_configs: dict[str, dict] | None = None
    source_content: Any | None = None
    version_context: dict | None = None
    workflow_metadata: dict | None = None
    current_item: dict | None = None
    file_path: str | None = None
    tools_path: str | None = None
    output_directory: str | None = None
    storage_backend: Optional["StorageBackend"] = None


@dataclass
class PromptPreparationResult:
    """Result of prompt preparation with rendered prompt, LLM context, and metadata."""

    formatted_prompt: str
    llm_context: dict[str, Any]
    passthrough_fields: dict[str, Any]
    metadata: dict[str, Any]
    prompt_context: dict[str, Any] | None = None


class PromptPreparationService:
    """Single point of truth for prompt preparation across batch and online modes."""

    @staticmethod
    def is_valid_mode(mode: str) -> bool:
        """Return True if mode is a valid RunMode value."""
        return mode in (RunMode.BATCH, RunMode.ONLINE)

    @staticmethod
    def prepare_prompt_with_context(
        agent_config: dict[str, Any],
        agent_name: str,
        contents: dict[str, Any],
        *,
        mode: RunMode = RunMode.ONLINE,
        agent_indices: dict[str, int] | None = None,
        dependency_configs: dict[str, dict] | None = None,
        source_content: Any | None = None,
        version_context: dict | None = None,
        workflow_metadata: dict | None = None,
        current_item: dict | None = None,
        file_path: str | None = None,
        tools_path: str | None = None,
        output_directory: str | None = None,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> PromptPreparationResult:
        """
        Unified entry point for prompt preparation (batch AND online).

        ARCHITECTURE INVARIANT: Single source of truth for context building.
        Both batch and online MUST use this method to ensure context parity.
        Do not add mode-specific context building logic here or in callers.

        See: https://github.com/Muizzkolapo/agent-actions/issues/640
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
        agent_config: dict[str, Any],
        agent_name: str,
        contents: dict[str, Any],
        *,
        mode: RunMode = RunMode.ONLINE,
        field_context: dict[str, Any],
        tools_path: str | None = None,
    ) -> PromptPreparationResult:
        """Prepare prompt using pre-loaded field_context, skipping context loading."""
        logger.debug(
            "Preparing prompt with pre-loaded context for '%s' in %s mode", agent_name, mode
        )

        raw_prompt = PromptFormatter.get_raw_prompt(agent_config)
        context_scope = agent_config.get("context_scope", {})

        static_data = PromptPreparationService._load_seed_data(
            agent_config, context_scope, agent_name
        )

        if not context_scope:
            PromptPreparationService._raise_missing_context_scope(agent_config, agent_name)

        prompt_context, llm_additional_context, passthrough_fields = apply_context_scope(
            field_context,
            context_scope,
            static_data=static_data,
            action_name=agent_name,
        )

        llm_context = PromptPreparationService._build_llm_context(
            mode=mode,
            contents=contents,
            llm_additional_context=llm_additional_context,
            context_scope=context_scope,
        )

        formatted_prompt = PromptPreparationService._render_prompt_template(
            raw_prompt,
            prompt_context,
            agent_name=agent_name,
            mode=mode,
        )

        formatted_prompt = PromptPreparationService._resolve_and_inject_dispatch(
            formatted_prompt, llm_context, agent_config, tools_path
        )

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
        """Orchestrate the complete prompt preparation pipeline from template to final output."""
        if request.agent_config is None:
            from agent_actions.errors.preflight import ContextStructureError  # type: ignore[unreachable]  # noqa: I001

            raise ContextStructureError(
                "agent_config is required and cannot be None",
                expected_fields=["agent_config"],
                actual_fields=[],
                agent_name=request.agent_name,
                mode=request.mode,
            )

        logger.debug("Preparing prompt for agent '%s' in %s mode", request.agent_name, request.mode)

        agent_indices = request.agent_indices or {}

        raw_prompt = PromptFormatter.get_raw_prompt(request.agent_config)
        logger.debug("Loaded raw prompt (length: %d)", len(raw_prompt))

        context_scope = request.agent_config.get("context_scope", {})

        field_context = build_field_context_with_history(
            agent_name=request.agent_name,
            agent_config=request.agent_config,
            agent_indices=agent_indices,
            source_content=request.source_content,
            version_context=request.version_context,
            workflow_metadata=request.workflow_metadata,
            current_item=request.current_item,
            context_scope=context_scope,
        )
        field_context_metadata: dict[str, Any] = field_context.pop("_dependency_metadata", {})
        logger.debug("Built field context with %d top-level keys", len(field_context))

        static_data = PromptPreparationService._load_seed_data(
            request.agent_config, context_scope, request.agent_name
        )

        if not context_scope:
            PromptPreparationService._raise_missing_context_scope(
                request.agent_config, request.agent_name
            )

        prompt_context, llm_additional_context, passthrough_fields = apply_context_scope(
            field_context,
            context_scope,
            static_data=static_data,
            action_name=request.agent_name,
        )
        logger.debug(
            "Applied context_scope: observe=%d, passthrough=%d, static_data=%d",
            len(llm_additional_context),
            len(passthrough_fields),
            len(static_data),
        )
        logger.debug(
            "prompt_context namespaces after apply_context_scope: %s",
            list(prompt_context.keys()),
        )

        llm_context = PromptPreparationService._build_llm_context(
            mode=request.mode,
            contents=request.contents,
            llm_additional_context=llm_additional_context,
            context_scope=context_scope,
        )
        logger.debug("Built LLM context for %s mode with %d keys", request.mode, len(llm_context))

        formatted_prompt = PromptPreparationService._render_prompt_template(
            raw_prompt,
            prompt_context,
            agent_name=request.agent_name,
            mode=request.mode,
            field_context_metadata=field_context_metadata,
        )

        formatted_prompt = PromptPreparationService._resolve_and_inject_dispatch(
            formatted_prompt, llm_context, request.agent_config, request.tools_path
        )

        metadata: dict[str, Any] = {
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
        prompt_context: dict[str, Any],
        *,
        agent_name: str | None = None,
        mode: str | None = None,
        field_context_metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Render Jinja2 template with the given context.

        Raises:
            TemplateVariableError: If template syntax is invalid or rendering fails.
        """
        if not prompt_context:
            logger.debug("No prompt_context, using raw prompt")
            return raw_prompt

        try:
            jinja_env = Environment(
                undefined=StrictUndefined,
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=True,
            )

            template = jinja_env.from_string(raw_prompt)
            formatted_prompt = template.render(**prompt_context)
            logger.debug("Rendered prompt template with Jinja2")
            return str(formatted_prompt)

        except TemplateSyntaxError as e:
            logger.debug("Jinja2 template syntax error: %s", e)
            raise TemplateVariableError(
                missing_variables=[],
                available_variables=list(prompt_context.keys()),
                template_line=e.lineno,
                agent_name=agent_name or "",
                mode=mode or "",
                cause=e,
            ) from e
        except Exception as e:
            logger.warning("Error rendering prompt template: %s", e, exc_info=True)

            namespace_context: dict[str, list[str]] = {}
            available_refs = []

            def _collect_refs_with_namespace(prefix: str, value: Any) -> None:
                if prefix:
                    available_refs.append(prefix)
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

            for var in missing:
                if "." in var:
                    ns, field = var.split(".", 1)
                    available = namespace_context.get(ns, [])
                    fire_event(
                        ContextFieldNotFoundEvent(
                            action_name=agent_name or "",
                            field_ref=var,
                            namespace=ns,
                            available_fields=available,
                        )
                    )
                else:
                    fire_event(
                        ContextFieldNotFoundEvent(
                            action_name=agent_name or "",
                            field_ref=var,
                            namespace="",
                            available_fields=list(namespace_context.keys()),
                        )
                    )

            # Detect fields that exist in storage but weren't loaded (no schema)
            storage_hints: dict[str, Any] = {}
            if field_context_metadata and missing:
                for var in missing:
                    if "." in var:
                        ns, field = var.split(".", 1)
                        ns_meta = field_context_metadata.get(ns)
                        if ns_meta is None:
                            continue
                        stored = ns_meta.get("stored_fields", [])
                        loaded = ns_meta.get("loaded_fields", [])
                        if field in stored and field not in loaded:
                            storage_hints[var] = {
                                "namespace": ns,
                                "field": field,
                                "stored_count": ns_meta.get("stored_count", 0),
                                "loaded_count": ns_meta.get("loaded_count", 0),
                            }
                    else:
                        # Takes first matching namespace; ambiguous if bare field exists in multiple
                        field = var
                        for ns, ns_meta in field_context_metadata.items():
                            stored = ns_meta.get("stored_fields", [])
                            loaded = ns_meta.get("loaded_fields", [])
                            if field in stored and field not in loaded:
                                storage_hints[var] = {
                                    "namespace": ns,
                                    "field": field,
                                    "stored_count": ns_meta.get("stored_count", 0),
                                    "loaded_count": ns_meta.get("loaded_count", 0),
                                }
                                break

            raise TemplateVariableError(
                missing_variables=missing,
                available_variables=available_refs,
                agent_name=agent_name or "",
                mode=mode or "",
                cause=e,
                namespace_context=namespace_context,
                field_context_metadata=field_context_metadata if field_context_metadata else None,
                storage_hints=storage_hints if storage_hints else None,
            ) from e

    @staticmethod
    def _load_seed_data(
        agent_config: dict[str, Any], context_scope: dict[str, Any], agent_name: str
    ) -> dict[str, Any]:
        """Load seed data files if configured, returning empty dict otherwise."""
        seed_path_config = context_scope.get("seed_path") if context_scope else None
        if not seed_path_config:
            return {}

        try:
            logger.debug("[SEED_DATA_LOAD] Starting seed data loading...")
            static_data_dir = PromptPreparationService._determine_static_data_dir(
                agent_config.get("workflow_config_path")
            )
            logger.debug("[SEED_DATA_LOAD] Seed data directory: %s", static_data_dir)

            static_data_loader = StaticDataLoader(static_data_dir=static_data_dir)
            static_data = static_data_loader.load_static_data(seed_path_config)

            logger.debug(
                "[SEED_DATA_LOAD] Loaded %d seed data files: %s",
                len(static_data),
                list(static_data.keys()),
            )
            logger.debug("[SEED_DATA_LOAD] Seed data keys: %s", list(static_data.keys()))
            return static_data
        except StaticDataLoadError as e:
            logger.exception("Failed to load static data: %s", e)
            raise
        except Exception as e:
            logger.exception("Unexpected error loading static data: %s", e)
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
    def _resolve_and_inject_dispatch(
        formatted_prompt: str,
        llm_context: dict[str, Any],
        agent_config: dict[str, Any],
        tools_path: str | None = None,
    ) -> str:
        """Resolve tools_path from agent_config if needed and inject dispatch_task() results."""
        if not tools_path:
            from agent_actions.utils.tools_resolver import resolve_tools_path

            tools_path = resolve_tools_path(agent_config)

        if tools_path:
            formatted_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
                formatted_prompt,
                tools_path,
                json.dumps(llm_context, ensure_ascii=False),
                agent_config=agent_config,
            )
            logger.debug("Injected function outputs for dispatch_task()")

        return formatted_prompt

    @staticmethod
    def _build_llm_context(
        mode: str,
        contents: dict[str, Any],
        llm_additional_context: dict[str, Any],
        context_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Build the complete LLM context by delegating to the mode-specific builder.

        When context_scope is defined, only observe fields form the LLM context.
        Raw contents never bypass the context_scope gate.

        Raises:
            ConfigurationError: If context_scope is not defined.
            ValueError: If mode is not RunMode.BATCH or RunMode.ONLINE.
        """
        if not context_scope:
            raise ConfigurationError(
                "context_scope is required. Every action must declare data dependencies.",
                context={
                    "hint": "Add context_scope with observe, passthrough, or drop directives."
                },
            )

        # Observe fields (in llm_additional_context) are the sole source of LLM context.
        # Raw contents are never used as the base — context_scope is the gate.
        base: dict[str, Any] = {}

        if mode == RunMode.BATCH:
            return LLMContextBuilder.build_llm_context_for_batch(
                row_content=base,
                llm_context=llm_additional_context,
                context_scope=context_scope,
            )
        if mode == RunMode.ONLINE:
            result = LLMContextBuilder.build_llm_context_for_online(
                processed_context=base,
                llm_additional_context=llm_additional_context,
                context_scope=context_scope,
            )
            return result if isinstance(result, dict) else {}
        raise ValueError(f"Invalid mode '{mode}'. Must be 'batch' or 'online'.")

    @staticmethod
    def _raise_missing_context_scope(agent_config: dict[str, Any], agent_name: str) -> None:
        """Raise ConfigurationError for missing/null context_scope with an actionable hint."""
        context_scope = agent_config.get("context_scope")
        if context_scope is None and "context_scope" in agent_config:
            hint = (
                "context_scope is null — check YAML indentation. "
                "observe/passthrough/drop must be indented under context_scope."
            )
        else:
            hint = "Add context_scope with observe/passthrough/drop directives."
        raise ConfigurationError(
            f"context_scope is required on action '{agent_name}'. {hint}",
            context={"agent_name": agent_name},
        )

    @staticmethod
    def _determine_static_data_dir(workflow_config_path: str | None) -> Path:
        """
        Determine seed data directory using unified PathManager.

        Resolution order:
        1. ``seed_data_path`` from ``agent_actions.yml`` (user-configurable)
        2. Workflow-level directory (sibling of ``agent_config/``)
        3. Project-level directory via ``PathManager``

        The directory name defaults to ``seed_data`` but can be overridden
        by setting ``seed_data_path`` in the project config.

        Raises:
            StaticDataLoadError: If seed data folder doesn't exist.
        """
        from agent_actions.config.path_config import get_seed_data_path
        from agent_actions.config.paths import (
            PathManager,
            ProjectRootNotFoundError,
        )

        workflow_seed_dir = None
        seed_dir_name = "seed_data"
        try:
            pm = PathManager()
            start_path = Path(workflow_config_path).parent if workflow_config_path else None
            if start_path:
                try:
                    project_root = pm.get_project_root(start_path=start_path)
                    seed_dir_name = get_seed_data_path(project_root)
                except ProjectRootNotFoundError:
                    logger.debug("No project root found from %s", start_path)

            if workflow_config_path:
                file_path_obj = Path(workflow_config_path).resolve()
                current = file_path_obj.parent
                workflow_root = None

                search_up = current
                while search_up != search_up.parent:
                    if (search_up / "agent_config").exists():
                        workflow_root = search_up
                        break
                    if search_up.name == "agent_config":  # In case we are inside it
                        workflow_root = search_up.parent
                        break
                    search_up = search_up.parent

                if not workflow_root:
                    workflow_root = current

                workflow_seed_dir = workflow_root / seed_dir_name
                if workflow_seed_dir.exists() and workflow_seed_dir.is_dir():
                    logger.debug("Found workflow-level seed data: %s", workflow_seed_dir)
                    return workflow_seed_dir

            project_seed_dir = pm.get_project_root() / seed_dir_name

            if project_seed_dir.exists() and project_seed_dir.is_dir():
                logger.debug("Found project-level seed data via PathManager: %s", project_seed_dir)
                return project_seed_dir

            logger.warning(
                "Could not find seed data at workflow level (%s) or project level (%s)",
                workflow_seed_dir if workflow_seed_dir is not None else "unknown",
                project_seed_dir,
            )

        except Exception as e:
            logger.warning("Error during seed data resolution: %s", e, exc_info=True)
            # Fall through to error raising

        # Not found - raise error
        raise StaticDataLoadError(
            f"Seed data directory not found. Create '{seed_dir_name}' folder "
            "at workflow root (same level as agent_config/, schema/, prompt_store/) "
            "to store static reference data files.",
            context={
                "workflow_config_path": str(workflow_config_path),
                "error_type": "missing_seed_data_directory",
            },
        )
