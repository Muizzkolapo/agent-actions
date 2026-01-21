#!/usr/bin/env python3
"""
Domain-Driven Restructure Migration Script

This script migrates the agent_actions codebase to the new domain-driven structure.
Run with --dry-run first to see what will happen.

Usage:
    python migrate.py --dry-run          # Preview changes
    python migrate.py --phase 1          # Run specific phase
    python migrate.py --all              # Run all phases
    python migrate.py --update-imports   # Only update imports (after files moved)
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from migration_map import DIRECTORY_STRUCTURE, FILE_MIGRATIONS, IMPORT_REWRITES


class MigrationRunner:
    def __init__(self, base_path: Path, dry_run: bool = True):
        self.base_path = base_path
        self.agent_actions = base_path / "agent_actions"
        self.dry_run = dry_run
        self.files_moved = 0
        self.imports_updated = 0
        self.errors = []

    def log(self, msg: str, level: str = "INFO"):
        prefix = {"INFO": "   ", "ACTION": ">> ", "ERROR": "!! ", "SKIP": "-- "}
        print(f"{prefix.get(level, '   ')}{msg}")

    def create_directory_structure(self):
        """Phase 0: Create all new directories."""
        print("\n=== Creating Directory Structure ===\n")

        for dir_path in DIRECTORY_STRUCTURE:
            full_path = self.agent_actions / dir_path
            if full_path.exists():
                self.log(f"Exists: {dir_path}", "SKIP")
            else:
                if self.dry_run:
                    self.log(f"Would create: {dir_path}", "ACTION")
                else:
                    full_path.mkdir(parents=True, exist_ok=True)
                    self.log(f"Created: {dir_path}", "ACTION")

                    # Create __init__.py
                    init_file = full_path / "__init__.py"
                    if not init_file.exists():
                        init_file.write_text('"""Package."""\n')

    def move_file(self, old_path: str, new_path: str) -> bool:
        """Move a single file from old to new location."""
        if new_path is None:
            # File should be deleted (empty __init__ etc)
            src = self.agent_actions / old_path
            if src.exists():
                if self.dry_run:
                    self.log(f"Would delete: {old_path}", "ACTION")
                else:
                    src.unlink()
                    self.log(f"Deleted: {old_path}", "ACTION")
            return True

        src = self.agent_actions / old_path
        dst = self.agent_actions / new_path

        if not src.exists():
            # Check if it's a directory pattern
            if old_path.endswith("/"):
                src_dir = self.agent_actions / old_path.rstrip("/")
                dst_dir = self.agent_actions / new_path.rstrip("/")
                if src_dir.exists() and src_dir.is_dir():
                    if self.dry_run:
                        self.log(f"Would copy dir: {old_path} -> {new_path}", "ACTION")
                    else:
                        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
                        self.log(f"Copied dir: {old_path} -> {new_path}", "ACTION")
                    return True
            self.log(f"Source not found: {old_path}", "SKIP")
            return False

        if dst.exists():
            self.log(f"Destination exists: {new_path}", "SKIP")
            return False

        # Ensure parent directory exists
        dst.parent.mkdir(parents=True, exist_ok=True)

        if self.dry_run:
            self.log(f"Would move: {old_path} -> {new_path}", "ACTION")
        else:
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                self.log(f"Copied dir: {old_path} -> {new_path}", "ACTION")
            else:
                shutil.copy2(src, dst)
                self.log(f"Moved: {old_path} -> {new_path}", "ACTION")
                self.files_moved += 1

        return True

    def update_imports_in_file(self, file_path: Path) -> int:
        """Update imports in a single file. Returns number of changes."""
        if not file_path.exists():
            return 0

        try:
            content = file_path.read_text()
        except Exception as e:
            self.log(f"Error reading {file_path}: {e}", "ERROR")
            return 0

        original_content = content
        changes = 0

        # Sort rewrites by length (longest first) to avoid partial matches
        sorted_rewrites = sorted(IMPORT_REWRITES.items(), key=lambda x: -len(x[0]))

        for old_import, new_import in sorted_rewrites:
            # Match various import patterns
            patterns = [
                # from X import Y
                (rf"from {re.escape(old_import)}(\s+import)", f"from {new_import}\\1"),
                # from X.submodule import Y
                (rf"from {re.escape(old_import)}\.(\w+)", f"from {new_import}.\\1"),
                # import X
                (rf"^import {re.escape(old_import)}$", f"import {new_import}", re.MULTILINE),
                # import X as Y
                (rf"import {re.escape(old_import)}(\s+as)", f"import {new_import}\\1"),
            ]

            for pattern_tuple in patterns:
                if len(pattern_tuple) == 3:
                    pattern, replacement, flags = pattern_tuple
                    new_content = re.sub(pattern, replacement, content, flags=flags)
                else:
                    pattern, replacement = pattern_tuple
                    new_content = re.sub(pattern, replacement, content)

                if new_content != content:
                    changes += content.count(old_import) - new_content.count(old_import)
                    content = new_content

        if content != original_content:
            if self.dry_run:
                self.log(
                    f"Would update imports in: {file_path.relative_to(self.base_path)} ({changes} changes)",
                    "ACTION",
                )
            else:
                file_path.write_text(content)
                self.log(
                    f"Updated imports in: {file_path.relative_to(self.base_path)} ({changes} changes)",
                    "ACTION",
                )
                self.imports_updated += changes

        return changes

    def update_all_imports(self):
        """Update imports across all Python files."""
        print("\n=== Updating Imports ===\n")

        python_files = list(self.agent_actions.rglob("*.py"))
        # Also check tests
        tests_dir = self.base_path / "tests"
        if tests_dir.exists():
            python_files.extend(tests_dir.rglob("*.py"))

        total_changes = 0
        for py_file in python_files:
            if "__pycache__" in str(py_file):
                continue
            changes = self.update_imports_in_file(py_file)
            total_changes += changes

        print(f"\nTotal import changes: {total_changes}")

    def run_phase(self, phase: int):
        """Run a specific migration phase."""
        phases = {
            0: ("Create directory structure", self.phase_0_directories),
            1: ("Move errors module", self.phase_1_errors),
            2: ("Move utils module", self.phase_2_utils),
            3: ("Move logging module", self.phase_3_logging),
            4: ("Move models module", self.phase_4_models),
            5: ("Move input domain", self.phase_5_input),
            6: ("Move processing domain", self.phase_6_processing),
            7: ("Move prompt domain", self.phase_7_prompt),
            8: ("Move output domain", self.phase_8_output),
            9: ("Move llm domain", self.phase_9_llm),
            10: ("Move config domain", self.phase_10_config),
            11: ("Move validation domain", self.phase_11_validation),
            12: ("Move workflow domain", self.phase_12_workflow),
            13: ("Move cli domain", self.phase_13_cli),
            14: ("Move tooling", self.phase_14_tooling),
            15: ("Update imports", self.phase_15_imports),
            16: ("Cleanup old directories", self.phase_16_cleanup),
        }

        if phase not in phases:
            print(f"Unknown phase: {phase}")
            return

        name, func = phases[phase]
        print(f"\n{'=' * 60}")
        print(f"Phase {phase}: {name}")
        print(f"{'=' * 60}")
        func()

    def phase_0_directories(self):
        self.create_directory_structure()

    def phase_1_errors(self):
        """Move errors module (foundation - no internal deps)."""
        migrations = {k: v for k, v in FILE_MIGRATIONS.items() if k.startswith("errors/")}
        for old, new in migrations.items():
            self.move_file(old, new)

    def phase_2_utils(self):
        """Move utilities -> utils."""
        migrations = {
            k: v
            for k, v in FILE_MIGRATIONS.items()
            if k.startswith("utilities/") and not k.startswith("utilities/processor/")
        }
        for old, new in migrations.items():
            self.move_file(old, new)

    def phase_3_logging(self):
        """Move logging module + shared/user_errors."""
        migrations = {
            k: v
            for k, v in FILE_MIGRATIONS.items()
            if k.startswith("logging/") or k.startswith("shared/")
        }
        for old, new in migrations.items():
            self.move_file(old, new)

    def phase_4_models(self):
        """Move models."""
        migrations = {k: v for k, v in FILE_MIGRATIONS.items() if k.startswith("models/")}
        for old, new in migrations.items():
            self.move_file(old, new)

    def phase_5_input(self):
        """Move input_loading + preprocessing -> input/."""
        migrations = {
            k: v
            for k, v in FILE_MIGRATIONS.items()
            if k.startswith("input_loading/") or k.startswith("preprocessing/")
        }
        # Filter out ones going to prompt/context
        migrations = {
            k: v for k, v in migrations.items() if v and not v.startswith("prompt/context/")
        }
        for old, new in migrations.items():
            self.move_file(old, new)

    def phase_6_processing(self):
        """Move core -> processing/."""
        migrations = {
            k: v
            for k, v in FILE_MIGRATIONS.items()
            if k.startswith("core/") or k.startswith("utilities/processor/")
        }
        for old, new in migrations.items():
            self.move_file(old, new)

        # Also move state_management/lineage_mixin.py to processing
        self.move_file("state_management/lineage_mixin.py", "processing/lineage_mixin.py")

    def phase_7_prompt(self):
        """Move prompt_generation -> prompt/ + LLM context files."""
        migrations = {
            k: v for k, v in FILE_MIGRATIONS.items() if k.startswith("prompt_generation/")
        }
        for old, new in migrations.items():
            self.move_file(old, new)

        # Move LLM context files from preprocessing
        self.move_file("preprocessing/context/llm_context_builder.py", "prompt/context/builder.py")
        self.move_file(
            "preprocessing/context/static_data_loader.py", "prompt/context/static_loader.py"
        )
        self.move_file(
            "preprocessing/context/context_scope_processor.py", "prompt/context/scope.py"
        )

    def phase_8_output(self):
        """Move file_io + response_processing -> output/."""
        migrations = {
            k: v
            for k, v in FILE_MIGRATIONS.items()
            if k.startswith("file_io/") or k.startswith("response_processing/")
        }
        for old, new in migrations.items():
            self.move_file(old, new)

    def phase_9_llm(self):
        """Move llm_invocation -> llm/."""
        migrations = {k: v for k, v in FILE_MIGRATIONS.items() if k.startswith("llm_invocation/")}
        for old, new in migrations.items():
            self.move_file(old, new)

    def phase_10_config(self):
        """Move configuration + state_management -> config/."""
        migrations = {
            k: v
            for k, v in FILE_MIGRATIONS.items()
            if k.startswith("configuration/") or k.startswith("state_management/")
        }
        # Filter out lineage_mixin (already moved in phase 6)
        migrations = {k: v for k, v in migrations.items() if "lineage_mixin" not in k}
        for old, new in migrations.items():
            self.move_file(old, new)

        # Move DI files from orchestration
        self.move_file("orchestration/dependency_injection.py", "config/di/container.py")
        self.move_file("orchestration/application_container.py", "config/di/application.py")

    def phase_11_validation(self):
        """Move validation (mostly renames)."""
        migrations = {k: v for k, v in FILE_MIGRATIONS.items() if k.startswith("validation/")}
        for old, new in migrations.items():
            self.move_file(old, new)

    def phase_12_workflow(self):
        """Move orchestration -> workflow/."""
        migrations = {k: v for k, v in FILE_MIGRATIONS.items() if k.startswith("orchestration/")}
        # Filter out DI files (moved in phase 10)
        migrations = {
            k: v
            for k, v in migrations.items()
            if "dependency_injection" not in k and "application_container" not in k
        }
        for old, new in migrations.items():
            self.move_file(old, new)

        # Move services
        self.move_file("services/workflow_schema_service.py", "workflow/schema_service.py")

    def phase_13_cli(self):
        """Move cli (reorganize commands)."""
        migrations = {k: v for k, v in FILE_MIGRATIONS.items() if k.startswith("cli/")}
        for old, new in migrations.items():
            self.move_file(old, new)

    def phase_14_tooling(self):
        """Move lsp + docs -> tooling/."""
        migrations = {
            k: v
            for k, v in FILE_MIGRATIONS.items()
            if k.startswith("lsp/") or k.startswith("docs/")
        }
        for old, new in migrations.items():
            self.move_file(old, new)

    def phase_15_imports(self):
        """Update all imports."""
        self.update_all_imports()

    def phase_16_cleanup(self):
        """Remove old empty directories."""
        old_dirs = [
            "orchestration",
            "core",
            "configuration",
            "state_management",
            "utilities",
            "shared",
            "input_loading",
            "preprocessing",
            "prompt_generation",
            "file_io",
            "response_processing",
            "llm_invocation",
            "lsp",
            "docs",
            "services",
        ]

        for dir_name in old_dirs:
            dir_path = self.agent_actions / dir_name
            if dir_path.exists():
                if self.dry_run:
                    self.log(f"Would remove old directory: {dir_name}", "ACTION")
                else:
                    try:
                        shutil.rmtree(dir_path)
                        self.log(f"Removed: {dir_name}", "ACTION")
                    except Exception as e:
                        self.log(f"Could not remove {dir_name}: {e}", "ERROR")

    def run_all(self):
        """Run all phases in order."""
        for phase in range(17):
            self.run_phase(phase)

    def print_summary(self):
        """Print migration summary."""
        print(f"\n{'=' * 60}")
        print("Migration Summary")
        print(f"{'=' * 60}")
        print(f"Files moved: {self.files_moved}")
        print(f"Imports updated: {self.imports_updated}")
        if self.errors:
            print(f"Errors: {len(self.errors)}")
            for error in self.errors:
                print(f"  - {error}")
        if self.dry_run:
            print("\n[DRY RUN - No changes made]")


def main():
    parser = argparse.ArgumentParser(description="Migrate agent_actions to domain-driven structure")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    parser.add_argument("--phase", type=int, help="Run specific phase (0-16)")
    parser.add_argument("--all", action="store_true", help="Run all phases")
    parser.add_argument("--update-imports", action="store_true", help="Only update imports")

    args = parser.parse_args()

    # Find project root
    script_dir = Path(__file__).parent
    base_path = script_dir.parent.parent  # scripts/restructure -> project root

    if not (base_path / "agent_actions").exists():
        print(f"Error: agent_actions not found at {base_path}")
        sys.exit(1)

    print(f"Project root: {base_path}")
    print(f"Dry run: {args.dry_run}")

    runner = MigrationRunner(base_path, dry_run=args.dry_run)

    if args.update_imports:
        runner.update_all_imports()
    elif args.phase is not None:
        runner.run_phase(args.phase)
    elif args.all:
        runner.run_all()
    else:
        # Default: show help
        parser.print_help()
        print("\n\nAvailable phases:")
        print("  0: Create directory structure")
        print("  1: Move errors module")
        print("  2: Move utils module")
        print("  3: Move logging module")
        print("  4: Move models module")
        print("  5: Move input domain")
        print("  6: Move processing domain")
        print("  7: Move prompt domain")
        print("  8: Move output domain")
        print("  9: Move llm domain")
        print("  10: Move config domain")
        print("  11: Move validation domain")
        print("  12: Move workflow domain")
        print("  13: Move cli domain")
        print("  14: Move tooling")
        print("  15: Update imports")
        print("  16: Cleanup old directories")
        return

    runner.print_summary()


if __name__ == "__main__":
    main()
