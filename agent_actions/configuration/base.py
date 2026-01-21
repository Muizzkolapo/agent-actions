"""Base classes for artifact system."""

from __future__ import annotations

import json
import logging
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ArtifactMetadata:
    """Standard metadata for all artifacts."""

    def __init__(self) -> None:
        self.generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.agent_actions_version = self._get_version()
        self.invocation_id = str(uuid.uuid4())
        self.schema_version = "1.0.0"

    def _get_version(self) -> str:
        try:
            import agent_actions  # type: ignore

            return getattr(agent_actions, "__version__")
        except Exception as e:
            logger.warning(
                "Failed to retrieve agent_actions version, using fallback: %s",
                e,
                exc_info=True,
                extra={"operation": "version_retrieval"},
            )
            return "1.2.0"

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary format."""
        return {
            "generated_at": self.generated_at,
            "agent_actions_version": self.agent_actions_version,
            "invocation_id": self.invocation_id,
            "schema_version": self.schema_version,
        }


class SecurityError(Exception):
    """Security-related artifact errors."""


class BaseArtifact(ABC):
    """Base class for all artifacts."""

    # Security limits
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_FILENAME_LENGTH = 255
    ALLOWED_EXTENSIONS = {".json"}

    def __init__(self, metadata: Optional[ArtifactMetadata] = None) -> None:
        self.metadata = metadata or ArtifactMetadata()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert artifact to dictionary format."""

    def _validate_path(self, path: Path) -> Path:
        """Validate file path for security."""
        # Resolve the path to handle .. and . components
        resolved_path = path.resolve()

        # Check file extension
        if resolved_path.suffix not in self.ALLOWED_EXTENSIONS:
            raise SecurityError(f"File extension {resolved_path.suffix} not allowed")

        # Check filename length
        if len(resolved_path.name) > self.MAX_FILENAME_LENGTH:
            raise SecurityError(f"Filename too long (max {self.MAX_FILENAME_LENGTH} chars)")

        # Sanitize filename
        if not re.match(r"^[\w\-_./]+$", str(resolved_path)):
            raise SecurityError("Path contains invalid characters")

        return resolved_path

    def _validate_content_size(self, content: str) -> None:
        """Validate content size for security."""
        if len(content.encode("utf-8")) > self.MAX_FILE_SIZE:
            raise SecurityError(f"Content too large (max {self.MAX_FILE_SIZE} bytes)")

    def save(self, path: Path) -> None:
        """Persist artifact to a JSON file."""
        try:
            self._logger.debug("Saving %s to %s", self.__class__.__name__, path)

            # CRITICAL SECURITY FIX: Validate path for security
            validated_path = self._validate_path(path)

            # Serialize and validate content size
            content = json.dumps(self.to_dict(), indent=2, default=str)
            self._validate_content_size(content)

            validated_path.parent.mkdir(parents=True, exist_ok=True)

            # Use secure file permissions (readable/writable by owner only)
            with open(validated_path, "w", encoding="utf-8") as fh:
                fh.write(content)

            # Set secure file permissions (0o600 = rw-------)
            validated_path.chmod(0o600)

            self._logger.info(
                "Successfully saved %s to %s", self.__class__.__name__, validated_path
            )

        except SecurityError:
            self._logger.error("Security validation failed for path: %s", path)
            raise
        except Exception as e:
            self._logger.error("Failed to save %s to %s: %s", self.__class__.__name__, path, e)
            raise

    @classmethod
    def load(cls, path: Path) -> "BaseArtifact":
        """Load artifact from JSON file with security validation."""
        load_logger = logging.getLogger(f"{__name__}.{cls.__name__}")

        try:
            load_logger.debug("Loading %s from %s", cls.__name__, path)

            # Validate path
            resolved_path = path.resolve()

            # Check file exists
            if not resolved_path.exists():
                raise SecurityError(f"Artifact file not found: {resolved_path}")

            # Check file extension
            if resolved_path.suffix not in cls.ALLOWED_EXTENSIONS:
                raise SecurityError(f"File extension {resolved_path.suffix} not allowed")

            # Check file size before loading
            if resolved_path.stat().st_size > cls.MAX_FILE_SIZE:
                raise SecurityError(f"File too large (max {cls.MAX_FILE_SIZE} bytes)")

            try:
                with open(resolved_path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except json.JSONDecodeError as e:
                raise SecurityError(f"Invalid JSON format: {e}") from e
            except Exception as e:
                raise SecurityError(f"Failed to load artifact: {e}") from e

            # Validate JSON structure
            if not isinstance(data, dict):
                raise SecurityError("Artifact must be a JSON object")

            if "metadata" not in data:
                raise SecurityError("Artifact missing required metadata")

            artifact = cls.from_dict(data)
            load_logger.info("Successfully loaded %s from %s", cls.__name__, resolved_path)
            return artifact

        except SecurityError:
            load_logger.error("Security validation failed when loading from: %s", path)
            raise
        except Exception as e:
            load_logger.error("Failed to load %s from %s: %s", cls.__name__, path, e)
            raise

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseArtifact":
        """Create artifact from dictionary."""
