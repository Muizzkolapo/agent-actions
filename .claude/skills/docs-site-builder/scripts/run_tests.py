#!/usr/bin/env python3
"""
Run Playwright browser automation tests for the documentation site.

This script runs all or specific Playwright tests to validate the
documentation site functionality.
"""

import subprocess
import sys
import glob

def main():
    # Find all test files
    test_files = glob.glob("test-*.js")

    if not test_files:
        print("❌ No test files found (test-*.js)", file=sys.stderr)
        print("Make sure you're running from the project root directory", file=sys.stderr)
        sys.exit(1)

    print("🧪 Found test files:")
    for i, test in enumerate(test_files, 1):
        print(f"  {i}. {test}")
    print()

    # Allow running specific tests or all
    if len(sys.argv) > 1:
        test_pattern = sys.argv[1]
        matching_tests = [t for t in test_files if test_pattern in t]
        if not matching_tests:
            print(f"❌ No tests matching '{test_pattern}'", file=sys.stderr)
            sys.exit(1)
        tests_to_run = matching_tests
    else:
        tests_to_run = test_files

    print(f"▶️  Running {len(tests_to_run)} test(s)...\n")

    failed_tests = []

    for test in tests_to_run:
        print(f"🔍 Running {test}...")
        try:
            subprocess.run(["node", test], check=True)
            print(f"✅ {test} passed\n")
        except subprocess.CalledProcessError:
            print(f"❌ {test} failed\n")
            failed_tests.append(test)

    # Summary
    print("\n" + "="*50)
    if failed_tests:
        print(f"❌ {len(failed_tests)} test(s) failed:")
        for test in failed_tests:
            print(f"  - {test}")
        sys.exit(1)
    else:
        print(f"✅ All {len(tests_to_run)} test(s) passed!")

if __name__ == "__main__":
    main()
