"""Tests for seed field reference validation in preflight checks.

Covers:
- Namespace mismatches (error): seed.X where X is not in seed
- Nested field mismatches (warning): seed.rubric.typo where typo doesn't exist
- Deeply nested field walks
- Array boundary handling
- JSON parse failures
- Did-you-mean suggestions
- Multiple actions sharing seed keys
- Wildcard path handling
- Existing file-level checks are unchanged
"""

import json

from agent_actions.validation.preflight.resolution_service import (
    WorkflowResolutionService,
    _nested_key_exists,
)


def _make_project(tmp_path, seed_files=None):
    """Create project directory structure with seed files.

    Returns the workflow_config_path string.
    """
    project = tmp_path / "project"
    agent_config = project / "agent_config"
    agent_config.mkdir(parents=True)
    seed_data = project / "seed_data"
    seed_data.mkdir()

    for name, content in (seed_files or {}).items():
        (seed_data / name).write_text(
            json.dumps(content) if isinstance(content, (dict, list)) else content
        )

    return str(agent_config / "workflow.yml")


# ---------------------------------------------------------------------------
# _nested_key_exists helper
# ---------------------------------------------------------------------------


class TestNestedKeyExists:
    def test_top_level_key(self):
        assert _nested_key_exists({"a": 1}, "a") is True

    def test_top_level_missing(self):
        assert _nested_key_exists({"a": 1}, "b") is False

    def test_nested_key(self):
        assert _nested_key_exists({"a": {"b": {"c": 1}}}, "a.b.c") is True

    def test_nested_missing(self):
        assert _nested_key_exists({"a": {"b": 1}}, "a.c") is False

    def test_array_boundary_stops(self):
        assert _nested_key_exists({"items": [1, 2, 3]}, "items.0.name") is True

    def test_non_dict_returns_false(self):
        assert _nested_key_exists({"a": 42}, "a.b") is False

    def test_empty_dict(self):
        assert _nested_key_exists({}, "a") is False


# ---------------------------------------------------------------------------
# Namespace mismatch — ERROR (blocks execution)
# ---------------------------------------------------------------------------


class TestSeedNamespaceValidation:
    """Referencing seed.X when X is not in seed produces a blocking error."""

    def test_undeclared_namespace_from_observe(self, tmp_path):
        """observe: [seed.missing.field] with no seed entry for 'missing'."""
        wf_path = _make_project(tmp_path, {"rubric.json": {"scoring": 1}})

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": ["seed.missing.field"],
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        ns_errors = [e for e in result.errors if "seed.missing" in e.message]
        assert len(ns_errors) == 1
        assert "not declared in context_scope.seed" in ns_errors[0].message
        assert "rubric" in ns_errors[0].hint  # suggests declared key

    def test_undeclared_namespace_no_seed_at_all(self, tmp_path):
        """Action references seed.X but has no seed config."""
        wf_path = _make_project(tmp_path)

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "observe": ["seed.rubric.field"],
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        ns_errors = [e for e in result.errors if "seed.rubric" in e.message]
        assert len(ns_errors) == 1
        assert "not declared" in ns_errors[0].message

    def test_declared_namespace_passes(self, tmp_path):
        """Referencing a declared seed key produces no namespace errors."""
        wf_path = _make_project(tmp_path, {"rubric.json": {"scoring": 1}})

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": ["seed.rubric"],
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        ns_errors = [e for e in result.errors if "not declared" in e.message]
        assert len(ns_errors) == 0


# ---------------------------------------------------------------------------
# Nested field mismatch — WARNING (non-blocking)
# ---------------------------------------------------------------------------


class TestSeedFieldValidation:
    """Referencing seed.rubric.typo where typo doesn't exist produces a warning."""

    def test_missing_nested_field_warning(self, tmp_path):
        """Typo in nested field reference produces a warning, not error."""
        wf_path = _make_project(
            tmp_path,
            {"rubric.json": {"scoring_criteria": {"weight": 0.5}, "tone": "formal"}},
        )

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": ["seed.rubric.scoring_critera"],  # typo
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        # No blocking errors from this
        ns_errors = [e for e in result.errors if "seed" in e.message.lower()]
        assert len(ns_errors) == 0

        # Warning with did-you-mean
        assert len(result.warnings) == 1
        w = result.warnings[0]
        assert "scoring_critera" in w.message
        assert "Does not exist" in w.message or "does not exist" in w.message
        assert "scoring_criteria" in w.hint  # did-you-mean suggestion

    def test_valid_nested_field_no_warning(self, tmp_path):
        """Valid nested field reference produces no warnings."""
        wf_path = _make_project(
            tmp_path,
            {"rubric.json": {"scoring_criteria": {"weight": 0.5}}},
        )

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": ["seed.rubric.scoring_criteria"],
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        assert len(result.warnings) == 0

    def test_deeply_nested_field_walk(self, tmp_path):
        """Validates path walk through multiple nesting levels."""
        wf_path = _make_project(
            tmp_path,
            {"rubric.json": {"scoring": {"helpfulness": {"weight": 0.35, "description": "help"}}}},
        )

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": [
                            "seed.rubric.scoring.helpfulness.weight",  # valid
                            "seed.rubric.scoring.helpfulness.typo",  # invalid
                        ],
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        assert len(result.warnings) == 1
        assert "scoring.helpfulness.typo" in result.warnings[0].message

    def test_array_boundary_accepted(self, tmp_path):
        """Array boundary stops validation — accepts the reference."""
        wf_path = _make_project(
            tmp_path,
            {"rubric.json": {"items": [{"name": "a"}, {"name": "b"}]}},
        )

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": ["seed.rubric.items"],
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        assert len(result.warnings) == 0

    def test_did_you_mean_suggestion(self, tmp_path):
        """Close misspelling triggers did-you-mean hint."""
        wf_path = _make_project(
            tmp_path,
            {"rules.json": {"marketplace_rules": 1, "brand_voice": 2}},
        )

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "seed": {"rules": "$file:rules.json"},
                        "observe": ["seed.rules.marketplace_ruls"],  # close typo
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        assert len(result.warnings) == 1
        assert "marketplace_rules" in result.warnings[0].hint

    def test_no_suggestion_for_distant_name(self, tmp_path):
        """Completely different name gets no did-you-mean, just available fields."""
        wf_path = _make_project(
            tmp_path,
            {"rubric.json": {"scoring_criteria": 1, "tone": 2}},
        )

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": ["seed.rubric.zzz_completely_wrong"],
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        assert len(result.warnings) == 1
        assert "Available fields:" in result.warnings[0].hint

    def test_wildcard_path_skipped(self, tmp_path):
        """Wildcard paths (passthrough: seed.rubric.*) are not validated."""
        wf_path = _make_project(tmp_path, {"rubric.json": {"a": 1}})

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "passthrough": ["seed.rubric.*"],
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        assert len(result.warnings) == 0


# ---------------------------------------------------------------------------
# JSON parse failures — ERROR
# ---------------------------------------------------------------------------


class TestSeedJsonParseFailure:
    def test_malformed_json_error(self, tmp_path):
        """Malformed JSON in seed file produces a blocking error."""
        wf_path = _make_project(tmp_path, {"bad.json": "not valid json {"})

        svc = WorkflowResolutionService(
            action_configs={
                "loader": {
                    "context_scope": {
                        "seed": {"data": "$file:bad.json"},
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        parse_errors = [e for e in result.errors if "failed to parse" in e.message]
        assert len(parse_errors) == 1
        assert "valid JSON" in parse_errors[0].hint


# ---------------------------------------------------------------------------
# Multiple actions
# ---------------------------------------------------------------------------


class TestMultipleActions:
    def test_two_actions_same_seed_key(self, tmp_path):
        """Two actions referencing same seed key — both validated independently."""
        wf_path = _make_project(
            tmp_path,
            {"rubric.json": {"scoring_criteria": 1, "tone": 2}},
        )

        svc = WorkflowResolutionService(
            action_configs={
                "action_a": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": ["seed.rubric.scoring_criteria"],  # valid
                    },
                },
                "action_b": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": ["seed.rubric.typo_field"],  # invalid
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        # Only action_b should have a warning
        assert len(result.warnings) == 1
        assert "action_b" in result.warnings[0].message

    def test_action_without_seed_referencing_seed(self, tmp_path):
        """Action A has seed, action B doesn't but references seed."""
        wf_path = _make_project(tmp_path, {"rubric.json": {"a": 1}})

        svc = WorkflowResolutionService(
            action_configs={
                "action_a": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": ["seed.rubric"],
                    },
                },
                "action_b": {
                    "context_scope": {
                        "observe": ["seed.rubric.field"],  # no seed!
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        # action_b should have a namespace error
        ns_errors = [
            e for e in result.errors if "action_b" in e.message and "not declared" in e.message
        ]
        assert len(ns_errors) == 1


# ---------------------------------------------------------------------------
# Inline prompt extraction
# ---------------------------------------------------------------------------


class TestInlinePromptExtraction:
    """Seed references in inline prompts are validated."""

    def test_inline_prompt_seed_ref_validated(self, tmp_path):
        """Seed reference in inline Jinja2 prompt is caught."""
        wf_path = _make_project(
            tmp_path,
            {"rubric.json": {"scoring_criteria": 1}},
        )

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "name": "processor",
                    "prompt": "Score using {{ seed.rubric.scoring_critera }}",
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        assert len(result.warnings) == 1
        assert "scoring_critera" in result.warnings[0].message

    def test_inline_prompt_undeclared_namespace(self, tmp_path):
        """Seed reference to undeclared namespace from inline prompt is an error."""
        wf_path = _make_project(tmp_path, {"rubric.json": {"a": 1}})

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "name": "processor",
                    "prompt": "Use {{ seed.missing_data.field }}",
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        ns_errors = [e for e in result.errors if "seed.missing_data" in e.message]
        assert len(ns_errors) == 1


# ---------------------------------------------------------------------------
# Existing file-level checks unchanged
# ---------------------------------------------------------------------------


class TestExistingChecksUnchanged:
    """Verify that file existence and path security checks still work."""

    def test_missing_file_still_detected(self, tmp_path):
        """Missing seed file is still caught (existing behavior)."""
        wf_path = _make_project(tmp_path)

        svc = WorkflowResolutionService(
            action_configs={
                "loader": {
                    "context_scope": {
                        "seed": {"field1": "$file:missing.json"},
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "Seed file not found" in e.message]
        assert len(seed_errors) == 1

    def test_path_traversal_still_caught(self, tmp_path):
        """Path traversal is still caught (existing behavior)."""
        wf_path = _make_project(tmp_path)

        svc = WorkflowResolutionService(
            action_configs={
                "loader": {
                    "context_scope": {
                        "seed": {"field1": "$file:../../etc/passwd"},
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "escapes base directory" in e.message]
        assert len(seed_errors) == 1

    def test_no_seed_no_errors(self):
        """No seed in config produces no errors (existing behavior)."""
        svc = WorkflowResolutionService(
            action_configs={"loader": {"context_scope": {}}},
        )
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "seed" in e.message.lower()]
        assert len(seed_errors) == 0

    def test_seed_data_dir_missing_with_seed_refs_errors(self, tmp_path):
        """No seed directory anywhere with declared seed refs is a blocking error."""
        project = tmp_path / "project"
        agent_config = project / "agent_config"
        agent_config.mkdir(parents=True)
        # No seed_data dir

        svc = WorkflowResolutionService(
            action_configs={
                "loader": {
                    "context_scope": {
                        "seed": {"field1": "$file:data.json"},
                    },
                },
            },
            workflow_config_path=str(agent_config / "workflow.yml"),
        )
        result = svc.resolve_all()

        dir_errors = [e for e in result.errors if "Seed data directory not found" in e.message]
        assert len(dir_errors) == 1


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_same_ref_from_multiple_directives_deduplicated(self, tmp_path):
        """Same seed ref in observe and passthrough produces one finding, not two."""
        wf_path = _make_project(
            tmp_path,
            {"rubric.json": {"scoring_criteria": 1}},
        )

        svc = WorkflowResolutionService(
            action_configs={
                "processor": {
                    "context_scope": {
                        "seed": {"rubric": "$file:rubric.json"},
                        "observe": ["seed.rubric.typo_field"],
                        "passthrough": ["seed.rubric.typo_field"],
                    },
                },
            },
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        assert len(result.warnings) == 1
