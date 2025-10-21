#!/bin/bash

# Generate comprehensive API documentation using pdoc
# This script generates HTML documentation for all agent_actions modules

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Change to repository root (parent of docs_scripts)
cd "$SCRIPT_DIR/.."

echo "Generating API documentation with pdoc..."
echo "Working directory: $(pwd)"

# Remove old documentation
rm -rf pdoc_docs

# Generate documentation for all main modules
pdoc agent_actions \
     agent_actions.agents \
     agent_actions.core \
     agent_actions.integrations \
     agent_actions.tasks \
     agent_actions.cli \
     -o pdoc_docs

echo "Documentation generated in: pdoc_docs/"
echo "Open pdoc_docs/index.html in your browser to view the docs"
echo ""
echo "Total HTML files generated: $(find pdoc_docs -name '*.html' | wc -l)"
