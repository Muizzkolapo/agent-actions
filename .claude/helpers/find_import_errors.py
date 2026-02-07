#!/usr/bin/env python3
"""
Find Import Errors - Systematically identify all import errors in test files.

Runs pytest collection on each test file and extracts the specific import errors.
"""

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import re


def collect_test_file(test_file: Path) -> Tuple[bool, str]:
    """
    Try to collect a single test file.

    Returns:
        (success, error_message)
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "--co", "-q"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Check if there was an error
        if result.returncode != 0 and (
            "ModuleNotFoundError" in result.stdout or "ImportError" in result.stdout
        ):
            return (False, result.stdout)

        return (True, "")

    except subprocess.TimeoutExpired:
        return (False, "Timeout")
    except Exception as e:
        return (False, str(e))


def extract_missing_module(error_output: str) -> str:
    """
    Extract the missing module name from error output.

    Returns:
        Module name or empty string
    """
    # Look for "ModuleNotFoundError: No module named 'X'"
    match = re.search(r"ModuleNotFoundError: No module named '([^']+)'", error_output)
    if match:
        return match.group(1)

    # Look for "ImportError: cannot import name 'X' from 'Y'"
    match = re.search(r"ImportError: cannot import name '([^']+)' from '([^']+)'", error_output)
    if match:
        return f"{match.group(2)}.{match.group(1)}"

    # Look for "ImportError: ..." with module context
    match = re.search(r"from ([^\s]+) import", error_output)
    if match:
        return match.group(1)

    return ""


def find_all_import_errors() -> Dict[str, List[str]]:
    """
    Find all import errors in test files.

    Returns:
        {missing_module: [test_files]}
    """
    errors_by_module = {}

    # Find all test files
    test_files = list(Path("tests").rglob("test_*.py"))

    print(f"🔍 Checking {len(test_files)} test files for import errors...\n")

    failed_count = 0

    for test_file in sorted(test_files):
        success, error = collect_test_file(test_file)

        if not success:
            failed_count += 1
            missing_module = extract_missing_module(error)

            if missing_module:
                if missing_module not in errors_by_module:
                    errors_by_module[missing_module] = []
                errors_by_module[missing_module].append(str(test_file))

                rel_path = test_file.relative_to("tests")
                print(f"❌ {rel_path}")
                print(f"   Missing: {missing_module}\n")

    print(f"\n📊 Summary:")
    print(f"   Total test files: {len(test_files)}")
    print(f"   Files with import errors: {failed_count}")
    print(f"   Unique missing modules: {len(errors_by_module)}")

    return errors_by_module


def print_grouped_errors(errors_by_module: Dict[str, List[str]]):
    """Print errors grouped by missing module."""

    print("\n" + "=" * 80)
    print("ERRORS GROUPED BY MISSING MODULE")
    print("=" * 80)

    for module in sorted(errors_by_module.keys()):
        test_files = errors_by_module[module]
        print(f"\n❌ Missing: {module}")
        print(f"   Affected test files: {len(test_files)}")
        for tf in test_files[:3]:
            print(f"   • {Path(tf).relative_to('tests')}")
        if len(test_files) > 3:
            print(f"   ... and {len(test_files) - 3} more")


def main():
    """Main entry point."""
    print("🔧 Finding all import errors in tests...\n")

    errors = find_all_import_errors()

    if errors:
        print_grouped_errors(errors)

        # Save to file
        output_file = "import_errors.txt"
        with open(output_file, "w") as f:
            f.write("Import Errors Report\n")
            f.write("=" * 80 + "\n\n")

            for module, test_files in sorted(errors.items()):
                f.write(f"Missing: {module}\n")
                f.write(f"Affected files ({len(test_files)}):\n")
                for tf in test_files:
                    f.write(f"  - {tf}\n")
                f.write("\n")

        print(f"\n📄 Detailed report saved to: {output_file}")
    else:
        print("\n✅ No import errors found!")


if __name__ == "__main__":
    main()
