"""Base classes for artifact system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import json
import uuid
import re
import logging


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
        except Exception:
            return "1.2.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "agent_actions_version": self.agent_actions_version,
            "invocation_id": self.invocation_id,
            "schema_version": self.schema_version,
        }


class SecurityError(Exception):
    """Security-related artifact errors."""
    pass


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
        if not re.match(r'^[\w\-_./]+$', str(resolved_path)):
            raise SecurityError("Path contains invalid characters")
        
        return resolved_path
    
    def _validate_content_size(self, content: str) -> None:
        """Validate content size for security."""
        if len(content.encode('utf-8')) > self.MAX_FILE_SIZE:
            raise SecurityError(f"Content too large (max {self.MAX_FILE_SIZE} bytes)")

    def save(self, path: Path) -> None:
        """Persist artifact to a JSON file."""
        try:
            self._logger.debug(f"Saving {self.__class__.__name__} to {path}")
            
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
            
            self._logger.info(f"Successfully saved {self.__class__.__name__} to {validated_path}")
            
        except SecurityError:
            self._logger.error(f"Security validation failed for path: {path}")
            raise
        except Exception as e:
            self._logger.error(f"Failed to save {self.__class__.__name__} to {path}: {e}")
            raise

    @classmethod
    def load(cls, path: Path) -> "BaseArtifact":
        """Load artifact from JSON file with security validation."""
        logger = logging.getLogger(f"{__name__}.{cls.__name__}")
        
        try:
            logger.debug(f"Loading {cls.__name__} from {path}")
            
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
                raise SecurityError(f"Invalid JSON format: {e}")
            except Exception as e:
                raise SecurityError(f"Failed to load artifact: {e}")
            
            # Validate JSON structure
            if not isinstance(data, dict):
                raise SecurityError("Artifact must be a JSON object")
            
            if "metadata" not in data:
                raise SecurityError("Artifact missing required metadata")
            
            artifact = cls.from_dict(data)
            logger.info(f"Successfully loaded {cls.__name__} from {resolved_path}")
            return artifact
            
        except SecurityError:
            logger.error(f"Security validation failed when loading from: {path}")
            raise
        except Exception as e:
            logger.error(f"Failed to load {cls.__name__} from {path}: {e}")
            raise

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseArtifact":
        """Create artifact from dictionary."""
