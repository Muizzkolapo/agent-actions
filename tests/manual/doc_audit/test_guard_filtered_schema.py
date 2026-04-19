#!/usr/bin/env python3
"""Manual end-to-end test: guard-filtered schema validation.

Simulates the full lifecycle of a guard-filtered record flowing through
a downstream tool action.  Proves that:

  1. WITHOUT the fix, jsonschema.validate crashes on None fields
  2. The auto-fix modifies only the right fields in the schema
  3. AFTER the fix, filtered records pass validation
  4. Non-filtered records are still validated strictly
  5. The fix works with post-expansion guard format (behavior key)
  6. Transitive passthrough chains are also fixed

Run:
    python tests/manual/doc_audit/test_guard_filtered_schema.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

# --- path fixup for standalone execution ---
if __name__ == "__main__":
    _root = Path(__file__).resolve().parents[3]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import jsonschema

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    apply_guard_nullable_schema_fixes,
)

# ── Colors ──────────────────────────────────────────────────────────

CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _header(title: str) -> None:
    print(f"\n{CYAN}{'═' * 72}")
    print(f"  {title}")
    print(f"{'═' * 72}{RESET}")


def _pass(msg: str) -> None:
    print(f"  {GREEN}PASS{RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"  {DIM}INFO{RESET}  {msg}")


def _show_schema(label: str, schema: dict) -> None:
    print(f"  {YELLOW}{label}:{RESET}")
    for line in json.dumps(schema, indent=2).splitlines():
        print(f"    {DIM}{line}{RESET}")


# ── Workflow simulation ─────────────────────────────────────────────


def build_action_configs() -> dict[str, dict[str, Any]]:
    """Simulate what the config pipeline produces for a real workflow.

    Workflow:
        fix_failed_validation (guarded, on_false: filter)
          -> produces: options (object), answer (string)

        select_validated_questions (tool, observes fix_failed_validation.options)
          -> schema: options (object), summary (string)
    """
    return {
        "fix_failed_validation": {
            "model_vendor": "openai",
            # Post-expansion guard format (what coordinator actually sees)
            "guard": {
                "clause": 'validation_status == "FAIL"',
                "scope": "item",
                "behavior": "filter",
            },
        },
        "select_validated_questions": {
            "model_vendor": "tool",
            "json_output_schema": {
                "type": "object",
                "properties": {
                    "options": {"type": "object"},
                    "summary": {"type": "string"},
                },
                "required": ["options", "summary"],
                "additionalProperties": False,
            },
            "context_scope": {
                "observe": [
                    "fix_failed_validation.options",
                ],
            },
        },
    }


def build_transitive_action_configs() -> dict[str, dict[str, Any]]:
    """Simulate a transitive passthrough chain: guarded -> intermediate -> tool.

    Workflow:
        extract_qa (guarded, on_false: filter)
          -> produces: qa_content (object)

        enrich_qa (passthrough extract_qa.*)
          -> adds: enrichment (string)

        format_output (tool, observes enrich_qa.qa_content)
          -> schema: qa_content (object), enrichment (string)
    """
    return {
        "extract_qa": {
            "model_vendor": "openai",
            "guard": {
                "clause": "has_qa_content == true",
                "scope": "item",
                "behavior": "filter",
            },
            "schema": [{"id": "qa_content", "type": "object"}],
        },
        "enrich_qa": {
            "model_vendor": "openai",
            "context_scope": {
                "observe": ["extract_qa.qa_content"],
                "passthrough": ["extract_qa.*"],
            },
        },
        "format_output": {
            "model_vendor": "tool",
            "json_output_schema": {
                "type": "object",
                "properties": {
                    "qa_content": {"type": "object"},
                    "enrichment": {"type": "string"},
                },
                "required": ["qa_content", "enrichment"],
                "additionalProperties": False,
            },
            "context_scope": {
                "observe": [
                    "enrich_qa.qa_content",
                    "enrich_qa.enrichment",
                ],
            },
        },
    }


# ── Test scenarios ──────────────────────────────────────────────────

passed = 0
failed = 0


def check(condition: bool, msg: str) -> None:
    global passed, failed
    if condition:
        _pass(msg)
        passed += 1
    else:
        _fail(msg)
        failed += 1


def scenario_1_crash_without_fix() -> None:
    """Prove that WITHOUT the fix, a filtered record crashes."""
    _header("SCENARIO 1: Without fix — filtered record CRASHES")

    configs = build_action_configs()
    schema = configs["select_validated_questions"]["json_output_schema"]
    _show_schema("Schema before fix", schema)

    # Simulate what the tool returns when upstream was filtered
    filtered_record_output = {"options": None, "summary": "Record passed validation"}

    _info("Tool output for filtered record: options=None, summary='...'")

    try:
        jsonschema.validate(instance=filtered_record_output, schema=schema)
        _fail("Expected ValidationError but validation passed!")
        check(False, "Unfixed schema rejects None for 'options'")
    except jsonschema.ValidationError as e:
        _info(f"Error: {e.message}")
        check(
            "None is not of type" in e.message,
            "Unfixed schema rejects None for 'options'",
        )


def scenario_2_fix_applied() -> None:
    """Show what the fix does to the schema."""
    _header("SCENARIO 2: Auto-fix modifies schema")

    configs = build_action_configs()
    schema_before = copy.deepcopy(configs["select_validated_questions"]["json_output_schema"])

    fixes = apply_guard_nullable_schema_fixes(configs)
    schema_after = configs["select_validated_questions"]["json_output_schema"]

    _info(f"Fixes applied: {fixes}")
    _show_schema("Schema BEFORE", schema_before)
    _show_schema("Schema AFTER", schema_after)

    check(
        fixes == ["select_validated_questions.options"],
        "Fix targets exactly 'select_validated_questions.options'",
    )
    check(
        schema_after["properties"]["options"]["type"] == ["object", "null"],
        "'options' type changed to ['object', 'null']",
    )
    check(
        schema_after["properties"]["summary"]["type"] == "string",
        "'summary' type unchanged (not from guarded upstream)",
    )
    check(
        "options" in schema_after.get("required", []),
        "'options' still required (field must be present, just nullable)",
    )


def scenario_3_filtered_record_passes() -> None:
    """After fix, a filtered record's None values pass validation."""
    _header("SCENARIO 3: After fix — filtered record PASSES")

    configs = build_action_configs()
    apply_guard_nullable_schema_fixes(configs)
    schema = configs["select_validated_questions"]["json_output_schema"]

    filtered_output = {"options": None, "summary": "Record passed validation"}
    _info(f"Tool output: {json.dumps(filtered_output)}")

    try:
        jsonschema.validate(instance=filtered_output, schema=schema)
        check(True, "Filtered record (options=None) passes validation")
    except jsonschema.ValidationError as e:
        _fail(f"Unexpected error: {e.message}")
        check(False, "Filtered record (options=None) passes validation")


def scenario_4_non_filtered_still_strict() -> None:
    """Non-filtered records are still validated strictly."""
    _header("SCENARIO 4: Non-filtered records — still strict")

    configs = build_action_configs()
    apply_guard_nullable_schema_fixes(configs)
    schema = configs["select_validated_questions"]["json_output_schema"]

    # Valid object passes
    valid_output = {"options": {"a": 1, "b": 2}, "summary": "Looks good"}
    try:
        jsonschema.validate(instance=valid_output, schema=schema)
        check(True, "Valid object for 'options' still passes")
    except jsonschema.ValidationError:
        check(False, "Valid object for 'options' still passes")

    # Wrong type still fails
    wrong_type_output = {"options": "not an object", "summary": "Looks good"}
    try:
        jsonschema.validate(instance=wrong_type_output, schema=schema)
        check(False, "String for 'options' still fails")
    except jsonschema.ValidationError:
        check(True, "String for 'options' still fails")

    # Missing required field still fails
    missing_field_output = {"summary": "No options at all"}
    try:
        jsonschema.validate(instance=missing_field_output, schema=schema)
        check(False, "Missing 'options' still fails")
    except jsonschema.ValidationError:
        check(True, "Missing 'options' still fails")

    # None for NON-guarded field still fails
    none_summary_output = {"options": {"a": 1}, "summary": None}
    try:
        jsonschema.validate(instance=none_summary_output, schema=schema)
        check(False, "None for non-guarded 'summary' still fails")
    except jsonschema.ValidationError:
        check(True, "None for non-guarded 'summary' still fails")


def scenario_5_warn_guard_not_fixed() -> None:
    """Guards with on_false: 'warn' should NOT be treated as filterable."""
    _header("SCENARIO 5: Warn guard — no fix applied")

    configs = build_action_configs()
    # Change guard to warn (post-expansion format)
    configs["fix_failed_validation"]["guard"]["behavior"] = "warn"

    fixes = apply_guard_nullable_schema_fixes(configs)
    schema = configs["select_validated_questions"]["json_output_schema"]

    _info(f"Fixes applied: {fixes}")

    check(fixes == [], "No fixes applied for warn guard")
    check(
        schema["properties"]["options"]["type"] == "object",
        "'options' type remains 'object' (not made nullable)",
    )


def scenario_6_transitive_passthrough() -> None:
    """Fix works through transitive passthrough chains."""
    _header("SCENARIO 6: Transitive passthrough chain")

    configs = build_transitive_action_configs()
    schema_before = copy.deepcopy(configs["format_output"]["json_output_schema"])

    fixes = apply_guard_nullable_schema_fixes(configs)
    schema_after = configs["format_output"]["json_output_schema"]

    _info("Chain: extract_qa (guarded) -> enrich_qa (passthrough) -> format_output (tool)")
    _info(f"Fixes applied: {fixes}")
    _show_schema("Schema BEFORE", schema_before)
    _show_schema("Schema AFTER", schema_after)

    check(
        "format_output.qa_content" in fixes,
        "Transitive field 'qa_content' fixed through passthrough",
    )
    check(
        "format_output.enrichment" not in fixes,
        "'enrichment' NOT fixed (not from guarded upstream)",
    )
    check(
        schema_after["properties"]["qa_content"]["type"] == ["object", "null"],
        "'qa_content' type changed to ['object', 'null']",
    )
    check(
        schema_after["properties"]["enrichment"]["type"] == "string",
        "'enrichment' type unchanged",
    )

    # Verify filtered record passes after fix
    filtered_output = {"qa_content": None, "enrichment": "n/a"}
    try:
        jsonschema.validate(instance=filtered_output, schema=schema_after)
        check(True, "Filtered transitive record passes validation")
    except jsonschema.ValidationError as e:
        _fail(f"Unexpected error: {e.message}")
        check(False, "Filtered transitive record passes validation")


# ── Main ────────────────────────────────────────────────────────────


def main() -> int:
    print(f"\n{BOLD}{CYAN}Guard-Filtered Schema Validation — End-to-End Test{RESET}")
    print(f"{DIM}Simulates the full lifecycle: config expansion -> auto-fix -> validation")
    print("Proves the fix works for direct observation, transitive passthrough,")
    print(f"and preserves strict validation for non-filtered records.{RESET}")

    scenario_1_crash_without_fix()
    scenario_2_fix_applied()
    scenario_3_filtered_record_passes()
    scenario_4_non_filtered_still_strict()
    scenario_5_warn_guard_not_fixed()
    scenario_6_transitive_passthrough()

    # Summary
    total = passed + failed
    print(f"\n{CYAN}{'═' * 72}{RESET}")
    color = GREEN if failed == 0 else RED
    print(f"  {color}{passed}/{total} passed, {failed} failed{RESET}")
    print(f"{CYAN}{'═' * 72}{RESET}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
