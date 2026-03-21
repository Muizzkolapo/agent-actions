"""Client for Human-in-the-Loop approval workflow."""

import json
import logging
from pathlib import Path
from typing import Any, ClassVar

from agent_actions.config.schema import HitlConfig
from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.hitl.server import HitlServer

logger = logging.getLogger(__name__)


class HitlClient:
    """Client for Human-in-the-Loop approval workflow."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": False,
        "supports_vision": False,
        "required_fields": [],
        "optional_fields": [],
    }

    @staticmethod
    def invoke(
        agent_config: dict[str, Any],
        context_data: str | dict,
        tool_args: dict[str, Any] | None = None,
        source_content: Any | None = None,
    ) -> dict[str, Any]:
        """
        Launch approval UI and block until user responds.

        Args:
            agent_config: Action configuration containing hitl settings
            context_data: Context data to display (from context_scope.observe)
            tool_args: Unused (for signature compatibility)
            source_content: Unused (for signature compatibility)

        Returns:
            Dict with keys:
            - hitl_status: "approved" | "rejected" | "timeout"
            - user_comment: Optional[str]
            - timestamp: str (ISO format)

        Raises:
            ConfigurationError: If hitl config is missing or invalid
        """
        hitl_config = agent_config.get("hitl")
        if not hitl_config:
            raise ConfigurationError(
                "HITL action requires 'hitl' configuration",
                context={"action_name": agent_config.get("name")},
            )

        # Extract config — defaults sourced from HitlConfig schema (single source of truth)
        _hitl_defaults = HitlConfig.model_fields
        port = hitl_config.get("port", _hitl_defaults["port"].default)
        instructions = hitl_config.get("instructions", "")
        timeout = hitl_config.get("timeout", _hitl_defaults["timeout"].default)
        require_comment_on_reject = hitl_config.get(
            "require_comment_on_reject", _hitl_defaults["require_comment_on_reject"].default
        )

        # Preserve observe field order for UI rendering (full qualified refs)
        context_scope = agent_config.get("context_scope") or {}
        observe_refs = context_scope.get("observe") or []
        field_order = [
            ref for ref in observe_refs if isinstance(ref, str) and not ref.endswith(".*")
        ]

        if isinstance(context_data, str):
            try:
                context_dict = json.loads(context_data)
            except json.JSONDecodeError:
                context_dict = {"raw": context_data}
        else:
            context_dict = context_data

        # Compute state file path for review persistence
        state_file: Path | None = None
        hitl_state_dir = agent_config.get("_hitl_state_dir")
        if hitl_state_dir:
            file_stem = agent_config.get("_hitl_file_stem", "default")
            state_file = Path(hitl_state_dir) / f".hitl_reviews_{file_stem}.json"

        # Start server and wait for response
        server = HitlServer(
            port=port,
            instructions=instructions,
            context_data=context_dict,
            timeout=timeout,
            require_comment_on_reject=require_comment_on_reject,
            field_order=field_order,
            state_file=state_file,
        )

        response = server.start_and_wait()

        logger.info(
            "HITL review completed",
            extra={
                "action_name": agent_config.get("name"),
                "status": response.get("hitl_status"),
                "has_comment": bool(response.get("user_comment")),
            },
        )

        return response
