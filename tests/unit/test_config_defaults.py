"""Smoke tests for config/defaults.py — living inventory of all defaults."""

from agent_actions.config.defaults import (
    ApiDefaults,
    DocsDefaults,
    LockDefaults,
    OllamaDefaults,
    PromptDefaults,
    SeedDataDefaults,
    StorageDefaults,
)


class TestStorageDefaults:
    def test_sqlite_lock_timeout(self):
        assert StorageDefaults.SQLITE_LOCK_TIMEOUT_SECONDS == 30.0
        assert isinstance(StorageDefaults.SQLITE_LOCK_TIMEOUT_SECONDS, float)


class TestLockDefaults:
    def test_simple_lock_timeout(self):
        assert LockDefaults.SIMPLE_LOCK_TIMEOUT_SECONDS == 5.0
        assert isinstance(LockDefaults.SIMPLE_LOCK_TIMEOUT_SECONDS, float)

    def test_atomic_lock_timeout(self):
        assert LockDefaults.ATOMIC_LOCK_TIMEOUT_SECONDS == 10.0
        assert isinstance(LockDefaults.ATOMIC_LOCK_TIMEOUT_SECONDS, float)

    def test_atomic_greater_than_simple(self):
        assert LockDefaults.ATOMIC_LOCK_TIMEOUT_SECONDS > LockDefaults.SIMPLE_LOCK_TIMEOUT_SECONDS


class TestOllamaDefaults:
    def test_base_url(self):
        assert OllamaDefaults.BASE_URL == "http://localhost:11434"


class TestApiDefaults:
    def test_max_response_bytes(self):
        assert ApiDefaults.MAX_RESPONSE_BYTES == 10 * 1024 * 1024

    def test_request_timeout(self):
        assert ApiDefaults.REQUEST_TIMEOUT_SECONDS == 30


class TestSeedDataDefaults:
    def test_max_file_size(self):
        assert SeedDataDefaults.MAX_FILE_SIZE_BYTES == 10 * 1024 * 1024


class TestPromptDefaults:
    def test_max_prompt_size(self):
        assert PromptDefaults.MAX_PROMPT_SIZE_BYTES == 100 * 1024


class TestDocsDefaults:
    def test_readme_max_bytes(self):
        assert DocsDefaults.README_MAX_BYTES == 100 * 1024
