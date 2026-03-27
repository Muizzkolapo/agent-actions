"""Tests for ConfigValidator to improve coverage."""

from unittest.mock import patch

import pytest

from agent_actions.validation.config_validator import ConfigValidator


@pytest.fixture
def validator():
    """Create a ConfigValidator with events disabled."""
    return ConfigValidator(fire_events=False)


# ---------------------------------------------------------------------------
# validate() dispatch and top-level routing
# ---------------------------------------------------------------------------


class TestValidateDispatch:
    """Test the top-level validate() routing logic."""

    def test_non_dict_data_returns_false(self, validator):
        """Non-dict data should fail validation."""
        result = validator.validate("not a dict")
        assert result is False
        assert any("dictionary" in e.lower() for e in validator.get_errors())

    def test_missing_operation_adds_error(self, validator):
        """Missing operation key should produce an error."""
        result = validator.validate({"agent_name": "foo"})
        assert result is False
        assert any("operation" in e.lower() for e in validator.get_errors())

    def test_unknown_operation_adds_error(self, validator):
        """Unknown operation string should produce an error."""
        result = validator.validate({"operation": "does_not_exist"})
        assert result is False
        assert any("unknown operation" in e.lower() for e in validator.get_errors())

    def test_validate_agent_entries_missing_fields(self, validator):
        """validate_agent_entries without required fields should error."""
        result = validator.validate(
            {"operation": "validate_agent_entries", "agent_config_data": []}
        )
        assert result is False
        assert any("agent_name_context" in e for e in validator.get_errors())

    def test_validate_agent_config_file_meta_missing_fields(self, validator):
        """validate_agent_config_file_meta without config_path/project_dir should error."""
        result = validator.validate(
            {"operation": "validate_agent_config_file_meta", "agent_name": "test"}
        )
        assert result is False

    def test_validate_agent_entries_dispatches_correctly(self, validator):
        """Valid validate_agent_entries call with empty list should warn but pass."""
        result = validator.validate(
            {
                "operation": "validate_agent_entries",
                "agent_config_data": [],
                "agent_name_context": "test_agent",
            }
        )
        # Empty list produces a warning, not an error
        assert result is True
        assert len(validator.get_warnings()) > 0


# ---------------------------------------------------------------------------
# _parse_properties_dict
# ---------------------------------------------------------------------------


class TestParsePropertiesDict:
    """Test JSON/Python literal parsing of properties part."""

    def test_valid_json(self, validator):
        result = validator._parse_properties_dict('{"name": "string"}')
        assert result == {"name": "string"}

    def test_valid_python_literal(self, validator):
        result = validator._parse_properties_dict("{'name': 'string'}")
        assert result == {"name": "string"}

    def test_invalid_string(self, validator):
        result = validator._parse_properties_dict("not valid at all")
        assert result is None

    def test_empty_string(self, validator):
        result = validator._parse_properties_dict("")
        assert result is None


# ---------------------------------------------------------------------------
# _validate_property_type
# ---------------------------------------------------------------------------


class TestValidatePropertyType:
    """Test single property type validation."""

    @pytest.mark.parametrize(
        "type_str",
        ["string", "number", "integer", "boolean", "object"],
    )
    def test_valid_basic_types(self, validator, type_str):
        assert validator._validate_property_type(type_str) is True

    @pytest.mark.parametrize(
        "type_str",
        ["string!", "number!", "integer!", "boolean!", "object!"],
    )
    def test_valid_required_types(self, validator, type_str):
        assert validator._validate_property_type(type_str) is True

    def test_invalid_type(self, validator):
        assert validator._validate_property_type("array") is False

    def test_empty_string(self, validator):
        assert validator._validate_property_type("") is False


# ---------------------------------------------------------------------------
# _is_valid_array_object_type
# ---------------------------------------------------------------------------


class TestIsValidArrayObjectType:
    """Test array[object:...] notation validation."""

    def test_valid_json_notation(self, validator):
        result = validator._is_valid_array_object_type(
            'array[object:{"name": "string", "age": "number"}]'
        )
        assert result is True

    def test_valid_python_notation(self, validator):
        result = validator._is_valid_array_object_type("array[object:{'name': 'string'}]")
        assert result is True

    def test_invalid_prefix(self, validator):
        assert validator._is_valid_array_object_type("object:{}") is False

    def test_invalid_properties(self, validator):
        assert validator._is_valid_array_object_type("array[object:invalid]") is False

    def test_invalid_property_type(self, validator):
        result = validator._is_valid_array_object_type('array[object:{"name": "unknown_type"}]')
        assert result is False


# ---------------------------------------------------------------------------
# _is_valid_schema_type
# ---------------------------------------------------------------------------


class TestIsValidSchemaType:
    """Test composite schema type checking."""

    def test_basic_valid_type(self, validator):
        valid = {"string", "number"}
        assert validator._is_valid_schema_type("string", valid, set()) is True

    def test_array_valid_type(self, validator):
        valid_array = {"array[string]"}
        assert validator._is_valid_schema_type("array[string]", set(), valid_array) is True

    def test_array_object_fallthrough(self, validator):
        result = validator._is_valid_schema_type('array[object:{"x": "string"}]', set(), set())
        assert result is True

    def test_invalid_type(self, validator):
        assert validator._is_valid_schema_type("invalid", set(), set()) is False


# ---------------------------------------------------------------------------
# _validate_agent_entries_list_logic
# ---------------------------------------------------------------------------


class TestValidateAgentEntriesListLogic:
    """Test agent entry list validation."""

    def test_non_list_adds_error(self, validator):
        validator._validate_agent_entries_list_logic("not_a_list", "agent1")
        assert validator.has_errors()
        assert any("must be a list" in e for e in validator.get_errors())

    def test_empty_list_adds_warning(self, validator):
        validator.clear_errors()
        validator.clear_warnings()
        validator._validate_agent_entries_list_logic([], "agent1")
        assert not validator.has_errors()
        assert len(validator.get_warnings()) > 0

    def test_valid_entries_delegates_to_orchestrator(self, validator):
        """List of entries should be passed to the orchestrator."""
        with patch.object(validator, "_validate_single_agent_entry_logic") as mock:
            validator._validate_agent_entries_list_logic(
                [{"model_vendor": "openai", "model_name": "gpt-4", "prompt": "test"}],
                "agent1",
            )
            mock.assert_called_once()


# ---------------------------------------------------------------------------
# _extract_dependencies_from_entry
# ---------------------------------------------------------------------------


class TestExtractDependenciesFromEntry:
    """Test dependency extraction from agent entries."""

    def test_no_dependencies_key(self, validator):
        deps = validator._extract_dependencies_from_entry({"prompt": "test"})
        assert deps == set()

    def test_valid_dependencies(self, validator):
        deps = validator._extract_dependencies_from_entry({"dependencies": ["AgentA", "AgentB"]})
        assert deps == {"agenta", "agentb"}

    def test_non_string_dependencies_ignored(self, validator):
        deps = validator._extract_dependencies_from_entry({"dependencies": [123, "AgentA"]})
        assert deps == {"agenta"}

    def test_non_list_dependencies(self, validator):
        deps = validator._extract_dependencies_from_entry({"dependencies": "AgentA"})
        assert deps == set()

    def test_non_dict_entry(self, validator):
        deps = validator._extract_dependencies_from_entry("not_a_dict")
        assert deps == set()


# ---------------------------------------------------------------------------
# _validate_config_dependencies_logic
# ---------------------------------------------------------------------------


class TestValidateConfigDependenciesLogic:
    """Test dependency resolution across agents."""

    def test_no_missing_deps(self, validator):
        config = {
            "agentA": [{"dependencies": ["agentB"]}],
            "agentB": [{"prompt": "hello"}],
        }
        validator._validate_config_dependencies_logic(config)
        assert not validator.has_errors()

    def test_missing_deps_adds_error(self, validator):
        config = {
            "agentA": [{"dependencies": ["nonexistent"]}],
        }
        validator._validate_config_dependencies_logic(config)
        assert validator.has_errors()
        assert any("missing dependencies" in e.lower() for e in validator.get_errors())


# ---------------------------------------------------------------------------
# _check_circular_dependencies_logic
# ---------------------------------------------------------------------------


class TestCheckCircularDependenciesLogic:
    """Test circular dependency detection."""

    def test_no_cycle(self, validator):
        config = {
            "a": [{"dependencies": ["b"]}],
            "b": [{"dependencies": []}],
        }
        validator._check_circular_dependencies_logic(config)
        assert not validator.has_errors()

    def test_simple_cycle(self, validator):
        config = {
            "a": [{"dependencies": ["b"]}],
            "b": [{"dependencies": ["a"]}],
        }
        validator._check_circular_dependencies_logic(config)
        assert validator.has_errors()
        assert any("circular" in e.lower() for e in validator.get_errors())

    def test_three_node_cycle(self, validator):
        config = {
            "a": [{"dependencies": ["b"]}],
            "b": [{"dependencies": ["c"]}],
            "c": [{"dependencies": ["a"]}],
        }
        validator._check_circular_dependencies_logic(config)
        assert validator.has_errors()

    def test_no_entries(self, validator):
        config = {}
        validator._check_circular_dependencies_logic(config)
        assert not validator.has_errors()


# ---------------------------------------------------------------------------
# _validate_operational_dependencies_logic
# ---------------------------------------------------------------------------


class TestValidateOperationalDependenciesLogic:
    """Test operational dependency validation."""

    def test_active_depends_on_active_ok(self, validator):
        cfgs = {
            "agent1": {"is_operational": True, "dependencies": ["agent2"]},
            "agent2": {"is_operational": True, "dependencies": []},
        }
        validator._validate_operational_dependencies_logic(cfgs)
        assert not validator.has_errors()

    def test_active_depends_on_inactive_error(self, validator):
        cfgs = {
            "agent1": {"is_operational": True, "dependencies": ["agent2"]},
            "agent2": {"is_operational": False, "dependencies": []},
        }
        validator._validate_operational_dependencies_logic(cfgs)
        assert validator.has_errors()
        assert any("inactive" in e.lower() for e in validator.get_errors())

    def test_active_depends_on_nonexistent_error(self, validator):
        cfgs = {
            "agent1": {"is_operational": True, "dependencies": ["ghost"]},
        }
        validator._validate_operational_dependencies_logic(cfgs)
        assert validator.has_errors()
        assert any("non-existent" in e.lower() for e in validator.get_errors())

    def test_inactive_agent_deps_not_checked(self, validator):
        cfgs = {
            "agent1": {"is_operational": False, "dependencies": ["ghost"]},
        }
        validator._validate_operational_dependencies_logic(cfgs)
        assert not validator.has_errors()

    def test_non_string_dependency_error(self, validator):
        cfgs = {
            "agent1": {"is_operational": True, "dependencies": [123]},
        }
        validator._validate_operational_dependencies_logic(cfgs)
        assert validator.has_errors()
        assert any("non-string" in e.lower() for e in validator.get_errors())

    def test_deps_not_a_list_error(self, validator):
        cfgs = {
            "agent1": {"is_operational": True, "dependencies": "agent2"},
        }
        validator._validate_operational_dependencies_logic(cfgs)
        assert validator.has_errors()
        assert any("not a list" in e.lower() for e in validator.get_errors())


# ---------------------------------------------------------------------------
# _validate_config_file_access
# ---------------------------------------------------------------------------


class TestValidateConfigFileAccess:
    """Test config file access validation."""

    def test_nonexistent_file(self, validator, tmp_path):
        result = validator._validate_config_file_access(tmp_path / "nope.yaml")
        assert result is False
        assert validator.has_errors()

    def test_path_is_directory(self, validator, tmp_path):
        result = validator._validate_config_file_access(tmp_path)
        assert result is False
        assert any("not a file" in e for e in validator.get_errors())

    def test_valid_file(self, validator, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("hello")
        result = validator._validate_config_file_access(f)
        assert result is True
        assert not validator.has_errors()


# ---------------------------------------------------------------------------
# _build_agent_sets
# ---------------------------------------------------------------------------


class TestBuildAgentSets:
    """Test agent set construction."""

    def test_all_active(self, validator):
        cfgs = {
            "Agent1": {"is_operational": True},
            "Agent2": {},
        }
        active, all_agents = validator._build_agent_sets(cfgs)
        assert active == {"agent1", "agent2"}
        assert all_agents == {"agent1", "agent2"}

    def test_some_inactive(self, validator):
        cfgs = {
            "Agent1": {"is_operational": True},
            "Agent2": {"is_operational": False},
        }
        active, all_agents = validator._build_agent_sets(cfgs)
        assert active == {"agent1"}
        assert all_agents == {"agent1", "agent2"}


# ---------------------------------------------------------------------------
# _find_name_conflicts
# ---------------------------------------------------------------------------


class TestFindNameConflicts:
    """Test name conflict detection."""

    def test_no_conflict(self, validator):
        locations = {"agent1": ["/path/a.yaml"]}
        conflicts = validator._find_name_conflicts("agent1", locations, "/path/a.yaml")
        assert conflicts == []

    def test_has_conflict(self, validator):
        locations = {"agent1": ["/path/a.yaml", "/path/b.yaml"]}
        conflicts = validator._find_name_conflicts("agent1", locations, "/path/a.yaml")
        assert conflicts == ["/path/b.yaml"]

    def test_case_insensitive(self, validator):
        locations = {"agent1": ["/path/a.yaml"]}
        conflicts = validator._find_name_conflicts("Agent1", locations)
        assert conflicts == ["/path/a.yaml"]
