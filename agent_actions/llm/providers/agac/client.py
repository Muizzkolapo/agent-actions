"""
Agac Provider - Mock LLM Client for Testing.

Provides deterministic fake responses for testing agent-actions features
without real API calls. Generates realistic data based on schema and prompts.
"""

import json
import logging
import time
import uuid
from typing import Any, ClassVar

from agent_actions.config import sandbox
from agent_actions.llm.providers.agac import faults
from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator
from agent_actions.llm.providers.client_base import BaseClient, warn_schema_without_json_mode
from agent_actions.llm.providers.generation_params import VendorParamSpec
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    LLMRequestEvent,
)
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.utils import deep_json
from agent_actions.utils.constants import MODEL_NAME_KEY, RECORD_GUID_KEY, RECORD_ID_KEY

logger = logging.getLogger(__name__)


class AgacClient(BaseClient):
    """
    Agac mock client for testing.

    Features:
    - Schema-aware fake data generation
    - Prompt-aware responses (uses prompt to seed RNG for reproducibility)
    - Field-name-aware generation (email fields get emails, etc.)
    - Attempt-based quality variation for testing recovery

    Quality by attempt:
    - Attempt 1: Short responses (3 words) - likely fails validation
    - Attempt 2: Medium responses (8 words) - may still fail
    - Attempt 3+: Full responses (25 words) - should pass validation
    """

    # Fake data reads no request settings, so a workflow switched to it keeps its own.
    VENDOR_PARAMS: ClassVar[VendorParamSpec] = VendorParamSpec(accepted=None)
    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": [],
    }

    @classmethod
    def reset(cls):
        """Reset attempt tracking (useful between tests)."""
        FakeDataGenerator.set_context()  # Reset generator context too
        from agent_actions.llm.providers.agac.contract import reset_runs

        reset_runs()
        logger.debug("AgacClient state reset")

    @classmethod
    def _get_attempt_count(cls, identifier: str, agent_config: Any = None) -> int:
        """How many times this action has been called for this record in this run.

        Each run counts from 1 again: the run, not the process, is what a repair belongs to.
        """
        from agent_actions.llm.providers.agac.contract import next_attempt

        session = (
            agent_config.get("workflow_session_id") if isinstance(agent_config, dict) else None
        )
        return next_attempt(session, identifier)

    @staticmethod
    def get_api_key(agent_config: dict[str, Any]) -> str | None:
        """Override to skip API key validation for mock client."""
        return "agac-mock-key"

    @staticmethod
    def _action_name(agent_config: Any) -> str:
        """The action being generated for, which distinguishes concurrent siblings."""
        if isinstance(agent_config, dict):
            for key in ("name", "agent_type"):
                value = agent_config.get(key)
                if isinstance(value, str) and value:
                    return value
        return "action"

    @staticmethod
    def _extract_identifier(agent_config: Any, context_data: Any) -> str:
        """The record whose attempts are counted: the call's record id, else the context's guid."""
        if isinstance(agent_config, dict):
            record_id = agent_config.get(RECORD_ID_KEY)
            if isinstance(record_id, str) and record_id:
                return record_id
        identifier = "default"
        if isinstance(context_data, dict):
            identifier = context_data.get("source_guid", identifier)
        elif isinstance(context_data, str):
            try:
                parsed = deep_json.loads(context_data)
                if isinstance(parsed, dict):
                    identifier = parsed.get("source_guid", identifier)
            except (json.JSONDecodeError, AttributeError):
                logger.debug(
                    "Failed to parse context_data as JSON for identifier extraction", exc_info=True
                )
        return identifier

    @staticmethod
    def _record_of(agent_config: Any) -> str | None:
        """The record a main call answers, named alike in every run; None for a side call."""
        if isinstance(agent_config, dict):
            for key in (RECORD_GUID_KEY, RECORD_ID_KEY):
                value = agent_config.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    @staticmethod
    def _fault(
        agent_config: dict[str, Any], action: str, context_data: Any, attempt: int
    ) -> tuple[Any, str | None, str | None]:
        """The scenario's rules for this main call, the record, and the fault it fails with.

        Waits the call's latency first. ``(None, None, None)`` outside a sandbox scenario
        and for a side call, which ``judge.pass_rate`` alone governs.
        """
        followed = sandbox.scenario()
        record = AgacClient._record_of(agent_config)
        if followed is None or record is None:
            return None, None, None
        rules = followed.rules_for(action, context_data)
        wait = followed.latency_ms(action, record, attempt, rules)
        if wait:
            time.sleep(wait / 1000)
        fault = followed.error_for(action, record, attempt, rules)
        if fault is not None:
            followed.count("errors")
            logger.info(
                "Sandbox scenario %s: action '%s' fails attempt %d of record %s with %s",
                followed.name,
                action,
                attempt,
                record,
                fault,
            )
        return rules, record, fault

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
        action = AgacClient._action_name(agent_config)
        # Per action and record: a version fan-out sends several actions
        # for one record, and a shared counter would hand them attempt 1, 2 and
        # 3 in whatever order they happened to arrive.
        identifier = f"{action}:{AgacClient._extract_identifier(agent_config, context_data)}"
        attempt = AgacClient._get_attempt_count(identifier, agent_config)
        prompt = AgacClient._extract_prompt(prompt_config)
        # Seeds the generator. The action name makes sibling versions of one
        # prompt answer differently, as a vote needs; the record's guid is left
        # out because it is minted fresh on every run, which would make the same
        # workflow produce different fake data each time it ran.
        seed_key = f"{action}:{prompt}"

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

        start_time = time.perf_counter()

        logger.info(
            "AgacClient.call_json: id=%s, attempt=%d, schema=%s, prompt_len=%d",
            identifier,
            attempt,
            "present" if schema else "absent",
            len(prompt),
        )

        model = str(agent_config.get(MODEL_NAME_KEY) or "agac-mock")
        rules, record, fault = AgacClient._fault(agent_config, action, context_data, attempt)
        if fault is not None and fault not in faults.NEEDS_ANSWER:
            return faults.json_answer(fault, None, model)

        FakeDataGenerator.set_context(prompt=seed_key)

        # Imported here: every vendor loads this module, and only the mock reads rules.
        from agent_actions.llm.providers.agac.contract import Contract

        actual_schema: dict[str, Any] = {}
        if schema:
            actual_schema = FakeDataGenerator.unwrap_schema(schema)
            contract = Contract.for_request(agent_config, action, context_data)
            fake_data = contract.generate(actual_schema, attempt)
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

        if fault is not None:
            return faults.json_answer(fault, fake_data, model)
        followed = sandbox.scenario()
        if rules is not None and record is not None and followed is not None:
            if not schema:
                contract = Contract.for_request(agent_config, action, context_data)
            contract.follow(followed, rules, fake_data, actual_schema, record, attempt)

        latency_ms = (time.perf_counter() - start_time) * 1000

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
        action = AgacClient._action_name(agent_config)
        # Per action and record: a version fan-out sends several actions
        # for one record, and a shared counter would hand them attempt 1, 2 and
        # 3 in whatever order they happened to arrive.
        identifier = f"{action}:{AgacClient._extract_identifier(agent_config, context_data)}"
        attempt = AgacClient._get_attempt_count(identifier, agent_config)
        prompt = AgacClient._extract_prompt(prompt_config)
        # Seeds the generator. The action name makes sibling versions of one
        # prompt answer differently, as a vote needs; the record's guid is left
        # out because it is minted fresh on every run, which would make the same
        # workflow produce different fake data each time it ran.
        seed_key = f"{action}:{prompt}"

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

        start_time = time.perf_counter()

        logger.info(
            "AgacClient.call_non_json: id=%s, attempt=%d, prompt_len=%d",
            identifier,
            attempt,
            len(prompt),
        )

        model = str(agent_config.get(MODEL_NAME_KEY) or "agac-mock")
        _, _, fault = AgacClient._fault(agent_config, action, context_data, attempt)
        if fault is not None:
            return ResponseBuilder.wrap_non_json(faults.text_answer(fault, model), agent_config)

        # A prompt that ends by offering the answer's exact shapes gets one of them back.
        shapes = FakeDataGenerator.offered_answer_shapes(prompt)
        followed = sandbox.scenario()
        if shapes:
            # Seeded without the attempt: every judge call of an action shares one attempt
            # counter, so a verdict seeded with it would depend on the calls before it.
            passing = followed.judge_passes(action, prompt) if followed is not None else None
            content = FakeDataGenerator.generate_offered_answer(shapes, seed_key, passing)
        else:
            content = FakeDataGenerator.generate_text_response(seed_key, attempt)

        latency_ms = (time.perf_counter() - start_time) * 1000

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
            warn_schema_without_json_mode(agent_config)
        return cls.call_non_json(None, agent_config, prompt_config, context_data)
