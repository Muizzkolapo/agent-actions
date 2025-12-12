#!/usr/bin/env python3
"""
Generate sample documentation data (catalog.json and runs.json).

This script runs the sample data generator to create workflow catalogs
and sample execution runs for testing the documentation site.
"""

import subprocess
import sys
import os

def main():
    print("🔄 Generating sample documentation data...")
    print("📝 This will create/update catalog.json and runs.json\n")

    try:
        # Run the generate_sample_prompts.py script
        result = subprocess.run([
            sys.executable, "generate_sample_prompts.py"
        ], check=True, capture_output=True, text=True)

        # Print output
        if result.stdout:
            print(result.stdout)

        print("\n✅ Sample data generated successfully")
        print("💡 Run the server with serve.py to view the documentation")

    except subprocess.CalledProcessError as e:
        print(f"❌ Error generating data: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("❌ Error: generate_sample_prompts.py not found", file=sys.stderr)
        print("Make sure you're running from the project root directory", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
