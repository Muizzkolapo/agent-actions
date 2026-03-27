"""Tests documenting the exception hierarchy after orphan migration (Task 42)."""

from agent_actions.errors.base import AgentActionsError
from agent_actions.errors.configuration import ConfigurationError
from agent_actions.errors.filesystem import FileSystemError
from agent_actions.errors.processing import ProcessingError
from agent_actions.errors.validation import ValidationError


class TestPathManagerExceptionHierarchy:
    def test_path_manager_error_is_filesystem_error(self):
        from agent_actions.config.paths import PathManagerError

        assert issubclass(PathManagerError, FileSystemError)
        assert issubclass(PathManagerError, AgentActionsError)

    def test_project_root_not_found_is_path_manager_error(self):
        from agent_actions.config.paths import ProjectRootNotFoundError

        assert issubclass(ProjectRootNotFoundError, FileSystemError)
        assert issubclass(ProjectRootNotFoundError, AgentActionsError)

    def test_path_manager_validation_error_is_path_manager_error(self):
        from agent_actions.config.paths import PathManagerValidationError

        assert issubclass(PathManagerValidationError, FileSystemError)
        assert issubclass(PathManagerValidationError, AgentActionsError)


class TestChunkingExceptionHierarchy:
    def test_field_chunking_error_is_processing_error(self):
        from agent_actions.input.preprocessing.chunking.errors import FieldChunkingError

        assert issubclass(FieldChunkingError, ProcessingError)
        assert issubclass(FieldChunkingError, AgentActionsError)

    def test_field_chunking_validation_error_is_validation_error(self):
        from agent_actions.input.preprocessing.chunking.errors import (
            FieldChunkingValidationError,
        )

        assert issubclass(FieldChunkingValidationError, ValidationError)
        assert issubclass(FieldChunkingValidationError, AgentActionsError)


class TestFieldResolutionExceptionHierarchy:
    def test_field_resolution_error_is_processing_error(self):
        from agent_actions.input.preprocessing.field_resolution.exceptions import (
            FieldResolutionError,
        )

        assert issubclass(FieldResolutionError, ProcessingError)
        assert issubclass(FieldResolutionError, AgentActionsError)

    def test_all_subclasses_are_processing_errors(self):
        from agent_actions.input.preprocessing.field_resolution.exceptions import (
            DependencyValidationError,
            InvalidReferenceError,
            ReferenceNotFoundError,
            SchemaFieldValidationError,
        )

        for cls in (
            InvalidReferenceError,
            ReferenceNotFoundError,
            DependencyValidationError,
            SchemaFieldValidationError,
        ):
            assert issubclass(cls, ProcessingError), f"{cls.__name__} not a ProcessingError"
            assert issubclass(cls, AgentActionsError), f"{cls.__name__} not an AgentActionsError"


class TestDuplicateActionErrorHierarchy:
    def test_duplicate_action_error_is_configuration_error(self):
        from agent_actions.workflow.managers.manifest import DuplicateActionError

        assert issubclass(DuplicateActionError, ConfigurationError)
        assert issubclass(DuplicateActionError, AgentActionsError)
        assert not issubclass(DuplicateActionError, ValueError)


class TestNegativeAssertions:
    """Guard against accidental reversion to old base classes."""

    def test_chunking_errors_not_bare_exception(self):
        from agent_actions.input.preprocessing.chunking.errors import (
            FieldChunkingError,
            FieldChunkingValidationError,
        )

        assert not issubclass(FieldChunkingValidationError, ValueError)
        # FieldChunkingError was Exception; now ProcessingError (still an Exception,
        # but must be AgentActionsError)
        assert issubclass(FieldChunkingError, AgentActionsError)

    def test_field_resolution_not_bare_exception(self):
        from agent_actions.input.preprocessing.field_resolution.exceptions import (
            FieldResolutionError,
        )

        # Must not be a direct Exception subclass (should go through ProcessingError)
        assert FieldResolutionError.__bases__[0] is ProcessingError


class TestConstructorCompatibility:
    """Verify migrated exceptions accept single-string construction."""

    def test_path_manager_error_single_string(self):
        from agent_actions.config.paths import PathManagerError

        e = PathManagerError("test message")
        assert str(e) == "test message"
        assert e.context == {}

    def test_field_chunking_error_single_string(self):
        from agent_actions.input.preprocessing.chunking.errors import FieldChunkingError

        e = FieldChunkingError("test message")
        assert str(e) == "test message"

    def test_field_resolution_error_single_string(self):
        from agent_actions.input.preprocessing.field_resolution.exceptions import (
            FieldResolutionError,
        )

        e = FieldResolutionError("test message")
        assert str(e) == "test message"
