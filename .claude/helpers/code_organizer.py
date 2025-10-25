#!/usr/bin/env python3
"""
Code Organizer - Analyze and organize Python codebase structure.

This tool helps understand and document code organization by:
1. Analyzing directory structure and module organization
2. Identifying code patterns and architectural layers
3. Detecting organizational issues (circular dependencies, misplaced files)
4. Generating organization reports and recommendations
5. Creating visual representations of code structure

Based on the agent-actions 13-stage architecture:
- agent_actions/
  ├── input_loading/       # Stage 1: Load and extract data from various sources
  ├── preprocessing/       # Stage 2: Transform, filter, chunk, and prepare data
  ├── validation/          # Stage 3: Validate configuration and data
  ├── prompt_generation/   # Stage 4: Generate prompts and context for LLMs
  ├── llm_invocation/      # Stage 5: Invoke LLM APIs (batch and realtime)
  ├── response_processing/ # Stage 6: Parse and process LLM responses
  ├── postprocessing/      # Stage 7: Post-process results and generate outputs
  ├── orchestration/       # Workflow orchestration and agent execution
  ├── state_management/    # State, artifacts, and path management
  ├── configuration/       # Configuration management and DI
  ├── cli/                 # Command-line interface
  ├── utilities/           # Shared utilities and helpers
  └── shared/              # Shared types and exceptions
"""

import os
import sys
import ast
import json
import argparse
from pathlib import Path
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Set, Tuple, Optional
import fnmatch


@dataclass
class ModuleInfo:
    """Information about a Python module."""
    path: Path
    name: str
    imports: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    lines_of_code: int = 0
    docstring: Optional[str] = None
    has_tests: bool = False


@dataclass
class DirectoryInfo:
    """Information about a directory."""
    path: Path
    name: str
    modules: List[str] = field(default_factory=list)
    subdirs: List[str] = field(default_factory=list)
    total_files: int = 0
    total_lines: int = 0
    has_init: bool = False


@dataclass
class OrganizationReport:
    """Complete organization report."""
    root_path: Path
    total_modules: int = 0
    total_directories: int = 0
    total_lines: int = 0
    architecture_layers: Dict[str, DirectoryInfo] = field(default_factory=dict)
    module_dependencies: Dict[str, List[str]] = field(default_factory=dict)
    organizational_issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class CodeOrganizer:
    """Analyze and organize code structure."""

    # Known architectural patterns (13-stage architecture)
    LAYER_PATTERNS = {
        'input_loading': 'Stage 1: Input Loading',
        'preprocessing': 'Stage 2: Pre-Processing',
        'validation': 'Stage 3: Validation',
        'prompt_generation': 'Stage 4: Prompt Generation',
        'llm_invocation': 'Stage 5: LLM Invocation',
        'response_processing': 'Stage 6: Response Processing',
        'postprocessing': 'Stage 7: Post-Processing',
        'orchestration': 'Workflow Orchestration',
        'state_management': 'State Management',
        'configuration': 'Configuration & DI',
        'cli': 'CLI Interface',
        'utilities': 'Utilities',
        'shared': 'Shared Components',
        'tests': 'Test Suite',
    }

    # Processing stages in the agent pipeline (updated for 13-stage architecture)
    PROCESSING_STAGES = {
        "1_INPUT_LOADING": {
            "name": "Input Loading & Extraction",
            "description": "Load and extract data from various sources (JSON, CSV, XML, text)",
            "patterns": ["input_loading/", "file_reader", "loader"],
            "keywords": ["loader", "extractor", "reader", "load", "extract", "read"]
        },
        "2_PRE_PROCESSING": {
            "name": "Pre-Processing & Data Preparation",
            "description": "Transform, filter, chunk, and prepare data before LLM processing",
            "patterns": ["preprocessing/", "staging", "filter", "chunk"],
            "keywords": ["staging", "filter", "chunk", "transform", "prepare", "preprocess"]
        },
        "3_VALIDATION": {
            "name": "Validation",
            "description": "Validate inputs, prompts, configurations, and outputs",
            "patterns": ["validation/", "validator"],
            "keywords": ["validator", "validate", "validation", "check"]
        },
        "4_PROMPT_GENERATION": {
            "name": "Prompt Generation & Context Building",
            "description": "Build prompts, manage context, apply templates",
            "patterns": ["prompt_generation/", "generator", "prompt", "render"],
            "keywords": ["generator", "prompt", "template", "render", "context"]
        },
        "5_LLM_INVOCATION": {
            "name": "LLM Invocation & Provider Integration",
            "description": "Call LLM providers (OpenAI, Anthropic, Gemini, etc.) for real-time and batch processing",
            "patterns": ["llm_invocation/", "provider", "vendor", "handler"],
            "keywords": ["provider", "vendor", "handler", "llm", "model"]
        },
        "5B_BATCH_PROCESSING": {
            "name": "Batch Processing & Queue Management",
            "description": "Manage batch operations, queue submissions, async result polling, and bulk LLM processing",
            "patterns": ["llm_invocation/batch/", "batch_service", "queue"],
            "keywords": ["batch", "batch_service", "queue", "async", "poll", "submit", "result", "bulk"]
        },
        "6_RESPONSE_PROCESSING": {
            "name": "Response Processing & Transformation",
            "description": "Process LLM responses, parse JSON, transform outputs",
            "patterns": ["response_processing/", "response_transformer", "interceptor"],
            "keywords": ["transformer", "response", "interceptor", "strategy", "parse"]
        },
        "7_POST_PROCESSING": {
            "name": "Post-Processing & Output Generation",
            "description": "Generate final outputs, apply post-processing",
            "patterns": ["postprocessing/", "target", "output", "writer"],
            "keywords": ["target", "output", "writer", "write", "generate"]
        },
        "8_ORCHESTRATION": {
            "name": "Workflow Orchestration & Execution",
            "description": "Manage workflow execution, dependencies, and task orchestration",
            "patterns": ["orchestration/", "workflow", "runner", "graph"],
            "keywords": ["workflow", "runtime", "runner", "orchestrat", "execut", "graph"]
        },
        "9_STATE_MANAGEMENT": {
            "name": "State Management & Context",
            "description": "Manage application state, context, and artifacts",
            "patterns": ["state_management/", "artifact", "lineage", "manifest"],
            "keywords": ["context", "artifact", "state", "lineage", "manifest", "path_manager"]
        },
        "10_CONFIGURATION": {
            "name": "Configuration & Schema Management",
            "description": "Parse and manage configuration, schemas, DI, and bootstrapping",
            "patterns": ["configuration/", "config", "schema", "di_configurator"],
            "keywords": ["config", "schema", "bootstrap", "di_configurator", "container"]
        },
        "11_CLI_INTERFACE": {
            "name": "CLI & User Interface",
            "description": "Command-line interface and user interactions",
            "patterns": ["cli/", "command"],
            "keywords": ["cli", "command", "task", "interface"]
        },
        "12_UTILITIES": {
            "name": "Utilities & Common Functions",
            "description": "Shared utilities, helpers, and common functions",
            "patterns": ["utils", "common", "helper"],
            "keywords": ["utils", "helper", "common", "utility"]
        },
    }

    COMMON_SUBMODULES = {
        'base': 'Base classes and interfaces',
        'handlers': 'Request/response handlers',
        'validators': 'Validation logic',
        'utils': 'Utility functions',
        'extractors': 'Data extraction',
        'generators': 'Data generation',
        'transformers': 'Data transformation',
        'loaders': 'Data loading',
        'providers': 'Service providers',
        'strategies': 'Strategy patterns',
        'interceptors': 'Interceptor patterns',
        'services': 'Business services',
        'contracts': 'Interfaces and contracts',
        'context': 'Context management',
        'graph': 'Graph structures',
        'parser': 'Parsing logic',
        'runtime': 'Runtime execution',
        'migration': 'Data migration',
        'lineage': 'Lineage tracking',
        'filters': 'Filtering logic',
        'bootstrap': 'Initialization',
        'common': 'Common utilities',
        'staging': 'Staging operations',
    }

    def __init__(self, root_path: str, exclude_patterns: List[str] = None):
        """Initialize organizer."""
        self.root_path = Path(root_path).resolve()
        self.exclude_patterns = exclude_patterns or ['__pycache__', '*.pyc', '.git', 'venv', 'env']
        self.modules: Dict[str, ModuleInfo] = {}
        self.directories: Dict[str, DirectoryInfo] = {}

    def should_exclude(self, path: Path) -> bool:
        """Check if path should be excluded."""
        path_str = str(path)
        return any(fnmatch.fnmatch(path_str, pattern) for pattern in self.exclude_patterns)

    def analyze_module(self, file_path: Path) -> ModuleInfo:
        """Analyze a single Python module."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content)
        except Exception as e:
            print(f"  ⚠️  Error parsing {file_path}: {e}", file=sys.stderr)
            return ModuleInfo(path=file_path, name=file_path.stem)

        imports = []
        classes = []
        functions = []
        docstring = ast.get_docstring(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend([alias.name for alias in node.names])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, ast.FunctionDef):
                if not node.name.startswith('_'):  # Skip private functions
                    functions.append(node.name)

        lines_of_code = len(content.splitlines())

        return ModuleInfo(
            path=file_path,
            name=file_path.stem,
            imports=imports,
            classes=classes,
            functions=functions,
            lines_of_code=lines_of_code,
            docstring=docstring,
        )

    def analyze_directory(self, dir_path: Path) -> DirectoryInfo:
        """Analyze a directory."""
        modules = []
        subdirs = []
        total_files = 0
        total_lines = 0
        has_init = False

        try:
            for item in dir_path.iterdir():
                if self.should_exclude(item):
                    continue

                if item.is_file() and item.suffix == '.py':
                    total_files += 1
                    module_info = self.analyze_module(item)
                    modules.append(module_info.name)
                    total_lines += module_info.lines_of_code
                    self.modules[str(item.relative_to(self.root_path))] = module_info

                    if item.name == '__init__.py':
                        has_init = True

                elif item.is_dir():
                    subdirs.append(item.name)
        except PermissionError:
            pass

        return DirectoryInfo(
            path=dir_path,
            name=dir_path.name,
            modules=modules,
            subdirs=subdirs,
            total_files=total_files,
            total_lines=total_lines,
            has_init=has_init,
        )

    def scan_codebase(self):
        """Scan entire codebase."""
        print(f"🔍 Scanning codebase: {self.root_path}")
        print("=" * 80)

        for root, dirs, files in os.walk(self.root_path):
            root_path = Path(root)

            # Skip excluded directories
            dirs[:] = [d for d in dirs if not self.should_exclude(root_path / d)]

            if self.should_exclude(root_path):
                continue

            # Analyze directory
            dir_info = self.analyze_directory(root_path)
            rel_path = str(root_path.relative_to(self.root_path))
            self.directories[rel_path] = dir_info

        print(f"✅ Scanned {len(self.modules)} modules in {len(self.directories)} directories")

    def identify_layers(self) -> Dict[str, DirectoryInfo]:
        """Identify architectural layers."""
        layers = {}

        for dir_path, dir_info in self.directories.items():
            # Check if this is a top-level directory (architectural layer)
            parts = Path(dir_path).parts
            if len(parts) == 1 and parts[0] in self.LAYER_PATTERNS:
                layers[parts[0]] = dir_info

        return layers

    def classify_module_by_stage(self, module_path: str) -> List[str]:
        """Classify a module into one or more processing stages."""
        stages = []
        module_lower = module_path.lower()

        for stage_id, stage_info in self.PROCESSING_STAGES.items():
            # Check patterns
            for pattern in stage_info['patterns']:
                if pattern.lower() in module_lower:
                    stages.append(stage_id)
                    break

            # Check keywords in filename
            if not stages or stage_id not in stages:
                for keyword in stage_info['keywords']:
                    if keyword in module_lower:
                        stages.append(stage_id)
                        break

        return stages

    def identify_processing_stages(self) -> Dict[str, List[str]]:
        """Identify modules for each processing stage."""
        stage_modules = defaultdict(list)

        for module_path in self.modules.keys():
            stages = self.classify_module_by_stage(module_path)
            for stage in stages:
                stage_modules[stage].append(module_path)

        return dict(stage_modules)

    def detect_circular_dependencies(self) -> List[str]:
        """Detect potential circular dependencies."""
        issues = []

        for module_path, module_info in self.modules.items():
            module_dir = str(Path(module_path).parent)

            for imp in module_info.imports:
                # Check if import is from a lower layer importing from higher layer
                if self._is_circular_import(module_dir, imp):
                    issues.append(f"{module_path} -> {imp} (potential circular dependency)")

        return issues

    def _is_circular_import(self, module_dir: str, import_name: str) -> bool:
        """Check if import creates circular dependency."""
        # Simple heuristic: check if importing from parent or sibling at higher level
        # This is a simplified check - full cycle detection would require graph analysis
        if not import_name.startswith('agent_actions'):
            return False

        parts = import_name.split('.')
        if len(parts) < 2:
            return False

        # Check for internal importing core (lower level importing higher level)
        if '_internal' in module_dir and 'core' in parts:
            return True

        return False

    def detect_organizational_issues(self) -> List[str]:
        """Detect organizational issues."""
        issues = []

        # Check for missing __init__.py files
        for dir_path, dir_info in self.directories.items():
            if dir_info.total_files > 0 and not dir_info.has_init:
                if '.' not in dir_path:  # Not already a relative path issue
                    issues.append(f"Missing __init__.py in {dir_path}")

        # Check for oversized modules (>500 LOC)
        for module_path, module_info in self.modules.items():
            if module_info.lines_of_code > 500:
                issues.append(f"Large module ({module_info.lines_of_code} LOC): {module_path}")

        # Check for circular dependencies
        circular = self.detect_circular_dependencies()
        issues.extend(circular)

        # Check for misplaced files (utils in non-utils directories, etc.)
        for module_path in self.modules.keys():
            if 'util' in module_path.lower() and 'utils' not in module_path:
                issues.append(f"Utility module outside utils directory: {module_path}")

        return issues

    def generate_recommendations(self, issues: List[str]) -> List[str]:
        """Generate organizational recommendations."""
        recommendations = []

        # Analyze issue patterns
        large_modules = [i for i in issues if 'Large module' in i]
        missing_inits = [i for i in issues if 'Missing __init__.py' in i]
        circular_deps = [i for i in issues if 'circular dependency' in i]

        if large_modules:
            recommendations.append(
                f"📏 Consider splitting {len(large_modules)} large modules (>500 LOC) into smaller, more focused modules"
            )

        if missing_inits:
            recommendations.append(
                f"📦 Add __init__.py files to {len(missing_inits)} directories to make them proper Python packages"
            )

        if circular_deps:
            recommendations.append(
                f"🔄 Refactor {len(circular_deps)} potential circular dependencies by introducing interfaces or moving shared code"
            )

        # General recommendations based on codebase size
        total_modules = len(self.modules)
        if total_modules > 200:
            recommendations.append(
                "📚 Large codebase (200+ modules): Consider creating architecture documentation and module dependency diagrams"
            )

        # Check for utils proliferation
        utils_count = sum(1 for path in self.modules.keys() if 'utils' in path.lower())
        if utils_count > 10:
            recommendations.append(
                f"🛠️  Multiple utils modules ({utils_count}): Consider consolidating or better organizing utility code"
            )

        return recommendations

    def generate_report(self) -> OrganizationReport:
        """Generate complete organization report."""
        print("\n📊 Generating organization report...")

        layers = self.identify_layers()
        issues = self.detect_organizational_issues()
        recommendations = self.generate_recommendations(issues)

        total_lines = sum(m.lines_of_code for m in self.modules.values())

        # Build dependency map
        dependencies = {}
        for module_path, module_info in self.modules.items():
            internal_imports = [
                imp for imp in module_info.imports
                if imp.startswith('agent_actions')
            ]
            if internal_imports:
                dependencies[module_path] = internal_imports

        return OrganizationReport(
            root_path=self.root_path,
            total_modules=len(self.modules),
            total_directories=len(self.directories),
            total_lines=total_lines,
            architecture_layers=layers,
            module_dependencies=dependencies,
            organizational_issues=issues,
            recommendations=recommendations,
        )

    def print_report(self, report: OrganizationReport):
        """Print organization report."""
        print("\n" + "=" * 80)
        print("📋 CODE ORGANIZATION REPORT")
        print("=" * 80)

        print(f"\n📁 Root Path: {report.root_path}")
        print(f"📦 Total Modules: {report.total_modules}")
        print(f"📂 Total Directories: {report.total_directories}")
        print(f"📝 Total Lines of Code: {report.total_lines:,}")

        # Print processing stages
        print(f"\n🔄 PROCESSING STAGES BREAKDOWN:")
        print("   (Modules classified by their role in the agent pipeline)\n")

        stage_modules = self.identify_processing_stages()
        for stage_id in sorted(stage_modules.keys()):
            stage_info = self.PROCESSING_STAGES[stage_id]
            modules = stage_modules[stage_id]

            print(f"   {stage_info['name']}")
            print(f"   {stage_info['description']}")
            print(f"   📦 {len(modules)} modules")

            # Show a few example modules
            if modules:
                examples = sorted(modules)[:3]
                for example in examples:
                    print(f"      • {example}")
                if len(modules) > 3:
                    print(f"      ... and {len(modules) - 3} more")
            print()

        if report.architecture_layers:
            print(f"\n🏗️  Architectural Layers:")
            for layer_name, layer_info in sorted(report.architecture_layers.items()):
                description = self.LAYER_PATTERNS.get(layer_name, 'Unknown')
                print(f"  • {layer_name}/ - {description}")
                print(f"    Files: {layer_info.total_files}, Lines: {layer_info.total_lines:,}")
                if layer_info.subdirs:
                    print(f"    Submodules: {', '.join(sorted(layer_info.subdirs)[:5])}")
                    if len(layer_info.subdirs) > 5:
                        print(f"                ... and {len(layer_info.subdirs) - 5} more")

        if report.organizational_issues:
            print(f"\n⚠️  Organizational Issues ({len(report.organizational_issues)}):")
            # Group by type
            issues_by_type = defaultdict(list)
            for issue in report.organizational_issues:
                if 'Missing __init__' in issue:
                    issues_by_type['Missing __init__.py'].append(issue)
                elif 'Large module' in issue:
                    issues_by_type['Large modules'].append(issue)
                elif 'circular dependency' in issue:
                    issues_by_type['Circular dependencies'].append(issue)
                else:
                    issues_by_type['Other'].append(issue)

            for issue_type, issues in sorted(issues_by_type.items()):
                print(f"\n  {issue_type} ({len(issues)}):")
                for issue in issues[:5]:  # Show first 5
                    print(f"    • {issue}")
                if len(issues) > 5:
                    print(f"    ... and {len(issues) - 5} more")

        if report.recommendations:
            print(f"\n💡 Recommendations:")
            for i, rec in enumerate(report.recommendations, 1):
                print(f"  {i}. {rec}")

        print("\n" + "=" * 80)

    def export_json(self, report: OrganizationReport, output_file: Path):
        """Export report as JSON."""
        # Convert to dict, handling Path objects
        report_dict = {
            'root_path': str(report.root_path),
            'total_modules': report.total_modules,
            'total_directories': report.total_directories,
            'total_lines': report.total_lines,
            'architecture_layers': {
                name: {
                    'path': str(info.path),
                    'name': info.name,
                    'modules': info.modules,
                    'subdirs': info.subdirs,
                    'total_files': info.total_files,
                    'total_lines': info.total_lines,
                    'has_init': info.has_init,
                }
                for name, info in report.architecture_layers.items()
            },
            'module_dependencies': report.module_dependencies,
            'organizational_issues': report.organizational_issues,
            'recommendations': report.recommendations,
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report_dict, f, indent=2)

        print(f"📄 Report exported to: {output_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze and organize Python codebase structure',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze current directory
  python code_organizer.py .

  # Analyze specific directory
  python code_organizer.py /path/to/agent_actions

  # Export report as JSON
  python code_organizer.py . --json report.json

  # Exclude additional patterns
  python code_organizer.py . --exclude "*.bak" "temp_*"
        """
    )

    parser.add_argument(
        'path',
        type=str,
        help='Root path to analyze (default: current directory)',
        nargs='?',
        default='.'
    )

    parser.add_argument(
        '--json',
        type=str,
        help='Export report as JSON to specified file',
        metavar='FILE'
    )

    parser.add_argument(
        '--exclude',
        nargs='+',
        help='Additional patterns to exclude',
        default=[]
    )

    args = parser.parse_args()

    # Create organizer
    organizer = CodeOrganizer(
        root_path=args.path,
        exclude_patterns=['__pycache__', '*.pyc', '.git', 'venv', 'env'] + args.exclude
    )

    # Scan codebase
    organizer.scan_codebase()

    # Generate report
    report = organizer.generate_report()

    # Print report
    organizer.print_report(report)

    # Export JSON if requested
    if args.json:
        output_file = Path(args.json)
        organizer.export_json(report, output_file)

    return 0


if __name__ == '__main__':
    sys.exit(main())
