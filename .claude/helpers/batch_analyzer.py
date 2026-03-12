#!/usr/bin/env python3
"""
Batch code analyzer for reviewing multiple modules.

Scans a directory and generates a prioritized summary report.
"""

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileAnalysis:
    """Analysis results for a single file."""

    file_path: Path
    complexity_score: int = 0
    maintainability_index: float = 0.0
    loc: int = 0
    violations_count: int = 0
    violations_by_severity: dict[str, int] = field(default_factory=dict)
    violations_details: list[dict] = field(default_factory=list)  # NEW: actual violations
    dead_code_count: int = 0
    dead_code_details: list[str] = field(default_factory=list)  # NEW: actual dead code items
    high_complexity_functions: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # NEW: what this file imports
    imported_by: list[str] = field(default_factory=list)  # NEW: what files import this


def analyze_file(file_path: Path) -> FileAnalysis:
    """Analyze a single Python file."""
    result = FileAnalysis(file_path=file_path)

    # Radon complexity
    try:
        cmd = subprocess.run(
            ["radon", "cc", str(file_path), "-j"], capture_output=True, text=True, timeout=10
        )
        if cmd.returncode == 0 and cmd.stdout:
            data = json.loads(cmd.stdout)
            file_key = str(file_path)
            if file_key in data:
                for item in data[file_key]:
                    cc = item.get("complexity", 0)
                    result.complexity_score += cc
                    if cc > 10:  # Flag high complexity
                        result.high_complexity_functions.append(
                            f"{item.get('name', 'Unknown')} (CC={cc})"
                        )
    except Exception:
        pass

    # Radon maintainability
    try:
        cmd = subprocess.run(
            ["radon", "mi", str(file_path), "-j"], capture_output=True, text=True, timeout=10
        )
        if cmd.returncode == 0 and cmd.stdout:
            data = json.loads(cmd.stdout)
            file_key = str(file_path)
            if file_key in data:
                result.maintainability_index = data[file_key].get("mi", 0)
    except Exception:
        pass

    # Radon raw metrics
    try:
        cmd = subprocess.run(
            ["radon", "raw", str(file_path), "-j"], capture_output=True, text=True, timeout=10
        )
        if cmd.returncode == 0 and cmd.stdout:
            data = json.loads(cmd.stdout)
            file_key = str(file_path)
            if file_key in data:
                result.loc = data[file_key].get("loc", 0)
    except Exception:
        pass

    # Prospector violations
    try:
        cmd = subprocess.run(
            ["prospector", str(file_path), "--output-format", "json", "--no-autodetect"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if cmd.returncode in [0, 1] and cmd.stdout:
            data = json.loads(cmd.stdout)
            if "messages" in data:
                messages = data["messages"]
                result.violations_count = len(messages)
                for msg in messages:
                    severity = msg.get("severity", "unknown")
                    result.violations_by_severity[severity] = (
                        result.violations_by_severity.get(severity, 0) + 1
                    )
                    # Store actual violation details
                    result.violations_details.append(
                        {
                            "line": msg.get("location", {}).get("line", 0),
                            "source": msg.get("source", "unknown"),
                            "code": msg.get("code", ""),
                            "message": msg.get("message", ""),
                            "severity": severity,
                        }
                    )
    except Exception:
        pass

    # Vulture dead code
    try:
        cmd = subprocess.run(
            ["vulture", str(file_path)], capture_output=True, text=True, timeout=10
        )
        if cmd.stdout:
            lines = [l for l in cmd.stdout.strip().split("\n") if l.strip()]
            result.dead_code_count = len(lines)
            result.dead_code_details = lines  # Store actual findings

    except Exception:
        pass

    # Parse imports using AST
    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        import ast

        tree = ast.parse(source, filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result.imports.append(node.module)
    except Exception:
        pass

    return result


def build_dependency_graph(analyses: list[FileAnalysis]) -> None:
    """Build cross-reference of imports (what files import what)."""
    # Create a mapping of module names to file paths
    module_to_file = {}
    for analysis in analyses:
        # Extract module name from file path
        # e.g., agent_actions/agents/base/agent_builder.py -> agent_actions.agents.base.agent_builder
        parts = analysis.file_path.parts
        if "agent_actions" in parts:
            start_idx = parts.index("agent_actions")
            module_parts = parts[start_idx:]
            if module_parts[-1].endswith(".py"):
                module_parts = list(module_parts[:-1]) + [module_parts[-1][:-3]]
            module_name = ".".join(module_parts)
            module_to_file[module_name] = analysis.file_path

    # Now build imported_by relationships
    for analysis in analyses:
        for imp in analysis.imports:
            # Find which file this import corresponds to
            for module_name, file_path in module_to_file.items():
                if imp in module_name or module_name.startswith(imp):
                    # Find the analysis for that file and add this file as a dependent
                    for target_analysis in analyses:
                        if target_analysis.file_path == file_path:
                            rel_path = str(analysis.file_path)
                            if rel_path not in target_analysis.imported_by:
                                target_analysis.imported_by.append(rel_path)
                            break


def generate_summary_report(analyses: list[FileAnalysis], directory: Path) -> str:
    """Generate a summary report from multiple file analyses."""
    lines = []

    lines.append("═" * 100)
    lines.append("📊 BATCH CODE ANALYSIS SUMMARY REPORT")
    lines.append("═" * 100)
    lines.append(f"Directory: {directory}")
    lines.append(f"Files Analyzed: {len(analyses)}")
    lines.append("")

    # Overall statistics
    total_loc = sum(a.loc for a in analyses)
    total_violations = sum(a.violations_count for a in analyses)
    total_dead_code = sum(a.dead_code_count for a in analyses)
    avg_complexity = sum(a.complexity_score for a in analyses) / len(analyses) if analyses else 0
    avg_maintainability = (
        sum(a.maintainability_index for a in analyses) / len(analyses) if analyses else 0
    )

    lines.append("─" * 100)
    lines.append("📈 OVERALL STATISTICS")
    lines.append("─" * 100)
    lines.append(f"  Total Lines of Code: {total_loc:,}")
    lines.append(f"  Total Violations: {total_violations}")
    lines.append(f"  Total Dead Code Findings: {total_dead_code}")
    lines.append(f"  Average Complexity Score: {avg_complexity:.1f}")
    lines.append(f"  Average Maintainability Index: {avg_maintainability:.1f}")
    lines.append("")

    # Top 10 most complex files
    lines.append("─" * 100)
    lines.append("🔥 TOP 10 MOST COMPLEX FILES (Highest Complexity Score)")
    lines.append("─" * 100)
    sorted_by_complexity = sorted(analyses, key=lambda a: a.complexity_score, reverse=True)[:10]
    for i, analysis in enumerate(sorted_by_complexity, 1):
        rel_path = analysis.file_path.relative_to(directory.parent)
        lines.append(f"  {i}. {rel_path}")
        lines.append(
            f"     Complexity: {analysis.complexity_score}, MI: {analysis.maintainability_index:.1f}, LOC: {analysis.loc}"
        )
        if analysis.high_complexity_functions:
            lines.append(
                f"     High complexity functions: {', '.join(analysis.high_complexity_functions[:3])}"
            )
    lines.append("")

    # Top 10 files with most violations
    lines.append("─" * 100)
    lines.append("⚠️  TOP 10 FILES WITH MOST VIOLATIONS")
    lines.append("─" * 100)
    sorted_by_violations = sorted(analyses, key=lambda a: a.violations_count, reverse=True)[:10]
    for i, analysis in enumerate(sorted_by_violations, 1):
        if analysis.violations_count > 0:
            rel_path = analysis.file_path.relative_to(directory.parent)
            lines.append(f"  {i}. {rel_path}")
            # Build the violations line
            viol_line = f"     Violations: {analysis.violations_count}"
            if analysis.violations_by_severity:
                sev_str = ", ".join(
                    [f"{k}: {v}" for k, v in analysis.violations_by_severity.items()]
                )
                viol_line += f" ({sev_str})"
            lines.append(viol_line)
    lines.append("")

    # Lowest maintainability
    lines.append("─" * 100)
    lines.append("📉 TOP 10 LOWEST MAINTAINABILITY INDEX (Needs Refactoring)")
    lines.append("─" * 100)
    sorted_by_mi = sorted(
        [a for a in analyses if a.maintainability_index > 0], key=lambda a: a.maintainability_index
    )[:10]
    for i, analysis in enumerate(sorted_by_mi, 1):
        rel_path = analysis.file_path.relative_to(directory.parent)
        mi_rank = (
            "A"
            if analysis.maintainability_index >= 20
            else "B"
            if analysis.maintainability_index >= 10
            else "C"
        )
        lines.append(f"  {i}. {rel_path}")
        lines.append(
            f"     MI: {analysis.maintainability_index:.1f} (Rank: {mi_rank}), Complexity: {analysis.complexity_score}"
        )
    lines.append("")

    # Files with dead code
    lines.append("─" * 100)
    lines.append("💀 TOP 10 FILES WITH MOST DEAD CODE")
    lines.append("─" * 100)
    sorted_by_dead = sorted(
        [a for a in analyses if a.dead_code_count > 0],
        key=lambda a: a.dead_code_count,
        reverse=True,
    )[:10]
    if sorted_by_dead:
        for i, analysis in enumerate(sorted_by_dead, 1):
            rel_path = analysis.file_path.relative_to(directory.parent)
            lines.append(f"  {i}. {rel_path}")
            lines.append(f"     Dead code findings: {analysis.dead_code_count}")
    else:
        lines.append("  ✅ No dead code detected!")
    lines.append("")

    # Detailed analysis of top problem files
    lines.append("─" * 100)
    lines.append("🔍 DETAILED ANALYSIS - TOP PROBLEM FILES")
    lines.append("─" * 100)
    lines.append("")

    # Get top 5 files by violations for detailed view
    top_violation_files = sorted(
        [a for a in analyses if a.violations_count > 0],
        key=lambda a: a.violations_count,
        reverse=True,
    )[:5]

    for analysis in top_violation_files:
        rel_path = analysis.file_path.relative_to(directory.parent)
        lines.append(f"📄 {rel_path}")
        lines.append(
            f"   Violations: {analysis.violations_count}, Complexity: {analysis.complexity_score}, "
            f"MI: {analysis.maintainability_index:.1f}, LOC: {analysis.loc}"
        )

        # Show downstream impact
        if analysis.imported_by:
            lines.append(
                f"   ⚠️  Downstream Impact: {len(analysis.imported_by)} files depend on this"
            )
            lines.append(
                f"      Used by: {', '.join([Path(p).name for p in analysis.imported_by[:3]])}"
                + (
                    f" (+{len(analysis.imported_by) - 3} more)"
                    if len(analysis.imported_by) > 3
                    else ""
                )
            )

        # Show sample violations
        if analysis.violations_details:
            lines.append("   Sample violations:")
            # Group by severity and show top 3
            by_severity = {}
            for v in analysis.violations_details:
                sev = v["severity"]
                if sev not in by_severity:
                    by_severity[sev] = []
                by_severity[sev].append(v)

            shown = 0
            for sev in ["high", "medium", "low", "unknown"]:
                if sev in by_severity and shown < 5:
                    for v in by_severity[sev][:3]:
                        if shown >= 5:
                            break
                        lines.append(
                            f"      • Line {v['line']}: [{v['source']}] {v['message'][:80]}"
                        )
                        shown += 1

        # Show dead code details
        if analysis.dead_code_details:
            lines.append("   Dead code findings (showing first 3):")
            for detail in analysis.dead_code_details[:3]:
                lines.append(f"      • {detail}")

        lines.append("")

    # Priority recommendations
    lines.append("─" * 100)
    lines.append("🎯 PRIORITY RECOMMENDATIONS")
    lines.append("─" * 100)

    # Find files that need attention
    critical_files = []
    for analysis in analyses:
        score = 0
        reasons = []

        if analysis.complexity_score > 50:
            score += 3
            reasons.append(f"High complexity ({analysis.complexity_score})")

        if analysis.maintainability_index > 0 and analysis.maintainability_index < 10:
            score += 3
            reasons.append(f"Low maintainability ({analysis.maintainability_index:.1f})")

        if analysis.violations_count > 20:
            score += 2
            reasons.append(f"{analysis.violations_count} violations")

        if analysis.dead_code_count > 5:
            score += 1
            reasons.append(f"{analysis.dead_code_count} dead code items")

        if score >= 3:
            critical_files.append((analysis, score, reasons))

    critical_files.sort(key=lambda x: x[1], reverse=True)

    if critical_files:
        lines.append("  Files needing immediate attention:")
        lines.append("")
        for analysis, score, reasons in critical_files[:10]:
            rel_path = analysis.file_path.relative_to(directory.parent)
            lines.append(f"  🔴 {rel_path}")
            lines.append(f"     Priority Score: {score}/10")
            lines.append(f"     Issues: {', '.join(reasons)}")
            lines.append("")
    else:
        lines.append("  ✅ All files are in good shape!")

    lines.append("═" * 100)
    lines.append("")
    lines.append("💡 NEXT STEPS:")
    lines.append("  1. Review files in the priority list above")
    lines.append("  2. Run detailed analysis on specific files:")
    lines.append("     python .claude/helpers/code_analyzer.py <file_path>")
    lines.append("  3. Use /review-clean-code command for detailed Feynman-style review")
    lines.append("")
    lines.append("═" * 100)

    return "\n".join(lines)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python batch_analyzer.py <directory>", file=sys.stderr)
        sys.exit(1)

    directory = Path(sys.argv[1])
    if not directory.is_dir():
        print(f"Error: {directory} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Find all Python files
    python_files = list(directory.rglob("*.py"))
    python_files = [f for f in python_files if "__pycache__" not in str(f)]

    # Progress messages to stderr (so they don't pollute the report)
    print(f"Found {len(python_files)} Python files in {directory}", file=sys.stderr)
    print("Analyzing... (this may take a minute)\n", file=sys.stderr)

    # Analyze each file
    analyses = []
    for i, file_path in enumerate(python_files, 1):
        print(f"  [{i}/{len(python_files)}] {file_path.name}...", end="\r", file=sys.stderr)
        analysis = analyze_file(file_path)
        analyses.append(analysis)

    print("\n\nBuilding dependency graph...\n", file=sys.stderr)

    # Build dependency relationships
    build_dependency_graph(analyses)

    print("Generating report...\n", file=sys.stderr)

    # Generate and print summary to stdout (clean output for redirection)
    report = generate_summary_report(analyses, directory)
    print(report)


if __name__ == "__main__":
    main()
