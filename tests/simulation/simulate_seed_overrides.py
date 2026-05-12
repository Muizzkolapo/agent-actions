"""Manual simulation: dynamic seed override resolution verification (Spec 414).

This simulation has TWO parts:

PART A — "Assumptions" (must pass NOW, before any implementation)
    Tests the REAL production code to verify assumptions the spec makes.
    If these fail, the spec's design is wrong and must be revised.

PART B — "Contracts" (must pass AFTER implementation)
    Tests that import from the real implementation module. They FAIL until
    the code is written. Once implemented, they must all pass. If the
    implementer's code passes Part B, the feature works correctly.

Run:
    python tests/simulation/simulate_seed_overrides.py

Expected output before implementation:
    Part A: all pass
    Part B: all fail (ImportError — module doesn't exist yet)

Expected output after implementation:
    Part A: all pass (nothing broken)
    Part B: all pass (feature works)
"""

import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml

# ======================================================================
# Real production imports — these exist TODAY
# ======================================================================
from agent_actions.errors.configuration import ConfigValidationError
from agent_actions.output.response.expander_merge import deep_merge_context_scope
from agent_actions.utils.path_security import resolve_seed_path
from agent_actions.workflow.runner_file_processing import (
    collect_files_from_upstream,
    should_skip_item,
)

# ======================================================================
# Test harness
# ======================================================================

passed = 0
failed = 0
skipped = 0
errors: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  \u2713 {name}")
    else:
        failed += 1
        msg = f"  \u2717 {name}"
        if detail:
            msg += f" -- {detail}"
        print(msg)
        errors.append(name)


def skip(name: str, reason: str) -> None:
    global skipped
    skipped += 1
    print(f"  - {name} [SKIP: {reason}]")


# ======================================================================
# Helpers
# ======================================================================


def make_workflow_config(seed_path: dict[str, str] | None = None) -> dict[str, Any]:
    """Realistic agent_config with seed_path in context_scope."""
    return {
        "name": "test_action",
        "model_name": "gpt-4",
        "context_scope": {
            "observe": ["field_a", "field_b"],
            "passthrough": ["source_id"],
            "seed_path": seed_path
            or {
                "exam_syllabus": "$file:mcp_qanalabs_syllabus.json",
                "question_design_rules": "$file:question_design_rules.json",
                "authoring_rules": "$file:question_authoring_rules.json",
                "validation_contract": "$file:question_validation_contract.json",
                "question_examples": "$file:question_examples.json",
            },
        },
        "workflow_config_path": "/tmp/fake/agent_config/workflow.yml",
    }


def create_staging_layout(base_dir: Path, layout: dict[str, str | None]) -> None:
    for rel_path, content in layout.items():
        full_path = base_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        if content is not None:
            full_path.write_text(content, encoding="utf-8")


# ######################################################################
#
#  PART A: ASSUMPTION TESTS (real production code, must pass NOW)
#
# ######################################################################


def partA_deep_merge_shared_reference():
    """A1: deep_merge_context_scope returns shared seed_path reference when only defaults has it.

    This is the BUG-15 trap. The spec assumes this IS shared and the implementation
    must handle it. If this test fails, the trap doesn't exist and BUG-15 is invalid.
    """
    print("\n-- A1: deep_merge_context_scope shared reference (BUG-15 assumption)")

    defaults_scope = {
        "observe": ["field_a"],
        "seed_path": {
            "exam_syllabus": "$file:default.json",
            "design_rules": "$file:rules.json",
        },
    }
    action_scope = {"observe": ["field_a", "field_b"]}  # no seed_path

    merged = deep_merge_context_scope(defaults_scope, action_scope)

    # The assumption: merged["seed_path"] IS the same object as defaults_scope["seed_path"]
    is_shared = id(merged["seed_path"]) == id(defaults_scope["seed_path"])
    check(
        "seed_path IS shared reference (trap exists)",
        is_shared,
        "If false, BUG-15 does not apply and spec section should be removed",
    )

    # Consequence: mutating merged["seed_path"] corrupts defaults
    if is_shared:
        # Prove the danger by cloning first
        defaults_before = defaults_scope["seed_path"]["exam_syllabus"]
        merged["seed_path"]["exam_syllabus"] = "$file:CORRUPTED.json"
        check(
            "mutation DOES corrupt defaults",
            defaults_scope["seed_path"]["exam_syllabus"] == "$file:CORRUPTED.json",
        )
        # Restore
        defaults_scope["seed_path"]["exam_syllabus"] = defaults_before


def partA_deep_merge_both_scopes_creates_new_dict():
    """A2: When BOTH defaults and action have seed_path, merge creates a new dict."""
    print("\n-- A2: deep_merge with both scopes creates new seed_path dict")

    defaults_scope = {"seed_path": {"key_a": "val_a", "key_b": "val_b"}}
    action_scope = {"seed_path": {"key_b": "override_b", "key_c": "val_c"}}

    merged = deep_merge_context_scope(defaults_scope, action_scope)

    check(
        "merged seed_path is NEW object", id(merged["seed_path"]) != id(defaults_scope["seed_path"])
    )
    check("key_a inherited", merged["seed_path"]["key_a"] == "val_a")
    check("key_b overridden", merged["seed_path"]["key_b"] == "override_b")
    check("key_c added", merged["seed_path"]["key_c"] == "val_c")


def partA_deep_merge_none_returns_other():
    """A3: deep_merge_context_scope with one None returns the other directly."""
    print("\n-- A3: deep_merge None handling")

    scope = {"seed_path": {"key": "val"}}
    result = deep_merge_context_scope(None, scope)
    check("None defaults returns action scope", result is scope)

    result2 = deep_merge_context_scope(scope, None)
    check("None action returns defaults scope", result2 is scope)


def partA_resolve_seed_path_traversal():
    """A4: resolve_seed_path rejects path traversal — the security boundary the spec relies on."""
    print("\n-- A4: resolve_seed_path traversal rejection")

    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "seed_data"
        base_dir.mkdir()

        traversal_specs = [
            ("../../../etc/passwd", "parent traversal"),
            ("$file:../../../etc/passwd", "parent traversal with $file:"),
            ("$file:subdir/../../etc/passwd", "nested traversal"),
        ]
        for spec, label in traversal_specs:
            try:
                resolve_seed_path(spec, base_dir)
                check(f"{label} rejected", False, "no exception raised")
            except ValueError:
                check(f"{label} rejected", True)

        # Valid path should work
        (base_dir / "valid.json").write_text("{}")
        try:
            result = resolve_seed_path("$file:valid.json", base_dir)
            check("valid path accepted", result.exists())
        except ValueError:
            check("valid path accepted", False, "unexpected ValueError")


def partA_resolve_seed_path_empty():
    """A5: resolve_seed_path rejects empty specs."""
    print("\n-- A5: resolve_seed_path empty spec rejection")

    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        for spec, label in [("", "empty string"), ("$file:", "$file: with no path")]:
            try:
                resolve_seed_path(spec, base_dir)
                check(f"{label} rejected", False, "no exception raised")
            except ValueError:
                check(f"{label} rejected", True)


def partA_should_skip_item_excludes_overrides():
    """A6: should_skip_item excludes override files."""
    print("\n-- A6: should_skip_item excludes seed override files")

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        subfolder = staging / "aws"
        subfolder.mkdir(parents=True)

        (subfolder / "_seed_overrides.yml").write_text("key: val\n")
        (subfolder / "_seed_overrides.yaml").write_text("key: val\n")
        (subfolder / "data.json").write_text("{}")

        processed: set = set()

        check(
            "_seed_overrides.yml skipped",
            should_skip_item(subfolder / "_seed_overrides.yml", staging, processed),
        )
        check(
            "_seed_overrides.yaml skipped",
            should_skip_item(subfolder / "_seed_overrides.yaml", staging, processed),
        )
        check(
            "data.json NOT skipped",
            not should_skip_item(subfolder / "data.json", staging, processed),
        )


def partA_collect_files_excludes_overrides():
    """A7: collect_files_from_upstream excludes override files."""
    print("\n-- A7: collect_files_from_upstream excludes seed override files")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "target" / "action_a"
        subfolder = target / "aws"
        subfolder.mkdir(parents=True)

        (subfolder / "_seed_overrides.yml").write_text("key: val\n")
        (subfolder / "output.json").write_text("{}")

        result = collect_files_from_upstream([str(target)])
        all_filenames = [p.name for paths in result.values() for p in paths]

        check("_seed_overrides.yml NOT collected", "_seed_overrides.yml" not in all_filenames)
        check("output.json IS collected", "output.json" in all_filenames)


def partA_yaml_safe_load_security():
    """A8: yaml.safe_load blocks dangerous YAML constructs."""
    print("\n-- A8: yaml.safe_load security guarantees")

    # safe_load blocks !!python/object
    dangerous = "!!python/object/apply:os.system ['echo pwned']"
    try:
        yaml.safe_load(dangerous)
        check("!!python/object blocked", False, "loaded successfully — DANGEROUS")
    except yaml.YAMLError:
        check("!!python/object blocked", True)

    # safe_load handles valid dict
    result = yaml.safe_load("key: value\n")
    check("valid dict parsed", result == {"key": "value"})

    # safe_load returns None for empty
    check("empty returns None", yaml.safe_load("") is None)
    check("comment-only returns None", yaml.safe_load("# comment\n") is None)


def partA_config_validation_error_format():
    """A9: ConfigValidationError produces actionable messages with the reason/config_key pattern."""
    print("\n-- A9: ConfigValidationError message format")

    try:
        raise ConfigValidationError(
            reason="Unknown seed override keys: ['exm_syllabus']. Valid keys: ['exam_syllabus']",
            config_key="_seed_overrides.yml",
        )
    except ConfigValidationError as e:
        msg = str(e)
        check("message includes config_key", "_seed_overrides.yml" in msg)
        check("message includes reason", "Unknown seed override keys" in msg)
        check("message includes valid keys", "exam_syllabus" in msg)


def partA_file_type_filter_none_does_not_protect():
    """A10: When file_type_filter is None, .yml files pass should_skip_item — no extension protection."""
    print("\n-- A10: file_type_filter=None does NOT filter .yml files")

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        staging.mkdir()
        (staging / "data.yml").write_text("key: val\n")

        processed: set = set()

        # With file_type_filter=None (default staging), .yml passes
        check(
            ".yml passes with filter=None",
            not should_skip_item(staging / "data.yml", staging, processed, file_type_filter=None),
        )

        # With file_type_filter={"json"}, .yml is filtered
        check(
            ".yml filtered with filter={'json'}",
            should_skip_item(staging / "data.yml", staging, processed, file_type_filter={"json"}),
        )


# ######################################################################
#
#  PART B: CONTRACT TESTS (must pass AFTER implementation)
#
#  These import from the implementation module. They WILL FAIL with
#  ImportError until the code is written. That's the point — they are
#  not theater because they test real code, not reference implementations.
#
# ######################################################################

PART_B_AVAILABLE = False
PART_B_IMPORT_ERROR = ""

try:
    # These imports will succeed ONLY after the implementer creates the code.
    # The import paths match the spec's proposed module locations.
    from agent_actions.input.preprocessing.staging.initial_pipeline import (
        MAX_OVERRIDE_FILE_SIZE,
        SEED_OVERRIDE_FILENAMES,
        _apply_seed_overrides,
        _find_override_file,
        _load_and_validate_seed_overrides,
    )
    from agent_actions.workflow.runner_file_processing import (
        is_framework_sidecar,
    )

    PART_B_AVAILABLE = True
except ImportError as e:
    PART_B_IMPORT_ERROR = str(e)

# Also try the updated should_skip_item / collect_files_from_upstream
PART_B_FILTERING_FIXED = False
try:
    # After implementation, these should exclude override files
    # We test by checking if is_framework_sidecar exists (added by implementation)
    if PART_B_AVAILABLE:
        PART_B_FILTERING_FIXED = True
except Exception:
    pass


def partB_find_override_file_yml():
    """B1: _find_override_file detects .yml extension."""
    print("\n-- B1: _find_override_file (.yml)")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "_seed_overrides.yml").write_text("key: val\n")
        result = _find_override_file(d)
        check("finds .yml file", result is not None and result.name == "_seed_overrides.yml")


def partB_find_override_file_yaml():
    """B2: _find_override_file detects .yaml extension."""
    print("\n-- B2: _find_override_file (.yaml)")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "_seed_overrides.yaml").write_text("key: val\n")
        result = _find_override_file(d)
        check("finds .yaml file", result is not None and result.name == "_seed_overrides.yaml")


def partB_find_override_file_missing():
    """B3: _find_override_file returns None when no override exists."""
    print("\n-- B3: _find_override_file (missing)")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "data.json").write_text("{}")
        check("returns None", _find_override_file(d) is None)


def partB_load_validates_unknown_keys():
    """B4: _load_and_validate_seed_overrides rejects unknown keys with valid key listing."""
    print("\n-- B4: Unknown key rejection")
    config = make_workflow_config()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "_seed_overrides.yml"
        p.write_text("exm_syllabus: $file:typo.json\n")  # typo
        try:
            _load_and_validate_seed_overrides(p, config)
            check("raises ConfigValidationError", False, "no exception")
        except ConfigValidationError as e:
            msg = str(e)
            check("raises ConfigValidationError", True)
            check("mentions unknown key", "exm_syllabus" in msg)
            check("lists valid keys", "exam_syllabus" in msg)


def partB_load_validates_non_string_values():
    """B5: Non-string override values are rejected (BUG-13)."""
    print("\n-- B5: Non-string value rejection")
    config = make_workflow_config()
    cases = [
        ("dict", "exam_syllabus:\n  nested: value\n"),
        ("list", "exam_syllabus:\n  - item\n"),
        ("null", "exam_syllabus:\n"),
        ("int", "exam_syllabus: 42\n"),
        ("bool", "exam_syllabus: true\n"),
    ]
    for label, content in cases:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "_seed_overrides.yml"
            p.write_text(content)
            try:
                _load_and_validate_seed_overrides(p, config)
                check(f"{label} rejected", False, "no exception")
            except ConfigValidationError:
                check(f"{label} rejected", True)


def partB_load_empty_file_returns_empty():
    """B6: Empty/null YAML returns empty dict (no overrides)."""
    print("\n-- B6: Empty override file")
    config = make_workflow_config()
    for label, content in [("empty", ""), ("comment", "# nothing\n"), ("null", "---\n")]:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "_seed_overrides.yml"
            p.write_text(content)
            result = _load_and_validate_seed_overrides(p, config)
            check(f"{label} -> empty dict", result == {})


def partB_load_non_dict_rejected():
    """B7: Non-dict YAML content is rejected."""
    print("\n-- B7: Non-dict content rejection")
    config = make_workflow_config()
    for label, content in [("list", "- a\n- b\n"), ("string", "just text\n"), ("number", "42\n")]:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "_seed_overrides.yml"
            p.write_text(content)
            try:
                _load_and_validate_seed_overrides(p, config)
                check(f"{label} rejected", False, "no exception")
            except ConfigValidationError:
                check(f"{label} rejected", True)


def partB_load_file_size_limit():
    """B8: Override file exceeding size limit is rejected (BUG-14)."""
    print("\n-- B8: File size limit")
    config = make_workflow_config()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "_seed_overrides.yml"
        p.write_text("exam_syllabus: " + "x" * (MAX_OVERRIDE_FILE_SIZE + 100) + "\n")
        try:
            _load_and_validate_seed_overrides(p, config)
            check("oversized rejected", False, "no exception")
        except ConfigValidationError:
            check("oversized rejected", True)


def partB_load_bad_yaml():
    """B9: Malformed YAML raises clear error."""
    print("\n-- B9: Bad YAML")
    config = make_workflow_config()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "_seed_overrides.yml"
        p.write_text("exam_syllabus: [invalid yaml\n  broken: {{\n")
        try:
            _load_and_validate_seed_overrides(p, config)
            check("bad YAML rejected", False, "no exception")
        except (yaml.YAMLError, ConfigValidationError):
            check("bad YAML rejected", True)


def partB_apply_overrides_merges_correctly():
    """B10: _apply_seed_overrides produces correct merged seed_path."""
    print("\n-- B10: Override merging")
    config = make_workflow_config()
    overrides = {"exam_syllabus": "$file:aws_syllabus.json"}
    effective = _apply_seed_overrides(config, overrides)
    sp = effective["context_scope"]["seed_path"]

    check("overridden key", sp["exam_syllabus"] == "$file:aws_syllabus.json")
    check("inherited key", sp["question_design_rules"] == "$file:question_design_rules.json")
    check("total keys", len(sp) == 5)


def partB_apply_overrides_never_mutates_original():
    """B11: _apply_seed_overrides never mutates the original config (BUG-15 critical)."""
    print("\n-- B11: Config mutation prevention (BUG-15)")
    config = make_workflow_config()
    cs_id_before = id(config["context_scope"])
    sp_id_before = id(config["context_scope"]["seed_path"])
    sp_values_before = dict(config["context_scope"]["seed_path"])

    effective = _apply_seed_overrides(config, {"exam_syllabus": "$file:aws.json"})

    # Original identity checks
    check("context_scope identity unchanged", id(config["context_scope"]) == cs_id_before)
    check("seed_path identity unchanged", id(config["context_scope"]["seed_path"]) == sp_id_before)
    check("seed_path values unchanged", config["context_scope"]["seed_path"] == sp_values_before)

    # Effective is new objects
    check("effective is new object", id(effective) != id(config))
    check("effective context_scope is new", id(effective["context_scope"]) != cs_id_before)
    check("effective seed_path is new", id(effective["context_scope"]["seed_path"]) != sp_id_before)


def partB_cross_file_bleed_prevention():
    """B12: File A overrides don't bleed to file B processed next with the same shared config."""
    print("\n-- B12: Cross-file override bleed prevention")
    shared_config = make_workflow_config()
    original_syllabus = shared_config["context_scope"]["seed_path"]["exam_syllabus"]

    # File A gets overrides
    effective_a = _apply_seed_overrides(shared_config, {"exam_syllabus": "$file:aws.json"})

    # File B uses shared_config directly (no overrides)
    effective_b = shared_config

    check(
        "file_a gets override",
        effective_a["context_scope"]["seed_path"]["exam_syllabus"] == "$file:aws.json",
    )
    check(
        "file_b gets original",
        effective_b["context_scope"]["seed_path"]["exam_syllabus"] == original_syllabus,
    )
    check(
        "shared config unchanged",
        shared_config["context_scope"]["seed_path"]["exam_syllabus"] == original_syllabus,
    )


def partB_defaults_only_seed_path_isolation():
    """B13: When seed_path from defaults only, overrides on action A don't corrupt action B (BUG-15 deep)."""
    print("\n-- B13: Defaults-only seed_path isolation")

    defaults_scope = {
        "observe": ["field_a"],
        "seed_path": {"exam_syllabus": "$file:default.json", "rules": "$file:rules.json"},
    }
    # Two actions, neither declares seed_path at action level
    config_a = {
        "name": "a",
        "context_scope": deep_merge_context_scope(defaults_scope, {"observe": ["x"]}),
    }
    config_b = {
        "name": "b",
        "context_scope": deep_merge_context_scope(defaults_scope, {"drop": ["y"]}),
    }

    effective_a = _apply_seed_overrides(config_a, {"exam_syllabus": "$file:override.json"})

    check(
        "action_a effective has override",
        effective_a["context_scope"]["seed_path"]["exam_syllabus"] == "$file:override.json",
    )
    check(
        "action_a original NOT corrupted",
        config_a["context_scope"]["seed_path"]["exam_syllabus"] == "$file:default.json",
    )
    check(
        "action_b NOT corrupted",
        config_b["context_scope"]["seed_path"]["exam_syllabus"] == "$file:default.json",
    )
    check(
        "defaults NOT corrupted",
        defaults_scope["seed_path"]["exam_syllabus"] == "$file:default.json",
    )


def partB_is_framework_sidecar():
    """B14: is_framework_sidecar recognizes both extensions and nothing else."""
    print("\n-- B14: is_framework_sidecar")
    check(".yml recognized", is_framework_sidecar(Path("_seed_overrides.yml")))
    check(".yaml recognized", is_framework_sidecar(Path("_seed_overrides.yaml")))
    check("data.json NOT recognized", not is_framework_sidecar(Path("data.json")))
    check(".json NOT recognized", not is_framework_sidecar(Path("_seed_overrides.json")))
    check("no underscore NOT recognized", not is_framework_sidecar(Path("seed_overrides.yml")))


def partB_should_skip_item_excludes_overrides():
    """B15: After implementation, should_skip_item excludes override files."""
    print("\n-- B15: should_skip_item excludes overrides (post-implementation)")
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        sub = staging / "aws"
        sub.mkdir(parents=True)
        (sub / "_seed_overrides.yml").write_text("k: v\n")
        (sub / "_seed_overrides.yaml").write_text("k: v\n")
        (sub / "data.json").write_text("{}")

        processed: set = set()
        check(
            ".yml now excluded", should_skip_item(sub / "_seed_overrides.yml", staging, processed)
        )
        check(
            ".yaml now excluded", should_skip_item(sub / "_seed_overrides.yaml", staging, processed)
        )
        check(
            "data.json still NOT excluded",
            not should_skip_item(sub / "data.json", staging, processed),
        )


def partB_collect_files_excludes_overrides():
    """B16: After implementation, collect_files_from_upstream excludes override files."""
    print("\n-- B16: collect_files_from_upstream excludes overrides (post-implementation)")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "target"
        sub = target / "aws"
        sub.mkdir(parents=True)
        (sub / "_seed_overrides.yml").write_text("k: v\n")
        (sub / "_seed_overrides.yaml").write_text("k: v\n")
        (sub / "output.json").write_text("{}")

        result = collect_files_from_upstream([str(target)])
        all_filenames = [p.name for paths in result.values() for p in paths]

        check(".yml NOT collected", "_seed_overrides.yml" not in all_filenames)
        check(".yaml NOT collected", "_seed_overrides.yaml" not in all_filenames)
        check("output.json IS collected", "output.json" in all_filenames)


def partB_full_staging_walk():
    """B17: Full staging walk — override files excluded, correct overrides applied per subfolder."""
    print("\n-- B17: Full staging walk (end-to-end)")
    shared_config = make_workflow_config()

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        create_staging_layout(
            staging,
            {
                "aws/_seed_overrides.yml": "exam_syllabus: $file:aws_syllabus.json\n",
                "aws/aws_docs.json": '[{"text": "aws"}]',
                "mcp/_seed_overrides.yaml": "exam_syllabus: $file:mcp_syllabus.json\n",
                "mcp/mcp_docs.json": '[{"text": "mcp"}]',
                "general_docs.json": '[{"text": "general"}]',
            },
        )

        # Walk like production: rglob, skip framework sidecars
        results: dict[str, str] = {}  # filename -> effective exam_syllabus
        for item in sorted(staging.rglob("*")):
            if should_skip_item(item, staging, set()):
                continue

            override_file = _find_override_file(item.parent)
            if override_file:
                overrides = _load_and_validate_seed_overrides(override_file, shared_config)
                effective = _apply_seed_overrides(shared_config, overrides)
            else:
                effective = shared_config

            results[item.name] = effective["context_scope"]["seed_path"]["exam_syllabus"]

        check("3 data files processed", len(results) == 3, f"got {len(results)}: {list(results)}")
        check("aws gets aws override", results.get("aws_docs.json") == "$file:aws_syllabus.json")
        check("mcp gets mcp override", results.get("mcp_docs.json") == "$file:mcp_syllabus.json")
        check(
            "general gets default",
            results.get("general_docs.json") == "$file:mcp_qanalabs_syllabus.json",
        )
        check(
            "shared config unchanged",
            shared_config["context_scope"]["seed_path"]["exam_syllabus"]
            == "$file:mcp_qanalabs_syllabus.json",
        )


def partB_nested_subfolder_no_inheritance():
    """B18: Nested dir does NOT inherit parent's override."""
    print("\n-- B18: No directory inheritance")
    with tempfile.TemporaryDirectory() as tmp:
        parent = Path(tmp) / "aws"
        child = parent / "region1"
        child.mkdir(parents=True)
        (parent / "_seed_overrides.yml").write_text("exam_syllabus: $file:aws.json\n")
        (child / "docs.json").write_text("{}")

        check("child dir has no override", _find_override_file(child) is None)
        check("parent dir has override", _find_override_file(parent) is not None)


def partB_seed_override_filenames_constant():
    """B19: SEED_OVERRIDE_FILENAMES includes both extensions."""
    print("\n-- B19: SEED_OVERRIDE_FILENAMES constant")
    check("contains .yml", "_seed_overrides.yml" in SEED_OVERRIDE_FILENAMES)
    check("contains .yaml", "_seed_overrides.yaml" in SEED_OVERRIDE_FILENAMES)
    check("is frozenset", isinstance(SEED_OVERRIDE_FILENAMES, frozenset))


def partB_multiple_overrides_merge():
    """B20: Multiple keys in override file all merge correctly."""
    print("\n-- B20: Multiple keys in single override file")
    config = make_workflow_config()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "_seed_overrides.yml"
        p.write_text(
            textwrap.dedent("""\
            exam_syllabus: $file:aws_syllabus.json
            question_design_rules: $file:aws_design_rules.json
        """)
        )
        overrides = _load_and_validate_seed_overrides(p, config)
        effective = _apply_seed_overrides(config, overrides)
        sp = effective["context_scope"]["seed_path"]

        check("syllabus overridden", sp["exam_syllabus"] == "$file:aws_syllabus.json")
        check(
            "design_rules overridden", sp["question_design_rules"] == "$file:aws_design_rules.json"
        )
        check(
            "authoring_rules inherited",
            sp["authoring_rules"] == "$file:question_authoring_rules.json",
        )


# ======================================================================
# Main
# ======================================================================

if __name__ == "__main__":
    print("=" * 72)
    print("Simulation: Dynamic Seed Override Resolution (Spec 414)")
    print("=" * 72)

    # ------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("PART A: Assumption Tests (real production code, must pass NOW)")
    print("=" * 72)

    partA_deep_merge_shared_reference()  # A1
    partA_deep_merge_both_scopes_creates_new_dict()  # A2
    partA_deep_merge_none_returns_other()  # A3
    partA_resolve_seed_path_traversal()  # A4
    partA_resolve_seed_path_empty()  # A5
    partA_should_skip_item_excludes_overrides()  # A6
    partA_collect_files_excludes_overrides()  # A7
    partA_yaml_safe_load_security()  # A8
    partA_config_validation_error_format()  # A9
    partA_file_type_filter_none_does_not_protect()  # A10

    part_a_passed = passed
    part_a_failed = failed

    # ------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("PART B: Contract Tests (must pass AFTER implementation)")
    print("=" * 72)

    if not PART_B_AVAILABLE:
        print("\n  Part B SKIPPED: implementation not found")
        print(f"  ImportError: {PART_B_IMPORT_ERROR}")
        print("\n  This is EXPECTED before implementation.")
        print("  After implementing spec 414, re-run this simulation.")
        print("  All Part B tests must pass for the feature to be correct.\n")
        part_b_ran = False
    else:
        part_b_ran = True
        partB_find_override_file_yml()  # B1
        partB_find_override_file_yaml()  # B2
        partB_find_override_file_missing()  # B3
        partB_load_validates_unknown_keys()  # B4
        partB_load_validates_non_string_values()  # B5
        partB_load_empty_file_returns_empty()  # B6
        partB_load_non_dict_rejected()  # B7
        partB_load_file_size_limit()  # B8
        partB_load_bad_yaml()  # B9
        partB_apply_overrides_merges_correctly()  # B10
        partB_apply_overrides_never_mutates_original()  # B11
        partB_cross_file_bleed_prevention()  # B12
        partB_defaults_only_seed_path_isolation()  # B13
        partB_is_framework_sidecar()  # B14
        partB_should_skip_item_excludes_overrides()  # B15
        partB_collect_files_excludes_overrides()  # B16
        partB_full_staging_walk()  # B17
        partB_nested_subfolder_no_inheritance()  # B18
        partB_seed_override_filenames_constant()  # B19
        partB_multiple_overrides_merge()  # B20

    # ------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("Results")
    print("=" * 72)

    part_b_passed = passed - part_a_passed
    part_b_failed = failed - part_a_failed

    print(f"\n  Part A (assumptions):  {part_a_passed} passed, {part_a_failed} failed")
    if part_b_ran:
        print(f"  Part B (contracts):    {part_b_passed} passed, {part_b_failed} failed")
    else:
        print("  Part B (contracts):    SKIPPED (implementation not found)")
    print(f"  Total:                 {passed} passed, {failed} failed, {skipped} skipped")

    if errors:
        print("\n  Failed checks:")
        for e in errors:
            print(f"    \u2717 {e}")

    if part_a_failed > 0:
        print("\n  PART A FAILURES: spec assumptions are wrong. Revise spec before implementing.")
        sys.exit(2)
    elif not part_b_ran:
        print("\n  Part A all green. Implement spec 414, then re-run to validate Part B.")
        sys.exit(0)
    elif part_b_failed > 0:
        print("\n  PART B FAILURES: implementation has bugs. Fix before merging.")
        sys.exit(1)
    else:
        print("\n  All checks passed. Feature is correct.")
        sys.exit(0)
