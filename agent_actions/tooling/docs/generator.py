"""Catalog and runs data generator."""

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from agent_actions.config.path_config import get_tool_dirs
from agent_actions.models.action_schema import ActionSchema, FieldInfo, FieldSource
from agent_actions.prompt.context.scope_parsing import parse_field_reference
from agent_actions.utils.atomic_write import atomic_json_write
from agent_actions.utils.constants import DEFAULT_ACTION_KIND
from agent_actions.workflow.schema_service import WorkflowSchemaService

from . import scanner
from .parser import WorkflowParser
from .run_tracker import _empty_runs_data
from .scanner import PROBLEM_LEVELS, ReadmeData

logger = logging.getLogger(__name__)


def _event_sort_key(event: dict) -> tuple[str, int]:
    """Order by emit time, then by position in the log the row came from.

    Defensive about shape: these rows are read back from a file on disk, and one
    malformed row must not abort the whole catalog build.
    """
    meta = event.get("meta")
    timestamp = meta.get("timestamp") if isinstance(meta, dict) else None
    seq = event.get("seq")
    return (str(timestamp or ""), seq if isinstance(seq, int) else 0)


# Scanner projections that exist to be folded into the catalog, not shipped in it.
_PER_LOG_ONLY = frozenset({"events", "level_counts", "is_workflow"})

# Derived, so a level the scanner retains always has a pass here — without one
# its rows are a problem nothing asks for, and they vanish. The equal share, not
# this order, is what protects a rare level from a common one.
_SEVERITY = ("error", "warn")


def problem_priority(levels: tuple[str, ...]) -> tuple[str, ...]:
    """Rarest known severity first; anything unranked still gets its own pass."""
    return tuple(
        sorted(levels, key=lambda lv: _SEVERITY.index(lv) if lv in _SEVERITY else len(_SEVERITY))
    )


PROBLEM_PRIORITY = problem_priority(PROBLEM_LEVELS)


def _round_robin(queues: list[list[dict]], budget: int) -> list[dict]:
    """Take from each queue in turn until the budget runs out."""
    taken: list[dict] = []
    for depth in range(max((len(q) for q in queues), default=0)):
        if len(taken) >= budget:
            break
        for queue in queues:
            if depth < len(queue) and len(taken) < budget:
                taken.append(queue[depth])
    return taken


def _merge_event_tails(sources: list[tuple[str, list[dict]]], limit: int) -> list[dict]:
    """Merge per-log event tails into one reverse-chronological window.

    Problems and recent rows each hold half, either spending what the other
    cannot fill; the problem half is filled rarest level first, or warnings
    crowd out errors here as they do inside one log's budget. Each pass is
    round-robin because a project-level log accumulates across every CLI
    invocation and a global sort hands it everything. Sources are pairs: a
    workflow may share a name with the project log.
    """
    stamped = [
        [{**evt, "id": f"{name}:{evt.get('seq')}"} for evt in reversed(rows)]
        for name, rows in sources
        if rows
    ]
    is_problem = lambda evt: evt.get("level") in PROBLEM_LEVELS  # noqa: E731
    recent = [[e for e in q if not is_problem(e)] for q in stamped]

    budget = max(limit // 2, limit - sum(len(q) for q in recent))
    by_level = {
        level: [[e for e in q if e.get("level") == level] for q in stamped]
        for level in PROBLEM_PRIORITY
    }

    # Each level owns a share of the problem half, for the reason the per-log
    # budgets are per level: whichever level is loudest would otherwise take it
    # all. Rarest first, then whatever a level could not fill is offered back.
    share = budget // len(PROBLEM_PRIORITY) if PROBLEM_PRIORITY else 0
    merged: list[dict] = []
    taken = {}
    for level in PROBLEM_PRIORITY:
        rows = _round_robin(by_level[level], share)
        taken[level] = len(rows)
        merged += rows
    for level in PROBLEM_PRIORITY:
        if len(merged) >= budget:
            break
        want = taken[level] + (budget - len(merged))
        merged += _round_robin(by_level[level], want)[taken[level] :]

    merged += _round_robin(recent, limit - len(merged))
    merged.sort(key=_event_sort_key, reverse=True)
    return merged


def _copy_readme_images(
    readme_data: ReadmeData,
    workflow_id: str,
    artefact_dir: Path,
) -> str:
    """Copy images referenced in README to artefact/images/ and rewrite paths.

    Substitutions are applied at exact regex-match spans (not via
    ``str.replace``) so that a short relative path like ``logo.png`` is not
    rewritten inside an unrelated longer path like ``dark/logo.png``.

    A copy failure for one image (disk full, permission error, etc.) is
    logged and skipped — the catalog generation continues for the remaining
    images.
    """
    content = readme_data.content
    images_dir = artefact_dir / "images" / workflow_id

    # Match both <img src="..."> and ![alt](...) and capture the URL group
    # so the replacement span is limited to the path itself.
    img_patterns: list[tuple[re.Pattern[str], int]] = [
        (re.compile(r'<img\s+[^>]*src="([^"]+)"'), 1),
        (re.compile(r"!\[([^\]]*)\]\(([^)]+)\)"), 2),
    ]

    # (start, end, replacement) for each URL-group span we want to rewrite.
    # No dedup set is needed: html and markdown URL spans live in disjoint
    # surrounding chars (`src="..."` vs `](...)`) so their (start, end) tuples
    # can never coincide, and `finditer` already yields non-overlapping
    # matches within a single pattern.
    spans: list[tuple[int, int, str]] = []
    images_dir_ready = False

    for pattern, group_idx in img_patterns:
        for match in pattern.finditer(content):
            rel_path = match.group(group_idx)

            # Skip URLs (http://, https://, data:)
            if rel_path.startswith(("http://", "https://", "data:")):
                continue

            # Resolve relative to README's directory
            source = (readme_data.source_dir / rel_path).resolve()
            if not source.exists() or not source.is_file():
                continue

            # Lazy-create the images directory the first time we have a
            # genuine image to stage. A failure here is systemic (parent
            # unwritable) so we abandon the rewrite entirely instead of
            # logging the same diagnostic per image.
            if not images_dir_ready:
                try:
                    images_dir.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    logger.warning(
                        "Cannot create images directory %s for workflow %s: %s",
                        images_dir,
                        workflow_id,
                        e,
                    )
                    return content
                images_dir_ready = True

            # Copy to artefact/images/{workflow_id}/{filename}. A single
            # copy failure must not abort the rest of the catalog.
            dest = images_dir / source.name
            try:
                shutil.copy2(source, dest)
            except OSError as e:
                logger.warning(
                    "Failed to copy README image %s for workflow %s: %s",
                    source,
                    workflow_id,
                    e,
                )
                continue

            new_path = f"/artefact/images/{workflow_id}/{source.name}"
            spans.append(match.span(group_idx) + (new_path,))

    if not spans:
        return content

    # Apply substitutions right-to-left so earlier offsets remain valid as
    # we splice into the string.
    spans.sort(key=lambda s: s[0], reverse=True)
    for start, end, new_text in spans:
        content = content[:start] + new_text + content[end:]

    return content


def _reported_drop_refs(context_scope: dict[str, Any]) -> list[str]:
    """The `context_scope.drop` refs the runtime can perform, in its own spelling.

    The namespace is kept because the runtime removes `prompt_context[ns][field]`, so
    `upstream.body` and `body` are different claims when an action declares a field of
    its own by that name. A ref that does not parse is excluded: the runtime logs
    "Field will NOT be removed" and skips it. So is one carrying a wildcard inside the
    path (`a.*.c`) — there is no path to walk, and the runtime warns that it removed
    nothing. A dotted path IS reported: the runtime traverses it (#1116), so reporting it
    describes a drop that really runs.
    """
    refs = context_scope.get("drop")
    if not isinstance(refs, list):
        return []
    reported: list[str] = []
    for ref in refs:
        try:
            namespace, field = parse_field_reference(ref)
        except ValueError:
            continue
        if field != "*" and "*" in field:
            continue
        actionable = f"{namespace}.{field}"
        if actionable not in reported:
            reported.append(actionable)
    return reported


_STAT_KEYS = (
    "total_workflows",
    "total_actions",
    "llm_actions",
    "tool_actions",
    "total_prompts",
    "total_schemas",
    "total_tool_functions",
    "total_runs",
    "validation_errors",
    "validation_warnings",
    "runtime_warnings",
    "runtime_errors",
    "total_vendors",
    "total_error_types",
    "total_event_types",
    "total_examples",
    "total_data_loaders",
    "total_processing_states",
    "total_data_nodes",
)


def _size(data: Any) -> int:
    return len(data) if data else 0


def _with_used_by(entries: dict[str, Any] | None) -> dict[str, Any]:
    """Copy each entry with an empty ``used_by`` list for the actions that reference it."""
    with_refs = {}
    for name, data in (entries or {}).items():
        with_refs[name] = data.copy()
        with_refs[name]["used_by"] = []
    return with_refs


def _record_use(entries: dict[str, Any], ref: Any, workflow_id: str, action_name: str) -> None:
    if ref and ref in entries:
        entries[ref]["used_by"].append({"workflow": workflow_id, "action": action_name})


def _readme_for(
    readmes_data: dict[str, ReadmeData] | None, workflow_id: str, artefact_dir: Path | None
) -> str | None:
    if not readmes_data or workflow_id not in readmes_data:
        return None
    if artefact_dir:
        return _copy_readme_images(readmes_data[workflow_id], workflow_id, artefact_dir)
    return readmes_data[workflow_id].content


def _count_workflow(stats: dict[str, Any], actions: dict[str, Any]) -> None:
    stats["total_workflows"] += 1
    stats["total_actions"] += len(actions)
    for action in actions.values():
        if action.get("type") == DEFAULT_ACTION_KIND:
            stats["llm_actions"] += 1
        elif action.get("type") == "tool":
            stats["tool_actions"] += 1


def _runtime_warning_entries(
    runs_data: dict[str, Any] | None,
) -> tuple[list[dict], list[dict]]:
    """Split every workflow's runtime warnings into (warnings, errors) catalog rows."""
    warnings: list[dict] = []
    errors: list[dict] = []
    for wf_data in (runs_data or {}).values():
        for evt in wf_data.get("runtime_warnings", []):
            target = evt.get("action_name") or evt.get("event_type") or "NOT_SET"
            entry = {
                "target": target,
                "message": evt.get("message", ""),
                "timestamp": evt.get("timestamp", ""),
            }
            if evt.get("level") == "error":
                errors.append(entry)
            else:
                warnings.append(entry)
    return warnings, errors


def _failed_execution_entries(executions_data: list[dict[str, Any]] | None) -> list[dict]:
    """Runtime error rows for each failed run and failed action in runs.json."""
    entries: list[dict] = []
    for exec_rec in executions_data or []:
        status = (exec_rec.get("status") or "").upper()
        if status == "FAILED":
            entries.append(
                {
                    "target": exec_rec.get("workflow_name")
                    or exec_rec.get("workflow_id")
                    or "NOT_SET",
                    "message": exec_rec.get("error_message")
                    or f"Run {exec_rec.get('id', '?')} failed",
                    "timestamp": exec_rec.get("ended_at") or exec_rec.get("started_at") or "",
                }
            )
        for action_name, action_data in (exec_rec.get("actions") or {}).items():
            if (action_data.get("status") or "").upper() == "FAILED":
                entries.append(
                    {
                        "target": action_name,
                        "message": action_data.get("error")
                        or f"Action {action_name} failed in run {exec_rec.get('id', '?')}",
                        "timestamp": action_data.get("ended_at")
                        or exec_rec.get("started_at")
                        or "",
                    }
                )
    return entries


def _event_sources(
    logs_data: dict[str, Any] | None, runs_data: dict[str, Any] | None
) -> list[tuple[str, list[dict]]]:
    """Every log the project wrote, each under a distinct name that row ids are built from."""
    taken_names: set[str] = set()

    def distinct(name: str) -> str:
        candidate, suffix = name, 2
        while candidate in taken_names:
            candidate, suffix = f"{name}~{suffix}", suffix + 1
        taken_names.add(candidate)
        return candidate

    sources: list[tuple[str, list[dict]]] = [
        (distinct("project:logs"), (logs_data or {}).get("events", []))
    ]
    # A stray directory yields a run entry named after itself, and only the
    # scanner knows whether it read a workflow config for it.
    sources += [
        (
            distinct(f"{'workflow' if data.get('is_workflow', True) else 'project'}:{name}"),
            data.get("events", []),
        )
        for name, data in sorted((runs_data or {}).items())
    ]
    return sources


def _event_level_totals(
    logs_data: dict[str, Any] | None, runs_data: dict[str, Any] | None
) -> dict[str, int]:
    """Totals over every log, so "N in view" can be read against the whole."""
    event_levels: dict[str, int] = {}
    for counts in [(logs_data or {}).get("level_counts", {})] + [
        data.get("level_counts", {}) for data in (runs_data or {}).values()
    ]:
        for level, n in counts.items():
            event_levels[level] = event_levels.get(level, 0) + n
    return event_levels


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
            # Key presence is not a mapping: the docs parser reads raw YAML
            # (`parser.py:188`) with no validation layer, so `context_scope:` null or a
            # scalar arrives as written (#1193).
            context_scope = action["context_scope"]
            if not isinstance(context_scope, dict):
                context_scope = {}
            inputs = self.parser.extract_input_fields(context_scope)
            if inputs:
                enriched["inputs"] = inputs
            drops = _reported_drop_refs(context_scope)
            if drops:
                enriched["drops"] = drops

        # Clean up internal fields not needed in catalog
        enriched.pop("context_scope", None)

        return enriched

    def _enrich_workflow_actions(
        self,
        catalog: dict[str, Any],
        workflow_id: str,
        workflow: dict[str, Any],
        tool_functions_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Enrich a workflow's actions, index them, and record prompt/schema use."""
        schema_service = self._build_schema_service(workflow)
        enriched_actions = {}

        for action_name, action in workflow["actions"].items():
            action_schema = (
                schema_service.get_action_schema(action_name) if schema_service else None
            )
            enriched_action = self._enrich_action_with_fields(action, action_schema)

            if action.get("type") == "tool" and tool_functions_data:
                impl_name = action.get("implementation")
                if impl_name and impl_name in tool_functions_data:
                    enriched_action["tool_function"] = tool_functions_data[impl_name]

            enriched_actions[action_name] = enriched_action

            action_with_workflow = enriched_action.copy()
            action_with_workflow["workflow_id"] = workflow_id
            catalog["actions"][f"{workflow_id}.{action_name}"] = action_with_workflow

            _record_use(catalog["prompts"], action.get("prompt"), workflow_id, action_name)
            schema_ref = action.get("schema")
            if isinstance(schema_ref, str):
                _record_use(catalog["schemas"], schema_ref, workflow_id, action_name)

        return enriched_actions

    def _add_workflow(
        self,
        catalog: dict[str, Any],
        workflow_id: str,
        paths: dict[str, Any],
        tool_functions_data: dict[str, Any] | None,
        runs_data: dict[str, Any] | None,
        readmes_data: dict[str, ReadmeData] | None,
        artefact_dir: Path | None,
    ) -> None:
        """Parse one workflow and add its entry, actions and counts to the catalog."""
        # Use rendered workflow if available, otherwise use original
        yaml_path = paths["rendered"] or paths["original"]
        workflow = self.parser.parse_workflow(
            yaml_path, self.project_path, rendered=bool(paths["rendered"])
        )
        if workflow is None:
            return

        enriched_actions = self._enrich_workflow_actions(
            catalog, workflow_id, workflow, tool_functions_data
        )

        workflow_runs = runs_data[workflow_id] if runs_data and workflow_id in runs_data else {}
        for action_name, metrics in workflow_runs.get("action_metrics", {}).items():
            if action_name in enriched_actions:
                enriched_actions[action_name]["metrics"] = metrics

        catalog["workflows"][workflow_id] = {
            "id": workflow_id,
            "name": workflow["name"],
            "description": workflow["description"],
            "path": workflow["path"],
            "version": workflow["version"],
            "defaults": workflow.get("defaults", {}),
            "actions": enriched_actions,
            "action_count": len(enriched_actions),
            "latest_run": workflow_runs.get("latest_run"),
            "manifest": workflow_runs.get("manifest"),
            "readme": _readme_for(readmes_data, workflow_id, artefact_dir),
        }

        _count_workflow(catalog["stats"], workflow["actions"])

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
        readmes_data: dict[str, ReadmeData] | None = None,
        executions_data: list[dict[str, Any]] | None = None,
        artefact_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Generate the complete catalog structure."""
        project_name = self.project_path.name if self.project_path else None
        catalog = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_workflows": len(self.workflows_data),
                "generator_version": "1.1.0",
                "project_name": project_name,
            },
            "workflows": {},
            "actions": {},  # Flattened index for faster lookup
            "prompts": _with_used_by(prompts_data),
            "schemas": _with_used_by(schemas_data),
            "tool_functions": tool_functions_data or {},
            # Each workflow's event tail is merged into logs.events below; keeping
            # the per-workflow copy here too would ship the same rows twice.
            "runs": {
                name: {k: v for k, v in data.items() if k not in _PER_LOG_ONLY}
                for name, data in (runs_data or {}).items()
            },
            # Global CLI logs and validation events. Copied, not aliased: the
            # caller's dict is still read below to build the event window.
            "logs": {k: v for k, v in (logs_data or {}).items() if k not in _PER_LOG_ONLY},
            "vendors": vendors_data or {},  # LLM vendor configurations
            "error_types": error_types_data or {},  # Error class hierarchy
            "event_types": event_types_data or {},  # Event type definitions
            "examples": examples_data or {},  # Example projects
            "data_loaders": data_loaders_data or {},  # Data loader implementations
            "processing_states": processing_states_data or {},  # Processing enums/types
            "workflow_data": workflow_data or {},  # Workflow output data previews
            "stats": dict.fromkeys(_STAT_KEYS, 0),
        }

        for workflow_id, paths in self.workflows_data.items():
            self._add_workflow(
                catalog,
                workflow_id,
                paths,
                tool_functions_data,
                runs_data,
                readmes_data,
                artefact_dir,
            )

        stats = catalog["stats"]
        stats["total_schemas"] = _size(schemas_data)
        stats["total_prompts"] = _size(prompts_data)
        stats["total_tool_functions"] = _size(tool_functions_data)
        stats["total_runs"] = _size(executions_data)

        if logs_data:
            stats["validation_errors"] = len(logs_data.get("validation_errors", []))
            stats["validation_warnings"] = len(logs_data.get("validation_warnings", []))

        runtime_warn_entries, runtime_error_entries = _runtime_warning_entries(runs_data)
        runtime_error_entries += _failed_execution_entries(executions_data)
        catalog["logs"]["runtime_warnings"] = runtime_warn_entries
        catalog["logs"]["runtime_errors"] = runtime_error_entries
        stats["runtime_warnings"] = len(runtime_warn_entries)
        stats["runtime_errors"] = len(runtime_error_entries)

        catalog["logs"]["events"] = _merge_event_tails(
            _event_sources(logs_data, runs_data), scanner.EVENT_TAIL_LIMIT
        )
        stats["event_levels"] = _event_level_totals(logs_data, runs_data)

        stats["total_vendors"] = _size(vendors_data)
        stats["total_error_types"] = sum(
            cat.get("error_count", 0) for cat in (error_types_data or {}).values()
        )
        stats["total_event_types"] = sum(
            cat.get("event_count", 0) for cat in (event_types_data or {}).values()
        )
        stats["total_examples"] = _size(examples_data)
        stats["total_data_loaders"] = _size(data_loaders_data)
        stats["total_processing_states"] = _size(processing_states_data)
        stats["total_data_nodes"] = sum(
            len(wf.get("nodes", {})) for wf in (workflow_data or {}).values()
        )

        return catalog


def _scan_project_artifacts(project_root: Path) -> dict[str, Any]:
    """Scan every catalog input except workflows and tool functions, in a fixed order."""
    return {
        "prompts_data": scanner.scan_prompts(project_root),
        "schemas_data": scanner.scan_schemas(project_root),
        "runs_data": scanner.scan_runs(project_root),
        "logs_data": scanner.scan_logs(project_root),
        "vendors_data": scanner.scan_vendors(project_root),
        "error_types_data": scanner.scan_error_types(),
        "event_types_data": scanner.scan_event_types(),
        "examples_data": scanner.scan_examples(project_root),
        "data_loaders_data": scanner.scan_data_loaders(),
        "processing_states_data": scanner.scan_processing_states(),
        "workflow_data": scanner.scan_workflow_data(project_root),
        "readmes_data": scanner.scan_readmes(project_root),
    }


def _load_executions(runs_path: Path) -> list[dict[str, Any]]:
    """Read the executions already in runs.json so failed runs surface in catalog logs."""
    if not runs_path.exists():
        return []
    try:
        with open(runs_path, encoding="utf-8") as f:
            runs_json = json.load(f)
        executions: list[dict[str, Any]] = runs_json.get("executions", [])
        return executions
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("Failed to load runs.json for execution data: %s", e)
        return []


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}{'s' if count != 1 else ''}"


# (stat key, verb, noun, suffix) for summary lines printed only when the count is positive.
_OPTIONAL_SUMMARY_LINES = (
    ("total_vendors", "Scanned", "vendor", ""),
    ("total_error_types", "Cataloged", "error type", ""),
    ("total_event_types", "Mapped", "event type", ""),
    ("total_examples", "Found", "example project", ""),
    ("total_data_loaders", "Indexed", "data loader", ""),
    ("total_processing_states", "Parsed", "processing type", ""),
    ("total_data_nodes", "Exported", "data node", " with previews"),
)


def _echo_error_warning_line(label: str, errors: int, warnings: int) -> None:
    if errors > 0 or warnings > 0:
        click.echo(f"  {label}: {_counted(errors, 'error')}, {_counted(warnings, 'warning')}")


def _echo_summary(stats: dict[str, Any], output_dir: Path) -> None:
    total_workflows = stats["total_workflows"]
    total_actions = stats["total_actions"]
    core_lines = (
        ("Found", total_workflows, "workflow"),
        ("Compiled", total_actions, "action"),
        ("Discovered", stats["total_prompts"], "prompt"),
        ("Loaded", stats["total_schemas"], "schema"),
        ("Indexed", stats["total_tool_functions"], "tool function"),
    )
    total_runs = stats["total_runs"]

    # Show path relative to CWD if possible, otherwise absolute
    try:
        display_path = output_dir.relative_to(Path.cwd())
    except ValueError:
        display_path = output_dir

    click.echo("\nBuilding catalog")
    for verb, count, noun in core_lines:
        click.echo(f"  {verb} {_counted(count, noun)}")
    if total_runs > 0:
        click.echo(f"  Loaded {_counted(total_runs, 'workflow run')} with metrics")
    _echo_error_warning_line(
        "Parsed logs", stats.get("validation_errors", 0), stats.get("validation_warnings", 0)
    )
    _echo_error_warning_line(
        "Runtime events", stats.get("runtime_errors", 0), stats.get("runtime_warnings", 0)
    )
    for key, verb, noun, suffix in _OPTIONAL_SUMMARY_LINES:
        count = stats.get(key, 0)
        if count > 0:
            click.echo(f"  {verb} {_counted(count, noun)}{suffix}")
    logger.info(
        "Documentation catalog generated: %d workflows, %d actions",
        total_workflows,
        total_actions,
    )
    click.echo(f"\nDone. Documentation compiled to {display_path}/")


def generate_docs(project_path: str, output_dir: Path) -> bool:
    """Generate documentation catalog from project workflows and write to output_dir."""
    project_root = Path(project_path).resolve()

    workflows_data = scanner.scan_workflows(project_root)
    if not workflows_data:
        logger.warning("No workflows found in %s", project_path)
        click.echo("No workflows found in project!")
        return False

    # Scan tool functions once — reused by both the catalog data and each
    # WorkflowSchemaService (avoids N redundant AST parses for N workflows).
    tool_functions_data = scanner.scan_tool_functions(project_root, get_tool_dirs(project_root))
    artifacts = _scan_project_artifacts(project_root)
    executions_data = _load_executions(output_dir / "runs.json")

    catalog_gen = CatalogGenerator(
        workflows_data, project_path=project_path, tool_schemas=tool_functions_data
    )
    catalog = catalog_gen.generate(
        tool_functions_data=tool_functions_data,
        executions_data=executions_data,
        artefact_dir=output_dir,
        **artifacts,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json_write(output_dir / "catalog.json", catalog, indent=2, fsync=False)

    # Initialize runs.json only if it doesn't exist
    # (RunTracker manages all updates to this file during workflow execution)
    runs_path = output_dir / "runs.json"
    if not runs_path.exists():
        atomic_json_write(runs_path, _empty_runs_data(), indent=2, fsync=False)

    _echo_summary(catalog["stats"], output_dir)
    return True
