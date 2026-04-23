"""Data-oriented scan functions: prompts, schemas, workflow DBs, runs, logs."""

import itertools
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigValidationError
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
    workflow_data = {}
    artefact_dir = project_root / "artefact"

    for agent_io_dir in project_root.rglob("agent_io"):
        if artefact_dir in agent_io_dir.parents or agent_io_dir == artefact_dir:
            continue

        store_dir = agent_io_dir / "store"
        if not store_dir.exists():
            continue

        for db_file in store_dir.glob("*.db"):
            workflow_name = db_file.stem

            try:
                data = scan_sqlite_readonly(db_file, workflow_name)
                if data is not None:
                    workflow_data[workflow_name] = data
            except (OSError, sqlite3.Error) as e:
                logger.warning("Failed to scan workflow DB %s: %s", db_file, e, exc_info=True)

    return workflow_data


def _unwrap_record_content(record: dict, action_name: str) -> dict:
    """Unwrap namespaced content for a specific action.

    With the additive model, record["content"] is
    {"action_a": {...}, "action_b": {...}, ...}. Replace it with the
    specific action's fields so consumers see actual output data.
    """
    content = record.get("content")
    if (
        isinstance(content, dict)
        and action_name in content
        and isinstance(content[action_name], dict)
    ):
        return {**record, "content": content[action_name]}
    return record


def scan_sqlite_readonly(db_file: Path, workflow_name: str) -> dict[str, Any] | None:
    """Open a workflow SQLite DB read-only and extract stats + preview data.

    Uses a direct sqlite3 connection in read-only mode so that scanning
    never modifies the database (safe on read-only mounts/checkouts).

    Tries ``mode=ro`` first so WAL data from active writers is visible.
    Falls back to ``immutable=1`` when the filesystem is truly read-only
    (``mode=ro`` still attempts WAL sidecar writes and raises
    ``OperationalError`` on read-only mounts).
    """
    import json as _json
    import sqlite3

    # Percent-encode the path so that # and ? in directory names
    # are treated as path bytes, not URI fragment/query separators.
    import urllib.parse

    # as_posix() ensures forward slashes on all platforms (Windows included).
    posix_path = db_file.as_posix()
    # Guarantee the path starts with / so file://{path} always has an
    # empty URI authority.  Unix paths already start with /; Windows
    # drive paths (C:/...) do not; UNC paths (//server/...) are fine.
    if not posix_path.startswith("/"):
        posix_path = "/" + posix_path
    encoded_path = urllib.parse.quote(posix_path, safe="/:")

    # mode=ro sees live WAL data; immutable=1 skips WAL but works on
    # read-only filesystems.  Try the richer mode first.
    ro_uri = f"file://{encoded_path}?mode=ro"
    try:
        conn = sqlite3.connect(ro_uri, uri=True)
        conn.row_factory = sqlite3.Row
        # Probe to surface WAL sidecar errors early.
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
    except sqlite3.OperationalError:
        conn = sqlite3.connect(f"file://{encoded_path}?immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()

        # Source count
        cursor.execute("SELECT COUNT(*) as count FROM source_data")
        source_count = cursor.fetchone()["count"]

        # Target counts per node — COALESCE guards against NULL record_count rows
        cursor.execute(
            "SELECT action_name, COALESCE(SUM(record_count), 0) as count "
            "FROM target_data GROUP BY action_name ORDER BY action_name"
        )
        node_counts = {row["action_name"]: row["count"] for row in cursor.fetchall()}

        # Total target count
        cursor.execute("SELECT SUM(record_count) as count FROM target_data")
        row = cursor.fetchone()
        target_count = row["count"] if row["count"] else 0

        # DB size
        db_size = db_file.stat().st_size if db_file.exists() else 0

        # Preview records per node
        nodes = {}
        for action_name, record_count in node_counts.items():
            # Collect ALL files for this action (no limit)
            cursor.execute(
                "SELECT DISTINCT relative_path FROM target_data "
                "WHERE action_name = ? ORDER BY relative_path",
                (action_name,),
            )
            files = [row["relative_path"] for row in cursor.fetchall()]

            # Preview: iterate the cursor lazily so we never load every
            # data blob into memory.  Cap at 20 flattened records.
            cursor.execute(
                "SELECT relative_path, data FROM target_data WHERE action_name = ?",
                (action_name,),
            )
            records: list[dict] = []
            for target_row in cursor:
                if len(records) >= 20:
                    break
                try:
                    row_data = _json.loads(target_row["data"])
                except (ValueError, _json.JSONDecodeError):
                    logger.debug(
                        "Skipping malformed JSON in %s node %s, file %s",
                        workflow_name,
                        action_name,
                        target_row["relative_path"],
                    )
                    continue
                file_path = target_row["relative_path"]
                if isinstance(row_data, list):
                    for item in row_data:
                        if len(records) >= 20:
                            break
                        if isinstance(item, dict):
                            item = _unwrap_record_content(item, action_name)
                            records.append({**item, "_file": file_path})
                        else:
                            records.append({"_file": file_path, "_value": item})
                elif isinstance(row_data, dict):
                    row_data = _unwrap_record_content(row_data, action_name)
                    records.append({**row_data, "_file": file_path})
                else:
                    records.append({"_file": file_path, "_value": row_data})
            nodes[action_name] = {
                "record_count": record_count,
                "files": files,
                "preview": records,
            }

        # Attach prompt traces to preview records (if table exists).
        # The prompt_trace table was added in v0.1.6; older DBs won't have it.
        try:
            for action_name, node_data in nodes.items():
                # Map source_guid → list of records (multiple records can share a guid)
                guid_map: dict[str, list[dict]] = {}
                for rec in node_data["preview"]:
                    sg = rec.get("source_guid")
                    if sg:
                        guid_map.setdefault(sg, []).append(rec)

                if not guid_map:
                    continue

                placeholders = ",".join("?" for _ in guid_map)
                cursor.execute(
                    f"SELECT record_id, compiled_prompt, llm_context, "
                    f"response_text, model_name, model_vendor, run_mode, "
                    f"prompt_length, response_length, attempt "
                    f"FROM prompt_trace "
                    f"WHERE action_name = ? AND record_id IN ({placeholders})"
                    f" ORDER BY attempt DESC",
                    [action_name, *guid_map.keys()],
                )
                seen: set[str] = set()
                for trace_row in cursor:
                    rid = trace_row["record_id"]
                    if rid in seen:
                        continue
                    seen.add(rid)
                    trace_data = {
                        "compiled_prompt": trace_row["compiled_prompt"],
                        "llm_context": trace_row["llm_context"],
                        "response_text": trace_row["response_text"],
                        "model_name": trace_row["model_name"],
                        "model_vendor": trace_row["model_vendor"],
                        "run_mode": trace_row["run_mode"],
                        "prompt_length": trace_row["prompt_length"],
                        "response_length": trace_row["response_length"],
                        "attempt": trace_row["attempt"],
                    }
                    for rec in guid_map.get(rid, []):
                        rec["_trace"] = trace_data
        except sqlite3.OperationalError:
            logger.debug("No prompt_trace table in %s — skipping trace attachment", db_file)

        # Format size
        if db_size < 1024:
            size_human = f"{db_size} B"
        elif db_size < 1024 * 1024:
            size_human = f"{db_size / 1024:.1f} KB"
        elif db_size < 1024 * 1024 * 1024:
            size_human = f"{db_size / (1024 * 1024):.1f} MB"
        elif db_size < 1024 * 1024 * 1024 * 1024:
            size_human = f"{db_size / (1024 * 1024 * 1024):.1f} GB"
        else:
            size_human = f"{db_size / (1024 * 1024 * 1024 * 1024):.1f} TB"

        return {
            "db_path": str(db_file),
            "db_size": size_human,
            "source_count": source_count,
            "target_count": target_count,
            "nodes": nodes,
        }
    finally:
        conn.close()


def scan_runs(project_root: Path) -> dict[str, Any]:
    """Scan project directory for workflow run data and execution metrics."""
    import json

    runs_data = {}

    # Find all agent_io directories
    for agent_io_dir in project_root.rglob("agent_io"):
        # Skip if inside artefact directory
        artefact_dir = project_root / "artefact"
        if artefact_dir in agent_io_dir.parents or agent_io_dir == artefact_dir:
            continue

        target_dir = agent_io_dir / "target"
        if not target_dir.exists():
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

        # Load run_results.json for latest run metadata
        run_results_path = target_dir / "run_results.json"
        latest_run = None
        if run_results_path.exists():
            try:
                with open(run_results_path, encoding="utf-8") as f:
                    latest_run = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("Failed to load run_results %s: %s", run_results_path, e)

        # Load events.json for detailed execution data
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


def scan_logs(project_root: Path) -> dict[str, Any]:
    """Scan project directory for global CLI and validation logs."""
    import json

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

    _LOG_LINE_LIMIT = 100_000
    try:
        with open(events_path, encoding="utf-8") as f:
            invocations = {}
            line_count = 0
            for line in itertools.islice(f, _LOG_LINE_LIMIT):
                line_count += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

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

            if line_count >= _LOG_LINE_LIMIT:
                logger.warning(
                    "scan_logs: line limit (%d) reached for %s; some events may be omitted",
                    _LOG_LINE_LIMIT,
                    events_path,
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
    import json

    warnings: list[dict[str, Any]] = []

    _LOG_LINE_LIMIT = 100_000
    try:
        with open(events_path, encoding="utf-8") as f:
            line_count = 0
            for line in itertools.islice(f, _LOG_LINE_LIMIT):
                line_count += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

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

            if line_count >= _LOG_LINE_LIMIT:
                logger.warning(
                    "extract_runtime_warnings: line limit (%d) reached for %s; "
                    "some events may be omitted",
                    _LOG_LINE_LIMIT,
                    events_path,
                )

    except OSError as e:
        logger.debug("Could not read runtime warnings from %s: %s", events_path, e)

    return warnings


def extract_action_metrics(events_path: Path) -> dict[str, Any]:
    """Extract per-action metrics from events.json file."""
    import json

    action_metrics: dict[str, Any] = {}

    _LOG_LINE_LIMIT = 100_000
    try:
        with open(events_path, encoding="utf-8") as f:
            line_count = 0
            for line in itertools.islice(f, _LOG_LINE_LIMIT):
                line_count += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

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

            if line_count >= _LOG_LINE_LIMIT:
                logger.warning(
                    "extract_action_metrics: line limit (%d) reached for %s; "
                    "some events may be omitted",
                    _LOG_LINE_LIMIT,
                    events_path,
                )

    except OSError as e:
        logger.debug("Could not read action metrics from %s: %s", events_path, e)

    # Post-process: convert accumulated latency to average per LLM request.
    for metrics in action_metrics.values():
        req_count = metrics.pop("llm_request_count", 0)
        if req_count > 0:
            metrics["latency_ms"] = round(metrics["latency_ms"] / req_count, 1)

    return action_metrics
