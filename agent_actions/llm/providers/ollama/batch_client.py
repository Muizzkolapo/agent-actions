"""
Ollama Batch Client — batch simulation for local and cloud.

Both vendors use the same in-process loop (no real batch API exists for
either). The ``cloud`` flag controls client construction (Bearer auth)
and whether the ``format`` param is passed to ``client.chat()``.

Records are processed concurrently via ``ThreadPoolExecutor``.  Its worker count
is the action's ``batch_max_workers`` (the constructor's ``max_workers``), else
``OLLAMA_BATCH_MAX_WORKERS``, else 1 (sequential).  ``record_concurrency`` is the
online setting: it never sets these workers, and is refused on a batch action.

When Ollama ships a real cloud batch API, add a
``_submit_to_cloud_batch_api`` branch inside ``_submit_to_provider_api``.
"""

import contextvars
import json
import logging
import os
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ollama import Client

from agent_actions.config.defaults import LLMDefaults, OllamaCloudDefaults, OllamaDefaults
from agent_actions.errors import ConfigurationError, VendorAPIError
from agent_actions.llm.providers.error_wrapper import wrap_vendor_error
from agent_actions.llm.providers.ollama.client import (
    _ERROR_MAPPING_CLOUD,
    _ERROR_MAPPING_LOCAL,
    _VENDOR_PARAMS,
    _extract_ollama_schema,
    read_json_reply,
)
from agent_actions.llm.providers.ollama.failure_injection import (
    failed_batch_id_for,
    is_injected_failed_batch,
    should_fail_batch_record,
)
from agent_actions.prompt.message_builder import MessageBuilder

from ..batch_base import BaseBatchClient, BatchResult, BatchTask
from ..mixins import OpenAICompatibleResponseMixin

logger = logging.getLogger(__name__)


def _finish_reason(ollama_response: dict | object) -> str:
    """Why the model stopped, from ``done_reason`` (``stop``, ``length``, ...) as online reads
    it."""
    if isinstance(ollama_response, dict):
        done_reason = ollama_response.get("done_reason")
        done = ollama_response.get("done")
    else:
        done_reason = getattr(ollama_response, "done_reason", None)
        done = getattr(ollama_response, "done", False)
    if done_reason:
        return str(done_reason)
    return "stop" if done else "length"


class OllamaBatchClient(OpenAICompatibleResponseMixin, BaseBatchClient):
    """
    Ollama batch client with in-process simulation.

    Parameterized by ``vendor_slug`` and ``cloud`` to serve both
    ``ollama_local`` and ``ollama_cloud`` from a single class.
    """

    _vendor_label = "Ollama"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        vendor_slug: str = "ollama_local",
        cloud: bool = False,
        max_workers: int | None = None,
        timeout: float = LLMDefaults.REQUEST_TIMEOUT_SECONDS,
    ):
        self.vendor_slug = vendor_slug
        self.cloud = cloud
        self._max_workers = max_workers

        if cloud:
            self.base_url = base_url or os.getenv(
                "OLLAMA_CLOUD_HOST", OllamaCloudDefaults.BASE_URL
            )
            if not api_key:
                raise ConfigurationError(
                    "ollama_cloud batch requires an API key",
                    context={
                        "vendor": "ollama_cloud",
                        "hint": (
                            "Set api_key in your action config or export OLLAMA_API_KEY. "
                            "Create a key at https://ollama.com/settings/keys"
                        ),
                    },
                )
            self.client = Client(
                host=self.base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
        else:
            self.base_url = base_url or os.getenv("OLLAMA_HOST", OllamaDefaults.BASE_URL)
            self.client = Client(host=self.base_url, timeout=timeout)

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Format task as OpenAI-compatible JSONL (for consistency)."""
        model_name = batch_task.model_config.get("model_name", self._get_default_model())
        # The messages online sends.
        envelope = MessageBuilder.build(
            self.vendor_slug,
            batch_task.prompt,
            batch_task.user_content,
            schema=schema,
            json_mode=batch_task.json_mode(schema),
            context_window=batch_task.model_config.get("context_window"),
        )
        body: dict[str, Any] = {
            "model": model_name,
            "messages": envelope.to_dicts(),
        }

        temperature = batch_task.model_config.get("temperature")
        if temperature is not None:
            body["temperature"] = temperature

        max_tokens = batch_task.model_config.get("max_tokens")
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        body.update(self._sampling_params(batch_task.model_config, stop_as_list=True))

        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": schema}
        elif batch_task.model_config.get("json_mode"):
            body["response_format"] = {"type": "json_object"}
        if batch_task.model_config.get("vendor_params"):
            body["vendor_params"] = batch_task.model_config.get("vendor_params")

        return {
            "custom_id": batch_task.custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body,
        }

    def _get_default_model(self) -> str:
        return "llama2"

    def _prepare_batch_input_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        return self._write_jsonl_file(tasks, batch_dir, batch_name, self.vendor_slug)

    _MAX_WORKERS_LIMIT: int = 32

    def _get_max_workers(self) -> int:
        """Resolve batch concurrency: constructor param > env var > class default."""
        default = (
            OllamaCloudDefaults.BATCH_MAX_WORKERS
            if self.cloud
            else OllamaDefaults.BATCH_MAX_WORKERS
        )

        setting = "batch_max_workers"
        if self._max_workers is not None:
            val = self._max_workers
        else:
            setting = "OLLAMA_BATCH_MAX_WORKERS"
            env_val = os.getenv(setting)
            if env_val:
                try:
                    val = int(env_val)
                except ValueError:
                    logger.warning(
                        "OLLAMA_BATCH_MAX_WORKERS=%s is not an integer, using default", env_val
                    )
                    return default
            else:
                return default

        if val < 1:
            logger.warning("%s=%s invalid (must be >= 1), using default", setting, val)
            return default
        if val > self._MAX_WORKERS_LIMIT:
            logger.warning(
                "%s=%s exceeds limit of %s, clamping",
                setting,
                val,
                self._MAX_WORKERS_LIMIT,
            )
            return self._MAX_WORKERS_LIMIT
        return val

    def _process_single_task(
        self, task: dict[str, Any], idx: int, total: int
    ) -> dict[str, Any] | None:
        """Process one batch task. Returns result dict, or None if injection-dropped."""
        custom_id = task["custom_id"]
        logger.debug("Processing request %d/%d: %s", idx + 1, total, custom_id)

        try:
            body = task["body"]
            messages = body["messages"]
            model = body.get("model", self._get_default_model())

            options: dict[str, Any] = {}
            temperature = body.get("temperature")
            if temperature is not None:
                options["temperature"] = temperature
            max_tokens = body.get("max_tokens")
            if max_tokens is not None:
                options["num_predict"] = max_tokens
            options.update({key: body[key] for key in ("top_p", "stop") if key in body})

            # Handle JSON mode with structured outputs.
            # Cloud: format param not supported (ollama/ollama#12362).
            format_param: str | dict[str, Any] | None = None
            if not self.cloud:
                response_format = body.get("response_format")
                if response_format and isinstance(response_format, dict):
                    if response_format.get("type") == "json_schema":
                        json_schema = response_format.get("json_schema", {})
                        format_param = _extract_ollama_schema(json_schema)
                    if not format_param:
                        format_param = "json"

            chat_kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "options": options,
                "format": format_param,
            }
            ollama_response = self.client.chat(**_VENDOR_PARAMS.apply(chat_kwargs, body))

            if should_fail_batch_record(custom_id, idx):
                logger.debug("[INJECTION] Simulating missing result for %s", custom_id)
                return None

            return self._transform_ollama_response(
                ollama_response,
                custom_id,
                model,  # type: ignore[arg-type]
            )

        except Exception as e:
            logger.error("Error processing %s: %s", custom_id, e)
            status = self._http_status(e)
            return {
                "custom_id": custom_id,
                "response": None,
                "error": {
                    "message": str(e),
                    "type": f"{self.vendor_slug}_error",
                    "code": "inference_error",
                    "status": status,
                },
                # Beside the error, not in it: the error dict becomes the record's error text.
                "retriable": (
                    self._online_retries(e, str(task.get("body", {}).get("model", "")))
                    if status is None
                    else None
                ),
            }

    @staticmethod
    def _http_status(error: Exception) -> int | None:
        """The status of an HTTP error answer; None for a failure that got no answer."""
        status = getattr(error, "status_code", None)
        if status is None:
            status = getattr(getattr(error, "response", None), "status_code", None)
        return status if isinstance(status, int) and status > 0 else None

    def _online_retries(self, error: Exception, model: str) -> bool:
        """Whether the online client retries *error*, classified as it classifies it."""
        from agent_actions.processing.recovery.retry import is_retriable_error

        mapping = _ERROR_MAPPING_CLOUD if self.cloud else _ERROR_MAPPING_LOCAL
        return is_retriable_error(wrap_vendor_error(error, model, mapping))

    def _extract_error_status(self, raw_response: dict[str, Any]) -> int | None:
        error = raw_response.get("error")
        status = error.get("status") if isinstance(error, dict) else None
        return status if isinstance(status, int) else None

    def _extract_retriable(self, raw_response: dict[str, Any]) -> bool | None:
        retriable = raw_response.get("retriable")
        return retriable if isinstance(retriable, bool) else None

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> tuple[str, str]:
        """Process batch with concurrent workers (default: 1 = sequential)."""
        injected_failed_id = failed_batch_id_for(batch_name)
        if injected_failed_id is not None:
            return (injected_failed_id, "submitted")

        batch_id = f"batch_{uuid.uuid4().hex}"

        tasks: list[dict[str, Any]] = []
        with open(input_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    tasks.append(json.loads(line))

        total = len(tasks)
        max_workers = self._get_max_workers()
        results: list[dict[str, Any]] = []

        with ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="ollama_batch"
        ) as pool:
            futures: dict[Future[dict[str, Any] | None], str] = {
                pool.submit(
                    contextvars.copy_context().run, self._process_single_task, task, idx, total
                ): task["custom_id"]
                for idx, task in enumerate(tasks)
            }
            for future in as_completed(futures):
                custom_id = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        results.append(result)
                except Exception as e:
                    logger.error("Unexpected error processing %s: %s", custom_id, e)

        completed = sum(1 for r in results if r.get("error") is None)
        failed = total - completed

        batch_dir = input_file.parent
        output_file_path = batch_dir / f"{batch_id}_results.jsonl"

        with open(output_file_path, "w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(result) + "\n")

        logger.info("%s batch output file: %s", self.vendor_slug, output_file_path)
        if failed > 0:
            logger.warning(
                "Batch completed with failures: %d succeeded, %d failed", completed, failed
            )
        else:
            logger.info("Batch completed successfully: %d records", completed)

        return (batch_id, "submitted")

    def _fetch_status(self, batch_id: str) -> str:
        if is_injected_failed_batch(batch_id):
            return "failed"
        return "completed"

    def _normalize_status(self, raw_status: str) -> str:
        return raw_status

    def retrieve_results(
        self, batch_id: str, output_directory: str | None = None
    ) -> list[BatchResult]:
        batch_dir = self._get_batch_directory(output_directory)
        output_file_path = batch_dir / f"{batch_id}_results.jsonl"
        return self._read_jsonl_file(output_file_path)

    def _get_result_file_name(self, batch_id: str) -> str:
        return f"{batch_id}_results.jsonl"

    def _parse_json_content(self, content_str: str) -> Any:
        """Read a reply with the online client's ``read_json_reply``; text it refuses stays
        text."""
        parsed = read_json_reply(content_str)
        return content_str if parsed is None else parsed

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        raise NotImplementedError("Ollama uses custom file-based retrieve_results()")

    def _transform_ollama_response(
        self, ollama_response: dict | object, custom_id: str, model: str
    ) -> dict:
        """Transform Ollama response to OpenAI batch output format."""
        if isinstance(ollama_response, dict):
            _msg = ollama_response.get("message", {})
            role = _msg.get("role") if isinstance(_msg, dict) else getattr(_msg, "role", None)
            content = (
                _msg.get("content") if isinstance(_msg, dict) else getattr(_msg, "content", None)
            )
        else:
            _msg = getattr(ollama_response, "message", None)
            role = getattr(_msg, "role", None) if _msg else None
            content = getattr(_msg, "content", None) if _msg else None

        if not role or content is None:
            raise VendorAPIError(
                f"Ollama response missing or malformed 'message' field for {custom_id!r}",
                context={"vendor": self.vendor_slug, "custom_id": custom_id},
            )

        return {
            "custom_id": custom_id,
            "response": {
                "status_code": 200,
                "request_id": f"req-{uuid.uuid4().hex[:12]}",
                "body": {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": role, "content": content},
                            "finish_reason": _finish_reason(ollama_response),
                        }
                    ],
                    "usage": {
                        "prompt_tokens": (
                            ollama_response.get("prompt_eval_count", 0)
                            if isinstance(ollama_response, dict)
                            else getattr(ollama_response, "prompt_eval_count", None) or 0
                        ),
                        "completion_tokens": (
                            ollama_response.get("eval_count", 0)
                            if isinstance(ollama_response, dict)
                            else getattr(ollama_response, "eval_count", None) or 0
                        ),
                        "total_tokens": (
                            ollama_response.get("prompt_eval_count", 0)
                            if isinstance(ollama_response, dict)
                            else getattr(ollama_response, "prompt_eval_count", None) or 0
                        )
                        + (
                            ollama_response.get("eval_count", 0)
                            if isinstance(ollama_response, dict)
                            else getattr(ollama_response, "eval_count", None) or 0
                        ),
                    },
                    "system_fingerprint": None,
                },
            },
            "error": None,
        }
