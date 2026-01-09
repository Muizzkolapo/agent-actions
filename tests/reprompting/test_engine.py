"""Tests for RepromptEngine core logic."""

import pytest
from agent_actions.reprompting.config import RepromptConfig
from agent_actions.reprompting.engine import RepromptEngine, RepromptResult


class TestRepromptEngineInit:
    """Tests for RepromptEngine initialization."""

    def test_init_with_basic_config(self):
        """Test initialization with basic config."""
        config = RepromptConfig.from_yaml(True)
        engine = RepromptEngine(config)
        assert engine.config == config
        assert engine.constraints == []

    def test_init_with_constraints(self):
        """Test initialization with constraints."""
        config = RepromptConfig.from_yaml(True)
        constraints = [{"not_contains": "maze"}]
        engine = RepromptEngine(config, constraints)
        assert engine.constraints == constraints

    def test_init_with_config_constraints(self):
        """Test initialization uses config constraints if no explicit ones."""
        config = RepromptConfig.from_yaml(
            {
                "preset": "basic",
                "constraints": [{"required_fields": ["name"]}],
            }
        )
        engine = RepromptEngine(config)
        assert engine.constraints == [{"required_fields": ["name"]}]


class TestRepromptEngineProcessResponse:
    """Tests for RepromptEngine.process_response()."""

    @pytest.fixture
    def basic_engine(self):
        """Create engine with basic config."""
        config = RepromptConfig.from_yaml(True)
        return RepromptEngine(config)

    @pytest.fixture
    def engine_with_constraints(self):
        """Create engine with constraints."""
        config = RepromptConfig.from_yaml(True)
        constraints = [{"not_contains": "maze"}]
        return RepromptEngine(config, constraints)

    def test_process_valid_response_succeeds(self, basic_engine):
        """Test processing valid response returns success."""
        result = basic_engine.process_response(
            {"name": "test"},
            {"original_prompt": "Generate JSON", "attempt": 0},
        )
        assert result.success is True
        assert result.needs_retry is False
        assert result.response == {"name": "test"}

    def test_process_valid_string_json(self, basic_engine):
        """Test processing valid JSON string repairs and succeeds."""
        result = basic_engine.process_response(
            '{"name": "test"}',
            {"original_prompt": "Generate JSON", "attempt": 0, "json_mode": True},
        )
        assert result.success is True
        assert result.response == {"name": "test"}
        assert result.repair_method == "direct_parse"

    def test_process_markdown_json_repairs(self, basic_engine):
        """Test processing markdown-wrapped JSON repairs it."""
        result = basic_engine.process_response(
            '```json\n{"name": "test"}\n```',
            {"original_prompt": "Generate JSON", "attempt": 0, "json_mode": True},
        )
        assert result.success is True
        assert result.response == {"name": "test"}
        assert result.repair_method == "strip_markdown"

    def test_process_error_dict_extracts_and_repairs(self, basic_engine):
        """Test processing error dict from provider extracts raw_response and repairs it."""
        # Simulate what Ollama client returns on JSON parse failure
        error_dict = {
            "raw_response": '```json\n{"name": "test", "value": 123}\n```',
            "_parse_error": "Expecting value: line 1 column 1 (char 0)",
        }
        result = basic_engine.process_response(
            error_dict,
            {"original_prompt": "Generate JSON", "attempt": 0, "json_mode": True},
        )
        assert result.success is True
        assert result.response == {"name": "test", "value": 123}
        assert result.repair_method in ["strip_markdown", "markdown_extraction"]

    def test_process_error_dict_with_trailing_comma(self, basic_engine):
        """Test processing error dict with trailing comma."""
        error_dict = {
            "raw_response": '{"name": "test", "items": [1, 2, 3,]}',
            "_parse_error": "Expecting ',' delimiter: line 1 column 35 (char 34)",
        }
        result = basic_engine.process_response(
            error_dict,
            {"original_prompt": "Generate JSON", "attempt": 0, "json_mode": True},
        )
        assert result.success is True
        assert result.response == {"name": "test", "items": [1, 2, 3]}
        assert result.repair_method == "fix_trailing_commas"

    def test_process_list_with_error_dict(self, basic_engine):
        """Test processing list containing error dict (real-world provider format)."""
        # Simulate what Ollama client actually returns
        error_list = [
            {
                "raw_response": '```json\n{"name": "test", "value": 123}\n```',
                "_parse_error": "Expecting value: line 1 column 1 (char 0)",
            }
        ]
        result = basic_engine.process_response(
            error_list,
            {"original_prompt": "Generate JSON", "attempt": 0, "json_mode": True},
        )
        assert result.success is True
        # Result should be a list with repaired data
        assert isinstance(result.response, list)
        assert len(result.response) == 1
        assert result.response[0] == {"name": "test", "value": 123}
        assert result.repair_method in ["strip_markdown", "markdown_extraction"]

    def test_process_list_with_error_dict_trailing_comma(self, basic_engine):
        """Test list error dict with trailing comma."""
        error_list = [
            {
                "raw_response": '{"name": "test", "items": [1, 2, 3,]}',
                "_parse_error": "Expecting ',' delimiter: line 1 column 35 (char 34)",
            }
        ]
        result = basic_engine.process_response(
            error_list,
            {"original_prompt": "Generate JSON", "attempt": 0, "json_mode": True},
        )
        assert result.success is True
        assert isinstance(result.response, list)
        assert len(result.response) == 1
        assert result.response[0] == {"name": "test", "items": [1, 2, 3]}
        assert result.repair_method == "fix_trailing_commas"

    def test_process_invalid_json_needs_retry(self, basic_engine):
        """Test processing invalid JSON returns needs_retry."""
        result = basic_engine.process_response(
            "not valid json {{{{",
            {"original_prompt": "Generate JSON", "attempt": 0, "json_mode": True},
        )
        assert result.success is False
        assert result.needs_retry is True
        assert result.improved_prompt is not None
        assert result.attempt == 1

    def test_process_constraint_violation_needs_retry(self, engine_with_constraints):
        """Test constraint violation returns needs_retry."""
        result = engine_with_constraints.process_response(
            {"description": "Navigate the maze"},
            {"original_prompt": "Generate description", "attempt": 0},
        )
        assert result.success is False
        assert result.needs_retry is True
        assert result.constraint_failed == "not_contains"
        assert "maze" in result.error

    def test_process_constraint_passes(self, engine_with_constraints):
        """Test constraint passes when condition met."""
        result = engine_with_constraints.process_response(
            {"description": "Navigate the path"},
            {"original_prompt": "Generate description", "attempt": 0},
        )
        assert result.success is True

    def test_process_max_attempts_reached(self, basic_engine):
        """Test max attempts reached returns success=False, needs_retry=False."""
        result = basic_engine.process_response(
            "invalid",
            {"original_prompt": "Generate", "attempt": 3},  # At max
        )
        assert result.success is False
        assert result.needs_retry is False
        assert result.metadata.get("max_attempts_reached") is True


class TestRepromptEngineGenerateImprovedPrompt:
    """Tests for RepromptEngine.generate_improved_prompt()."""

    @pytest.fixture
    def engine(self):
        config = RepromptConfig.from_yaml(True)
        return RepromptEngine(config)

    def test_generates_prompt_with_error_feedback(self, engine):
        """Test improved prompt includes error feedback."""
        improved = engine.generate_improved_prompt(
            original_prompt="Generate a quiz question",
            error="Missing required fields: ['question']",
            attempt=2,
            constraint_name="required_fields",
        )
        assert "Generate a quiz question" in improved
        assert "Missing" in improved
        assert "Attempt 2" in improved

    def test_uses_json_template_for_parse_errors(self, engine):
        """Test uses JSON-specific template for parse errors."""
        improved = engine.generate_improved_prompt(
            original_prompt="Generate JSON",
            error="JSONDecodeError: Unexpected token",
            attempt=1,
            constraint_name=None,
        )
        assert "valid JSON" in improved

    def test_uses_missing_fields_template(self, engine):
        """Test uses missing fields template."""
        improved = engine.generate_improved_prompt(
            original_prompt="Generate data",
            error="Missing fields: ['name']",
            attempt=1,
            constraint_name="required_fields",
        )
        assert "required fields" in improved.lower()


class TestRepromptResult:
    """Tests for RepromptResult dataclass."""

    def test_default_values(self):
        """Test default values for RepromptResult."""
        result = RepromptResult(success=True)
        assert result.success is True
        assert result.response is None
        assert result.needs_retry is False
        assert result.improved_prompt is None
        assert result.attempt == 0
        assert result.error is None
        assert result.repair_method is None
        assert result.constraint_failed is None
        assert result.metadata == {}

    def test_with_all_fields(self):
        """Test RepromptResult with all fields set."""
        result = RepromptResult(
            success=False,
            response={"data": "test"},
            needs_retry=True,
            improved_prompt="Try again",
            attempt=2,
            error="Constraint failed",
            repair_method="strip_markdown",
            constraint_failed="not_contains",
            metadata={"key": "value"},
        )
        assert result.success is False
        assert result.response == {"data": "test"}
        assert result.needs_retry is True
        assert result.improved_prompt == "Try again"
        assert result.attempt == 2
        assert result.error == "Constraint failed"
        assert result.repair_method == "strip_markdown"
        assert result.constraint_failed == "not_contains"
        assert result.metadata == {"key": "value"}


class TestRepromptEngineWithPresets:
    """Tests for RepromptEngine with different presets."""

    def test_basic_preset_no_critique(self):
        """Test basic preset never uses critique."""
        config = RepromptConfig.from_yaml("basic")
        engine = RepromptEngine(config)
        assert engine.should_use_critique(1) is False
        assert engine.should_use_critique(5) is False

    def test_smart_preset_uses_critique_after_2(self):
        """Test smart preset uses critique after attempt 2."""
        config = RepromptConfig.from_yaml("smart")
        engine = RepromptEngine(config)
        assert engine.should_use_critique(1) is False
        assert engine.should_use_critique(2) is True
        assert engine.should_use_critique(3) is True

    def test_thorough_preset_uses_reflection(self):
        """Test thorough preset uses self-reflection."""
        config = RepromptConfig.from_yaml("thorough")
        engine = RepromptEngine(config)
        assert engine.should_use_reflection(1) is True
        assert engine.should_use_reflection(3) is True


class TestMultipleConstraints:
    """Tests for handling multiple constraints."""

    def test_all_constraints_pass(self):
        """Test all constraints passing."""
        config = RepromptConfig.from_yaml(True)
        constraints = [
            {"required_fields": ["name", "description"]},
            {"non_empty": ["name"]},
            {"not_contains": "forbidden"},
        ]
        engine = RepromptEngine(config, constraints)

        result = engine.process_response(
            {"name": "test", "description": "A test item"},
            {"original_prompt": "Generate", "attempt": 0},
        )
        assert result.success is True

    def test_first_constraint_fails(self):
        """Test stops at first failing constraint."""
        config = RepromptConfig.from_yaml(True)
        constraints = [
            {"required_fields": ["name", "missing_field"]},
            {"non_empty": ["name"]},
        ]
        engine = RepromptEngine(config, constraints)

        result = engine.process_response(
            {"name": "test"},
            {"original_prompt": "Generate", "attempt": 0},
        )
        assert result.success is False
        assert result.constraint_failed == "required_fields"

    def test_second_constraint_fails(self):
        """Test continues to second constraint if first passes."""
        config = RepromptConfig.from_yaml(True)
        constraints = [
            {"required_fields": ["name"]},
            {"non_empty": ["name"]},
        ]
        engine = RepromptEngine(config, constraints)

        result = engine.process_response(
            {"name": ""},
            {"original_prompt": "Generate", "attempt": 0},
        )
        assert result.success is False
        assert result.constraint_failed == "non_empty"
