#!/usr/bin/env python3
"""
Generate comprehensive API documentation using pdoc.

This script generates HTML documentation for all agent_actions modules.
"""

import subprocess
import shutil
import os
from pathlib import Path


def main():
    """Generate API documentation."""
    # Change to repository root (parent of docs_scripts)
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    os.chdir(repo_root)

    print("Generating API documentation with pdoc...")
    print(f"Working directory: {os.getcwd()}")

    # Define output directory
    output_dir = Path("pdoc_docs")

    # Remove old documentation
    if output_dir.exists():
        print(f"Removing old documentation: {output_dir}")
        shutil.rmtree(output_dir)

    # Define modules to document
    modules = [
        "agent_actions",
        "agent_actions.agents",
        "agent_actions.core",
        "agent_actions.integrations",
        "agent_actions.tasks",
        "agent_actions.cli",
    ]

    # Generate documentation
    cmd = ["pdoc"] + modules + ["-o", str(output_dir)]

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)

        # Print warnings if any
        if result.stderr:
            print("\nWarnings during generation:")
            print(result.stderr)

        # Count generated files
        html_files = list(output_dir.glob("**/*.html"))

        print(f"\n✅ Documentation generated successfully!")
        print(f"📁 Location: {output_dir.absolute()}")
        print(f"📄 Total HTML files: {len(html_files)}")
        print(f"\nTo view: open {output_dir}/index.html")

    except subprocess.CalledProcessError as e:
        print(f"❌ Error generating documentation: {e}")
        if e.stderr:
            print(e.stderr)
        return 1
    except FileNotFoundError:
        print("❌ pdoc not found. Install it with: pip install pdoc")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
