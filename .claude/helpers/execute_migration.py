#!/usr/bin/env python3
"""
Execute Migration Plan - Move files according to a migration plan JSON.

Usage:
    python execute_migration.py plan_final.json --execute --backup
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def load_plan(plan_file: str) -> dict:
    """Load migration plan from JSON."""
    with open(plan_file) as f:
        return json.load(f)


def create_backup(root_path: Path):
    """Create backup of the codebase."""
    backup_path = root_path.parent / f"{root_path.name}_backup"

    if backup_path.exists():
        print(f"⚠️  Backup already exists at {backup_path}")
        response = input("Overwrite? (yes/no): ")
        if response.lower() != "yes":
            print("Using existing backup")
            return backup_path

        shutil.rmtree(backup_path)

    print(f"💾 Creating backup at {backup_path}...")
    shutil.copytree(root_path, backup_path)
    print("✅ Backup created!")

    return backup_path


def execute_migration(plan: dict, dry_run: bool = True):
    """Execute the migration plan."""
    rules = plan["rules"]

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No files will be moved\n")
    else:
        print(f"\n🚀 Executing migration of {len(rules)} files...\n")

    moved = 0
    errors = 0
    created_dirs = set()

    for rule in rules:
        source = Path(rule["source"])
        destination = Path(rule["destination"])

        try:
            if not dry_run:
                # Create destination directory
                dest_dir = destination.parent
                if dest_dir not in created_dirs:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    created_dirs.add(dest_dir)

                # Move file
                if source.exists():
                    shutil.move(str(source), str(destination))
                    moved += 1
                else:
                    print(f"   ⚠️  Source not found: {source}")
                    errors += 1
            else:
                # Dry run: just show what would happen
                if moved < 10 or moved % 20 == 0:  # Show first 10, then every 20th
                    print(f"   {source.relative_to(source.parents[3])}")
                    print(f"   → {destination.relative_to(destination.parents[3])}")
                    print()
                moved += 1

            if not dry_run and moved % 10 == 0:
                print(f"   Moved {moved}/{len(rules)} files...")

        except Exception as e:
            errors += 1
            print(f"   ❌ Error moving {source}: {e}")

    if dry_run:
        print("\n✅ Dry run complete!")
        print(f"   Would move: {moved} files")
    else:
        print("\n✅ Migration complete!")
        print(f"   Moved: {moved}")
        print(f"   Errors: {errors}")

    return moved, errors


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Execute migration plan from JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview only)
  python execute_migration.py plan_final.json

  # Execute with backup
  python execute_migration.py plan_final.json --execute --backup

  # Execute without backup (NOT RECOMMENDED)
  python execute_migration.py plan_final.json --execute
        """,
    )

    parser.add_argument("plan_file", type=str, help="Migration plan JSON file")

    parser.add_argument(
        "--execute", action="store_true", help="Execute migration (default: dry run)"
    )

    parser.add_argument("--backup", action="store_true", help="Create backup before executing")

    args = parser.parse_args()

    # Load plan
    print(f"📋 Loading migration plan from {args.plan_file}...")
    plan = load_plan(args.plan_file)

    print("\n📊 Migration Plan Summary:")
    print(f"   Files to migrate: {len(plan['rules'])}")
    print(f"   Remaining conflicts: {plan['stats']['conflicts']}")

    if plan["stats"]["conflicts"] > 0:
        print(f"\n❌ Cannot execute: {plan['stats']['conflicts']} conflicts remain!")
        print("   Resolve conflicts first, then try again.")
        sys.exit(1)

    # Create backup if requested
    if args.execute and args.backup:
        # Determine root path from first rule
        if plan["rules"]:
            root_path = Path(plan["rules"][0]["source"]).parents[1]  # agent_actions/
            create_backup(root_path)

    # Execute migration
    if args.execute:
        response = input("\n⚠️  This will move files. Continue? (yes/no): ")
        if response.lower() != "yes":
            print("Cancelled.")
            sys.exit(0)

    moved, errors = execute_migration(plan, dry_run=not args.execute)

    if args.execute and errors == 0:
        print("\n🎉 Migration successful!")
        print("\n⚠️  IMPORTANT NEXT STEPS:")
        print("   1. Fix import statements across the codebase")
        print("   2. Update __init__.py files in new directories")
        print("   3. Run tests to verify everything works")
        print("   4. Remove old empty directories")

    return 0


if __name__ == "__main__":
    sys.exit(main())
