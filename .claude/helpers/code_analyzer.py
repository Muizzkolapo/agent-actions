#!/usr/bin/env python3
"""
Code analysis utilities for clean code review.

Uses mature tools: radon, prospector, vulture
Provides AST parsing, lineage tracking, and ASCII diagram generation.
"""
import ast
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Optional
from dataclasses import dataclass, field


@dataclass
class CodeLineage:
    """Represents the lineage/dependencies of a code module."""
    module_path: str
    imports: List[str] = field(default_factory=list)
    from_imports: Dict[str, List[str]] = field(default_factory=dict)
    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    function_calls: Set[str] = field(default_factory=set)
    dependencies: Set[str] = field(default_factory=set)
    base_classes: Dict[str, List[str]] = field(default_factory=dict)
    complexity_score: int = 0


class ASTAnalyzer(ast.NodeVisitor):
    """AST visitor to extract code lineage information."""

    def __init__(self):
        self.lineage = CodeLineage(module_path="")
        self.current_class = None
        self.complexity = 0

    def visit_Import(self, node: ast.Import):
        """Track import statements."""
        for alias in node.names:
            self.lineage.imports.append(alias.name)
            self.lineage.dependencies.add(alias.name.split('.')[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Track from...import statements."""
        if node.module:
            module = node.module
            names = [alias.name for alias in node.names]
            self.lineage.from_imports[module] = names
            self.lineage.dependencies.add(module.split('.')[0])
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        """Track class definitions and inheritance."""
        self.lineage.classes.append(node.name)

        # Track base classes
        base_names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(self._get_full_name(base))

        if base_names:
            self.lineage.base_classes[node.name] = base_names

        # Track complexity
        self.complexity += 1

        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Track function definitions."""
        if self.current_class:
            self.lineage.functions.append(f"{self.current_class}.{node.name}")
        else:
            self.lineage.functions.append(node.name)

        # Track complexity (each function adds complexity)
        self.complexity += 1

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Track function/method calls."""
        call_name = self._get_call_name(node.func)
        if call_name:
            self.lineage.function_calls.add(call_name)
        self.generic_visit(node)

    def visit_If(self, node: ast.If):
        """Track if statements for complexity."""
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        """Track for loops for complexity."""
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While):
        """Track while loops for complexity."""
        self.complexity += 1
        self.generic_visit(node)

    def _get_call_name(self, node) -> str:
        """Extract the name of a function call."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self._get_full_name(node)
        return ""

    def _get_full_name(self, node) -> str:
        """Get full dotted name from an attribute node."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value = self._get_full_name(node.value)
            return f"{value}.{node.attr}" if value else node.attr
        return ""


def analyze_code(file_path: Path) -> CodeLineage:
    """
    Analyze a Python file and extract lineage information.

    Args:
        file_path: Path to the Python file to analyze

    Returns:
        CodeLineage object with extracted information
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        source = f.read()

    try:
        tree = ast.parse(source)
        analyzer = ASTAnalyzer()
        analyzer.lineage.module_path = str(file_path)
        analyzer.visit(tree)
        analyzer.lineage.complexity_score = analyzer.complexity
        return analyzer.lineage
    except SyntaxError as e:
        # Return empty lineage if file has syntax errors
        lineage = CodeLineage(module_path=str(file_path))
        return lineage


def generate_ascii_lineage_diagram(lineage: CodeLineage) -> str:
    """
    Generate an ASCII diagram showing the module's lineage.

    Args:
        lineage: CodeLineage object

    Returns:
        ASCII diagram as a string
    """
    lines = []

    # Header
    lines.append("┌─────────────────────────────────────────────┐")
    lines.append("│  MODULE LINEAGE & DEPENDENCIES              │")
    lines.append("├─────────────────────────────────────────────┤")

    # Imports
    if lineage.imports or lineage.from_imports:
        lines.append("│ 📦 IMPORTS:                                 │")
        for imp in lineage.imports[:5]:  # Limit to first 5
            lines.append(f"│  ├─ {imp:<40} │")
        for module, names in list(lineage.from_imports.items())[:5]:
            items = ', '.join(names[:3])
            if len(names) > 3:
                items += f"... (+{len(names)-3})"
            lines.append(f"│  ├─ from {module}: {items:<27} │")
        if len(lineage.imports) + len(lineage.from_imports) > 5:
            remaining = len(lineage.imports) + len(lineage.from_imports) - 5
            lines.append(f"│  └─ ... and {remaining} more                     │")

    lines.append("├─────────────────────────────────────────────┤")

    # Classes
    if lineage.classes:
        lines.append("│ 🏛️  CLASSES:                                 │")
        for cls in lineage.classes[:5]:
            bases = lineage.base_classes.get(cls, [])
            if bases:
                bases_str = f"({', '.join(bases[:2])})"
                lines.append(f"│  ├─ {cls} {bases_str:<30} │")
            else:
                lines.append(f"│  ├─ {cls:<40} │")
        if len(lineage.classes) > 5:
            lines.append(f"│  └─ ... and {len(lineage.classes)-5} more          │")

    lines.append("├─────────────────────────────────────────────┤")

    # Functions
    if lineage.functions:
        lines.append("│ ⚙️  FUNCTIONS/METHODS:                       │")
        for func in lineage.functions[:5]:
            lines.append(f"│  ├─ {func:<40} │")
        if len(lineage.functions) > 5:
            lines.append(f"│  └─ ... and {len(lineage.functions)-5} more      │")

    lines.append("├─────────────────────────────────────────────┤")

    # Complexity
    complexity_label = "Low" if lineage.complexity_score < 10 else "Medium" if lineage.complexity_score < 25 else "High"
    lines.append(f"│ 📊 COMPLEXITY: {lineage.complexity_score} ({complexity_label})              │")

    lines.append("└─────────────────────────────────────────────┘")

    return "\n".join(lines)


def generate_dependency_graph(lineage: CodeLineage) -> str:
    """
    Generate an ASCII dependency graph.

    Args:
        lineage: CodeLineage object

    Returns:
        ASCII dependency graph as a string
    """
    lines = []

    lines.append("┌─────────────────────────────────────────────┐")
    lines.append("│  DEPENDENCY GRAPH                           │")
    lines.append("└─────────────────────────────────────────────┘")
    lines.append("")

    module_name = Path(lineage.module_path).stem
    lines.append(f"        ┌─────────────────┐")
    lines.append(f"        │  {module_name:<15} │  (this module)")
    lines.append(f"        └─────────────────┘")
    lines.append(f"                │")
    lines.append(f"                ├─────→ Dependencies:")
    lines.append(f"                │")

    deps = sorted(lineage.dependencies)[:8]  # Show first 8
    for i, dep in enumerate(deps):
        if i == len(deps) - 1:
            lines.append(f"                └──→ {dep}")
        else:
            lines.append(f"                ├──→ {dep}")

    if len(lineage.dependencies) > 8:
        lines.append(f"                └──→ ... and {len(lineage.dependencies)-8} more")

    return "\n".join(lines)


def run_radon_complexity(file_path: Path) -> Dict:
    """
    Run radon to analyze cyclomatic complexity.

    Args:
        file_path: Path to Python file

    Returns:
        Dict with complexity metrics
    """
    try:
        result = subprocess.run(
            ['radon', 'cc', str(file_path), '-j'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            return data
        return {}
    except Exception:
        return {}


def run_radon_maintainability(file_path: Path) -> Dict:
    """
    Run radon to calculate maintainability index.

    Args:
        file_path: Path to Python file

    Returns:
        Dict with maintainability metrics
    """
    try:
        result = subprocess.run(
            ['radon', 'mi', str(file_path), '-j'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            return data
        return {}
    except Exception:
        return {}


def run_radon_raw_metrics(file_path: Path) -> Dict:
    """
    Run radon to get raw metrics (LOC, LLOC, etc.).

    Args:
        file_path: Path to Python file

    Returns:
        Dict with raw metrics
    """
    try:
        result = subprocess.run(
            ['radon', 'raw', str(file_path), '-j'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            return data
        return {}
    except Exception:
        return {}


def run_prospector(file_path: Path) -> Dict:
    """
    Run prospector for comprehensive code quality analysis.

    Args:
        file_path: Path to Python file

    Returns:
        Dict with prospector results
    """
    try:
        result = subprocess.run(
            ['prospector', str(file_path), '--output-format', 'json', '--no-autodetect'],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode in [0, 1] and result.stdout:  # prospector returns 1 if issues found
            data = json.loads(result.stdout)
            return data
        return {}
    except Exception:
        return {}


def run_vulture(file_path: Path) -> List[str]:
    """
    Run vulture to find dead code.

    Args:
        file_path: Path to Python file

    Returns:
        List of dead code findings
    """
    try:
        result = subprocess.run(
            ['vulture', str(file_path)],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.stdout:
            return result.stdout.strip().split('\n') if result.stdout.strip() else []
        return []
    except Exception:
        return []


def generate_comprehensive_report(file_path: Path) -> str:
    """
    Generate a comprehensive analysis report using all tools.

    Args:
        file_path: Path to Python file

    Returns:
        Formatted ASCII report
    """
    lines = []

    # Header
    lines.append("═" * 80)
    lines.append("📊 COMPREHENSIVE CODE ANALYSIS REPORT")
    lines.append("═" * 80)
    lines.append(f"File: {file_path}")
    lines.append("")

    # Basic lineage
    lineage = analyze_code(file_path)
    lines.append(generate_ascii_lineage_diagram(lineage))
    lines.append("")
    lines.append(generate_dependency_graph(lineage))
    lines.append("")

    # Radon metrics
    lines.append("─" * 80)
    lines.append("📏 COMPLEXITY METRICS (Radon)")
    lines.append("─" * 80)

    complexity = run_radon_complexity(file_path)
    if complexity:
        file_key = str(file_path)
        if file_key in complexity:
            lines.append("")
            for item in complexity[file_key]:
                name = item.get('name', 'Unknown')
                cc = item.get('complexity', 0)
                rank = item.get('rank', '?')
                lines.append(f"  • {name}: Complexity={cc} (Rank: {rank})")
    else:
        lines.append("  No complexity data available")

    lines.append("")

    # Maintainability
    maintainability = run_radon_maintainability(file_path)
    if maintainability:
        file_key = str(file_path)
        if file_key in maintainability:
            mi_data = maintainability[file_key]
            mi_score = mi_data.get('mi', 0)
            mi_rank = mi_data.get('rank', '?')
            lines.append(f"  Maintainability Index: {mi_score:.2f} (Rank: {mi_rank})")
            lines.append("")

    # Raw metrics
    raw_metrics = run_radon_raw_metrics(file_path)
    if raw_metrics:
        file_key = str(file_path)
        if file_key in raw_metrics:
            metrics = raw_metrics[file_key]
            lines.append(f"  LOC (Lines of Code): {metrics.get('loc', 0)}")
            lines.append(f"  LLOC (Logical Lines): {metrics.get('lloc', 0)}")
            lines.append(f"  SLOC (Source Lines): {metrics.get('sloc', 0)}")
            lines.append(f"  Comments: {metrics.get('comments', 0)}")
            lines.append(f"  Blank Lines: {metrics.get('blank', 0)}")

    lines.append("")

    # Prospector violations
    lines.append("─" * 80)
    lines.append("🔍 CODE QUALITY ISSUES (Prospector)")
    lines.append("─" * 80)

    prospector_results = run_prospector(file_path)
    if prospector_results and 'messages' in prospector_results:
        messages = prospector_results['messages']
        if messages:
            # Group by severity
            by_severity = {}
            for msg in messages:
                severity = msg.get('severity', 'unknown')
                if severity not in by_severity:
                    by_severity[severity] = []
                by_severity[severity].append(msg)

            for severity in ['error', 'warning', 'info']:
                if severity in by_severity:
                    lines.append(f"\n  {severity.upper()}S:")
                    for msg in by_severity[severity][:10]:  # Limit to 10 per severity
                        location = msg.get('location', {})
                        line_num = location.get('line', '?')
                        source = msg.get('source', 'unknown')
                        message = msg.get('message', '')
                        lines.append(f"    Line {line_num} [{source}]: {message}")

                    if len(by_severity[severity]) > 10:
                        lines.append(f"    ... and {len(by_severity[severity]) - 10} more")
        else:
            lines.append("  ✅ No issues found!")
    else:
        lines.append("  No prospector data available")

    lines.append("")

    # Dead code
    lines.append("─" * 80)
    lines.append("💀 DEAD CODE DETECTION (Vulture)")
    lines.append("─" * 80)

    dead_code = run_vulture(file_path)
    if dead_code and dead_code[0]:  # Check if not empty list
        lines.append("")
        for item in dead_code[:10]:  # Limit to 10 items
            if item.strip():
                lines.append(f"  {item}")
        if len(dead_code) > 10:
            lines.append(f"  ... and {len(dead_code) - 10} more")
    else:
        lines.append("  ✅ No dead code found!")

    lines.append("")
    lines.append("═" * 80)

    return "\n".join(lines)


if __name__ == "__main__":
    # Test with this file
    import sys
    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
        print(generate_comprehensive_report(file_path))
