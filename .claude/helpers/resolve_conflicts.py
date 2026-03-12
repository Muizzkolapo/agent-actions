#!/usr/bin/env python3
"""
Conflict Resolver - Handle duplicate file conflicts during stage refactoring.

When multiple files map to the same destination, this tool helps:
1. Compare files to detect duplicates
2. Rename conflicting files
3. Merge similar files
4. Generate resolution plan
"""

import difflib
import hashlib
import json
import sys
from pathlib import Path


def load_plan(plan_file: str) -> dict:
    """Load migration plan JSON."""
    with open(plan_file) as f:
        return json.load(f)


def get_file_hash(file_path: Path) -> str:
    """Get MD5 hash of file."""
    if not file_path.exists():
        return ""
    return hashlib.md5(file_path.read_bytes()).hexdigest()


def compare_files(file1: Path, file2: Path) -> tuple[bool, float]:
    """
    Compare two files.

    Returns:
        (identical, similarity_ratio)
    """
    if not file1.exists() or not file2.exists():
        return (False, 0.0)

    hash1 = get_file_hash(file1)
    hash2 = get_file_hash(file2)

    if hash1 == hash2:
        return (True, 1.0)

    # Compare content similarity
    content1 = file1.read_text(errors="ignore").splitlines()
    content2 = file2.read_text(errors="ignore").splitlines()

    matcher = difflib.SequenceMatcher(None, content1, content2)
    ratio = matcher.ratio()

    return (False, ratio)


def analyze_conflicts(plan: dict) -> dict[str, list[dict]]:
    """Analyze conflicts and suggest resolutions."""
    conflicts_by_dest = {}

    # Group conflicts
    for conflict in plan.get("conflicts", []):
        # Parse conflict string
        # Format: "Conflict at <dest>: <source1>, <source2>, ..."
        if "Conflict at" not in conflict:
            continue

        parts = conflict.split(": ")
        if len(parts) < 2:
            continue

        dest = parts[0].replace("Conflict at ", "")
        sources = [s.strip() for s in parts[1].split(", ")]

        conflicts_by_dest[dest] = {"destination": dest, "sources": sources, "resolutions": []}

    return conflicts_by_dest


def suggest_resolutions(conflicts: dict[str, list[dict]]) -> list[dict]:
    """Suggest resolutions for each conflict."""
    resolutions = []

    for dest, info in conflicts.items():
        sources = [Path(s) for s in info["sources"]]
        dest_path = Path(dest)

        print(f"\n🔴 Conflict: {dest_path.name}")
        print(f"   Destination: {dest}")
        print(f"   Sources ({len(sources)}):")

        # Compare all pairs
        comparisons = []
        for i, src1 in enumerate(sources):
            print(f"      {i + 1}. {src1}")
            for src2 in sources[i + 1 :]:
                identical, similarity = compare_files(src1, src2)
                comparisons.append(
                    {"file1": src1, "file2": src2, "identical": identical, "similarity": similarity}
                )

        # Suggest resolution
        if comparisons:
            max_similarity = max(c["similarity"] for c in comparisons)
            all_identical = all(c["identical"] for c in comparisons)

            if all_identical:
                suggestion = {
                    "type": "KEEP_ONE",
                    "action": f"Keep {sources[0]}, delete others (all identical)",
                    "keep": str(sources[0]),
                    "delete": [str(s) for s in sources[1:]],
                }
            elif max_similarity > 0.9:
                suggestion = {
                    "type": "MERGE",
                    "action": f"Files are {max_similarity:.0%} similar - review and merge",
                    "files": [str(s) for s in sources],
                }
            else:
                suggestion = {
                    "type": "RENAME",
                    "action": "Files are different - rename to preserve both",
                    "renames": [
                        {
                            "source": str(src),
                            "suggested_dest": str(
                                dest_path.parent / f"{src.parent.name}_{dest_path.name}"
                            ),
                        }
                        for src in sources
                    ],
                }

            print(f"   Suggestion: {suggestion['action']}")

            # Convert Path objects to strings for JSON serialization
            serializable_comparisons = []
            for comp in comparisons:
                serializable_comparisons.append(
                    {
                        "file1": str(comp["file1"]),
                        "file2": str(comp["file2"]),
                        "identical": comp["identical"],
                        "similarity": comp["similarity"],
                    }
                )

            resolutions.append(
                {
                    "destination": dest,
                    "sources": [str(s) for s in sources],
                    "suggestion": suggestion,
                    "comparisons": serializable_comparisons,
                }
            )

    return resolutions


def generate_resolution_plan(resolutions: list[dict], output_file: str):
    """Generate detailed resolution plan."""
    plan = {
        "total_conflicts": len(resolutions),
        "resolutions": resolutions,
        "actions": {"KEEP_ONE": [], "MERGE": [], "RENAME": []},
    }

    # Group by action type
    for res in resolutions:
        action_type = res["suggestion"]["type"]
        plan["actions"][action_type].append(res)

    with open(output_file, "w") as f:
        json.dump(plan, f, indent=2)

    print(f"\n📄 Resolution plan saved to: {output_file}")

    # Print summary
    print("\n📊 Conflict Resolution Summary:")
    print(f"   Total conflicts: {len(resolutions)}")
    print(f"   Keep one (identical files): {len(plan['actions']['KEEP_ONE'])}")
    print(f"   Merge (similar files): {len(plan['actions']['MERGE'])}")
    print(f"   Rename (different files): {len(plan['actions']['RENAME'])}")


def print_detailed_report(resolutions: list[dict]):
    """Print detailed conflict report."""
    print("\n" + "=" * 80)
    print("DETAILED CONFLICT ANALYSIS")
    print("=" * 80)

    for res in resolutions:
        dest = Path(res["destination"])
        suggestion = res["suggestion"]

        print(f"\n📁 {dest.name}")
        print(f"   Destination: {dest}")
        print(f"   Sources: {len(res['sources'])}")

        for i, src in enumerate(res["sources"], 1):
            print(f"      {i}. {src}")

        print(f"\n   💡 Suggested Action: {suggestion['type']}")
        print(f"      {suggestion['action']}")

        if suggestion["type"] == "RENAME":
            print("\n      Rename suggestions:")
            for rename in suggestion["renames"]:
                src = Path(rename["source"])
                new_dest = rename["suggested_dest"]
                print(f"         {src.name}")
                print(f"         → {new_dest}")

        # Show similarity scores
        if res["comparisons"]:
            print("\n      Similarity scores:")
            for comp in res["comparisons"]:
                f1 = Path(comp["file1"]).parent.name
                f2 = Path(comp["file2"]).parent.name
                sim = comp["similarity"]
                status = "✅ IDENTICAL" if comp["identical"] else f"{sim:.0%} similar"
                print(f"         {f1} vs {f2}: {status}")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python resolve_conflicts.py migration_plan.json")
        sys.exit(1)

    plan_file = sys.argv[1]
    output_file = plan_file.replace(".json", "_resolutions.json")

    print("🔍 Analyzing conflicts from migration plan...")

    # Load plan
    plan = load_plan(plan_file)

    # Analyze conflicts
    conflicts = analyze_conflicts(plan)

    if not conflicts:
        print("✅ No conflicts found!")
        sys.exit(0)

    print(f"\n📊 Found {len(conflicts)} conflicts")

    # Suggest resolutions
    resolutions = suggest_resolutions(conflicts)

    # Generate resolution plan
    generate_resolution_plan(resolutions, output_file)

    # Print detailed report
    print_detailed_report(resolutions)

    print("\n" + "=" * 80)
    print("NEXT STEPS:")
    print("=" * 80)
    print("1. Review the resolution plan: " + output_file)
    print("2. For KEEP_ONE: Delete duplicate files manually")
    print("3. For MERGE: Review and merge files manually")
    print("4. For RENAME: Update migration plan with new names")
    print("5. Re-run stage refactorer after resolving conflicts")


if __name__ == "__main__":
    main()
