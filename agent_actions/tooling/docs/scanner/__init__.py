"""Project scanner for finding workflow files and prompts.

All scan functions accept ``project_root: Path`` and return dicts.
Import the package and call functions directly::

    from agent_actions.tooling.docs import scanner

    workflows = scanner.scan_workflows(project_root)
    prompts   = scanner.scan_prompts(project_root)
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_actions.config.defaults import DocsDefaults
from agent_actions.tooling.code_scanner import (
    extract_function_details,
    extract_typed_dicts,
    scan_tool_functions,
)

from .component_scanners import (
    scan_data_loaders,
    scan_error_types,
    scan_event_types,
    scan_examples,
    scan_processing_states,
    scan_vendors,
)
from .data_scanners import (
    extract_action_metrics,
    extract_runtime_warnings,
    scan_logs,
    scan_prompts,
    scan_runs,
    scan_schemas,
    scan_sqlite_readonly,
    scan_workflow_data,
)

logger = logging.getLogger(__name__)

# Cap README content to prevent catalog.json bloat
_README_MAX_BYTES = DocsDefaults.README_MAX_BYTES

__all__ = [
    # Orchestration
    "scan_workflows",
    "scan_readmes",
    "ReadmeData",
    # Data scanners
    "scan_prompts",
    "scan_schemas",
    "scan_workflow_data",
    "scan_sqlite_readonly",
    "scan_runs",
    "scan_logs",
    "extract_action_metrics",
    "extract_runtime_warnings",
    # Code scanners
    "scan_tool_functions",
    "extract_typed_dicts",
    "extract_function_details",
    # Component scanners
    "scan_vendors",
    "scan_error_types",
    "scan_event_types",
    "scan_examples",
    "scan_data_loaders",
    "scan_processing_states",
]


def scan_workflows(project_root: Path) -> dict[str, dict[str, Any]]:
    """Scan project directory for rendered and original workflow YAML files."""
    workflows = {}
    artefact_dir = project_root / "artefact"

    # First, scan for rendered workflows inside artefact/
    rendered_dir = artefact_dir / "rendered_workflows"
    if rendered_dir.exists():
        for yaml_file in rendered_dir.glob("*.yml"):
            workflow_name = yaml_file.stem
            workflows[workflow_name] = {"rendered": str(yaml_file), "original": None}

    # Then, scan for original workflows with plan sections
    # Skip the artefact directory to avoid scanning generated docs
    for agent_config_dir in project_root.rglob("agent_config"):
        # Skip if inside artefact directory
        if artefact_dir in agent_config_dir.parents or agent_config_dir == artefact_dir:
            continue

        for yaml_file in agent_config_dir.glob("*.yml"):
            workflow_name = yaml_file.stem
            if workflow_name in workflows:
                workflows[workflow_name]["original"] = str(yaml_file)
            else:
                workflows[workflow_name] = {"rendered": None, "original": str(yaml_file)}

    return workflows


@dataclass
class ReadmeData:
    """README content paired with its source directory for resolving relative paths."""

    content: str
    source_dir: Path  # directory containing the README, for resolving relative image paths


def scan_readmes(project_root: Path) -> dict[str, ReadmeData]:
    """Scan for README.md files alongside agent_config directories.

    Uses last-write-wins on duplicate workflow stems, matching the
    collision policy in scan_workflows() so README content stays paired
    with the workflow metadata that catalog generation actually uses.
    rglob ordering is filesystem-dependent.

    READMEs larger than 100 KB are truncated with a trailing notice.
    """
    readmes: dict[str, ReadmeData] = {}
    artefact_dir = project_root / "artefact"

    for agent_config_dir in project_root.rglob("agent_config"):
        if artefact_dir in agent_config_dir.parents or agent_config_dir == artefact_dir:
            continue

        readme_path = agent_config_dir.parent / "README.md"
        if not readme_path.exists():
            continue

        try:
            content = readme_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Failed to read README %s: %s", readme_path, e)
            continue

        encoded = content.encode("utf-8")
        if len(encoded) > _README_MAX_BYTES:
            truncated = encoded[:_README_MAX_BYTES].decode("utf-8", errors="ignore")
            truncated = truncated.rsplit("\n", 1)[0]
            content = truncated + "\n\n---\n*README truncated (exceeds 100 KB)*\n"

        source_dir = readme_path.parent

        for yaml_file in agent_config_dir.glob("*.yml"):
            readmes[yaml_file.stem] = ReadmeData(
                content=content,
                source_dir=source_dir,
            )

    return readmes
