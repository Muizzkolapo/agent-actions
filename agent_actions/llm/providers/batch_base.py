"""Base batch client interface for batch processing systems."""

from __future__ import annotations

import functools
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.config.path_config import resolve_project_root
from agent_actions.output.response.config_fields import get_default

if TYPE_CHECKING:
    from agent_actions.processing.types import RecoveryMetadata

logger = logging.getLogger(__name__)


def retry(
    max_attempts: int = 3,
    delay: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
):
    """Simple retry decorator for batch operations."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if max_attempts < 1:
                return func(*args, **kwargs)
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        time.sleep(delay * (attempt + 1))
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator


@dataclass
class BatchTask:
    """Provider-agnostic representation of a batch task."""

    custom_id: str
    prompt: str
    user_content: str
    model_config: dict[str, Any]
    metadata: dict[str, Any] | None = None


@dataclass
class BatchResult:
    """Provider-agnostic representation of a batch result."""

    custom_id: str
    content: Any
    success: bool
    error: str | None = None
    metadata: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    recovery_metadata: RecoveryMetadata | None = None  # From agent_actions.core.types


class BaseBatchClient(ABC):
    """Abstract base class for batch processing clients."""

    _configured_model: str | None = None

    def prepare_tasks(
        self, data: list[dict[str, Any]], agent_config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Convert agent-actions data format to provider-specific task format (Template Method)."""
        self._configured_model = agent_config.get("model_name", self._get_default_model())

        tasks = []
        json_mode = agent_config.get("json_mode", get_default("json_mode"))
        schema = agent_config.get("compiled_schema") if json_mode else None

        for row in data:
            batch_task = BatchTask(
                custom_id=row.get("target_id", row.get("id", "")),
                prompt=row.get("prompt", agent_config.get("prompt", "")),
                user_content=json.dumps(row.get("content", row)),
                model_config={
                    "model_name": agent_config.get("model_name", self._get_default_model()),
                    "temperature": agent_config.get("temperature", self._get_default_temperature()),
                    "max_tokens": agent_config.get("max_tokens"),
                },
                metadata=row,
            )
            provider_task = self.format_task_for_provider(batch_task, schema)
            tasks.append(provider_task)

        return tasks

    @abstractmethod
    def _get_default_model(self) -> str:
        """Return provider's default model name."""

    def _get_default_temperature(self) -> float:
        """Return provider's default temperature (0.1)."""
        return 0.1

    @abstractmethod
    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Transform standardized BatchTask to provider-specific format."""

    def submit_batch(
        self, tasks: list[dict[str, Any]], batch_name: str, output_directory: str | None = None
    ) -> tuple[str, str]:
        """Submit a batch job to the provider (Template Method).

        Returns:
            Tuple of (batch_id, initial_status)
        """
        batch_dir = self._get_batch_directory(output_directory)
        input_file = self._prepare_batch_input_file(tasks, batch_dir, batch_name)
        logger.info("Submitting batch with %s tasks to %s...", len(tasks), self.__class__.__name__)
        return self._submit_to_provider_api(input_file, batch_name)

    def check_status(self, batch_id: str) -> str:
        """Check the status of a batch job (Template Method)."""
        try:
            raw_status = self._fetch_status(batch_id)
            return self._normalize_status(raw_status)
        except Exception as e:
            logger.error("Error checking batch %s: %s", batch_id, e)
            raise

    @abstractmethod
    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status from provider API."""

    @abstractmethod
    def _normalize_status(self, raw_status: str) -> str:
        """Normalize provider-specific status to standard format."""

    def retrieve_results(
        self, batch_id: str, output_directory: str | None = None
    ) -> list[BatchResult]:
        """Retrieve and parse results from a completed batch job (Template Method)."""
        # Fetch raw results with retry
        logger.info("Retrieving results for batch %s...", batch_id)

        @retry(max_attempts=3, delay=2.0)
        def _fetch_safe():
            return self._fetch_raw_results(batch_id)

        raw_results = _fetch_safe()

        # Optionally write to file
        if output_directory:
            result_file_path = self._write_results_to_file(batch_id, raw_results, output_directory)
            return self._read_jsonl_file(result_file_path)

        batch_results = []
        lines = raw_results.decode("utf-8").strip().split("\n")
        for line_num, line in enumerate(lines, 1):
            if line.strip():
                try:
                    raw_result = json.loads(line)
                    batch_result = self.parse_provider_response(raw_result)
                    batch_results.append(batch_result)
                except json.JSONDecodeError as e:
                    logger.error("JSON parsing error on line %s: %s", line_num, e)
                    batch_results.append(
                        BatchResult(
                            custom_id=f"error_line_{line_num}",
                            content=None,
                            success=False,
                            error=f"JSON parsing error: {e}",
                            metadata={"line_number": line_num, "raw_line": line[:500]},
                        )
                    )
        return batch_results

    def parse_provider_response(self, raw_response: Any) -> BatchResult:
        """Transform provider-specific response to standardized BatchResult (Template Method)."""
        # Extract custom_id
        custom_id = self._extract_custom_id(raw_response)

        error = self._extract_error_from_response(raw_response)
        if error:
            return BatchResult(custom_id=custom_id, content=None, success=False, error=error)

        # Extract successful response data
        content = self._extract_content_from_response(raw_response)

        # Parse JSON content if it's a string
        if isinstance(content, str):
            content = self._parse_json_content(content)

        metadata = self._extract_metadata_from_response(raw_response)
        usage = self._extract_usage_from_response(raw_response)

        return BatchResult(
            custom_id=custom_id,
            content=content,
            success=True,
            error=None,
            metadata=metadata,
            usage=usage,
        )

    def _extract_custom_id(self, raw_response: Any) -> str:
        """Extract custom_id from response, defaulting to 'unknown'."""
        return self._get_attribute_or_key(raw_response, "custom_id", "unknown")  # type: ignore[no-any-return]

    @abstractmethod
    def _extract_error_from_response(self, raw_response: Any) -> str | None:
        """Extract error message from response, or None if no error."""

    @abstractmethod
    def _extract_content_from_response(self, raw_response: Any) -> Any:
        """Extract main content from successful response."""

    @abstractmethod
    def _extract_metadata_from_response(self, raw_response: Any) -> dict[str, Any]:
        """Extract metadata from response (model name, finish_reason, etc.)."""

    @abstractmethod
    def _extract_usage_from_response(self, raw_response: Any) -> dict[str, Any] | None:
        """Extract token usage information from response."""

    def get_supported_models(self) -> list[str]:
        """Get list of model names supported by this provider."""
        return []

    def validate_config(self, agent_config: dict[str, Any]) -> tuple[bool, str | None]:
        """Validate agent configuration compatibility with this provider (Template Method)."""
        if not agent_config:
            return (False, "agent_config is required")

        return self._validate_provider_specific_config(agent_config)

    def _validate_provider_specific_config(
        self, _agent_config: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Perform provider-specific configuration validation. Override for custom checks."""
        return (True, None)

    def _get_batch_directory(
        self, output_directory: str | None = None, project_root: Path | None = None
    ) -> Path:
        """Get or create the batch directory."""
        from agent_actions.utils.path_utils import ensure_directory_exists

        if output_directory:
            batch_dir = Path(output_directory) / "batch"
        else:
            batch_dir = resolve_project_root(project_root) / "batch"
        ensure_directory_exists(batch_dir)
        return batch_dir

    def _write_jsonl_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str, provider_name: str
    ) -> Path:
        """Write tasks to JSONL file."""
        file_name = f"{Path(batch_name).stem}_{provider_name}_batch_input.jsonl"
        file_path = batch_dir / file_name
        with open(file_path, "w", encoding="utf-8") as file:
            for task in tasks:
                file.write(json.dumps(task) + "\n")
        logger.info("%s batch input file: %s", provider_name.title(), file_path)
        return file_path

    def _read_jsonl_file(self, file_path: Path) -> list[BatchResult]:
        """Read JSONL file and parse to BatchResults."""
        if not file_path.exists():
            from agent_actions.errors import (
                VendorAPIError,
            )

            raise VendorAPIError(
                vendor=self.__class__.__name__,
                endpoint="retrieve_results",
                context={"message": "Batch output file not found", "expected_path": str(file_path)},
            )
        batch_results = []
        with open(file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    try:
                        raw_result = json.loads(line)
                        batch_result = self.parse_provider_response(raw_result)
                        batch_results.append(batch_result)
                    except json.JSONDecodeError as e:
                        logger.error("JSON parsing error on line %s: %s", line_num, e)
                        batch_results.append(
                            BatchResult(
                                custom_id=f"error_line_{line_num}",
                                content=None,
                                success=False,
                                error=f"JSON parsing error: {e}",
                                metadata={"line_number": line_num, "raw_line": line[:100]},
                            )
                        )
        return batch_results

    def _add_optional_param(
        self, target: dict[str, Any], key: str, value: Any, default: Any = None
    ) -> None:
        """Add parameter to target dict only if value is not None."""
        if value is not None:
            target[key] = value
        elif default is not None:
            target[key] = default

    def _parse_json_content(self, content_str: str) -> Any:
        """
        Parse JSON string, return as-is if parsing fails.

        This helper eliminates duplicated JSON parsing logic across providers.

        Args:
            content_str: String to parse as JSON

        Returns:
            Parsed JSON object, or original string if parsing fails
        """
        if not isinstance(content_str, str):
            return content_str  # type: ignore[unreachable]

        try:
            return json.loads(content_str)
        except json.JSONDecodeError:
            return content_str

    def _get_attribute_or_key(self, obj: Any, key: str, default: Any = None) -> Any:
        """
        Get value from object attribute or dict key.

        This helper eliminates repeated hasattr/isinstance checks,
        particularly in Anthropic provider's parse_provider_response().

        Args:
            obj: Object to extract value from (can be object or dict)
            key: Attribute name or dict key
            default: Default value if key not found

        Returns:
            Value from obj.key or obj[key], or default if not found
        """
        if hasattr(obj, key):
            return getattr(obj, key)
        if isinstance(obj, dict):
            return obj.get(key, default)
        return default

    def _write_results_to_file(
        self, batch_id: str, raw_results: bytes, output_directory: str | None = None
    ) -> Path:
        """
        Write raw results to JSONL file.

        This helper eliminates duplicated file writing logic across providers.

        Args:
            batch_id: Batch job ID (used for filename)
            raw_results: Raw results as bytes
            output_directory: Optional directory for results

        Returns:
            Path to written file
        """
        batch_dir = self._get_batch_directory(output_directory)
        result_file_name = self._get_result_file_name(batch_id)
        result_file_path = batch_dir / result_file_name

        with open(result_file_path, "wb") as f:
            f.write(raw_results)

        logger.info("Saved raw results to: %s", result_file_path)
        return result_file_path

    @abstractmethod
    def _get_result_file_name(self, batch_id: str) -> str:
        """
        Get the result file name for a batch.

        Subclasses MUST implement this to specify their result file naming convention.

        Args:
            batch_id: Batch job ID

        Returns:
            File name for results (e.g., "batch_123_results.jsonl")
        """

    @abstractmethod
    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """
        Fetch raw results from provider API.

        Subclasses MUST implement this to call their provider's results API.

        Args:
            batch_id: Provider-specific batch job ID

        Returns:
            Raw results as bytes
        """

    @abstractmethod
    def _prepare_batch_input_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """
        Prepare batch input file.

        Subclasses MUST implement this to write tasks to a file in their provider's format.

        Args:
            tasks: List of provider-specific task dictionaries
            batch_dir: Directory to write file to
            batch_name: Base name for the batch

        Returns:
            Path to created input file
        """

    @abstractmethod
    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> tuple[str, str]:
        """
        Submit batch to provider API.

        Subclasses MUST implement this to call their provider's batch submission API.

        Args:
            input_file: Path to prepared input file
            batch_name: Name for the batch job

        Returns:
            Tuple of (batch_id, initial_status)
        """
