"""Catalog and runs data generator."""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from agent_actions.config.path_config import get_tool_dirs
from agent_actions.models.action_schema import ActionSchema, FieldInfo, FieldSource
from agent_actions.utils.constants import DEFAULT_ACTION_KIND
from agent_actions.workflow.schema_service import WorkflowSchemaService

from . import scanner
from .parser import WorkflowParser
from .run_tracker import _empty_runs_data

logger = logging.getLogger(__name__)


class CatalogGenerator:
    """Generate catalog.json from workflows."""

    def __init__(
        self,
        workflows_data: dict[str, dict],
        project_path: str | None = None,
        tool_schemas: dict[str, Any] | None = None,
    ):
        self.workflows_data = workflows_data
        self.parser = WorkflowParser()
        self.project_path = Path(project_path) if project_path else None
        self._tool_schemas = tool_schemas

    def _build_schema_service(self, workflow: dict[str, Any]) -> WorkflowSchemaService | None:
        """Build a WorkflowSchemaService for a parsed workflow.

        Returns None only if the workflow has no actions.
        """
        actions = workflow.get("actions", {})
        if not actions:
            return None

        return WorkflowSchemaService.from_action_configs(
            workflow.get("name", "unknown"),
            actions,
            project_root=self.project_path,
            tool_schemas=self._tool_schemas,
        )

    def _enrich_action_with_fields(
        self, action: dict[str, Any], action_schema: ActionSchema | None = None
    ) -> dict[str, Any]:
        """Enrich action with input/output field information for lineage.

        Uses ActionSchema from WorkflowSchemaService when available (preferred).
        Falls back to inline schema dict extraction for inline definitions.
        """
        enriched = action.copy()

        if action_schema and action_schema.output_fields:
            # Preferred path: consume pre-resolved ActionSchema
            non_dropped = [f for f in action_schema.output_fields if not f.is_dropped]
            enriched["outputs"] = [f.name for f in non_dropped]
            enriched["output_fields"] = [f.to_dict() for f in non_dropped]
        elif "schema" in action and isinstance(action["schema"], dict):
            # Inline schema dict — not file-based, so WorkflowSchemaService
            # doesn't resolve these. Extract field names directly.
            schema_value = action["schema"]
            field_names = list(schema_value.keys())
            enriched["outputs"] = field_names
            enriched["output_fields"] = [
                FieldInfo(
                    name=name,
                    source=FieldSource.SCHEMA,
                    is_required=True,
                    is_dropped=False,
                    field_type=type_val if isinstance(type_val, str) else "unknown",
                    description="",
                ).to_dict()
                for name, type_val in schema_value.items()
            ]

        # Extract input fields from context_scope
        if "context_scope" in action:
            inputs = self.parser.extract_input_fields(action["context_scope"])
            if inputs:
                enriched["inputs"] = inputs

        # Clean up internal fields not needed in catalog
        enriched.pop("context_scope", None)

        return enriched

    def generate(
        self,
        prompts_data: dict[str, Any] | None = None,
        schemas_data: dict[str, Any] | None = None,
        tool_functions_data: dict[str, Any] | None = None,
        runs_data: dict[str, Any] | None = None,
        logs_data: dict[str, Any] | None = None,
        vendors_data: dict[str, Any] | None = None,
        error_types_data: dict[str, Any] | None = None,
        event_types_data: dict[str, Any] | None = None,
        examples_data: dict[str, Any] | None = None,
        data_loaders_data: dict[str, Any] | None = None,
        processing_states_data: dict[str, Any] | None = None,
        workflow_data: dict[str, Any] | None = None,
        readmes_data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Generate the complete catalog structure."""
        # Initialize prompts with used_by tracking
        prompts_with_refs = {}
        for prompt_name, prompt_data in (prompts_data or {}).items():
            prompts_with_refs[prompt_name] = prompt_data.copy()
            prompts_with_refs[prompt_name]["used_by"] = []

        # Initialize schemas with used_by tracking
        schemas_with_refs = {}
        for schema_name, schema_data in (schemas_data or {}).items():
            schemas_with_refs[schema_name] = schema_data.copy()
            schemas_with_refs[schema_name]["used_by"] = []

        catalog = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_workflows": len(self.workflows_data),
                "generator_version": "1.1.0",
            },
            "workflows": {},
            "actions": {},  # Flattened index for faster lookup
            "prompts": prompts_with_refs,
            "schemas": schemas_with_refs,
            "tool_functions": tool_functions_data or {},
            "runs": runs_data or {},  # Workflow run data and metrics
            "logs": logs_data or {},  # Global CLI logs and validation events
            "vendors": vendors_data or {},  # LLM vendor configurations
            "error_types": error_types_data or {},  # Error class hierarchy
            "event_types": event_types_data or {},  # Event type definitions
            "examples": examples_data or {},  # Example projects
            "data_loaders": data_loaders_data or {},  # Data loader implementations
            "processing_states": processing_states_data or {},  # Processing enums/types
            "workflow_data": workflow_data or {},  # Workflow output data previews
            "stats": {
                "total_workflows": 0,
                "total_actions": 0,
                "llm_actions": 0,
                "tool_actions": 0,
                "total_prompts": 0,
                "total_schemas": 0,
                "total_tool_functions": 0,
                "total_runs": 0,
                "validation_errors": 0,
                "validation_warnings": 0,
                "total_vendors": 0,
                "total_error_types": 0,
                "total_event_types": 0,
                "total_examples": 0,
                "total_data_loaders": 0,
                "total_processing_states": 0,
                "total_data_nodes": 0,
            },
        }

        # Track unique schemas and prompts across all workflows
        unique_schemas = set()
        actions_with_prompts = 0

        for workflow_name, paths in self.workflows_data.items():
            # Use rendered workflow if available, otherwise use original
            yaml_path = paths["rendered"] or paths["original"]
            workflow = self.parser.parse_workflow(yaml_path)

            # Skip if workflow parsing failed
            if workflow is None:
                continue

            # Build WorkflowSchemaService for this workflow to get ActionSchemas
            schema_service = self._build_schema_service(workflow)

            # Merge dependencies and enrich actions with field information
            enriched_actions = {}
            workflow_id = workflow_name

            for action_name, action in workflow["actions"].items():
                # Get pre-resolved ActionSchema (has field types, descriptions)
                action_schema = (
                    schema_service.get_action_schema(action_name) if schema_service else None
                )
                # Enrich with input/output fields for lineage
                enriched_action = self._enrich_action_with_fields(action, action_schema)

                # Attach tool function details for tool actions
                if action.get("type") == "tool" and tool_functions_data:
                    impl_name = action.get("implementation")
                    if impl_name and impl_name in tool_functions_data:
                        enriched_action["tool_function"] = tool_functions_data[impl_name]

                enriched_actions[action_name] = enriched_action

                # Add to flattened actions index with workflow reference
                action_with_workflow = enriched_action.copy()
                action_with_workflow["workflow_id"] = workflow_id
                catalog["actions"][f"{workflow_id}.{action_name}"] = action_with_workflow

                # Track prompt-to-action relationships
                prompt_ref = action.get("prompt")
                if prompt_ref and prompt_ref in catalog["prompts"]:
                    catalog["prompts"][prompt_ref]["used_by"].append(
                        {"workflow": workflow_id, "action": action_name}
                    )

                # Track schema-to-action relationships
                schema_ref = action.get("schema")
                if schema_ref and isinstance(schema_ref, str) and schema_ref in catalog["schemas"]:
                    catalog["schemas"][schema_ref]["used_by"].append(
                        {"workflow": workflow_id, "action": action_name}
                    )

            # Merge action metrics from runs data if available
            if runs_data and workflow_id in runs_data:
                workflow_runs = runs_data[workflow_id]
                action_metrics = workflow_runs.get("action_metrics", {})
                for action_name, metrics in action_metrics.items():
                    if action_name in enriched_actions:
                        enriched_actions[action_name]["metrics"] = metrics

            # Get latest run info and manifest if available
            latest_run = None
            manifest = None
            if runs_data and workflow_id in runs_data:
                latest_run = runs_data[workflow_id].get("latest_run")
                manifest = runs_data[workflow_id].get("manifest")

            # Create workflow entry
            catalog["workflows"][workflow_id] = {
                "id": workflow_id,
                "name": workflow["name"],
                "description": workflow["description"],
                "path": workflow["path"],
                "version": workflow["version"],
                "defaults": workflow.get("defaults", {}),
                "actions": enriched_actions,
                "action_count": len(enriched_actions),
                "latest_run": latest_run,
                "manifest": manifest,
                "readme": (readmes_data or {}).get(workflow_id),
            }

            # Update stats
            catalog["stats"]["total_workflows"] += 1
            catalog["stats"]["total_actions"] += len(workflow["actions"])

            # Count action types, schemas, and prompts
            for action in workflow["actions"].values():
                if action.get("type") == DEFAULT_ACTION_KIND:
                    catalog["stats"]["llm_actions"] += 1
                elif action.get("type") == "tool":
                    catalog["stats"]["tool_actions"] += 1

                # Count unique schemas (only string references, not inline dicts)
                schema = action.get("schema")
                if schema and isinstance(schema, str):
                    unique_schemas.add(schema)

                # Count actions with prompts (LLM actions typically have prompts)
                if action.get("prompt") or (
                    action.get("type") == DEFAULT_ACTION_KIND and action.get("intent")
                ):
                    actions_with_prompts += 1

        # Update global stats for schemas, prompts, tool functions, and runs
        catalog["stats"]["total_schemas"] = len(schemas_data) if schemas_data else 0
        catalog["stats"]["total_prompts"] = len(prompts_data) if prompts_data else 0
        catalog["stats"]["total_tool_functions"] = (
            len(tool_functions_data) if tool_functions_data else 0
        )
        catalog["stats"]["total_runs"] = len(runs_data) if runs_data else 0

        # Update validation stats from logs
        if logs_data:
            catalog["stats"]["validation_errors"] = len(logs_data.get("validation_errors", []))
            catalog["stats"]["validation_warnings"] = len(logs_data.get("validation_warnings", []))

        # Update stats for new categories
        catalog["stats"]["total_vendors"] = len(vendors_data) if vendors_data else 0
        catalog["stats"]["total_error_types"] = sum(
            cat.get("error_count", 0) for cat in (error_types_data or {}).values()
        )
        catalog["stats"]["total_event_types"] = sum(
            cat.get("event_count", 0) for cat in (event_types_data or {}).values()
        )
        catalog["stats"]["total_examples"] = len(examples_data) if examples_data else 0
        catalog["stats"]["total_data_loaders"] = len(data_loaders_data) if data_loaders_data else 0
        catalog["stats"]["total_processing_states"] = (
            len(processing_states_data) if processing_states_data else 0
        )
        catalog["stats"]["total_data_nodes"] = sum(
            len(wf.get("nodes", {})) for wf in (workflow_data or {}).values()
        )

        return catalog


def generate_docs(project_path: str, output_dir: Path) -> bool:
    """Generate documentation catalog from project workflows and write to output_dir."""
    project_root = Path(project_path).resolve()

    # Step 1: Scan project
    workflows_data = scanner.scan_workflows(project_root)

    if not workflows_data:
        logger.warning("No workflows found in %s", project_path)
        click.echo("No workflows found in project!")
        return False

    # Resolve tool_path from project config
    tool_paths = get_tool_dirs(project_root)

    # Scan tool functions once — reused by both the catalog data and each
    # WorkflowSchemaService (avoids N redundant AST parses for N workflows).
    tool_functions_data = scanner.scan_tool_functions(project_root, tool_paths)

    # Step 1b–1n: Scan all project artifacts
    prompts_data = scanner.scan_prompts(project_root)
    schemas_data = scanner.scan_schemas(project_root)
    runs_data = scanner.scan_runs(project_root)
    logs_data = scanner.scan_logs(project_root)
    vendors_data = scanner.scan_vendors(project_root)
    error_types_data = scanner.scan_error_types()
    event_types_data = scanner.scan_event_types()
    examples_data = scanner.scan_examples(project_root)
    data_loaders_data = scanner.scan_data_loaders()
    processing_states_data = scanner.scan_processing_states()
    workflow_data = scanner.scan_workflow_data(project_root)
    readmes_data = scanner.scan_readmes(project_root)

    # Step 2: Generate catalog
    catalog_gen = CatalogGenerator(
        workflows_data, project_path=project_path, tool_schemas=tool_functions_data
    )
    catalog = catalog_gen.generate(
        prompts_data=prompts_data,
        schemas_data=schemas_data,
        tool_functions_data=tool_functions_data,
        runs_data=runs_data,
        logs_data=logs_data,
        vendors_data=vendors_data,
        error_types_data=error_types_data,
        event_types_data=event_types_data,
        examples_data=examples_data,
        data_loaders_data=data_loaders_data,
        processing_states_data=processing_states_data,
        workflow_data=workflow_data,
        readmes_data=readmes_data,
    )

    # Step 3: Write data files
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write catalog.json (atomic write to prevent corruption on crash)
    catalog_path = output_dir / "catalog.json"
    dir_path = str(output_dir)
    fd, tmp = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(catalog, f, indent=2)
        os.replace(tmp, str(catalog_path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    # Initialize runs.json only if it doesn't exist
    # (RunTracker manages all updates to this file during workflow execution)
    runs_path = output_dir / "runs.json"
    if not runs_path.exists():
        with open(runs_path, "w", encoding="utf-8") as f:
            json.dump(_empty_runs_data(), f, indent=2)

    # Print summary
    stats = catalog["stats"]
    total_workflows = stats["total_workflows"]
    total_actions = stats["total_actions"]
    total_prompts = stats["total_prompts"]
    total_schemas = stats["total_schemas"]
    total_tool_functions = stats["total_tool_functions"]
    total_runs = stats["total_runs"]
    validation_errors = stats.get("validation_errors", 0)
    validation_warnings = stats.get("validation_warnings", 0)
    total_vendors = stats.get("total_vendors", 0)
    total_error_types = stats.get("total_error_types", 0)
    total_event_types = stats.get("total_event_types", 0)
    total_examples = stats.get("total_examples", 0)
    total_data_loaders = stats.get("total_data_loaders", 0)
    total_processing_states = stats.get("total_processing_states", 0)
    total_data_nodes = stats.get("total_data_nodes", 0)

    # Show path relative to CWD if possible, otherwise absolute
    try:
        display_path = output_dir.relative_to(Path.cwd())
    except ValueError:
        display_path = output_dir

    click.echo("\nBuilding catalog")
    click.echo(f"  Found {total_workflows} workflow{'s' if total_workflows != 1 else ''}")
    click.echo(f"  Compiled {total_actions} action{'s' if total_actions != 1 else ''}")
    click.echo(f"  Discovered {total_prompts} prompt{'s' if total_prompts != 1 else ''}")
    click.echo(f"  Loaded {total_schemas} schema{'s' if total_schemas != 1 else ''}")
    func_suffix = "s" if total_tool_functions != 1 else ""
    click.echo(f"  Indexed {total_tool_functions} tool function{func_suffix}")
    if total_runs > 0:
        click.echo(
            f"  Loaded {total_runs} workflow run{'s' if total_runs != 1 else ''} with metrics"
        )
    if validation_errors > 0 or validation_warnings > 0:
        click.echo(
            f"  Parsed logs: {validation_errors} error{'s' if validation_errors != 1 else ''}, {validation_warnings} warning{'s' if validation_warnings != 1 else ''}"
        )
    if total_vendors > 0:
        click.echo(f"  Scanned {total_vendors} vendor{'s' if total_vendors != 1 else ''}")
    if total_error_types > 0:
        click.echo(
            f"  Cataloged {total_error_types} error type{'s' if total_error_types != 1 else ''}"
        )
    if total_event_types > 0:
        click.echo(
            f"  Mapped {total_event_types} event type{'s' if total_event_types != 1 else ''}"
        )
    if total_examples > 0:
        click.echo(f"  Found {total_examples} example project{'s' if total_examples != 1 else ''}")
    if total_data_loaders > 0:
        click.echo(
            f"  Indexed {total_data_loaders} data loader{'s' if total_data_loaders != 1 else ''}"
        )
    if total_processing_states > 0:
        click.echo(
            f"  Parsed {total_processing_states} processing type{'s' if total_processing_states != 1 else ''}"
        )
    if total_data_nodes > 0:
        click.echo(
            f"  Exported {total_data_nodes} data node{'s' if total_data_nodes != 1 else ''} with previews"
        )
    logger.info(
        "Documentation catalog generated: %d workflows, %d actions",
        total_workflows,
        total_actions,
    )
    click.echo(f"\nDone. Documentation compiled to {display_path}/")

    return True
