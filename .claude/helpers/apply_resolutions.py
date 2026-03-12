#!/usr/bin/env python3
"""
Apply Conflict Resolutions - Automatically handle resolved conflicts.

This tool applies the resolutions from the conflict resolver:
1. KEEP_ONE: Updates migration plan to use chosen file
2. MERGE: Guides manual merge process
3. RENAME: Updates migration plan with renamed destinations
"""

import json
import sys
from pathlib import Path


def load_plans(migration_file: str, resolution_file: str) -> tuple:
    """Load migration and resolution plans."""
    with open(migration_file) as f:
        migration = json.load(f)
    with open(resolution_file) as f:
        resolutions = json.load(f)
    return migration, resolutions


def apply_keep_one(migration: dict, resolutions: list[dict]) -> dict:
    """
    Apply KEEP_ONE resolutions.

    Removes duplicate rules from migration plan, keeping only the chosen file.
    """
    print("\n🔵 Applying KEEP_ONE resolutions...")

    keep_one_actions = resolutions["actions"]["KEEP_ONE"]

    if not keep_one_actions:
        print("   No KEEP_ONE actions to apply")
        return migration

    updated_rules = migration["rules"].copy()
    removed_count = 0

    for action in keep_one_actions:
        dest = action["destination"]
        keep_file = action["suggestion"]["keep"]
        delete_files = action["suggestion"]["delete"]

        print(f"\n   📁 {Path(dest).name}")
        print(f"      Keeping: {Path(keep_file).parent.name}/{Path(keep_file).name}")

        # Remove rules for files to delete
        for delete_file in delete_files:
            # Find and remove rules with this source
            updated_rules = [rule for rule in updated_rules if rule["source"] != delete_file]
            removed_count += 1
            print(f"      Removed: {Path(delete_file).parent.name}/{Path(delete_file).name}")

    migration["rules"] = updated_rules
    migration["stats"]["conflicts"] -= len(keep_one_actions)

    print(f"\n   ✅ Removed {removed_count} duplicate rules")
    print(f"   ✅ Resolved {len(keep_one_actions)} KEEP_ONE conflicts")

    return migration


def generate_merge_guide(resolutions: list[dict]) -> str:
    """Generate guide for manual merge actions."""
    merge_actions = resolutions["actions"]["MERGE"]

    if not merge_actions:
        return "No MERGE actions needed"

    guide = []
    guide.append("\n" + "=" * 80)
    guide.append("📘 MANUAL MERGE GUIDE")
    guide.append("=" * 80)
    guide.append(f"\nYou need to manually merge {len(merge_actions)} file conflicts.")
    guide.append("These files are 90%+ similar but have small differences.\n")

    for i, action in enumerate(merge_actions, 1):
        dest = Path(action["destination"])
        sources = action["sources"]

        guide.append(f"\n{i}. {dest.name}")
        guide.append(f"   Destination: {dest}")
        guide.append(f"   Sources ({len(sources)}):")

        for j, src in enumerate(sources, 1):
            src_path = Path(src)
            guide.append(f"      {j}. {src_path.parent.name}/{src_path.name}")

        guide.append("\n   Similarity:")
        for comp in action["comparisons"]:
            f1 = Path(comp["file1"]).parent.name
            f2 = Path(comp["file2"]).parent.name
            sim = comp["similarity"]
            guide.append(f"      • {f1} vs {f2}: {sim:.0%}")

        guide.append("\n   💡 Next Steps:")
        guide.append(f"      1. Compare files: diff {sources[0]} {sources[1]}")
        guide.append("      2. Manually merge differences")
        guide.append("      3. Keep the merged version in one location")
        guide.append("      4. Delete the other version")

    guide.append("\n" + "=" * 80)

    return "\n".join(guide)


def apply_rename(migration: dict, resolutions: list[dict]) -> dict:
    """
    Apply RENAME resolutions.

    Updates migration plan with renamed destinations to avoid conflicts.
    """
    print("\n🔵 Applying RENAME resolutions...")

    rename_actions = resolutions["actions"]["RENAME"]

    if not rename_actions:
        print("   No RENAME actions to apply")
        return migration

    updated_rules = migration["rules"].copy()
    renamed_count = 0

    for action in rename_actions:
        dest = action["destination"]
        renames = action["suggestion"]["renames"]

        print(f"\n   📁 {Path(dest).name}")

        for rename in renames:
            old_source = rename["source"]
            new_dest = rename["suggested_dest"]

            # Find and update rule
            for rule in updated_rules:
                if rule["source"] == old_source:
                    rule["destination"] = new_dest
                    renamed_count += 1

                    src_path = Path(old_source)
                    print(f"      {src_path.parent.name}/{src_path.name}")
                    print(f"      → {Path(new_dest).name}")
                    break

    migration["rules"] = updated_rules
    migration["stats"]["conflicts"] -= len(rename_actions)

    print(f"\n   ✅ Renamed {renamed_count} destination paths")
    print(f"   ✅ Resolved {len(rename_actions)} RENAME conflicts")

    return migration


def update_conflicts(migration: dict, resolutions: dict) -> dict:
    """Remove resolved conflicts from migration plan."""
    resolved_dests = set()

    for action_type in ["KEEP_ONE", "RENAME"]:
        for action in resolutions["actions"][action_type]:
            resolved_dests.add(action["destination"])

    # Keep only unresolved conflicts
    migration["conflicts"] = [
        c for c in migration["conflicts"] if not any(dest in c for dest in resolved_dests)
    ]

    return migration


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python apply_resolutions.py migration_plan.json plan_resolutions.json")
        sys.exit(1)

    migration_file = sys.argv[1]
    resolution_file = sys.argv[2]

    print("🔧 Applying conflict resolutions...")

    # Load plans
    migration, resolutions = load_plans(migration_file, resolution_file)

    print("\n📊 Resolution Summary:")
    print(f"   KEEP_ONE: {len(resolutions['actions']['KEEP_ONE'])} conflicts")
    print(f"   MERGE: {len(resolutions['actions']['MERGE'])} conflicts")
    print(f"   RENAME: {len(resolutions['actions']['RENAME'])} conflicts")

    # Apply KEEP_ONE
    migration = apply_keep_one(migration, resolutions)

    # Apply RENAME
    migration = apply_rename(migration, resolutions)

    # Update conflicts list
    migration = update_conflicts(migration, resolutions)

    # Save updated migration plan
    output_file = migration_file.replace(".json", "_updated.json")
    with open(output_file, "w") as f:
        json.dump(migration, f, indent=2)

    print(f"\n✅ Updated migration plan saved to: {output_file}")

    # Generate merge guide
    merge_guide = generate_merge_guide(resolutions)

    if resolutions["actions"]["MERGE"]:
        merge_file = "merge_guide.txt"
        with open(merge_file, "w") as f:
            f.write(merge_guide)

        print(f"📘 Merge guide saved to: {merge_file}")
        print(merge_guide)

    # Final summary
    print("\n" + "=" * 80)
    print("📊 FINAL STATUS")
    print("=" * 80)
    print(f"Original conflicts: {resolutions['total_conflicts']}")
    print(
        f"Auto-resolved: {len(resolutions['actions']['KEEP_ONE']) + len(resolutions['actions']['RENAME'])}"
    )
    print(f"Remaining (manual merge): {len(resolutions['actions']['MERGE'])}")
    print(f"Updated migration plan: {output_file}")

    if resolutions["actions"]["MERGE"]:
        print(
            f"\n⚠️  NEXT STEP: Review merge_guide.txt and manually merge {len(resolutions['actions']['MERGE'])} files"
        )
    else:
        print("\n✅ All conflicts resolved! Ready to execute migration:")
        print("   python .claude/helpers/stage_refactorer.py agent_actions/ --execute --backup")


if __name__ == "__main__":
    main()
