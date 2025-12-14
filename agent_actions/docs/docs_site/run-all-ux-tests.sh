#!/bin/bash

# Run All UX Tests for Agent Actions Docs Site
# This script runs all UX audits and generates comprehensive reports

echo "🔍 Starting Complete UX Audit Suite..."
echo "======================================"
echo ""

# Check if node is installed
if ! command -v node &> /dev/null; then
    echo "❌ Error: Node.js is not installed"
    echo "Please install Node.js to run UX tests"
    exit 1
fi

# Check if server is running
echo "📡 Checking if dev server is running at http://localhost:8890..."
if ! curl -s http://localhost:8890 > /dev/null; then
    echo "⚠️  Warning: Dev server not detected at http://localhost:8890"
    echo "Please start the server before running tests"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "Running UX audits..."
echo "--------------------"
echo ""

# Run comprehensive UX audit
echo "1️⃣  Running Comprehensive UX Audit..."
node test-ux-comprehensive.js
if [ $? -eq 0 ]; then
    echo "✅ Comprehensive audit complete"
else
    echo "❌ Comprehensive audit failed"
fi
echo ""

# Run navigation analysis
echo "2️⃣  Running Navigation Analysis..."
node test-ux-navigation.js
if [ $? -eq 0 ]; then
    echo "✅ Navigation analysis complete"
else
    echo "❌ Navigation analysis failed"
fi
echo ""

echo "======================================"
echo "🎉 All UX tests completed!"
echo ""
echo "📊 Generated Reports:"
echo "  - MASTER_UX_TASKS.md (Consolidated task list)"
echo "  - UX_PRODUCTION_READINESS.md (Detailed findings)"
echo "  - UX_NAVIGATION_ANALYSIS.md (Navigation patterns)"
echo ""
echo "📸 Screenshots saved to:"
echo "  - ux-comprehensive-screenshots/"
echo ""
echo "🚀 Next Steps:"
echo "  1. Review MASTER_UX_TASKS.md"
echo "  2. Start with Phase 1 (Critical Fixes)"
echo "  3. Test changes and re-run this script"
echo ""
