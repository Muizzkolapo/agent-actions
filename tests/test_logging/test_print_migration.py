"""
Tests to enforce print() statement migration to logging.

This test ensures that diagnostic print statements are converted to structured
logging, while allowing legitimate user-facing print statements in CLI modules.
"""

import os
import re
from pathlib import Path
import pytest


class TestPrintStatementMigration:
    """Tests to catch unauthorized print() statements in source code."""

    # Allowlist of files where print() is acceptable (user-facing CLI output)
    ALLOWED_PRINT_FILES = {
        # CLI modules with user-facing output
        "agent_actions/cli/list_udfs.py",  # Table output, discovery messages
        "agent_actions/cli/main.py",  # User error messages, version display
        "agent_actions/validation/validate_udfs.py",  # Validation results output
        # Orchestration modules with user-facing progress/status
        "agent_actions/orchestration/agent_workflow.py",  # Real-time workflow progress
        "agent_actions/orchestration/agent_executor.py",  # Agent execution status
        "agent_actions/orchestration/skip_evaluator.py",  # Skip decision notifications
        "agent_actions/orchestration/batch_manager.py",  # Batch status messages
        "agent_actions/orchestration/output_manager.py",  # Loop correlation messages
        "agent_actions/orchestration/action_level_executor.py",  # Action execution status
        # Prompt generation with user notifications
        "agent_actions/prompt_generation/directory_handler.py",  # Copy notifications
        # LLM invocation with debug output
        "agent_actions/llm_invocation/realtime/services/prompt_service.py",  # Debug mode output
        "agent_actions/llm_invocation/realtime/services/interceptor_service.py",  # Interceptor status
        "agent_actions/llm_invocation/providers/gemini/provider.py",  # Provider debug output
        # Response processing
        "agent_actions/response_processing/schema_loader.py",  # Schema loading status
        # UDF-related user output
        "agent_actions/input_loading/udf_loader.py",  # UDF discovery count
    }

    # Patterns that indicate diagnostic (non-user-facing) prints that should use logging
    DIAGNOSTIC_PATTERNS = [
        re.compile(r"print.*debug", re.IGNORECASE),
        re.compile(r"print.*traceback", re.IGNORECASE),
        re.compile(r"print.*exception", re.IGNORECASE),
        re.compile(r"print.*\bif\s+debug\b", re.IGNORECASE),
        re.compile(r"print.*\bif\s+verbose\b", re.IGNORECASE),
    ]

    @pytest.fixture
    def source_files(self):
        """Get all Python source files in agent_actions package."""
        project_root = Path(__file__).parent.parent.parent
        agent_actions_dir = project_root / "agent_actions"

        if not agent_actions_dir.exists():
            pytest.skip(f"agent_actions directory not found at {agent_actions_dir}")

        source_files = []
        for py_file in agent_actions_dir.rglob("*.py"):
            # Skip __pycache__ and test files
            if "__pycache__" in str(py_file) or "test_" in py_file.name:
                continue

            # Get relative path from project root
            rel_path = py_file.relative_to(project_root)
            source_files.append((str(rel_path), py_file))

        return source_files

    def test_no_diagnostic_print_statements(self, source_files):
        """
        Test that diagnostic print statements have been converted to logging.

        This test scans all source files for print() statements that match
        diagnostic patterns (debug, traceback, exception, etc.) which should
        use the logging system instead.

        Note: Files in ALLOWED_PRINT_FILES are skipped since they may have
        legitimate debug output for users (e.g., --debug flag output).
        """
        violations = []

        for rel_path, file_path in source_files:
            # Skip allowlisted files (they may have user-facing debug output)
            if rel_path in self.ALLOWED_PRINT_FILES:
                continue

            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines, start=1):
                # Skip comments
                if line.strip().startswith("#"):
                    continue

                # Check if line contains print()
                if "print(" in line or "print (" in line:
                    # Check if it matches diagnostic patterns
                    for pattern in self.DIAGNOSTIC_PATTERNS:
                        if pattern.search(line):
                            violations.append(
                                {
                                    "file": rel_path,
                                    "line": line_num,
                                    "content": line.strip(),
                                    "pattern": pattern.pattern,
                                }
                            )
                            break

        if violations:
            error_msg = "\n\nFound diagnostic print() statements that should use logging:\n\n"
            for v in violations:
                error_msg += f"  {v['file']}:{v['line']}\n"
                error_msg += f"    {v['content']}\n"
                error_msg += f"    (matches pattern: {v['pattern']})\n\n"
            error_msg += "Please convert these to use logger.debug(), logger.info(), etc.\n"
            pytest.fail(error_msg)

    def test_print_statements_only_in_allowed_files(self, source_files):
        """
        Test that print() statements outside allowlist are investigated.

        This test identifies print() statements in files not on the allowlist.
        It's informational rather than enforcing, to help track migration progress.
        """
        print_usage = {}

        for rel_path, file_path in source_files:
            # Skip allowlisted files
            if rel_path in self.ALLOWED_PRINT_FILES:
                continue

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Count print statements (simple regex, may have false positives)
            # This looks for print( or print ( but excludes comments and strings
            lines = content.split("\n")
            print_lines = []

            for line_num, line in enumerate(lines, start=1):
                # Skip comments
                if line.strip().startswith("#"):
                    continue

                # Check for print statements
                if re.search(r"\bprint\s*\(", line):
                    print_lines.append((line_num, line.strip()))

            if print_lines:
                print_usage[rel_path] = print_lines

        # This test is informational - it reports but doesn't fail
        if print_usage:
            report = "\n\n=== Print Statement Migration Status ===\n\n"
            report += f"Found print() statements in {len(print_usage)} non-allowlisted files:\n\n"

            for file_path, lines in sorted(print_usage.items()):
                report += f"\n{file_path} ({len(lines)} print statements):\n"
                for line_num, line_content in lines[:3]:  # Show first 3
                    report += f"  Line {line_num}: {line_content[:80]}\n"
                if len(lines) > 3:
                    report += f"  ... and {len(lines) - 3} more\n"

            report += "\n=== End Report ===\n"

            # Print report but don't fail (this is informational)
            print(report)

            # Optional: You can make this a warning instead of just info
            # pytest.warn(UserWarning(report))

    def test_allowlist_files_exist(self):
        """Test that all files in the allowlist actually exist."""
        project_root = Path(__file__).parent.parent.parent

        missing_files = []
        for allowed_file in self.ALLOWED_PRINT_FILES:
            file_path = project_root / allowed_file
            if not file_path.exists():
                missing_files.append(allowed_file)

        if missing_files:
            error_msg = "\n\nAllowlist contains non-existent files:\n"
            for f in missing_files:
                error_msg += f"  - {f}\n"
            error_msg += "\nPlease update ALLOWED_PRINT_FILES in test_print_migration.py\n"
            pytest.fail(error_msg)

    def test_no_bare_print_in_new_code(self, source_files):
        """
        Test that helps prevent new print() statements in modules that have
        been fully migrated to logging.

        This is a stricter check for modules that should have NO print statements.
        """
        # List of modules that have been fully migrated (no prints allowed)
        FULLY_MIGRATED_MODULES = {
            "agent_actions/orchestration/agent_runner.py",
            "agent_actions/input_loading/extractors_source_data_loader.py",
            "agent_actions/preprocessing/staging_loader.py",
            "agent_actions/llm_invocation/batch/batch_service.py",
            "agent_actions/llm_invocation/batch/batch_side_output_handler.py",
            "agent_actions/response_processing/where_parser.py",
            "agent_actions/utilities/processor_helpers.py",
            "agent_actions/utilities/path_utils.py",
            "agent_actions/preprocessing/operator_registry/registry.py",
        }

        violations = []

        for rel_path, file_path in source_files:
            # Only check fully migrated modules
            if rel_path not in FULLY_MIGRATED_MODULES:
                continue

            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines, start=1):
                # Skip comments
                if line.strip().startswith("#"):
                    continue

                # Check for print statements
                if re.search(r"\bprint\s*\(", line):
                    violations.append({"file": rel_path, "line": line_num, "content": line.strip()})

        if violations:
            error_msg = "\n\nFound print() statements in fully migrated modules:\n\n"
            for v in violations:
                error_msg += f"  {v['file']}:{v['line']}\n"
                error_msg += f"    {v['content']}\n\n"
            error_msg += "These modules should use logging only. Please use logger.debug/info/warning/error instead.\n"
            pytest.fail(error_msg)
