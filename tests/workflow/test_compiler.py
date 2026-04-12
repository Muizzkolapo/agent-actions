"""Tests for the WorkflowCompiler — cross-workflow DAG compilation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_actions.errors import ConfigurationError
from agent_actions.workflow.compiler import (
    SEPARATOR,
    compile_workflows,
    needs_compilation,
    qualify,
    unqualify,
)
from agent_actions.workflow.models import CompilationResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_workflow(
    workflows_root: Path,
    name: str,
    actions: list[dict],
    defaults: dict | None = None,
) -> Path:
    """Write a minimal workflow YAML under workflows_root/{name}/agent_config/{name}.yml."""
    wf_dir = workflows_root / name / "agent_config"
    wf_dir.mkdir(parents=True, exist_ok=True)
    config_path = wf_dir / f"{name}.yml"
    config: dict = {"name": name, "actions": actions}
    if defaults:
        config["defaults"] = defaults
    config_path.write_text(yaml.dump(config, default_flow_style=False))
    return config_path


# ---------------------------------------------------------------------------
# needs_compilation
# ---------------------------------------------------------------------------


class TestNeedsCompilation:
    def test_no_cross_deps_returns_false(self):
        config = {"actions": [{"name": "a", "dependencies": ["b"]}]}
        assert needs_compilation(config) is False

    def test_dict_deps_returns_true(self):
        config = {
            "actions": [{"name": "a", "dependencies": [{"workflow": "other", "action": "x"}]}]
        }
        assert needs_compilation(config) is True

    def test_upstream_flag_returns_true(self):
        config = {"actions": [{"name": "a"}]}
        assert needs_compilation(config, run_upstream=True) is True

    def test_downstream_flag_returns_true(self):
        config = {"actions": [{"name": "a"}]}
        assert needs_compilation(config, run_downstream=True) is True

    def test_empty_actions_returns_false(self):
        config = {"actions": []}
        assert needs_compilation(config) is False

    def test_no_actions_key_returns_false(self):
        config = {"name": "wf"}
        assert needs_compilation(config) is False

    def test_mixed_string_and_dict_deps(self):
        config = {
            "actions": [
                {
                    "name": "a",
                    "dependencies": ["local", {"workflow": "other", "action": "x"}],
                }
            ]
        }
        assert needs_compilation(config) is True

    def test_depends_on_alias(self):
        """Legacy depends_on key with dict deps should trigger compilation."""
        config = {"actions": [{"name": "a", "depends_on": [{"workflow": "other", "action": "x"}]}]}
        assert needs_compilation(config) is True


# ---------------------------------------------------------------------------
# qualify / unqualify
# ---------------------------------------------------------------------------


class TestQualifyUnqualify:
    def test_qualify(self):
        assert qualify("wf_a", "extract") == f"wf_a{SEPARATOR}extract"

    def test_unqualify(self):
        assert unqualify(f"wf_a{SEPARATOR}extract") == ("wf_a", "extract")

    def test_roundtrip(self):
        q = qualify("enrichment", "classify")
        assert unqualify(q) == ("enrichment", "classify")

    def test_unqualify_no_separator_raises(self):
        with pytest.raises(ValueError, match="Not a qualified"):
            unqualify("plain_name")

    def test_separator_only_in_first_split(self):
        """Action names with :: in them (shouldn't happen, but defensive)."""
        q = qualify("wf", f"action{SEPARATOR}sub")
        wf, action = unqualify(q)
        assert wf == "wf"
        assert action == f"action{SEPARATOR}sub"


# ---------------------------------------------------------------------------
# compile_workflows — basic scenarios
# ---------------------------------------------------------------------------


class TestCompileBasic:
    def test_single_workflow_no_cross_deps(self, tmp_path: Path):
        """Single workflow compiles to qualified names with no cross-workflow deps."""
        config_path = _write_workflow(
            tmp_path,
            "wf_a",
            actions=[
                {"name": "extract", "dependencies": []},
                {"name": "classify", "dependencies": ["extract"]},
            ],
        )

        result = compile_workflows(config_path, tmp_path)

        assert isinstance(result, CompilationResult)
        assert result.primary_workflow == "wf_a"
        assert result.involved_workflows == ["wf_a"]
        assert len(result.merged_actions) == 2

        # Actions are qualified.
        names = [a["name"] for a in result.merged_actions]
        assert "wf_a::extract" in names
        assert "wf_a::classify" in names

        # Intra-workflow deps are qualified.
        classify = next(a for a in result.merged_actions if a["name"] == "wf_a::classify")
        assert classify["dependencies"] == ["wf_a::extract"]

    def test_cross_workflow_deps_rewritten(self, tmp_path: Path):
        """Dict deps are rewritten to qualified string deps."""
        _write_workflow(
            tmp_path,
            "upstream",
            actions=[
                {"name": "produce", "dependencies": []},
            ],
        )
        config_path = _write_workflow(
            tmp_path,
            "downstream",
            actions=[
                {
                    "name": "consume",
                    "dependencies": [{"workflow": "upstream", "action": "produce"}],
                },
            ],
        )

        result = compile_workflows(config_path, tmp_path)

        assert set(result.involved_workflows) == {"upstream", "downstream"}
        consume = next(a for a in result.merged_actions if a["name"] == "downstream::consume")
        assert consume["dependencies"] == ["upstream::produce"]

    def test_mixed_local_and_cross_deps(self, tmp_path: Path):
        """Actions with both string and dict deps get both qualified."""
        _write_workflow(
            tmp_path,
            "upstream",
            actions=[{"name": "produce", "dependencies": []}],
        )
        config_path = _write_workflow(
            tmp_path,
            "downstream",
            actions=[
                {"name": "local_step", "dependencies": []},
                {
                    "name": "consume",
                    "dependencies": [
                        "local_step",
                        {"workflow": "upstream", "action": "produce"},
                    ],
                },
            ],
        )

        result = compile_workflows(config_path, tmp_path)
        consume = next(a for a in result.merged_actions if a["name"] == "downstream::consume")
        assert "downstream::local_step" in consume["dependencies"]
        assert "upstream::produce" in consume["dependencies"]

    def test_depends_on_alias_handled(self, tmp_path: Path):
        """Legacy depends_on key with dict deps gets rewritten and removed."""
        _write_workflow(
            tmp_path,
            "upstream",
            actions=[{"name": "produce", "dependencies": []}],
        )
        config_path = _write_workflow(
            tmp_path,
            "downstream",
            actions=[
                {
                    "name": "consume",
                    "depends_on": [{"workflow": "upstream", "action": "produce"}],
                },
            ],
        )

        result = compile_workflows(config_path, tmp_path)
        consume = next(a for a in result.merged_actions if a["name"] == "downstream::consume")
        assert consume["dependencies"] == ["upstream::produce"]
        assert "depends_on" not in consume


# ---------------------------------------------------------------------------
# compile_workflows — topological ordering
# ---------------------------------------------------------------------------


class TestCompileTopologicalOrder:
    def test_upstream_actions_before_downstream(self, tmp_path: Path):
        """Upstream workflow's actions appear before the primary's in involved_workflows."""
        _write_workflow(
            tmp_path,
            "upstream",
            actions=[{"name": "produce", "dependencies": []}],
        )
        config_path = _write_workflow(
            tmp_path,
            "downstream",
            actions=[
                {
                    "name": "consume",
                    "dependencies": [{"workflow": "upstream", "action": "produce"}],
                }
            ],
        )

        result = compile_workflows(config_path, tmp_path)
        # upstream should come before downstream in involved_workflows.
        assert result.involved_workflows.index("upstream") < result.involved_workflows.index(
            "downstream"
        )

    def test_transitive_upstream_ordering(self, tmp_path: Path):
        """A → B → C with --upstream: C's upstream chain is [A, B, C]."""
        _write_workflow(tmp_path, "wf_a", actions=[{"name": "step_a", "dependencies": []}])
        _write_workflow(
            tmp_path,
            "wf_b",
            actions=[
                {
                    "name": "step_b",
                    "dependencies": [{"workflow": "wf_a", "action": "step_a"}],
                }
            ],
        )
        config_path = _write_workflow(
            tmp_path,
            "wf_c",
            actions=[
                {
                    "name": "step_c",
                    "dependencies": [{"workflow": "wf_b", "action": "step_b"}],
                }
            ],
        )

        # Without --upstream: only direct dep (wf_b) + primary (wf_c).
        result = compile_workflows(config_path, tmp_path)
        assert result.involved_workflows == ["wf_b", "wf_c"]

        # With --upstream: full transitive chain.
        result_full = compile_workflows(config_path, tmp_path, run_upstream=True)
        assert result_full.involved_workflows == ["wf_a", "wf_b", "wf_c"]
        assert len(result_full.merged_actions) == 3


# ---------------------------------------------------------------------------
# compile_workflows — source metadata
# ---------------------------------------------------------------------------


class TestCompileSourceMetadata:
    def test_source_workflow_dir_injected(self, tmp_path: Path):
        config_path = _write_workflow(
            tmp_path,
            "wf_a",
            actions=[{"name": "extract", "dependencies": []}],
        )

        result = compile_workflows(config_path, tmp_path)
        action = result.merged_actions[0]
        assert action["_source_workflow_dir"] == str(tmp_path / "wf_a")
        assert action["_source_workflow_name"] == "wf_a"

    def test_action_metadata_populated(self, tmp_path: Path):
        config_path = _write_workflow(
            tmp_path,
            "wf_a",
            actions=[{"name": "extract", "dependencies": []}],
        )

        result = compile_workflows(config_path, tmp_path)
        meta = result.action_metadata["wf_a::extract"]
        assert meta.local_name == "extract"
        assert meta.source_workflow == "wf_a"
        assert meta.source_workflow_dir == tmp_path / "wf_a"

    def test_per_workflow_defaults_preserved(self, tmp_path: Path):
        """Each action's metadata carries its source workflow's data_source config."""
        _write_workflow(
            tmp_path,
            "upstream",
            actions=[{"name": "produce", "dependencies": []}],
            defaults={"data_source": "api"},
        )
        config_path = _write_workflow(
            tmp_path,
            "downstream",
            actions=[
                {
                    "name": "consume",
                    "dependencies": [{"workflow": "upstream", "action": "produce"}],
                }
            ],
            defaults={"data_source": "staging"},
        )

        result = compile_workflows(config_path, tmp_path)
        assert result.action_metadata["upstream::produce"].source_data_source == "api"
        assert result.action_metadata["downstream::consume"].source_data_source == "staging"

    def test_cross_workflow_actions_from_different_dirs(self, tmp_path: Path):
        """Actions from different workflows point to different directories."""
        _write_workflow(
            tmp_path,
            "upstream",
            actions=[{"name": "produce", "dependencies": []}],
        )
        config_path = _write_workflow(
            tmp_path,
            "downstream",
            actions=[
                {
                    "name": "consume",
                    "dependencies": [{"workflow": "upstream", "action": "produce"}],
                }
            ],
        )

        result = compile_workflows(config_path, tmp_path)
        up_action = next(a for a in result.merged_actions if "upstream" in a["name"])
        down_action = next(a for a in result.merged_actions if "downstream" in a["name"])
        assert up_action["_source_workflow_dir"] != down_action["_source_workflow_dir"]


# ---------------------------------------------------------------------------
# compile_workflows — cycle detection
# ---------------------------------------------------------------------------


class TestCompileCycleDetection:
    def test_direct_cycle_raises(self, tmp_path: Path):
        """A depends on B, B depends on A → cycle error."""
        _write_workflow(
            tmp_path,
            "wf_a",
            actions=[
                {
                    "name": "step_a",
                    "dependencies": [{"workflow": "wf_b", "action": "step_b"}],
                }
            ],
        )
        config_path = _write_workflow(
            tmp_path,
            "wf_b",
            actions=[
                {
                    "name": "step_b",
                    "dependencies": [{"workflow": "wf_a", "action": "step_a"}],
                }
            ],
        )

        with pytest.raises(Exception, match="[Cc]yclic"):
            compile_workflows(config_path, tmp_path)

    def test_self_cycle_raises(self, tmp_path: Path):
        """Workflow depends on itself → cycle error."""
        config_path = _write_workflow(
            tmp_path,
            "wf_a",
            actions=[
                {
                    "name": "step_a",
                    "dependencies": [{"workflow": "wf_a", "action": "step_a"}],
                }
            ],
        )

        with pytest.raises(Exception, match="[Cc]yclic"):
            compile_workflows(config_path, tmp_path)


# ---------------------------------------------------------------------------
# compile_workflows — --upstream / --downstream flags
# ---------------------------------------------------------------------------


class TestCompileFlags:
    def test_upstream_flag_includes_transitive_upstreams(self, tmp_path: Path):
        """--upstream pulls in all transitive upstream workflows."""
        _write_workflow(tmp_path, "wf_a", actions=[{"name": "step_a", "dependencies": []}])
        _write_workflow(
            tmp_path,
            "wf_b",
            actions=[
                {
                    "name": "step_b",
                    "dependencies": [{"workflow": "wf_a", "action": "step_a"}],
                }
            ],
        )
        # wf_c has no dict deps on its own — but --upstream should pull in wf_a and wf_b
        # if wf_c explicitly depends on wf_b.
        config_path = _write_workflow(
            tmp_path,
            "wf_c",
            actions=[
                {
                    "name": "step_c",
                    "dependencies": [{"workflow": "wf_b", "action": "step_b"}],
                }
            ],
        )

        result = compile_workflows(config_path, tmp_path, run_upstream=True)
        assert set(result.involved_workflows) == {"wf_a", "wf_b", "wf_c"}

    def test_downstream_flag_includes_dependents(self, tmp_path: Path):
        """--downstream pulls in workflows that depend on the primary."""
        config_path = _write_workflow(
            tmp_path,
            "wf_a",
            actions=[{"name": "step_a", "dependencies": []}],
        )
        _write_workflow(
            tmp_path,
            "wf_b",
            actions=[
                {
                    "name": "step_b",
                    "dependencies": [{"workflow": "wf_a", "action": "step_a"}],
                }
            ],
        )

        result = compile_workflows(config_path, tmp_path, run_downstream=True)
        assert set(result.involved_workflows) == {"wf_a", "wf_b"}


# ---------------------------------------------------------------------------
# compile_workflows — error handling
# ---------------------------------------------------------------------------


class TestCompileErrors:
    def test_missing_workflow_raises(self, tmp_path: Path):
        """Reference to non-existent workflow raises ConfigurationError."""
        config_path = _write_workflow(
            tmp_path,
            "downstream",
            actions=[
                {
                    "name": "consume",
                    "dependencies": [{"workflow": "nonexistent", "action": "x"}],
                }
            ],
        )

        with pytest.raises(Exception, match="not found"):
            compile_workflows(config_path, tmp_path)

    def test_invalid_yaml_raises(self, tmp_path: Path):
        """Malformed YAML raises ConfigurationError."""
        wf_dir = tmp_path / "bad" / "agent_config"
        wf_dir.mkdir(parents=True)
        (wf_dir / "bad.yml").write_text(":\n  - :\n  invalid: [")

        with pytest.raises(ConfigurationError):
            compile_workflows(wf_dir / "bad.yml", tmp_path)


# ---------------------------------------------------------------------------
# compile_workflows — workflow_graph output
# ---------------------------------------------------------------------------


class TestCompileWorkflowGraph:
    def test_workflow_graph_populated(self, tmp_path: Path):
        _write_workflow(
            tmp_path,
            "upstream",
            actions=[{"name": "produce", "dependencies": []}],
        )
        config_path = _write_workflow(
            tmp_path,
            "downstream",
            actions=[
                {
                    "name": "consume",
                    "dependencies": [{"workflow": "upstream", "action": "produce"}],
                }
            ],
        )

        result = compile_workflows(config_path, tmp_path)
        assert result.workflow_graph["downstream"] == ["upstream"]
        assert result.workflow_graph["upstream"] == []
