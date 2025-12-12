#!/usr/bin/env python3
"""
Start the Agent-Actions documentation development server.

This script starts the documentation site server on http://localhost:8000
with live reload for development.
"""

import subprocess
import sys
import os

def main():
    # Find the project root (where agent_actions package is)
    current_dir = os.getcwd()

    print("🚀 Starting Agent-Actions documentation server...")
    print("📍 Server will be available at http://localhost:8000")
    print("⏹  Press Ctrl+C to stop\n")

    try:
        # Start the server using Python module syntax
        subprocess.run([
            sys.executable, "-m", "agent_actions.docs.server"
        ], check=True)
    except KeyboardInterrupt:
        print("\n✅ Server stopped")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error starting server: {e}", file=sys.stderr)
        sys.exit(1)
    except ModuleNotFoundError:
        print("❌ Error: agent_actions module not found", file=sys.stderr)
        print("Make sure you're running from the project root directory", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
