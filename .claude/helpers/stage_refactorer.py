#!/usr/bin/env python3
"""
Stage Refactorer - Reorganize codebase by processing stages.

This tool helps migrate from architectural layers (agents/, core/, integrations/)
to processing stages (01_input_loading/, 02_preprocessing/, ... 12_utilities/).

Key feature: Stage 5 (LLM Invocation) has nested structure:
  05_llm_invocation/
    ├── realtime/    # Real-time processing
    └── batch/       # Batch processing
"""

import os
import sys
import json
import shutil
import argparse
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class MigrationRule:
    """Rule for migrating a file from old to new location."""
    source: Path
    destination: Path
    stage: str
    confidence: str  # HIGH, MEDIUM, LOW
    reason: str


@dataclass
class RefactoringPlan:
    """Complete refactoring plan."""
    rules: List[MigrationRule] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


class StageRefactorer:
    """Refactor codebase to stage-based structure."""

    # New stage-based structure (no numbering)
    STAGE_STRUCTURE = {
        "input_loading": {
            "name": "Input Loading & Extraction",
            "patterns": ["extractor", "loader", "reader", "load", "extract", "read"],
            "exclude_patterns": ["staging_loader"]  # Goes to preprocessing
        },
        "preprocessing": {
            "name": "Pre-Processing & Data Preparation",
            "patterns": ["staging", "filter", "chunk", "transform", "preprocess"],
            "exclude_patterns": []
        },
        "validation": {
            "name": "Pre-LLM Validation",
            "patterns": ["validator", "validation", "validate", "check"],
            "exclude_patterns": []
        },
        "prompt_generation": {
            "name": "Prompt Generation & Context Building",
            "patterns": ["generator", "prompt", "template", "render"],
            "exclude_patterns": ["target_generator"]  # Goes to postprocessing
        },
        "llm_invocation": {
            "name": "LLM Invocation & Provider Integration",
            "patterns": ["provider", "vendor", "handler", "llm", "model", "agent_builder"],
            "exclude_patterns": [],
            "subfolders": {
                "realtime": ["provider", "vendor", "handler", "agent_builder", "streaming"],
                "batch": ["batch", "queue", "poll"]
            }
        },
        "response_processing": {
            "name": "Response Processing & Transformation",
            "patterns": ["response", "interceptor", "strategy", "parse"],
            "exclude_patterns": []
        },
        "postprocessing": {
            "name": "Post-Processing & Output Generation",
            "patterns": ["target", "output", "writer", "write", "post"],
            "exclude_patterns": []
        },
        "orchestration": {
            "name": "Workflow Orchestration & Execution",
            "patterns": ["workflow", "runtime", "runner", "orchestrat", "execut", "graph"],
            "exclude_patterns": []
        },
        "state_management": {
            "name": "State Management & Context",
            "patterns": ["artifact", "lineage", "context", "state", "signature"],
            "exclude_patterns": []
        },
        "configuration": {
            "name": "Configuration & Schema Management",
            "patterns": ["parser", "config", "schema", "contract", "migration", "bootstrap"],
            "exclude_patterns": []
        },
        "cli": {
            "name": "CLI & User Interface",
            "patterns": ["cli", "command", "task", "main"],
            "exclude_patterns": []
        },
        "utilities": {
            "name": "Utilities & Common Functions",
            "patterns": ["util", "helper", "common", "constant"],
            "exclude_patterns": []
        },
        "shared": {
            "name": "Shared / Cross-Cutting Concerns",
            "patterns": ["base", "exception", "type", "interface", "contract"],
            "exclude_patterns": []
        }
    }

    def __init__(self, root_path: str, dry_run: bool = True):
        """Initialize refactorer."""
        self.root_path = Path(root_path).resolve()
        self.dry_run = dry_run
        self.plan = RefactoringPlan()

    def classify_file(self, file_path: Path) -> Tuple[Optional[str], Optional[str], str]:
        """
        Classify file into a stage.

        Returns:
            (stage, subfolder, confidence)
        """
        file_str = str(file_path).lower()
        file_name = file_path.name.lower()

        # Special case: batch files go to llm_invocation/batch/
        if "batch" in file_str and "batch" in file_name:
            # batch_validator → validation/batch_validator.py
            if "validat" in file_name:
                return ("validation", None, "HIGH")
            # batch_service, batch.py → llm_invocation/batch/
            return ("llm_invocation", "batch", "HIGH")

        # Check each stage
        for stage, info in self.STAGE_STRUCTURE.items():
            # Check exclusions first
            if any(excl in file_str for excl in info.get("exclude_patterns", [])):
                continue

            # Check patterns
            for pattern in info["patterns"]:
                if pattern in file_str or pattern in file_name:
                    # Check if stage has subfolders (e.g., 05_llm_invocation)
                    subfolders = info.get("subfolders", {})
                    if subfolders:
                        # Determine subfolder
                        for subfolder, sub_patterns in subfolders.items():
                            if any(sp in file_str for sp in sub_patterns):
                                return (stage, subfolder, "HIGH")
                        # Default to "realtime" if no specific match
                        if stage == "llm_invocation":
                            return (stage, "realtime", "MEDIUM")

                    return (stage, None, "HIGH")

        # Default to shared if it's a base class
        if "base" in file_name or file_path.parent.name == "base":
            return ("shared", "base", "MEDIUM")

        # Unknown
        return (None, None, "LOW")

    def build_migration_plan(self):
        """Build complete migration plan."""
        print(f"🔍 Scanning {self.root_path} for files to migrate...")

        total_files = 0
        classified_files = 0

        for root, dirs, files in os.walk(self.root_path):
            # Skip already processed stage directories and pycache
            stage_dirs = list(self.STAGE_STRUCTURE.keys())
            dirs[:] = [d for d in dirs if d not in stage_dirs and d != '__pycache__']

            root_path = Path(root)

            for file_name in files:
                if not file_name.endswith('.py') or file_name.startswith('.'):
                    continue

                source_file = root_path / file_name
                relative_path = source_file.relative_to(self.root_path)
                total_files += 1

                # Classify
                stage, subfolder, confidence = self.classify_file(source_file)

                if stage:
                    classified_files += 1

                    # Build destination path
                    if subfolder:
                        dest_dir = self.root_path / stage / subfolder
                    else:
                        dest_dir = self.root_path / stage

                    # Preserve some directory structure
                    # e.g., providers/openai/provider.py → realtime/providers/openai/provider.py
                    if "providers" in str(relative_path):
                        # Extract provider structure
                        parts = relative_path.parts
                        if "providers" in parts:
                            idx = parts.index("providers")
                            provider_structure = Path(*parts[idx:])
                            dest_file = dest_dir / provider_structure
                        else:
                            dest_file = dest_dir / file_name
                    else:
                        dest_file = dest_dir / file_name

                    reason = f"Matched patterns: {self.STAGE_STRUCTURE[stage]['patterns'][:3]}"

                    rule = MigrationRule(
                        source=source_file,
                        destination=dest_file,
                        stage=stage,
                        confidence=confidence,
                        reason=reason
                    )

                    self.plan.rules.append(rule)
                else:
                    self.plan.warnings.append(f"Unclassified: {relative_path}")

        self.plan.stats = {
            "total_files": total_files,
            "classified": classified_files,
            "unclassified": total_files - classified_files,
            "conflicts": len(self.plan.conflicts)
        }

        print(f"✅ Scanned {total_files} files")
        print(f"   Classified: {classified_files}")
        print(f"   Unclassified: {total_files - classified_files}")

    def detect_conflicts(self):
        """Detect naming conflicts in destination."""
        dest_files = defaultdict(list)

        for rule in self.plan.rules:
            dest_files[rule.destination].append(rule.source)

        for dest, sources in dest_files.items():
            if len(sources) > 1:
                self.plan.conflicts.append(
                    f"Conflict at {dest}: {', '.join(str(s) for s in sources)}"
                )

    def print_plan(self):
        """Print migration plan."""
        print("\n" + "=" * 80)
        print("📋 MIGRATION PLAN")
        print("=" * 80)

        # Group by stage
        by_stage = defaultdict(list)
        for rule in self.plan.rules:
            by_stage[rule.stage].append(rule)

        for stage in sorted(by_stage.keys()):
            rules = by_stage[stage]
            stage_name = self.STAGE_STRUCTURE[stage]["name"]
            print(f"\n{stage}/ - {stage_name}")
            print(f"   {len(rules)} files")

            # Show a few examples
            for rule in rules[:3]:
                rel_source = rule.source.relative_to(self.root_path)
                rel_dest = rule.destination.relative_to(self.root_path)
                print(f"   • {rel_source}")
                print(f"     → {rel_dest}")

            if len(rules) > 3:
                print(f"   ... and {len(rules) - 3} more")

        # Stats
        print(f"\n📊 Statistics:")
        for key, value in self.plan.stats.items():
            print(f"   {key}: {value}")

        # Warnings
        if self.plan.warnings:
            print(f"\n⚠️  Warnings ({len(self.plan.warnings)}):")
            for warning in self.plan.warnings[:5]:
                print(f"   • {warning}")
            if len(self.plan.warnings) > 5:
                print(f"   ... and {len(self.plan.warnings) - 5} more")

        # Conflicts
        if self.plan.conflicts:
            print(f"\n🔴 Conflicts ({len(self.plan.conflicts)}):")
            for conflict in self.plan.conflicts:
                print(f"   • {conflict}")

    def export_plan(self, output_file: Path):
        """Export plan as JSON."""
        plan_dict = {
            "rules": [
                {
                    "source": str(r.source),
                    "destination": str(r.destination),
                    "stage": r.stage,
                    "confidence": r.confidence,
                    "reason": r.reason
                }
                for r in self.plan.rules
            ],
            "conflicts": self.plan.conflicts,
            "warnings": self.plan.warnings,
            "stats": self.plan.stats
        }

        with open(output_file, 'w') as f:
            json.dump(plan_dict, f, indent=2)

        print(f"\n📄 Plan exported to: {output_file}")

    def execute_migration(self):
        """Execute the migration plan."""
        if self.dry_run:
            print("\n⚠️  DRY RUN MODE - No files will be moved")
            return

        print(f"\n🚀 Executing migration of {len(self.plan.rules)} files...")

        moved = 0
        errors = 0

        for rule in self.plan.rules:
            try:
                # Create destination directory
                rule.destination.parent.mkdir(parents=True, exist_ok=True)

                # Move file
                shutil.move(str(rule.source), str(rule.destination))
                moved += 1

                if moved % 10 == 0:
                    print(f"   Moved {moved}/{len(self.plan.rules)} files...")

            except Exception as e:
                errors += 1
                print(f"   ❌ Error moving {rule.source}: {e}")

        print(f"\n✅ Migration complete!")
        print(f"   Moved: {moved}")
        print(f"   Errors: {errors}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Refactor codebase to stage-based structure',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview only)
  python stage_refactorer.py agent_actions/

  # Export plan as JSON
  python stage_refactorer.py agent_actions/ --json migration_plan.json

  # Execute migration (USE WITH CAUTION!)
  python stage_refactorer.py agent_actions/ --execute

  # Execute with backup
  python stage_refactorer.py agent_actions/ --execute --backup
        """
    )

    parser.add_argument(
        'path',
        type=str,
        help='Root path to refactor'
    )

    parser.add_argument(
        '--execute',
        action='store_true',
        help='Execute migration (default: dry run)'
    )

    parser.add_argument(
        '--json',
        type=str,
        help='Export plan as JSON',
        metavar='FILE'
    )

    parser.add_argument(
        '--backup',
        action='store_true',
        help='Create backup before executing'
    )

    args = parser.parse_args()

    # Create refactorer
    refactorer = StageRefactorer(
        root_path=args.path,
        dry_run=not args.execute
    )

    # Build plan
    refactorer.build_migration_plan()
    refactorer.detect_conflicts()

    # Print plan
    refactorer.print_plan()

    # Export if requested
    if args.json:
        output_file = Path(args.json)
        refactorer.export_plan(output_file)

    # Execute if requested
    if args.execute:
        # Backup if requested
        if args.backup:
            backup_path = Path(args.path).parent / f"{Path(args.path).name}_backup"
            print(f"\n💾 Creating backup at {backup_path}...")
            shutil.copytree(args.path, backup_path)
            print("   Backup created!")

        # Confirm
        response = input("\n⚠️  This will move files. Continue? (yes/no): ")
        if response.lower() == 'yes':
            refactorer.execute_migration()
        else:
            print("   Cancelled.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
