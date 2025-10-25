#!/usr/bin/env python3
"""
Dead code analyzer - focused exclusively on finding unused code.

Uses vulture + AST analysis to find:
- Unused functions
- Unused classes
- Unused variables
- Unused imports
- Unused methods
- Unreachable code
"""
import ast
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Set, Optional
from dataclasses import dataclass, field


@dataclass
class DeadCodeItem:
    """Represents a single dead code finding."""
    file_path: str
    line_number: int
    item_type: str  # function, class, variable, import, method, property, attribute
    item_name: str
    confidence: int  # 0-100
    reason: str
    size_lines: int = 0  # How many lines this item spans


@dataclass
class DeadCodeReport:
    """Complete dead code analysis for a file or directory."""
    analyzed_paths: List[str] = field(default_factory=list)
    total_files: int = 0
    total_dead_items: int = 0
    dead_items: List[DeadCodeItem] = field(default_factory=list)

    # Statistics by type
    unused_functions: int = 0
    unused_classes: int = 0
    unused_variables: int = 0
    unused_imports: int = 0
    unused_methods: int = 0
    unused_properties: int = 0
    unused_attributes: int = 0

    # Potential savings
    dead_lines_total: int = 0


class DeadCodeDetector(ast.NodeVisitor):
    """AST visitor to detect potentially unused code patterns."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.defined_names: Dict[str, int] = {}  # name -> line number
        self.used_names: Set[str] = set()
        self.imports: Dict[str, int] = {}  # import -> line number
        self.class_methods: Dict[str, List[str]] = {}  # class -> [method names]
        self.current_class: Optional[str] = None

    def visit_Import(self, node: ast.Import):
        """Track imports."""
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.imports[name] = node.lineno
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Track from imports."""
        for alias in node.names:
            if alias.name != '*':
                name = alias.asname if alias.asname else alias.name
                self.imports[name] = node.lineno
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        """Track class definitions."""
        self.defined_names[node.name] = node.lineno
        self.class_methods[node.name] = []

        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Track function definitions."""
        if self.current_class:
            self.class_methods[self.current_class].append(node.name)
            # Don't track magic methods or common overrides as unused
            if not (node.name.startswith('__') or node.name in ['setUp', 'tearDown', 'test_']):
                self.defined_names[f"{self.current_class}.{node.name}"] = node.lineno
        else:
            self.defined_names[node.name] = node.lineno

        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        """Track name usage."""
        if isinstance(node.ctx, (ast.Load, ast.Del)):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """Track attribute access."""
        self.used_names.add(node.attr)
        self.generic_visit(node)

    def get_unused_imports(self) -> List[DeadCodeItem]:
        """Find imports that are never used."""
        unused = []
        for name, line in self.imports.items():
            if name not in self.used_names:
                unused.append(DeadCodeItem(
                    file_path=self.file_path,
                    line_number=line,
                    item_type="import",
                    item_name=name,
                    confidence=90,
                    reason="Import is never used in the file",
                    size_lines=1
                ))
        return unused


def run_vulture_analysis(target_path: Path) -> List[DeadCodeItem]:
    """
    Run vulture to detect dead code.

    Args:
        target_path: Path to file or directory

    Returns:
        List of dead code items
    """
    dead_items = []

    try:
        result = subprocess.run(
            ['vulture', str(target_path), '--min-confidence', '60'],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.stdout:
            # Parse vulture output
            # Format: file_path:line_number: unused <type> '<name>' (confidence%)
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue

                try:
                    # Example: agent_actions/core/parser.py:45: unused function 'parse_data' (60% confidence)
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        file_path = parts[0].strip()
                        line_num = int(parts[1].strip())
                        message = parts[2].strip()

                        # Parse the message
                        # Format: "unused <type> '<name>' (confidence%)"
                        if 'unused' in message:
                            msg_parts = message.split("'")
                            if len(msg_parts) >= 2:
                                item_name = msg_parts[1]

                                # Extract type
                                type_part = message.split('unused')[1].split("'")[0].strip()
                                item_type = type_part.lower()

                                # Extract confidence
                                confidence = 60
                                if '(' in message and '%' in message:
                                    conf_str = message.split('(')[1].split('%')[0]
                                    confidence = int(conf_str)

                                dead_items.append(DeadCodeItem(
                                    file_path=file_path,
                                    line_number=line_num,
                                    item_type=item_type,
                                    item_name=item_name,
                                    confidence=confidence,
                                    reason=f"Vulture detected unused {item_type}",
                                    size_lines=1  # We'll calculate actual size later
                                ))
                except (ValueError, IndexError):
                    # Skip malformed lines
                    continue

    except subprocess.TimeoutExpired:
        print("Warning: Vulture analysis timed out", file=sys.stderr)
    except FileNotFoundError:
        print("Error: Vulture not found. Install with: pip install vulture", file=sys.stderr)
    except Exception as e:
        print(f"Error running vulture: {e}", file=sys.stderr)

    return dead_items


def analyze_file_ast(file_path: Path) -> List[DeadCodeItem]:
    """
    Analyze a single file using AST to find additional unused code.

    Args:
        file_path: Path to Python file

    Returns:
        List of dead code items
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source, filename=str(file_path))
        detector = DeadCodeDetector(str(file_path))
        detector.visit(tree)

        # Get unused imports
        return detector.get_unused_imports()

    except SyntaxError:
        return []
    except Exception as e:
        print(f"Error analyzing {file_path}: {e}", file=sys.stderr)
        return []


def calculate_line_spans(dead_items: List[DeadCodeItem]) -> None:
    """
    Calculate the actual line span for each dead code item.

    This reads the source files and determines how many lines
    each unused item occupies.
    """
    items_by_file: Dict[str, List[DeadCodeItem]] = {}

    # Group items by file
    for item in dead_items:
        if item.file_path not in items_by_file:
            items_by_file[item.file_path] = []
        items_by_file[item.file_path].append(item)

    # Process each file
    for file_path, items in items_by_file.items():
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            tree = ast.parse(''.join(lines), filename=file_path)

            # Map AST nodes to line spans
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    node_name = node.name
                    start_line = node.lineno
                    end_line = node.end_lineno or start_line
                    span = end_line - start_line + 1

                    # Update matching dead code items
                    for item in items:
                        if item.item_name == node_name and item.line_number == start_line:
                            item.size_lines = span

        except Exception:
            # If we can't calculate spans, leave them as 1
            pass


def analyze_dead_code(target_path: Path) -> DeadCodeReport:
    """
    Perform comprehensive dead code analysis on a file or directory.

    Args:
        target_path: Path to file or directory to analyze

    Returns:
        DeadCodeReport with all findings
    """
    report = DeadCodeReport()

    # Determine files to analyze
    if target_path.is_file():
        files = [target_path]
        report.analyzed_paths = [str(target_path)]
    else:
        files = [f for f in target_path.rglob("*.py") if '__pycache__' not in str(f)]
        report.analyzed_paths = [str(target_path)]

    report.total_files = len(files)

    # Run vulture on entire target
    print(f"Running vulture analysis on {target_path}...", file=sys.stderr)
    vulture_items = run_vulture_analysis(target_path)
    report.dead_items.extend(vulture_items)

    # Run AST analysis on each file for additional detection
    print(f"Running AST analysis on {len(files)} files...", file=sys.stderr)
    for file_path in files:
        ast_items = analyze_file_ast(file_path)
        # Add AST items that aren't duplicates
        for ast_item in ast_items:
            is_duplicate = any(
                item.file_path == ast_item.file_path and
                item.line_number == ast_item.line_number and
                item.item_name == ast_item.item_name
                for item in report.dead_items
            )
            if not is_duplicate:
                report.dead_items.append(ast_item)

    # Calculate line spans
    print("Calculating line spans...", file=sys.stderr)
    calculate_line_spans(report.dead_items)

    # Update statistics
    report.total_dead_items = len(report.dead_items)

    for item in report.dead_items:
        report.dead_lines_total += item.size_lines

        if item.item_type in ['function', 'def']:
            report.unused_functions += 1
        elif item.item_type in ['class', 'cls']:
            report.unused_classes += 1
        elif item.item_type in ['variable', 'var']:
            report.unused_variables += 1
        elif item.item_type == 'import':
            report.unused_imports += 1
        elif item.item_type in ['method', 'function']:
            report.unused_methods += 1
        elif item.item_type == 'property':
            report.unused_properties += 1
        elif item.item_type == 'attribute':
            report.unused_attributes += 1

    return report


def generate_ascii_report(report: DeadCodeReport, show_details: bool = True) -> str:
    """
    Generate a formatted ASCII report of dead code findings.

    Args:
        report: DeadCodeReport object
        show_details: Whether to show detailed findings

    Returns:
        Formatted ASCII report
    """
    lines = []

    lines.append("═" * 100)
    lines.append("💀 DEAD CODE ANALYSIS REPORT")
    lines.append("═" * 100)
    lines.append(f"Analyzed: {', '.join(report.analyzed_paths)}")
    lines.append(f"Files Scanned: {report.total_files}")
    lines.append("")

    # Summary statistics
    lines.append("─" * 100)
    lines.append("📊 SUMMARY STATISTICS")
    lines.append("─" * 100)
    lines.append(f"  Total Dead Code Items: {report.total_dead_items}")
    lines.append(f"  Estimated Dead Lines: {report.dead_lines_total:,}")
    lines.append("")
    lines.append("  Breakdown by Type:")
    if report.unused_functions > 0:
        lines.append(f"    • Unused Functions: {report.unused_functions}")
    if report.unused_classes > 0:
        lines.append(f"    • Unused Classes: {report.unused_classes}")
    if report.unused_methods > 0:
        lines.append(f"    • Unused Methods: {report.unused_methods}")
    if report.unused_variables > 0:
        lines.append(f"    • Unused Variables: {report.unused_variables}")
    if report.unused_imports > 0:
        lines.append(f"    • Unused Imports: {report.unused_imports}")
    if report.unused_properties > 0:
        lines.append(f"    • Unused Properties: {report.unused_properties}")
    if report.unused_attributes > 0:
        lines.append(f"    • Unused Attributes: {report.unused_attributes}")

    if report.total_dead_items == 0:
        lines.append("")
        lines.append("  ✅ No dead code detected! Your codebase is clean.")
        lines.append("═" * 100)
        return "\n".join(lines)

    lines.append("")

    # ASCII bar chart of dead code by type
    lines.append("─" * 100)
    lines.append("📈 DEAD CODE DISTRIBUTION")
    lines.append("─" * 100)

    type_counts = [
        ("Functions", report.unused_functions),
        ("Classes", report.unused_classes),
        ("Methods", report.unused_methods),
        ("Variables", report.unused_variables),
        ("Imports", report.unused_imports),
        ("Properties", report.unused_properties),
        ("Attributes", report.unused_attributes),
    ]

    max_count = max(count for _, count in type_counts if count > 0) if report.total_dead_items > 0 else 1

    for label, count in type_counts:
        if count > 0:
            bar_length = int((count / max_count) * 40)
            bar = "█" * bar_length
            lines.append(f"  {label:12} │ {bar} {count}")

    lines.append("")

    if show_details:
        # Group by file
        items_by_file: Dict[str, List[DeadCodeItem]] = {}
        for item in report.dead_items:
            if item.file_path not in items_by_file:
                items_by_file[item.file_path] = []
            items_by_file[item.file_path].append(item)

        # Sort files by number of dead items
        sorted_files = sorted(items_by_file.items(), key=lambda x: len(x[1]), reverse=True)

        lines.append("─" * 100)
        lines.append("📋 DETAILED FINDINGS BY FILE")
        lines.append("─" * 100)
        lines.append("")

        for file_path, items in sorted_files[:20]:  # Show top 20 files
            # Calculate relative path
            try:
                display_path = Path(file_path).relative_to(Path.cwd())
            except ValueError:
                display_path = Path(file_path)

            lines.append(f"📄 {display_path}")
            lines.append(f"   Dead Items: {len(items)}, Total Dead Lines: {sum(item.size_lines for item in items)}")
            lines.append("")

            # Sort items by line number
            sorted_items = sorted(items, key=lambda x: x.line_number)

            # Group by type
            by_type: Dict[str, List[DeadCodeItem]] = {}
            for item in sorted_items:
                if item.item_type not in by_type:
                    by_type[item.item_type] = []
                by_type[item.item_type].append(item)

            for item_type, type_items in sorted(by_type.items()):
                lines.append(f"   {item_type.upper()}S:")
                for item in type_items[:10]:  # Show up to 10 per type
                    confidence_indicator = "🔴" if item.confidence >= 80 else "🟡" if item.confidence >= 60 else "⚪"
                    size_info = f" ({item.size_lines} lines)" if item.size_lines > 1 else ""
                    lines.append(f"     {confidence_indicator} Line {item.line_number}: '{item.item_name}'{size_info} [{item.confidence}% confidence]")

                if len(type_items) > 10:
                    lines.append(f"     ... and {len(type_items) - 10} more")

            lines.append("")

        if len(sorted_files) > 20:
            lines.append(f"... and {len(sorted_files) - 20} more files with dead code")
            lines.append("")

    # Recommendations
    lines.append("─" * 100)
    lines.append("💡 RECOMMENDATIONS")
    lines.append("─" * 100)
    lines.append("")
    lines.append("  1. Review high-confidence items (🔴 80%+) first - these are very likely unused")
    lines.append("  2. Remove unused imports to improve module load times")
    lines.append("  3. Delete unused functions/classes to reduce maintenance burden")
    lines.append("  4. For medium-confidence items (🟡 60-79%), verify they're truly unused before removing")
    lines.append("")
    lines.append(f"  Potential Impact: Removing dead code could eliminate ~{report.dead_lines_total:,} lines")
    lines.append("")

    lines.append("═" * 100)

    return "\n".join(lines)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python dead_code_analyzer.py <file_or_directory> [--brief]", file=sys.stderr)
        print("", file=sys.stderr)
        print("  --brief: Show only summary statistics", file=sys.stderr)
        sys.exit(1)

    target_path = Path(sys.argv[1])
    show_details = '--brief' not in sys.argv

    if not target_path.exists():
        print(f"Error: {target_path} does not exist", file=sys.stderr)
        sys.exit(1)

    # Run analysis
    report = analyze_dead_code(target_path)

    # Generate and print report
    output = generate_ascii_report(report, show_details=show_details)
    print(output)


if __name__ == "__main__":
    main()
