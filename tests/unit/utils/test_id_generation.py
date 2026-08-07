"""Tests for IDGenerator: uuid4 uniqueness and content_hash determinism."""

from agent_actions.utils.id_generation import IDGenerator


class TestGenerateSourceGuid:
    """generate_source_guid() returns unique uuid4 values."""

    def test_returns_unique_values(self):
        guids = {IDGenerator.generate_source_guid() for _ in range(100)}
        assert len(guids) == 100

    def test_returns_valid_uuid_string(self):
        import uuid

        guid = IDGenerator.generate_source_guid()
        parsed = uuid.UUID(guid)
        assert parsed.version == 4


class TestGenerateContentHash:
    """generate_content_hash() is deterministic for same content."""

    def test_deterministic_for_same_dict(self):
        content = {"amount": 100, "date": "2024-01-01"}
        hash_a = IDGenerator.generate_content_hash(content)
        hash_b = IDGenerator.generate_content_hash(content)
        assert hash_a == hash_b

    def test_deterministic_for_same_string(self):
        content = "hello world"
        hash_a = IDGenerator.generate_content_hash(content)
        hash_b = IDGenerator.generate_content_hash(content)
        assert hash_a == hash_b

    def test_different_content_different_hash(self):
        hash_a = IDGenerator.generate_content_hash({"a": 1})
        hash_b = IDGenerator.generate_content_hash({"a": 2})
        assert hash_a != hash_b

    def test_returns_valid_uuid5(self):
        import uuid

        h = IDGenerator.generate_content_hash("test")
        parsed = uuid.UUID(h)
        assert parsed.version == 5
