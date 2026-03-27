"""Wave 10 regression tests: G-3, I-1, I-2, K-1, K-2, K-3."""

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# G-3: PROMPT_PATTERN supports dots in prompt names
# ---------------------------------------------------------------------------
class TestPromptPatternDotInName:
    def test_pattern_matches_simple_name(self):
        from agent_actions.prompt.handler import PROMPT_PATTERN

        assert PROMPT_PATTERN.search("{prompt my_prompt}") is not None

    def test_pattern_matches_dot_in_name(self):
        """G-3: {prompt file.block} must be matched by PROMPT_PATTERN."""
        from agent_actions.prompt.handler import PROMPT_PATTERN

        m = PROMPT_PATTERN.search("{prompt my.block}")
        assert m is not None
        assert m.group(1) == "my.block"

    def test_validate_prompt_blocks_catches_unclosed_dot_name(self, tmp_path):
        """G-3: validate_prompt_blocks must find and validate dot-in-name blocks."""
        from agent_actions.prompt.handler import PromptLoader

        content = "{prompt my.block}\nsome content\n"
        # No end_prompt → should raise ValueError (unclosed block)
        with pytest.raises(ValueError, match="my.block"):
            PromptLoader.validate_prompt_blocks("test.md", content)

    def test_get_all_prompt_names_includes_dot_name(self):
        """G-3: get_all_prompt_names must return dot-in-name blocks."""
        from agent_actions.prompt.handler import PromptLoader

        content = "{prompt intro.main}\ntext\n{end_prompt}\n{prompt simple}\ntext\n{end_prompt}"
        names = PromptLoader.get_all_prompt_names(content)
        assert "intro.main" in names
        assert "simple" in names


# ---------------------------------------------------------------------------
# I-1: LSP indexer skips unreadable files instead of crashing
# ---------------------------------------------------------------------------
class TestLspIndexerReadError:
    def test_unreadable_md_file_is_skipped(self, tmp_path):
        """I-1: OSError during read_text must log warning and continue, not crash."""
        import agent_actions.tooling.lsp.indexer as indexer_module
        from agent_actions.tooling.lsp.models import ProjectIndex

        prompt_dir = tmp_path / "prompt_store"
        prompt_dir.mkdir()
        (prompt_dir / "bad.md").touch()

        index = ProjectIndex(root=tmp_path)

        with patch("agent_actions.tooling.lsp.indexer.Path.read_text", side_effect=OSError("perm")):
            # Must not raise; bad file is skipped with a warning
            indexer_module._index_prompts(index, tmp_path)

        assert index.prompts == {}

    def test_unicode_error_skips_file(self, tmp_path):
        """I-1: UnicodeDecodeError must also be caught and skipped."""
        import agent_actions.tooling.lsp.indexer as indexer_module
        from agent_actions.tooling.lsp.models import ProjectIndex

        prompt_dir = tmp_path / "prompt_store"
        prompt_dir.mkdir()
        (prompt_dir / "bad.md").touch()

        index = ProjectIndex(root=tmp_path)

        with patch(
            "agent_actions.tooling.lsp.indexer.Path.read_text",
            side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, ""),
        ):
            indexer_module._index_prompts(index, tmp_path)

        assert index.prompts == {}


# ---------------------------------------------------------------------------
# I-2: COALESCE guards NULL record_count in scan_sqlite_readonly
# ---------------------------------------------------------------------------
class TestScanSqliteCoalesce:
    def test_null_record_count_defaults_to_zero(self, tmp_path):
        """I-2: SUM(record_count) with NULL rows must return 0, not None."""
        import sqlite3

        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE target_data "
            "(action_name TEXT, relative_path TEXT, data TEXT, record_count INTEGER)"
        )
        # Insert row with NULL record_count
        conn.execute(
            "INSERT INTO target_data VALUES (?, ?, ?, ?)",
            ("my_action", "file.json", '{"x":1}', None),
        )
        conn.execute(
            "CREATE TABLE source_data "
            "(id INTEGER PRIMARY KEY, relative_path TEXT, source_guid TEXT, data TEXT)"
        )
        conn.commit()
        conn.close()

        from agent_actions.tooling.docs.scanner.data_scanners import scan_sqlite_readonly

        result = scan_sqlite_readonly(db, "test_workflow")
        assert result is not None
        # Per-node count must be 0 (not None) — this is where COALESCE applies
        assert result["nodes"]["my_action"]["record_count"] == 0
        # Total target_count also guarded (separate SUM query)
        assert result["target_count"] == 0


# ---------------------------------------------------------------------------
# K-1: primary_dependency must reference an existing action name
# ---------------------------------------------------------------------------
class TestPrimaryDependencyValidation:
    def _make_workflow(self, actions):
        from agent_actions.config.schema import WorkflowConfig

        return WorkflowConfig(
            name="test",
            description="test",
            version="1",
            actions=actions,
        )

    def _action(self, name, **kwargs):
        from agent_actions.config.schema import ActionConfig

        return ActionConfig(name=name, intent="test intent", **kwargs)

    def test_valid_primary_dependency_passes(self):
        """K-1: primary_dependency pointing to an existing action must pass."""
        self._make_workflow(
            [
                self._action("a"),
                self._action("b", dependencies=["a"], primary_dependency="a"),
            ]
        )

    def test_invalid_primary_dependency_raises(self):
        """K-1: primary_dependency pointing to non-existent action must raise at config load."""
        with pytest.raises(Exception, match="primary_dependency"):
            self._make_workflow(
                [
                    self._action("a"),
                    self._action("b", primary_dependency="nonexistent"),
                ]
            )


# ---------------------------------------------------------------------------
# K-2: WRITE_TO / REPROCESS on_false must raise ConfigValidationError early
# ---------------------------------------------------------------------------
class TestUnsupportedGuardBehavior:
    def _make_evaluator(self):
        from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator

        return GuardEvaluator()

    def test_write_to_behavior_raises_config_error(self):
        """K-2: 'write_to' behavior must raise ConfigValidationError."""
        from agent_actions.errors.configuration import ConfigValidationError

        ev = self._make_evaluator()
        guard_config = {"clause": "True", "scope": "item", "behavior": "write_to"}
        with pytest.raises(ConfigValidationError):
            ev._evaluate_guard({}, guard_config)

    def test_reprocess_behavior_raises_config_error(self):
        """K-2: 'reprocess' behavior must raise ConfigValidationError."""
        from agent_actions.errors.configuration import ConfigValidationError

        ev = self._make_evaluator()
        guard_config = {"clause": "True", "scope": "item", "behavior": "reprocess"}
        with pytest.raises(ConfigValidationError):
            ev._evaluate_guard({}, guard_config)

    def test_valid_behaviors_do_not_raise(self):
        """skip and filter behaviors must still work normally."""
        ev = self._make_evaluator()
        for behavior in ("skip", "filter"):
            guard_config = {"clause": "item == item", "scope": "item", "behavior": behavior}
            result = ev._evaluate_guard({"item": "x"}, guard_config)
            assert result is not None


# ---------------------------------------------------------------------------
# K-3: parse() returns None on failure; resolve() treats it as success=False
# ---------------------------------------------------------------------------
class TestParseReturnsNone:
    def test_parse_returns_none_for_invalid_reference(self):
        """K-3: parse() must return None (not a fallback ParsedReference) on failure."""
        from agent_actions.input.preprocessing.field_resolution.reference_parser import (
            ReferenceParser,
        )

        parser = ReferenceParser()
        result = parser.parse("nodot", strict=False)
        assert result is None

    def test_parse_returns_none_for_empty_string(self):
        from agent_actions.input.preprocessing.field_resolution.reference_parser import (
            ReferenceParser,
        )

        parser = ReferenceParser()
        assert parser.parse("", strict=False) is None

    def test_resolve_handles_unparseable_reference(self):
        """K-3: resolve() must return success=False when parse() returns None."""
        from agent_actions.input.preprocessing.field_resolution.resolver import (
            FieldReferenceResolver,
        )

        resolver = FieldReferenceResolver(strict_mode=False)
        result = resolver.resolve("nodot", field_context={"dep": {"x": 1}})
        assert result.success is False
        assert "nodot" in result.error
