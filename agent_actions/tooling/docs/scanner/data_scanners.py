"""Data-oriented scan functions: prompts, schemas, workflow DBs, runs, logs."""

import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigValidationError, SchemaValidationError
from agent_actions.output.response.loader import SchemaLoader
from agent_actions.prompt.handler import PromptLoader

from ..parser import extract_fields_for_docs

logger = logging.getLogger(__name__)


def scan_prompts(project_root: Path) -> dict[str, Any]:
    """Scan project directory for prompt files in prompt_store/."""
    prompts: dict[str, Any] = {}

    # Pattern to match {prompt name} ... {end_prompt} — unified with prompt.handler.PROMPT_PATTERN
    prompt_pattern = re.compile(r"\{prompt\s+([\w.]+)\}(.*?)\{end_prompt\}", re.DOTALL)

    for md_file in PromptLoader.discover_prompt_files(project_root):
        try:
            content = md_file.read_text()
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Skipping unreadable prompt file %s: %s", md_file, e)
            continue

        # Find all prompts in this file
        for match in prompt_pattern.finditer(content):
            prompt_name = match.group(1)
            prompt_content = match.group(2).strip()

            # Calculate line numbers
            content_before = content[: match.start()]
            line_start = content_before.count("\n") + 1
            line_end = line_start + prompt_content.count("\n")

            prompts[prompt_name] = {
                "id": prompt_name,
                "name": prompt_name,
                "content": prompt_content,
                "source_file": str(md_file),
                "source_file_name": md_file.name,
                "line_start": line_start,
                "line_end": line_end,
                "length": len(prompt_content),
            }

    return prompts


def scan_schemas(project_root: Path) -> dict[str, Any]:
    """Scan project directory for schema YAML files."""
    schemas: dict[str, Any] = {}
    try:
        all_schema_files = SchemaLoader.discover_schema_files(project_root)
    except (ConfigValidationError, OSError):
        return schemas  # No schema_path configured — no schemas to scan

    for schema_name, yml_file in all_schema_files.items():
        try:
            raw_schema = SchemaLoader.load_schema(schema_name, project_root=project_root)
        except SchemaValidationError as e:
            # Ambiguous name — docs cannot know which file the user means.
            logger.warning("Skipping ambiguous schema name '%s': %s", schema_name, e)
            continue
        except (FileNotFoundError, OSError, UnicodeDecodeError) as e:
            logger.warning("Skipping unreadable schema file %s: %s", yml_file, e)
            continue

        fields = extract_fields_for_docs(raw_schema)
        schema_type = raw_schema.get("type", "object")
        if "fields" in raw_schema:
            schema_type = "object"  # Unified format

        schemas[schema_name] = {
            "id": schema_name,
            "name": raw_schema.get("name", schema_name),
            "type": schema_type,
            "source_file": str(yml_file),
            "source_file_name": yml_file.name,
            "fields": fields,
            "field_count": len(fields),
        }

    return schemas


def scan_workflow_data(project_root: Path) -> dict[str, Any]:
    """Scan project for SQLite target databases and export preview data."""
    from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

    workflow_data = {}
    artefact_dir = project_root / "artefact"

    for agent_io_dir in sorted(project_root.rglob("agent_io*"), key=lambda p: p.name):
        if not agent_io_dir.is_dir() or not agent_io_dir.name.startswith("agent_io"):
            continue
        if artefact_dir in agent_io_dir.parents or agent_io_dir == artefact_dir:
            continue

        store_dir = agent_io_dir / "store"
        if not store_dir.exists():
            continue

        for db_file in store_dir.glob("*.db"):
            workflow_name = db_file.stem

            try:
                backend = SQLiteBackend.create_readonly(db_file)
                try:
                    data = backend.scan_data()
                    if data is not None:
                        workflow_data[workflow_name] = data
                finally:
                    backend.close()
            except (OSError, sqlite3.Error) as e:
                logger.warning("Failed to scan workflow DB %s: %s", db_file, e, exc_info=True)

    return workflow_data


def scan_runs(project_root: Path) -> dict[str, Any]:
    """Scan project directory for workflow run data and execution metrics."""
    import json

    runs_data = {}

    # Find all agent_io directories
    for agent_io_dir in sorted(project_root.rglob("agent_io*"), key=lambda p: p.name):
        if not agent_io_dir.is_dir() or not agent_io_dir.name.startswith("agent_io"):
            continue
        # Skip if inside artefact directory
        artefact_dir = project_root / "artefact"
        if artefact_dir in agent_io_dir.parents or agent_io_dir == artefact_dir:
            continue

        # Extract workflow name from path (parent of agent_io is workflow dir)
        workflow_dir = agent_io_dir.parent
        # Get the workflow name from agent_config if possible
        agent_config_dir = workflow_dir / "agent_config"
        workflow_name = None
        if agent_config_dir.exists():
            yml_files = list(agent_config_dir.glob("*.yml"))
            if yml_files:
                workflow_name = yml_files[0].stem

        if not workflow_name:
            workflow_name = workflow_dir.name

        logs_dir = agent_io_dir / "logs"
        target_dir = agent_io_dir / "target"

        # Load run_results.json for latest run metadata
        run_results_path = logs_dir / "run_results.json"
        if not run_results_path.exists():
            run_results_path = target_dir / "run_results.json"
        latest_run = None
        if run_results_path.exists():
            try:
                with open(run_results_path, encoding="utf-8") as f:
                    latest_run = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("Failed to load run_results %s: %s", run_results_path, e)

        # Load events.json for detailed execution data
        events_path = logs_dir / "events.json"
        if not events_path.exists():
            events_path = target_dir / "events.json"
        action_metrics = {}
        runtime_warnings: list[dict[str, Any]] = []
        if events_path.exists():
            try:
                action_metrics = extract_action_metrics(events_path)
            except (OSError, ValueError, KeyError) as e:
                logger.warning(
                    "Failed to extract action metrics from %s: %s",
                    events_path,
                    e,
                    exc_info=True,
                )
            try:
                runtime_warnings = extract_runtime_warnings(events_path)
            except (OSError, ValueError) as e:
                logger.debug(
                    "Failed to extract runtime warnings from %s: %s",
                    events_path,
                    e,
                )

        # Load .manifest.json for execution plan and per-action status
        manifest_path = logs_dir / ".manifest.json"
        if not manifest_path.exists():
            manifest_path = target_dir / ".manifest.json"
        manifest_data = None
        if manifest_path.exists():
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest_data = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("Failed to load manifest %s: %s", manifest_path, e)

        runs_data[workflow_name] = {
            "workflow_name": workflow_name,
            "latest_run": latest_run,
            "action_metrics": action_metrics,
            "runtime_warnings": runtime_warnings,
            "manifest": manifest_data,
            "run_results_path": str(run_results_path) if run_results_path.exists() else None,
            "events_path": str(events_path) if events_path.exists() else None,
            "manifest_path": str(manifest_path) if manifest_path.exists() else None,
        }

    return runs_data


def _iter_events(path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON events from a JSONL file, skipping malformed lines."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def scan_logs(project_root: Path) -> dict[str, Any]:
    """Scan project directory for global CLI and validation logs."""
    logs_data: dict[str, Any] = {
        "events_path": None,
        "recent_invocations": [],
        "validation_errors": [],
        "validation_warnings": [],
    }

    logs_dir = project_root / "logs"
    if not logs_dir.exists():
        return logs_data

    events_path = logs_dir / "events.json"
    if not events_path.exists():
        return logs_data

    logs_data["events_path"] = str(events_path)

    try:
        invocations: dict[str, dict[str, Any]] = {}
        for event in _iter_events(events_path):
            event_type = event.get("event_type")
            meta = event.get("meta", {})
            data = event.get("data", {})

            # Track invocations
            invocation_id = meta.get("invocation_id")
            if invocation_id and invocation_id not in invocations:
                invocations[invocation_id] = {
                    "invocation_id": invocation_id,
                    "timestamp": meta.get("timestamp"),
                    "workflow_name": meta.get("workflow_name"),
                    "command": None,
                }

            # Extract CLI command
            if event_type == "CLIArgumentParsingEvent":
                if invocation_id and invocation_id in invocations:
                    invocations[invocation_id]["command"] = data.get("command")

            # Collect validation errors
            if event_type == "ValidationErrorEvent":
                logs_data["validation_errors"].append(
                    {
                        "target": data.get("target"),
                        "error": data.get("error"),
                        "field": data.get("field"),
                        "timestamp": meta.get("timestamp"),
                    }
                )

            # Collect validation warnings
            if event_type == "ValidationWarningEvent":
                logs_data["validation_warnings"].append(
                    {
                        "target": data.get("target"),
                        "warning": data.get("warning"),
                        "field": data.get("field"),
                        "timestamp": meta.get("timestamp"),
                    }
                )

        # Get recent invocations (last 10)
        logs_data["recent_invocations"] = list(invocations.values())[-10:]

    except OSError as e:
        logger.debug("Could not read events log from %s: %s", events_path, e)

    return logs_data


def extract_runtime_warnings(events_path: Path) -> list[dict[str, Any]]:
    """Extract warn/error-level LogEvents from a target events.json file.

    These are operational warnings emitted during workflow execution
    (e.g., "All N records filtered by guard") that the docs site should
    surface alongside static validation events.
    """
    warnings: list[dict[str, Any]] = []

    try:
        for event in _iter_events(events_path):
            level = event.get("level")
            if level not in ("warn", "error"):
                continue

            meta = event.get("meta", {})
            warnings.append(
                {
                    "level": level,
                    "message": event.get("message", ""),
                    "action_name": meta.get("action_name"),
                    "timestamp": meta.get("timestamp"),
                    "event_type": event.get("event_type"),
                    "code": event.get("code"),
                }
            )

    except OSError as e:
        logger.debug("Could not read runtime warnings from %s: %s", events_path, e)

    return warnings


def extract_action_metrics(events_path: Path) -> dict[str, Any]:
    """Extract per-action metrics from events.json file."""
    action_metrics: dict[str, Any] = {}

    try:
        for event in _iter_events(events_path):
            event_type = event.get("event_type")
            meta = event.get("meta", {})
            data = event.get("data", {})
            agent_name = meta.get("action_name") or data.get("action_name")

            if not agent_name:
                continue

            if agent_name not in action_metrics:
                action_metrics[agent_name] = {
                    "execution_time": None,
                    "tokens": {},
                    "record_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "filtered_count": 0,
                    "skipped_count": 0,
                    "exhausted_count": 0,
                    "latency_ms": 0.0,
                    "llm_request_count": 0,
                    "provider": None,
                    "model": None,
                    "cache_miss_count": 0,
                }

            # Extract from ActionCompleteEvent
            if event_type == "ActionCompleteEvent":
                action_metrics[agent_name]["execution_time"] = data.get("execution_time")
                action_metrics[agent_name]["record_count"] = data.get("record_count", 0)
                if data.get("tokens"):
                    action_metrics[agent_name]["tokens"] = data["tokens"]

            # Extract from ResultCollectionCompleteEvent
            elif event_type == "ResultCollectionCompleteEvent":
                action_metrics[agent_name]["success_count"] = data.get("total_success", 0)
                action_metrics[agent_name]["failed_count"] = data.get("total_failed", 0)
                action_metrics[agent_name]["filtered_count"] = data.get("total_filtered", 0)
                action_metrics[agent_name]["skipped_count"] = data.get("total_skipped", 0)
                action_metrics[agent_name]["exhausted_count"] = data.get("total_exhausted", 0)

            # Extract from LLMResponseEvent for token counts, latency, provider
            elif event_type == "LLMResponseEvent":
                tokens = action_metrics[agent_name]["tokens"]
                tokens["prompt_tokens"] = tokens.get("prompt_tokens", 0) + data.get(
                    "prompt_tokens", 0
                )
                tokens["completion_tokens"] = tokens.get("completion_tokens", 0) + data.get(
                    "completion_tokens", 0
                )
                # Accumulate latency for averaging later
                action_metrics[agent_name]["latency_ms"] += data.get("latency_ms", 0.0)
                action_metrics[agent_name]["llm_request_count"] += 1
                # Capture provider/model from first LLM event
                if action_metrics[agent_name]["provider"] is None:
                    action_metrics[agent_name]["provider"] = data.get("provider") or None
                    action_metrics[agent_name]["model"] = data.get("model") or None

            # Extract from CacheMissEvent
            elif event_type == "CacheMissEvent":
                action_metrics[agent_name]["cache_miss_count"] += 1

    except OSError as e:
        logger.debug("Could not read action metrics from %s: %s", events_path, e)

    # Post-process: convert accumulated latency to average per LLM request.
    for metrics in action_metrics.values():
        req_count = metrics.pop("llm_request_count", 0)
        if req_count > 0:
            metrics["latency_ms"] = round(metrics["latency_ms"] / req_count, 1)

    return action_metrics
