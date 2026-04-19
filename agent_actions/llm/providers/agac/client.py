"""
Agac Provider - Mock LLM Client for Testing.

Provides deterministic fake responses for testing agent-actions features
without real API calls. Generates realistic data based on schema and prompts.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, ClassVar

from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    LLMRequestEvent,
)
from agent_actions.output.response.response_builder import ResponseBuilder

logger = logging.getLogger(__name__)


class AgacClient(BaseClient):
    """
    Agac mock client for testing.

    Features:
    - Schema-aware fake data generation
    - Prompt-aware responses (uses prompt to seed RNG for reproducibility)
    - Field-name-aware generation (email fields get emails, etc.)
    - Attempt-based quality variation for testing reprompt/retry

    Quality by attempt:
    - Attempt 1: Short responses (3 words) - likely fails validation
    - Attempt 2: Medium responses (8 words) - may still fail
    - Attempt 3+: Full responses (25 words) - should pass validation
    """

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": [],
    }

    # Class-level tracking of attempts per ID
    _attempt_counts: dict[str, int] = {}

    @classmethod
    def reset(cls):
        """Reset attempt tracking (useful between tests)."""
        cls._attempt_counts.clear()
        FakeDataGenerator.set_context()  # Reset generator context too
        logger.debug("AgacClient state reset")

    @classmethod
    def _get_attempt_count(cls, identifier: str) -> int:
        """Get current attempt count for an identifier."""
        if identifier not in cls._attempt_counts:
            cls._attempt_counts[identifier] = 0
        cls._attempt_counts[identifier] += 1
        return cls._attempt_counts[identifier]

    @staticmethod
    def get_api_key(agent_config: dict[str, Any]) -> str | None:
        """Override to skip API key validation for mock client."""
        return "agac-mock-key"

    @staticmethod
    def _extract_identifier(context_data: Any) -> str:
        """Extract identifier from context data for attempt tracking."""
        identifier = "default"
        if isinstance(context_data, dict):
            identifier = context_data.get("source_guid", identifier)
        elif isinstance(context_data, str):
            try:
                parsed = json.loads(context_data)
                if isinstance(parsed, dict):
                    identifier = parsed.get("source_guid", identifier)
            except (json.JSONDecodeError, AttributeError):
                logger.debug(
                    "Failed to parse context_data as JSON for identifier extraction", exc_info=True
                )
        return identifier

    @staticmethod
    def _extract_prompt(prompt_config: Any) -> str:
        """Extract prompt text from prompt config."""
        if isinstance(prompt_config, str):
            return prompt_config
        if isinstance(prompt_config, dict):
            # Try common prompt keys
            for key in ("prompt", "system", "user", "content", "text"):
                if key in prompt_config:
                    val = prompt_config[key]
                    if isinstance(val, str):
                        return val
        return str(prompt_config) if prompt_config else ""

    @staticmethod
    def call_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """
        Call in JSON mode with schema-based fake data generation.

        Args:
            api_key: Ignored for mock
            agent_config: Agent configuration
            prompt_config: Prompt configuration (used to seed generation)
            context_data: Context data
            schema: JSON schema for structured output

        Returns:
            List of response dicts matching schema
        """
        identifier = AgacClient._extract_identifier(context_data)
        attempt = AgacClient._get_attempt_count(identifier)
        prompt = AgacClient._extract_prompt(prompt_config)

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event (mock provider)
        fire_event(
            LLMRequestEvent(
                provider="agac-fake-provider",
                model="agac-mock",
                request_id=request_id,
            )
        )

        start_time = datetime.now()

        logger.info(
            "AgacClient.call_json: id=%s, attempt=%d, schema=%s, prompt_len=%d",
            identifier,
            attempt,
            "present" if schema else "absent",
            len(prompt),
        )

        FakeDataGenerator.set_context(prompt=f"{identifier}:{prompt}")

        if schema:
            # Extract the actual schema structure
            # Schema can be: {"name": "...", "schema": {...}} or just {...}
            actual_schema = schema.get("schema", schema)
            fake_data = FakeDataGenerator.generate_from_schema(
                actual_schema, attempt, prompt=prompt
            )
            logger.debug(
                "Generated fake data from schema: attempt=%d, fields=%d",
                attempt,
                len(fake_data) if isinstance(fake_data, dict) else 0,
            )
        else:
            # No schema - generate generic response based on prompt
            fake_data = {
                "result": FakeDataGenerator.generate_text_response(prompt, attempt),
                "status": "success",
            }
            logger.debug("No schema provided, using generic response")

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(
            None, "agac-fake-provider", "agac-mock", latency_ms, request_id
        )

        return [fake_data]

    @staticmethod
    def call_non_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        """
        Call in non-JSON mode with raw text response.

        Args:
            api_key: Ignored for mock
            agent_config: Agent configuration
            prompt_config: Prompt configuration (used to generate response)
            context_data: Context data

        Returns:
            List with single response dict containing output_field
        """
        identifier = AgacClient._extract_identifier(context_data)
        attempt = AgacClient._get_attempt_count(identifier)
        prompt = AgacClient._extract_prompt(prompt_config)

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event (mock provider)
        fire_event(
            LLMRequestEvent(
                provider="agac-fake-provider",
                model="agac-mock",
                request_id=request_id,
            )
        )

        start_time = datetime.now()

        logger.info(
            "AgacClient.call_non_json: id=%s, attempt=%d, prompt_len=%d",
            identifier,
            attempt,
            len(prompt),
        )

        # Generate text response based on prompt
        content = FakeDataGenerator.generate_text_response(prompt, attempt)

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(
            None, "agac-fake-provider", "agac-mock", latency_ms, request_id
        )

        return ResponseBuilder.wrap_non_json(content, agent_config)

    @classmethod
    def invoke(
        cls,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Dispatch to JSON or non-JSON methods."""
        from agent_actions.utils.constants import JSON_MODE_KEY

        json_mode = agent_config.get(JSON_MODE_KEY, True)

        if json_mode:
            return cls.call_json(None, agent_config, prompt_config, context_data, schema)
        if schema is not None:
            logger.warning(
                "json_mode=false but schema was compiled for action '%s'. "
                "The schema will not be sent to the LLM. "
                "Set json_mode=true to enable schema enforcement.",
                agent_config.get("agent_type", "unknown"),
            )
        return cls.call_non_json(None, agent_config, prompt_config, context_data)
