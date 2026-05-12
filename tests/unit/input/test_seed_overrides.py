"""Tests for per-subfolder seed override resolution (spec 414).

Covers: override detection, YAML validation, key validation, value type validation,
size limits, merge correctness, config mutation prevention, shared-reference safety,
file filtering, and directory inheritance rules.
"""

import textwrap
from pathlib import Path
from typing import Any

import pytest

from agent_actions.errors.configuration import ConfigValidationError
from agent_actions.output.response.expander_merge import deep_merge_context_scope
from agent_actions.utils.constants import SEED_OVERRIDE_FILENAMES
from agent_actions.workflow.runner_file_processing import (
    collect_files_from_upstream,
    is_framework_sidecar,
    should_skip_item,
)

# ---------------------------------------------------------------------------
# Lazy imports for initial_pipeline (avoids circular import at collection)
# ---------------------------------------------------------------------------


@pytest.fixture()
def pipeline():
    """Lazy-import initial_pipeline to avoid circular import at collection time."""
    from agent_actions.input.preprocessing.staging import initial_pipeline

    initial_pipeline._override_cache.clear()
    yield initial_pipeline
    initial_pipeline._override_cache.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(seed_path: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "name": "test_action",
        "context_scope": {
            "observe": ["field_a"],
            "seed_path": seed_path
            or {
                "exam_syllabus": "$file:default_syllabus.json",
                "design_rules": "$file:design_rules.json",
                "authoring_rules": "$file:authoring_rules.json",
            },
        },
    }


def _write(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ===================================================================
# _find_override_file
# ===================================================================


class TestFindOverrideFile:
    def test_finds_yml(self, tmp_path, pipeline):
        _write(tmp_path / "_seed_overrides.yml", "k: v")
        assert pipeline._find_override_file(tmp_path) is not None

    def test_finds_yaml(self, tmp_path, pipeline):
        _write(tmp_path / "_seed_overrides.yaml", "k: v")
        result = pipeline._find_override_file(tmp_path)
        assert result is not None
        assert result.name == "_seed_overrides.yaml"

    def test_returns_none_when_absent(self, tmp_path, pipeline):
        _write(tmp_path / "data.json", "{}")
        assert pipeline._find_override_file(tmp_path) is None

    def test_ignores_wrong_names(self, tmp_path, pipeline):
        _write(tmp_path / "seed_overrides.yml", "k: v")
        _write(tmp_path / "_seed_overrides.json", "k: v")
        assert pipeline._find_override_file(tmp_path) is None


# ===================================================================
# _load_and_validate_seed_overrides
# ===================================================================


class TestLoadAndParse:
    """Tests for _load_and_parse_seed_overrides (structure/type checks, no key validation)."""

    def test_valid_override(self, tmp_path, pipeline):
        p = _write(tmp_path / "_seed_overrides.yml", "exam_syllabus: $file:aws.json\n")
        result = pipeline._load_and_parse_seed_overrides(p)
        assert result == {"exam_syllabus": "$file:aws.json"}

    def test_multiple_keys(self, tmp_path, pipeline):
        p = _write(
            tmp_path / "_seed_overrides.yml",
            textwrap.dedent("""\
            exam_syllabus: $file:aws.json
            design_rules: $file:aws_rules.json
        """),
        )
        result = pipeline._load_and_parse_seed_overrides(p)
        assert len(result) == 2
        assert result["exam_syllabus"] == "$file:aws.json"
        assert result["design_rules"] == "$file:aws_rules.json"

    # -- Empty/null YAML ---------------------------------------------------

    def test_empty_file(self, tmp_path, pipeline):
        p = _write(tmp_path / "_seed_overrides.yml", "")
        assert pipeline._load_and_parse_seed_overrides(p) == {}

    def test_comment_only(self, tmp_path, pipeline):
        p = _write(tmp_path / "_seed_overrides.yml", "# nothing\n")
        assert pipeline._load_and_parse_seed_overrides(p) == {}

    def test_yaml_null(self, tmp_path, pipeline):
        p = _write(tmp_path / "_seed_overrides.yml", "---\n")
        assert pipeline._load_and_parse_seed_overrides(p) == {}

    # -- Type validation errors --------------------------------------------

    @pytest.mark.parametrize(
        "content,label",
        [
            ("exam_syllabus:\n  nested: value\n", "dict"),
            ("exam_syllabus:\n  - item\n", "list"),
            ("exam_syllabus:\n", "null"),
            ("exam_syllabus: 42\n", "int"),
            ("exam_syllabus: true\n", "bool"),
        ],
    )
    def test_non_string_values_rejected(self, tmp_path, pipeline, content, label):
        p = _write(tmp_path / "_seed_overrides.yml", content)
        with pytest.raises(ConfigValidationError, match="string file reference"):
            pipeline._load_and_parse_seed_overrides(p)

    @pytest.mark.parametrize(
        "content",
        [
            "- a\n- b\n",
            "just a string\n",
            "42\n",
        ],
    )
    def test_non_dict_content_rejected(self, tmp_path, pipeline, content):
        p = _write(tmp_path / "_seed_overrides.yml", content)
        with pytest.raises(ConfigValidationError, match="YAML mapping"):
            pipeline._load_and_parse_seed_overrides(p)

    def test_bad_yaml_rejected(self, tmp_path, pipeline):
        p = _write(tmp_path / "_seed_overrides.yml", "key: [broken {{\n")
        with pytest.raises(ConfigValidationError, match="Invalid YAML"):
            pipeline._load_and_parse_seed_overrides(p)

    def test_oversized_file_rejected(self, tmp_path, pipeline):
        p = _write(
            tmp_path / "_seed_overrides.yml",
            "exam_syllabus: " + "x" * (pipeline.MAX_OVERRIDE_FILE_SIZE + 100),
        )
        with pytest.raises(ConfigValidationError, match="size limit"):
            pipeline._load_and_parse_seed_overrides(p)

    def test_file_prefix_optional(self, tmp_path, pipeline):
        p = _write(tmp_path / "_seed_overrides.yml", "exam_syllabus: bare_file.json\n")
        result = pipeline._load_and_parse_seed_overrides(p)
        assert result["exam_syllabus"] == "bare_file.json"


# ===================================================================
# _validate_override_keys — key validation against action's seed_path
# ===================================================================


class TestValidateOverrideKeys:
    def test_unknown_key_rejected(self, pipeline):
        overrides = {"typo_key": "$file:x.json"}
        with pytest.raises(ConfigValidationError, match="Unknown seed override keys"):
            pipeline._validate_override_keys(overrides, _config(), "test.yml")

    def test_unknown_key_lists_valid_keys(self, pipeline):
        overrides = {"typo_key": "$file:x.json"}
        with pytest.raises(ConfigValidationError, match="exam_syllabus"):
            pipeline._validate_override_keys(overrides, _config(), "test.yml")

    def test_valid_keys_pass(self, pipeline):
        overrides = {"exam_syllabus": "$file:x.json"}
        pipeline._validate_override_keys(overrides, _config(), "test.yml")  # no raise

    def test_revalidates_per_action(self, pipeline):
        """Key valid for action_a but invalid for action_b is caught."""
        config_a = _config({"key_a": "$file:a.json"})
        config_b = _config({"key_b": "$file:b.json"})
        overrides = {"key_a": "$file:override.json"}

        # Valid for action_a
        pipeline._validate_override_keys(overrides, config_a, "test.yml")

        # Invalid for action_b
        with pytest.raises(ConfigValidationError, match="Unknown seed override keys"):
            pipeline._validate_override_keys(overrides, config_b, "test.yml")


# ===================================================================
# _apply_seed_overrides — merge correctness & config isolation
# ===================================================================


class TestApplySeedOverrides:
    def test_merge_correctness(self, pipeline):
        config = _config()
        effective = pipeline._apply_seed_overrides(config, {"exam_syllabus": "$file:aws.json"})
        sp = effective["context_scope"]["seed_path"]
        assert sp["exam_syllabus"] == "$file:aws.json"
        assert sp["design_rules"] == "$file:design_rules.json"
        assert sp["authoring_rules"] == "$file:authoring_rules.json"

    def test_original_config_unchanged(self, pipeline):
        config = _config()
        sp_before = dict(config["context_scope"]["seed_path"])
        cs_id = id(config["context_scope"])
        sp_id = id(config["context_scope"]["seed_path"])

        pipeline._apply_seed_overrides(config, {"exam_syllabus": "$file:aws.json"})

        assert id(config["context_scope"]) == cs_id
        assert id(config["context_scope"]["seed_path"]) == sp_id
        assert config["context_scope"]["seed_path"] == sp_before

    def test_effective_is_new_objects(self, pipeline):
        config = _config()
        effective = pipeline._apply_seed_overrides(config, {"exam_syllabus": "$file:aws.json"})

        assert id(effective) != id(config)
        assert id(effective["context_scope"]) != id(config["context_scope"])
        assert id(effective["context_scope"]["seed_path"]) != id(
            config["context_scope"]["seed_path"]
        )

    def test_cross_file_bleed_prevention(self, pipeline):
        """Two calls with the same shared_config produce independent results."""
        shared = _config()
        orig_syllabus = shared["context_scope"]["seed_path"]["exam_syllabus"]

        eff_a = pipeline._apply_seed_overrides(shared, {"exam_syllabus": "$file:a.json"})
        eff_b = shared  # no overrides

        assert eff_a["context_scope"]["seed_path"]["exam_syllabus"] == "$file:a.json"
        assert eff_b["context_scope"]["seed_path"]["exam_syllabus"] == orig_syllabus

    def test_defaults_only_seed_path_isolation(self, pipeline):
        """When seed_path comes from defaults (shared reference via deep_merge),
        overrides on action A must not corrupt action B or defaults."""
        defaults = {
            "observe": ["x"],
            "seed_path": {"exam_syllabus": "$file:default.json", "rules": "$file:rules.json"},
        }
        merged_a = deep_merge_context_scope(defaults, {"observe": ["y"]})
        merged_b = deep_merge_context_scope(defaults, {"drop": ["z"]})

        config_a = {"name": "a", "context_scope": merged_a}
        config_b = {"name": "b", "context_scope": merged_b}

        effective_a = pipeline._apply_seed_overrides(
            config_a, {"exam_syllabus": "$file:override.json"}
        )

        assert effective_a["context_scope"]["seed_path"]["exam_syllabus"] == "$file:override.json"
        assert config_a["context_scope"]["seed_path"]["exam_syllabus"] == "$file:default.json"
        assert config_b["context_scope"]["seed_path"]["exam_syllabus"] == "$file:default.json"
        assert defaults["seed_path"]["exam_syllabus"] == "$file:default.json"


# ===================================================================
# _get_effective_config — caching and integration
# ===================================================================


class TestGetEffectiveConfig:
    def test_applies_override_from_subfolder(self, tmp_path, pipeline):
        sub = tmp_path / "aws"
        sub.mkdir()
        _write(sub / "_seed_overrides.yml", "exam_syllabus: $file:aws.json\n")
        data_file = _write(sub / "docs.json", "{}")

        config = _config()
        effective = pipeline._get_effective_config(str(data_file), config)
        assert effective["context_scope"]["seed_path"]["exam_syllabus"] == "$file:aws.json"

    def test_no_override_returns_original(self, tmp_path, pipeline):
        data_file = _write(tmp_path / "docs.json", "{}")
        config = _config()
        effective = pipeline._get_effective_config(str(data_file), config)
        assert effective is config

    def test_caches_per_directory(self, tmp_path, pipeline):
        sub = tmp_path / "aws"
        sub.mkdir()
        _write(sub / "_seed_overrides.yml", "exam_syllabus: $file:aws.json\n")
        f1 = _write(sub / "a.json", "{}")
        f2 = _write(sub / "b.json", "{}")

        config = _config()
        eff1 = pipeline._get_effective_config(str(f1), config)
        eff2 = pipeline._get_effective_config(str(f2), config)

        assert eff1["context_scope"]["seed_path"]["exam_syllabus"] == "$file:aws.json"
        assert eff2["context_scope"]["seed_path"]["exam_syllabus"] == "$file:aws.json"
        assert str(sub) in pipeline._override_cache

    def test_different_subfolders_get_different_overrides(self, tmp_path, pipeline):
        aws = tmp_path / "aws"
        mcp = tmp_path / "mcp"
        aws.mkdir()
        mcp.mkdir()
        _write(aws / "_seed_overrides.yml", "exam_syllabus: $file:aws.json\n")
        _write(mcp / "_seed_overrides.yml", "exam_syllabus: $file:mcp.json\n")

        config = _config()
        eff_aws = pipeline._get_effective_config(str(aws / "d.json"), config)
        eff_mcp = pipeline._get_effective_config(str(mcp / "d.json"), config)

        assert eff_aws["context_scope"]["seed_path"]["exam_syllabus"] == "$file:aws.json"
        assert eff_mcp["context_scope"]["seed_path"]["exam_syllabus"] == "$file:mcp.json"

    def test_nested_dir_no_inheritance(self, tmp_path, pipeline):
        """staging/aws/region1/docs.json does NOT inherit staging/aws/_seed_overrides.yml."""
        aws = tmp_path / "aws"
        region = aws / "region1"
        region.mkdir(parents=True)
        _write(aws / "_seed_overrides.yml", "exam_syllabus: $file:aws.json\n")
        data_file = _write(region / "docs.json", "{}")

        config = _config()
        effective = pipeline._get_effective_config(str(data_file), config)
        assert effective is config


# ===================================================================
# is_framework_sidecar
# ===================================================================


class TestIsFrameworkSidecar:
    @pytest.mark.parametrize("name", ["_seed_overrides.yml", "_seed_overrides.yaml"])
    def test_recognized(self, name):
        assert is_framework_sidecar(Path(name)) is True

    @pytest.mark.parametrize(
        "name",
        [
            "data.json",
            "_seed_overrides.json",
            "seed_overrides.yml",
            "_MANIFEST.md",
            ".seed_overrides.yml",
        ],
    )
    def test_not_recognized(self, name):
        assert is_framework_sidecar(Path(name)) is False


# ===================================================================
# should_skip_item — seed override exclusion
# ===================================================================


class TestShouldSkipItemOverrides:
    def test_yml_excluded(self, tmp_path):
        f = _write(tmp_path / "_seed_overrides.yml", "k: v")
        assert should_skip_item(f, tmp_path, set()) is True

    def test_yaml_excluded(self, tmp_path):
        f = _write(tmp_path / "_seed_overrides.yaml", "k: v")
        assert should_skip_item(f, tmp_path, set()) is True

    def test_data_file_not_excluded(self, tmp_path):
        f = _write(tmp_path / "data.json", "{}")
        assert should_skip_item(f, tmp_path, set()) is False

    def test_excluded_with_no_file_type_filter(self, tmp_path):
        f = _write(tmp_path / "_seed_overrides.yml", "k: v")
        assert should_skip_item(f, tmp_path, set(), file_type_filter=None) is True

    def test_excluded_in_root(self, tmp_path):
        f = _write(tmp_path / "_seed_overrides.yml", "k: v")
        assert should_skip_item(f, tmp_path, set()) is True


# ===================================================================
# collect_files_from_upstream — seed override exclusion
# ===================================================================


class TestCollectFilesOverrides:
    def test_excludes_override_files(self, tmp_path):
        sub = tmp_path / "aws"
        sub.mkdir()
        _write(sub / "_seed_overrides.yml", "k: v")
        _write(sub / "_seed_overrides.yaml", "k: v")
        _write(sub / "output.json", "{}")

        result = collect_files_from_upstream([str(tmp_path)])
        names = [p.name for paths in result.values() for p in paths]

        assert "_seed_overrides.yml" not in names
        assert "_seed_overrides.yaml" not in names
        assert "output.json" in names


# ===================================================================
# SEED_OVERRIDE_FILENAMES constant
# ===================================================================


class TestConstants:
    def test_both_extensions(self):
        assert "_seed_overrides.yml" in SEED_OVERRIDE_FILENAMES
        assert "_seed_overrides.yaml" in SEED_OVERRIDE_FILENAMES

    def test_is_frozenset(self):
        assert isinstance(SEED_OVERRIDE_FILENAMES, frozenset)


# ===================================================================
# Integration: full staging walk
# ===================================================================


class TestFullStagingWalk:
    def test_walk_with_mixed_subfolders(self, tmp_path, pipeline):
        """Three subfolders: aws (override), mcp (override), root (no override)."""
        staging = tmp_path / "staging"
        _write(staging / "aws" / "_seed_overrides.yml", "exam_syllabus: $file:aws.json\n")
        _write(staging / "aws" / "aws_docs.json", '[{"t": "aws"}]')
        _write(staging / "mcp" / "_seed_overrides.yaml", "exam_syllabus: $file:mcp.json\n")
        _write(staging / "mcp" / "mcp_docs.json", '[{"t": "mcp"}]')
        _write(staging / "general.json", '[{"t": "gen"}]')

        shared_config = _config()
        original_syllabus = shared_config["context_scope"]["seed_path"]["exam_syllabus"]
        results: dict[str, str] = {}

        for item in sorted(staging.rglob("*")):
            if should_skip_item(item, staging, set()):
                continue
            effective = pipeline._get_effective_config(str(item), shared_config)
            results[item.name] = effective["context_scope"]["seed_path"]["exam_syllabus"]

        assert len(results) == 3
        assert results["aws_docs.json"] == "$file:aws.json"
        assert results["mcp_docs.json"] == "$file:mcp.json"
        assert results["general.json"] == original_syllabus
        assert shared_config["context_scope"]["seed_path"]["exam_syllabus"] == original_syllabus
