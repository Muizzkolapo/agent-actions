"""Tests for BatchCommandArgs validation model."""

import pytest
from pydantic import ValidationError

from agent_actions.validation.batch_validator import BatchCommandArgs


class TestBatchCommandArgs:
    """Test the BatchCommandArgs Pydantic model."""

    def test_default_batch_id_is_none(self):
        """Creating without arguments should have batch_id=None."""
        args = BatchCommandArgs()
        assert args.batch_id is None

    def test_valid_batch_id(self):
        """A string batch_id should be accepted."""
        args = BatchCommandArgs(batch_id="batch_abc123")
        assert args.batch_id == "batch_abc123"

    def test_batch_id_none_explicit(self):
        """Explicitly passing None should be accepted."""
        args = BatchCommandArgs(batch_id=None)
        assert args.batch_id is None

    def test_invalid_batch_id_type_rejected(self):
        """Non-string, non-None values should be rejected by Pydantic."""
        with pytest.raises(ValidationError):
            BatchCommandArgs(batch_id=12345)
