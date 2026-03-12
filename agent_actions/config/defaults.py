"""Centralized default values for hardcoded constants."""


class StorageDefaults:
    """Defaults for storage backends."""

    SQLITE_LOCK_TIMEOUT_SECONDS: float = 30.0


class LockDefaults:
    """Defaults for portalocker file-lock timeouts."""

    SIMPLE_LOCK_TIMEOUT_SECONDS: float = 5.0
    ATOMIC_LOCK_TIMEOUT_SECONDS: float = 10.0


class OllamaDefaults:
    """Defaults for Ollama local LLM provider."""

    BASE_URL: str = "http://localhost:11434"


class ApiDefaults:
    """Defaults for HTTP/API data-source fetching."""

    MAX_RESPONSE_BYTES: int = 10 * 1024 * 1024  # 10 MB
    REQUEST_TIMEOUT_SECONDS: int = 30


class SeedDataDefaults:
    """Defaults for static/seed data file loading."""

    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB


class PromptDefaults:
    """Defaults for prompt validation."""

    MAX_PROMPT_SIZE_BYTES: int = 100 * 1024  # 100 KB


class DocsDefaults:
    """Defaults for documentation scanning."""

    README_MAX_BYTES: int = 100 * 1024  # 100 KB
