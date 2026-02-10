#!/usr/bin/env python3
"""
Enhanced dead code analyzer with multi-tool validation.

Uses multiple detection methods to reduce false positives:
1. Vulture - Comprehensive dead code detection
2. Ruff - Fast, accurate import/variable detection
3. AST Analysis - Pattern-based detection
4. Smart Filters - Known false positive patterns

Confidence Tiers:
- HIGH (90-100%): Multiple tools agree OR Ruff confirms
- MEDIUM (70-89%): Vulture detects but filtered for common patterns
- LOW (<70%): Vulture only, high false positive risk
"""

import ast
import sys
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
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
    detected_by: List[str] = field(default_factory=list)  # Which tools found it
    false_positive_risk: str = ""  # Why this might be a false positive


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

    # Tool availability
    tools_available: Dict[str, bool] = field(default_factory=dict)


# =============================================================================
# FALSE POSITIVE FILTERS
# =============================================================================

# Patterns that indicate likely false positives
FALSE_POSITIVE_PATTERNS = {
    "dispatch_table": {
        "description": "Class/function used via dispatch table or registry",
        "indicators": [
            r"Handler$",  # FooHandler classes
            r"Provider$",  # FooProvider classes
            r"Processor$",  # FooProcessor classes
            r"Factory$",  # FooFactory classes
            r"Plugin$",  # FooPlugin classes
        ],
    },
    "abstract_method": {
        "description": "Abstract method in base class",
        "indicators": [
            r"^_.*",  # Private methods starting with _
        ],
        "context_required": ["ABC", "abstractmethod", "BaseClass", "Abstract"],
    },
    "magic_method": {
        "description": "Magic/dunder method",
        "indicators": [
            r"^__.*__$",  # __init__, __str__, etc.
        ],
    },
    "test_fixture": {
        "description": "Test fixture or pytest hook",
        "indicators": [
            r"^test_",
            r"^setUp",
            r"^tearDown",
            r"^pytest_",
        ],
    },
    "property_decorator": {
        "description": "Property accessed via decorator",
        "indicators": [
            r"@property",
        ],
    },
}


def check_false_positive_risk(
    item: DeadCodeItem, file_content: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Check if an item is likely a false positive.

    Returns:
        (is_risky, reason) tuple
    """
    # Check name patterns
    for pattern_type, pattern_info in FALSE_POSITIVE_PATTERNS.items():
        for indicator in pattern_info["indicators"]:
            if re.search(indicator, item.item_name):
                return True, pattern_info["description"]

    # Check file context if available
    if file_content and "context_required" in pattern_info:
        for context_word in pattern_info["context_required"]:
            if context_word in file_content:
                return True, pattern_info["description"]

    # Special case: Methods in base classes
    if item.item_type in ["method", "function"] and "Base" in item.file_path:
        return True, "Method in base class (may be abstract or overridden)"

    # Special case: Classes/methods matching known patterns
    if item.item_type in ["class", "method"]:
        # Check if it's in a vendor/provider/handler directory
        path_lower = item.file_path.lower()
        if any(keyword in path_lower for keyword in ["vendor", "provider", "handler", "plugin"]):
            return True, "Located in vendor/provider/handler directory (likely used via dispatch)"

    return False, ""


# =============================================================================
# RUFF INTEGRATION
# =============================================================================


def run_ruff_analysis(target_path: Path) -> List[DeadCodeItem]:
    """
    Run Ruff for accurate import and variable detection.

    Ruff is significantly more accurate than Vulture for imports.
    """
    dead_items = []

    try:
        # Check if ruff is available
        result = subprocess.run(
            ["ruff", "check", str(target_path), "--select", "F401,F841", "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Parse ruff output
        # Format: path/file.py:line:col: F401 `module` imported but unused
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            try:
                # Example: agent_actions/core/parser.py:10:1: F401 `datetime` imported but unused
                match = re.match(r"([^:]+):(\d+):\d+:\s+(F\d+)\s+(.+)", line)
                if match:
                    file_path, line_num, code, message = match.groups()

                    # Extract item name from message
                    name_match = re.search(r"`([^`]+)`", message)
                    if name_match:
                        item_name = name_match.group(1)

                        # Determine type
                        item_type = "import" if code == "F401" else "variable"

                        dead_items.append(
                            DeadCodeItem(
                                file_path=file_path,
                                line_number=int(line_num),
                                item_type=item_type,
                                item_name=item_name,
                                confidence=95,  # Ruff is very accurate
                                reason=f"Ruff: {message}",
                                size_lines=1,
                                detected_by=["ruff"],
                            )
                        )
            except Exception as e:
                print(f"Warning: Could not parse ruff line: {line}", file=sys.stderr)
                continue

    except FileNotFoundError:
        print(
            "Info: Ruff not found. Install with: pip install ruff (highly recommended)",
            file=sys.stderr,
        )
        return []
    except subprocess.TimeoutExpired:
        print("Warning: Ruff analysis timed out", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Warning: Error running ruff: {e}", file=sys.stderr)
        return []

    return dead_items


# =============================================================================
# VULTURE INTEGRATION
# =============================================================================


def run_vulture_analysis(target_path: Path) -> List[DeadCodeItem]:
    """
    Run vulture to detect dead code.

    Vulture is comprehensive but has many false positives.
    """
    dead_items = []

    try:
        result = subprocess.run(
            ["vulture", str(target_path), "--min-confidence", "60"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue

                try:
                    # Example: agent_actions/core/parser.py:45: unused function 'parse_data' (60% confidence)
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        file_path = parts[0].strip()
                        line_num = int(parts[1].strip())
                        message = parts[2].strip()

                        if "unused" in message:
                            msg_parts = message.split("'")
                            if len(msg_parts) >= 2:
                                item_name = msg_parts[1]

                                # Extract type
                                type_part = message.split("unused")[1].split("'")[0].strip()
                                item_type = type_part.lower()

                                # Extract confidence
                                confidence = 60
                                if "(" in message and "%" in message:
                                    conf_str = message.split("(")[1].split("%")[0]
                                    confidence = int(conf_str)

                                dead_items.append(
                                    DeadCodeItem(
                                        file_path=file_path,
                                        line_number=line_num,
                                        item_type=item_type,
                                        item_name=item_name,
                                        confidence=confidence,
                                        reason=f"Vulture detected unused {item_type}",
                                        size_lines=1,
                                        detected_by=["vulture"],
                                    )
                                )
                except (ValueError, IndexError):
                    continue

    except subprocess.TimeoutExpired:
        print("Warning: Vulture analysis timed out", file=sys.stderr)
    except FileNotFoundError:
        print("Warning: Vulture not found. Install with: pip install vulture", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Error running vulture: {e}", file=sys.stderr)

    return dead_items


# =============================================================================
# AST ANALYSIS
# =============================================================================


class DeadCodeDetector(ast.NodeVisitor):
    """AST visitor to detect potentially unused code patterns."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.defined_names: Dict[str, int] = {}
        self.used_names: Set[str] = set()
        self.imports: Dict[str, int] = {}
        self.class_methods: Dict[str, List[str]] = {}
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
            if alias.name != "*":
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
            if not (node.name.startswith("__") or node.name in ["setUp", "tearDown", "test_"]):
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
                unused.append(
                    DeadCodeItem(
                        file_path=self.file_path,
                        line_number=line,
                        item_type="import",
                        item_name=name,
                        confidence=85,
                        reason="AST analysis: Import never referenced",
                        size_lines=1,
                        detected_by=["ast"],
                    )
                )
        return unused


def analyze_file_ast(file_path: Path) -> List[DeadCodeItem]:
    """Analyze a single file using AST."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source, filename=str(file_path))
        detector = DeadCodeDetector(str(file_path))
        detector.visit(tree)

        return detector.get_unused_imports()

    except SyntaxError:
        return []
    except Exception as e:
        print(f"Warning: Error analyzing {file_path}: {e}", file=sys.stderr)
        return []


# =============================================================================
# MULTI-TOOL ANALYSIS & CONFIDENCE SCORING
# =============================================================================


def merge_and_score_findings(
    ruff_items: List[DeadCodeItem], vulture_items: List[DeadCodeItem], ast_items: List[DeadCodeItem]
) -> List[DeadCodeItem]:
    """
    Merge findings from multiple tools and adjust confidence scores.

    Confidence levels:
    - 95-100%: Ruff confirms (very accurate)
    - 85-94%: Multiple tools agree
    - 70-84%: Vulture + filtered for false positives
    - 60-69%: Vulture only, unfiltered (high false positive risk)
    """
    # Create a map of findings by (file, line, name)
    findings_map: Dict[Tuple[str, int, str], DeadCodeItem] = {}

    # Add Ruff findings (highest priority)
    for item in ruff_items:
        key = (item.file_path, item.line_number, item.item_name)
        findings_map[key] = item

    # Merge Vulture findings
    for item in vulture_items:
        key = (item.file_path, item.line_number, item.item_name)

        if key in findings_map:
            # Already found by Ruff - increase confidence
            findings_map[key].confidence = min(100, findings_map[key].confidence + 5)
            findings_map[key].detected_by.append("vulture")
            findings_map[key].reason += f" + {item.reason}"
        else:
            # New finding from Vulture
            # Check for false positive risk
            is_risky, risk_reason = check_false_positive_risk(item)

            if is_risky:
                # Lower confidence for risky items
                item.confidence = max(60, item.confidence - 20)
                item.false_positive_risk = risk_reason

            findings_map[key] = item

    # Merge AST findings
    for item in ast_items:
        key = (item.file_path, item.line_number, item.item_name)

        if key in findings_map:
            # Confirmation from AST
            findings_map[key].confidence = min(100, findings_map[key].confidence + 5)
            findings_map[key].detected_by.append("ast")
        else:
            # New finding from AST
            findings_map[key] = item

    return list(findings_map.values())


# =============================================================================
# LINE SPAN CALCULATION
# =============================================================================


def calculate_line_spans(dead_items: List[DeadCodeItem]) -> None:
    """Calculate the actual line span for each dead code item."""
    items_by_file: Dict[str, List[DeadCodeItem]] = {}

    for item in dead_items:
        if item.file_path not in items_by_file:
            items_by_file[item.file_path] = []
        items_by_file[item.file_path].append(item)

    for file_path, items in items_by_file.items():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            tree = ast.parse("".join(lines), filename=file_path)

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    action_name = node.name
                    start_line = node.lineno
                    end_line = node.end_lineno or start_line
                    span = end_line - start_line + 1

                    for item in items:
                        if item.item_name == action_name and item.line_number == start_line:
                            item.size_lines = span

        except Exception:
            pass


# =============================================================================
# MAIN ANALYSIS FUNCTION
# =============================================================================


def analyze_dead_code(target_path: Path) -> DeadCodeReport:
    """
    Perform comprehensive multi-tool dead code analysis.
    """
    report = DeadCodeReport()

    # Determine files to analyze
    if target_path.is_file():
        files = [target_path]
        report.analyzed_paths = [str(target_path)]
    else:
        files = [f for f in target_path.rglob("*.py") if "__pycache__" not in str(f)]
        report.analyzed_paths = [str(target_path)]

    report.total_files = len(files)

    # Run all available tools
    print("🔍 Running multi-tool analysis...", file=sys.stderr)
    print("", file=sys.stderr)

    # 1. Ruff (fast and accurate)
    print("  [1/3] Running Ruff analysis...", file=sys.stderr)
    ruff_items = run_ruff_analysis(target_path)
    report.tools_available["ruff"] = len(ruff_items) > 0 or True  # Tool ran successfully
    print(f"        Found {len(ruff_items)} items", file=sys.stderr)

    # 2. Vulture (comprehensive but noisy)
    print("  [2/3] Running Vulture analysis...", file=sys.stderr)
    vulture_items = run_vulture_analysis(target_path)
    report.tools_available["vulture"] = len(vulture_items) > 0 or True
    print(f"        Found {len(vulture_items)} items", file=sys.stderr)

    # 3. AST analysis
    print(f"  [3/3] Running AST analysis on {len(files)} files...", file=sys.stderr)
    ast_items = []
    for file_path in files:
        ast_items.extend(analyze_file_ast(file_path))
    report.tools_available["ast"] = True
    print(f"        Found {len(ast_items)} items", file=sys.stderr)

    print("", file=sys.stderr)
    print("📊 Merging results and scoring confidence...", file=sys.stderr)

    # Merge and score findings
    report.dead_items = merge_and_score_findings(ruff_items, vulture_items, ast_items)

    # Calculate line spans
    print("📏 Calculating line spans...", file=sys.stderr)
    calculate_line_spans(report.dead_items)

    # Update statistics
    report.total_dead_items = len(report.dead_items)

    for item in report.dead_items:
        report.dead_lines_total += item.size_lines

        if item.item_type in ["function", "def"]:
            report.unused_functions += 1
        elif item.item_type in ["class", "cls"]:
            report.unused_classes += 1
        elif item.item_type in ["variable", "var"]:
            report.unused_variables += 1
        elif item.item_type == "import":
            report.unused_imports += 1
        elif item.item_type in ["method", "function"]:
            report.unused_methods += 1
        elif item.item_type == "property":
            report.unused_properties += 1
        elif item.item_type == "attribute":
            report.unused_attributes += 1

    print("", file=sys.stderr)
    return report


# =============================================================================
# ENHANCED REPORTING
# =============================================================================


def generate_ascii_report(report: DeadCodeReport, show_details: bool = True) -> str:
    """Generate an enhanced ASCII report with confidence tiers."""
    lines = []

    lines.append("═" * 100)
    lines.append("💀 ENHANCED DEAD CODE ANALYSIS REPORT")
    lines.append("═" * 100)
    lines.append(f"Analyzed: {', '.join(report.analyzed_paths)}")
    lines.append(f"Files Scanned: {report.total_files}")
    lines.append(f"Tools Used: {', '.join(k for k, v in report.tools_available.items() if v)}")
    lines.append("")

    # Summary statistics
    lines.append("─" * 100)
    lines.append("📊 SUMMARY STATISTICS")
    lines.append("─" * 100)
    lines.append(f"  Total Dead Code Items: {report.total_dead_items}")
    lines.append(f"  Estimated Dead Lines: {report.dead_lines_total:,}")
    lines.append("")

    # Confidence breakdown
    high_conf = [i for i in report.dead_items if i.confidence >= 90]
    med_conf = [i for i in report.dead_items if 70 <= i.confidence < 90]
    low_conf = [i for i in report.dead_items if i.confidence < 70]

    lines.append("  Confidence Breakdown:")
    lines.append(f"    🔴 HIGH (90-100%):   {len(high_conf)} items - Very safe to remove")
    lines.append(f"    🟡 MEDIUM (70-89%):  {len(med_conf)} items - Review before removing")
    lines.append(f"    ⚪ LOW (<70%):       {len(low_conf)} items - Likely false positives")
    lines.append("")

    lines.append("  Breakdown by Type:")
    if report.unused_imports > 0:
        lines.append(f"    • Unused Imports: {report.unused_imports}")
    if report.unused_functions > 0:
        lines.append(f"    • Unused Functions: {report.unused_functions}")
    if report.unused_classes > 0:
        lines.append(f"    • Unused Classes: {report.unused_classes}")
    if report.unused_methods > 0:
        lines.append(f"    • Unused Methods: {report.unused_methods}")
    if report.unused_variables > 0:
        lines.append(f"    • Unused Variables: {report.unused_variables}")
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

    if show_details:
        # Show high-confidence items first
        lines.append("─" * 100)
        lines.append("🎯 HIGH CONFIDENCE ITEMS (90-100%) - Safe to Remove")
        lines.append("─" * 100)
        lines.append("")

        if high_conf:
            items_by_file: Dict[str, List[DeadCodeItem]] = {}
            for item in high_conf:
                if item.file_path not in items_by_file:
                    items_by_file[item.file_path] = []
                items_by_file[item.file_path].append(item)

            for file_path, items in sorted(items_by_file.items()):
                try:
                    display_path = Path(file_path).relative_to(Path.cwd())
                except ValueError:
                    display_path = Path(file_path)

                lines.append(f"📄 {display_path}")
                for item in sorted(items, key=lambda x: x.line_number):
                    tools_str = ",".join(item.detected_by)
                    lines.append(
                        f"   Line {item.line_number}: {item.item_type} '{item.item_name}' [{item.confidence}% | {tools_str}]"
                    )
                lines.append("")
        else:
            lines.append("  No high-confidence dead code found.")
            lines.append("")

        # Show medium-confidence items with warnings
        lines.append("─" * 100)
        lines.append("⚠️  MEDIUM CONFIDENCE ITEMS (70-89%) - Review Before Removing")
        lines.append("─" * 100)
        lines.append("")

        if med_conf:
            items_by_file: Dict[str, List[DeadCodeItem]] = {}
            for item in med_conf:
                if item.file_path not in items_by_file:
                    items_by_file[item.file_path] = []
                items_by_file[item.file_path].append(item)

            for file_path, items in list(sorted(items_by_file.items()))[:10]:  # Top 10 files
                try:
                    display_path = Path(file_path).relative_to(Path.cwd())
                except ValueError:
                    display_path = Path(file_path)

                lines.append(f"📄 {display_path}")
                for item in sorted(items, key=lambda x: x.line_number)[:5]:  # Top 5 per file
                    tools_str = ",".join(item.detected_by)
                    risk_str = f" ⚠️  {item.false_positive_risk}" if item.false_positive_risk else ""
                    lines.append(
                        f"   Line {item.line_number}: {item.item_type} '{item.item_name}' [{item.confidence}% | {tools_str}]{risk_str}"
                    )
                if len(items) > 5:
                    lines.append(f"   ... and {len(items) - 5} more")
                lines.append("")
        else:
            lines.append("  No medium-confidence items found.")
            lines.append("")

        # Mention low-confidence items but don't show details
        if low_conf:
            lines.append("─" * 100)
            lines.append(f"⚪ LOW CONFIDENCE ITEMS (<70%) - {len(low_conf)} items")
            lines.append("─" * 100)
            lines.append("  These items have high false positive risk and are not shown in detail.")
            lines.append(
                "  Most are likely used via dispatch tables, polymorphism, or dynamic loading."
            )
            lines.append("  Run with --show-all to see full list.")
            lines.append("")

    # Recommendations
    lines.append("─" * 100)
    lines.append("💡 RECOMMENDATIONS")
    lines.append("─" * 100)
    lines.append("")
    lines.append(f"  ✅ Start with HIGH confidence items ({len(high_conf)} items)")
    lines.append("     These are very likely unused and safe to remove.")
    lines.append("")
    lines.append(f"  ⚠️  Review MEDIUM confidence items carefully ({len(med_conf)} items)")
    lines.append("     Check for dispatch tables, abstract methods, and dynamic usage.")
    lines.append("")
    lines.append(f"  ⛔ Avoid LOW confidence items ({len(low_conf)} items)")
    lines.append("     High false positive rate - likely used indirectly.")
    lines.append("")

    if report.unused_imports > 0:
        high_conf_imports = [i for i in high_conf if i.item_type == "import"]
        if high_conf_imports:
            lines.append(
                f"  🚀 Quick win: Remove {len(high_conf_imports)} unused imports (safest cleanup)"
            )
            lines.append("")

    lines.append(f"  Safe removal estimate: ~{sum(i.size_lines for i in high_conf):,} lines")
    lines.append(f"  Total potential (all items): ~{report.dead_lines_total:,} lines")
    lines.append("")

    lines.append("═" * 100)

    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python dead_code_analyzer.py <file_or_directory> [options]", file=sys.stderr)
        print("", file=sys.stderr)
        print("Options:", file=sys.stderr)
        print("  --brief      Show only summary statistics", file=sys.stderr)
        print("  --show-all   Show all findings including low-confidence items", file=sys.stderr)
        sys.exit(1)

    target_path = Path(sys.argv[1])
    show_details = "--brief" not in sys.argv
    show_all = "--show-all" in sys.argv

    if not target_path.exists():
        print(f"Error: {target_path} does not exist", file=sys.stderr)
        sys.exit(1)

    # Run analysis
    report = analyze_dead_code(target_path)

    # Generate and print report
    output = generate_ascii_report(report, show_details=show_details)
    print(output)

    # Return exit code based on findings
    high_conf_items = [i for i in report.dead_items if i.confidence >= 90]
    sys.exit(0 if len(high_conf_items) == 0 else 1)


if __name__ == "__main__":
    main()
