"""Project scanner for finding workflow files and prompts."""

import ast
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from agent_actions.config.defaults import DocsDefaults
from agent_actions.output.response.loader import SchemaLoader

from .parser import extract_fields_for_docs

logger = logging.getLogger(__name__)


class ProjectScanner:
    """Scan project directory for agent workflows and prompts."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.workflows_found: list[str] = []

    def scan(self) -> dict[str, dict[str, Any]]:
        """Scan project directory for rendered and original workflow YAML files."""
        workflows = {}
        artefact_dir = self.project_root / "artefact"

        # First, scan for rendered workflows inside artefact/
        rendered_dir = artefact_dir / "rendered_workflows"
        if rendered_dir.exists():
            for yaml_file in rendered_dir.glob("*.yml"):
                workflow_name = yaml_file.stem
                workflows[workflow_name] = {"rendered": str(yaml_file), "original": None}

        # Then, scan for original workflows with plan sections
        # Skip the artefact directory to avoid scanning generated docs
        for agent_config_dir in self.project_root.rglob("agent_config"):
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

    # Cap README content to prevent catalog.json bloat
    _README_MAX_BYTES = DocsDefaults.README_MAX_BYTES

    def scan_readmes(self) -> dict[str, str]:
        """Scan for README.md files alongside agent_config directories.

        Uses last-write-wins on duplicate workflow stems, matching the
        collision policy in scan() so README content stays paired with the
        workflow metadata that catalog generation actually uses.  rglob
        ordering is filesystem-dependent.

        READMEs larger than 100 KB are truncated with a trailing notice.
        """
        readmes: dict[str, str] = {}
        artefact_dir = self.project_root / "artefact"

        for agent_config_dir in self.project_root.rglob("agent_config"):
            if artefact_dir in agent_config_dir.parents or agent_config_dir == artefact_dir:
                continue

            readme_path = agent_config_dir.parent / "README.md"
            if not readme_path.exists():
                continue

            try:
                content = readme_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            encoded = content.encode("utf-8")
            if len(encoded) > self._README_MAX_BYTES:
                truncated = encoded[: self._README_MAX_BYTES].decode("utf-8", errors="ignore")
                truncated = truncated.rsplit("\n", 1)[0]
                content = truncated + "\n\n---\n*README truncated (exceeds 100 KB)*\n"

            for yaml_file in agent_config_dir.glob("*.yml"):
                readmes[yaml_file.stem] = content

        return readmes

    def scan_prompts(self) -> dict[str, Any]:
        """Scan project directory for prompt files in prompt_store/."""
        prompts: dict[str, Any] = {}
        prompt_store_dir = self.project_root / "prompt_store"

        if not prompt_store_dir.exists():
            return prompts

        # Pattern to match {prompt name} ... {end_prompt}
        prompt_pattern = re.compile(r"\{prompt\s+(\w+)\}(.*?)\{end_prompt\}", re.DOTALL)

        for md_file in prompt_store_dir.glob("*.md"):
            content = md_file.read_text()

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

    def scan_schemas(self) -> dict[str, Any]:
        """Scan project directory for schema YAML files."""
        schemas: dict[str, Any] = {}
        schema_dir = self.project_root / "schema"

        if not schema_dir.exists():
            return schemas

        for yml_file in schema_dir.glob("*.yml"):
            schema_name = yml_file.stem

            try:
                raw_schema = SchemaLoader.load_schema(schema_name, schema_dir)
            except FileNotFoundError:
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

    def scan_workflow_data(self) -> dict[str, Any]:
        """Scan project for SQLite target databases and export preview data."""
        workflow_data = {}
        artefact_dir = self.project_root / "artefact"

        for agent_io_dir in self.project_root.rglob("agent_io"):
            if artefact_dir in agent_io_dir.parents or agent_io_dir == artefact_dir:
                continue

            target_dir = agent_io_dir / "target"
            if not target_dir.exists():
                continue

            for db_file in target_dir.glob("*.db"):
                workflow_name = db_file.stem

                try:
                    data = self._scan_sqlite_readonly(db_file, workflow_name)
                    if data is not None:
                        workflow_data[workflow_name] = data
                except Exception as e:
                    logger.debug("Failed to scan workflow DB %s: %s", db_file, e, exc_info=True)

        return workflow_data

    @staticmethod
    def _scan_sqlite_readonly(db_file: Path, workflow_name: str) -> dict[str, Any] | None:
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

            # Target counts per node
            cursor.execute(
                "SELECT action_name, SUM(record_count) as count "
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
                                records.append({**item, "_file": file_path})
                            else:
                                records.append({"_file": file_path, "_value": item})
                    elif isinstance(row_data, dict):
                        records.append({**row_data, "_file": file_path})
                    else:
                        records.append({"_file": file_path, "_value": row_data})
                nodes[action_name] = {
                    "record_count": record_count,
                    "files": files,
                    "preview": records,
                }

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

    def scan_runs(self) -> dict[str, Any]:
        """Scan project directory for workflow run data and execution metrics."""
        import json

        runs_data = {}

        # Find all agent_io directories
        for agent_io_dir in self.project_root.rglob("agent_io"):
            # Skip if inside artefact directory
            artefact_dir = self.project_root / "artefact"
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
                except (OSError, json.JSONDecodeError):
                    pass

            # Load events.json for detailed execution data
            events_path = target_dir / "events.json"
            action_metrics = {}
            if events_path.exists():
                try:
                    action_metrics = self._extract_action_metrics(events_path)
                except Exception as e:
                    logger.debug(
                        "Failed to extract action metrics from %s: %s",
                        events_path,
                        e,
                        exc_info=True,
                    )

            # Load .manifest.json for execution plan and per-action status
            manifest_path = target_dir / ".manifest.json"
            manifest_data = None
            if manifest_path.exists():
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        manifest_data = json.load(f)
                except (OSError, json.JSONDecodeError):
                    pass

            runs_data[workflow_name] = {
                "workflow_name": workflow_name,
                "latest_run": latest_run,
                "action_metrics": action_metrics,
                "manifest": manifest_data,
                "run_results_path": str(run_results_path) if run_results_path.exists() else None,
                "events_path": str(events_path) if events_path.exists() else None,
                "manifest_path": str(manifest_path) if manifest_path.exists() else None,
            }

        return runs_data

    def scan_logs(self) -> dict[str, Any]:
        """Scan project directory for global CLI and validation logs."""
        import json

        logs_data: dict[str, Any] = {
            "events_path": None,
            "recent_invocations": [],
            "validation_errors": [],
            "validation_warnings": [],
        }

        logs_dir = self.project_root / "logs"
        if not logs_dir.exists():
            return logs_data

        events_path = logs_dir / "events.json"
        if not events_path.exists():
            return logs_data

        logs_data["events_path"] = str(events_path)

        try:
            with open(events_path, encoding="utf-8") as f:
                invocations = {}
                for line in f:
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

                # Get recent invocations (last 10)
                logs_data["recent_invocations"] = list(invocations.values())[-10:]

        except OSError as e:
            logger.debug("Could not read events log from %s: %s", events_path, e)

        return logs_data

    def _extract_action_metrics(self, events_path: Path) -> dict[str, Any]:
        """Extract per-action metrics from events.json file."""
        import json

        action_metrics: dict[str, Any] = {}

        try:
            with open(events_path, encoding="utf-8") as f:
                for line in f:
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
                    agent_name = meta.get("agent_name") or data.get("agent_name")

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
                        }

                    # Extract from AgentCompleteEvent
                    if event_type == "AgentCompleteEvent":
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

                    # Extract from LLMResponseEvent for token counts
                    elif event_type == "LLMResponseEvent":
                        tokens = action_metrics[agent_name]["tokens"]
                        tokens["prompt_tokens"] = tokens.get("prompt_tokens", 0) + data.get(
                            "prompt_tokens", 0
                        )
                        tokens["completion_tokens"] = tokens.get("completion_tokens", 0) + data.get(
                            "completion_tokens", 0
                        )

        except OSError as e:
            logger.debug("Could not read action metrics from %s: %s", events_path, e)

        return action_metrics

    def scan_tool_functions(self) -> dict[str, Any]:
        """Scan project directory for @udf_tool function implementations."""
        tool_functions = {}

        # Look for user_code directory
        user_code_dirs = [
            self.project_root / "user_code",
            self.project_root / "tools",
            self.project_root / "functions",
        ]

        for user_code_dir in user_code_dirs:
            if not user_code_dir.exists():
                continue

            # Scan all Python files
            for py_file in user_code_dir.rglob("*.py"):
                try:
                    source = py_file.read_text()
                    tree = ast.parse(source)

                    # First pass: collect all TypedDict classes in this file
                    typed_dicts = self._extract_typed_dicts(tree)

                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            func_name = node.name

                            # Skip private functions
                            if func_name.startswith("_"):
                                continue

                            # Extract function details including UDF metadata
                            func_data = self._extract_function_details(
                                node, source, py_file, typed_dicts
                            )
                            if func_data:
                                tool_functions[func_name] = func_data

                except (SyntaxError, UnicodeDecodeError):
                    # Skip files that can't be parsed
                    continue

        return tool_functions

    def _extract_typed_dicts(self, tree: ast.AST) -> dict[str, list[dict[str, Any]]]:
        """Extract TypedDict class definitions from AST."""
        typed_dicts = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check if this class inherits from TypedDict
                is_typed_dict = any(
                    (isinstance(base, ast.Name) and base.id == "TypedDict")
                    or (
                        isinstance(base, ast.Call)
                        and isinstance(base.func, ast.Name)
                        and base.func.id == "TypedDict"
                    )
                    for base in node.bases
                )

                if not is_typed_dict:
                    continue

                # Check for total=False in class definition (all fields optional)
                all_optional = False
                for base in node.bases:
                    if isinstance(base, ast.Call):
                        for keyword in base.keywords:
                            if keyword.arg == "total" and isinstance(keyword.value, ast.Constant):
                                all_optional = not keyword.value.value

                # Extract field definitions from class body
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        field_name = item.target.id
                        field_type = ast.unparse(item.annotation) if item.annotation else "Any"
                        fields.append(
                            {"name": field_name, "type": field_type, "required": not all_optional}
                        )

                typed_dicts[node.name] = fields

        return typed_dicts

    def _extract_function_details(
        self,
        node: ast.FunctionDef,
        source: str,
        file_path: Path,
        typed_dicts: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any] | None:
        """Extract details from a function AST node, including UDF metadata."""
        try:
            # Get source lines
            lines = source.splitlines()

            # Build signature
            args = []
            for arg in node.args.args:
                arg_str = arg.arg
                # Add type annotation if present
                if arg.annotation:
                    arg_str += f": {ast.unparse(arg.annotation)}"
                args.append(arg_str)

            # Handle *args and **kwargs
            if node.args.vararg:
                args.append(f"*{node.args.vararg.arg}")
            if node.args.kwarg:
                args.append(f"**{node.args.kwarg.arg}")

            signature = f"def {node.name}({', '.join(args)})"

            # Add return type if present
            if node.returns:
                signature += f" -> {ast.unparse(node.returns)}"

            signature += ":"

            # Get docstring
            docstring = ast.get_docstring(node) or ""

            # Get source code (from function start to end)
            start_line = node.lineno - 1
            end_line = node.end_lineno if hasattr(node, "end_lineno") else start_line + 1
            source_code = "\n".join(lines[start_line:end_line])

            result = {
                "found": True,
                "file_path": str(file_path.relative_to(self.project_root)),
                "signature": signature,
                "docstring": docstring,
                "source_code": source_code,
                "line_start": node.lineno,
                "line_end": end_line,
                "is_udf": False,
                "input_schema": None,
            }

            # Check for @udf_tool decorator
            for decorator in node.decorator_list:
                decorator_name = None
                decorator_args = {}

                if isinstance(decorator, ast.Name):
                    decorator_name = decorator.id
                elif isinstance(decorator, ast.Call):
                    if isinstance(decorator.func, ast.Name):
                        decorator_name = decorator.func.id
                    elif isinstance(decorator.func, ast.Attribute):
                        decorator_name = decorator.func.attr

                    # Extract keyword arguments from decorator
                    for keyword in decorator.keywords:
                        if keyword.arg and isinstance(keyword.value, ast.Name):
                            decorator_args[keyword.arg] = keyword.value.id

                if decorator_name in ("udf_tool", "udf"):
                    result["is_udf"] = True

                    # Resolve input_type to TypedDict fields
                    input_type_name = decorator_args.get("input_type")
                    if input_type_name and typed_dicts and input_type_name in typed_dicts:
                        result["input_schema"] = {
                            "name": input_type_name,
                            "fields": typed_dicts[input_type_name],
                        }

                    break  # Found the UDF decorator, no need to check others

            return result

        except (SyntaxError, AttributeError, TypeError, IndexError, ValueError):
            return None

    # =========================================================================
    # New scan methods: vendors, errors, events, examples, loaders, processing
    # =========================================================================

    def scan_vendors(self) -> dict[str, Any]:
        """Scan for LLM vendor configurations via AST parsing."""
        vendors: dict[str, Any] = {}
        vendor_file = self.project_root.parent / "agent_actions" / "llm" / "config" / "vendor.py"

        # Also check if we're inside agent_actions already
        if not vendor_file.exists():
            vendor_file = (
                Path(__file__).resolve().parent.parent.parent / "llm" / "config" / "vendor.py"
            )

        if not vendor_file.exists():
            return vendors

        try:
            source = vendor_file.read_text()
            tree = ast.parse(source)

            # Extract VendorType enum values and config classes
            enum_values: dict[str, Any] = {}
            config_classes: dict[str, Any] = {}

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                # Check for VendorType enum
                is_enum = any(
                    (isinstance(b, ast.Name) and b.id in ("Enum", "str")) for b in node.bases
                )
                if node.name == "VendorType" and is_enum:
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name) and isinstance(
                                    item.value, ast.Constant
                                ):
                                    enum_values[target.id] = item.value.value

                # Check for *Config classes inheriting from BaseVendorConfig
                is_config = any(
                    (isinstance(b, ast.Name) and b.id == "BaseVendorConfig") for b in node.bases
                )
                if is_config:
                    docstring = ast.get_docstring(node) or ""
                    fields = []
                    for item in node.body:
                        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                            field_name = item.target.id
                            default_val = None
                            if item.value:
                                # Try to get the constant default
                                if isinstance(item.value, ast.Constant):
                                    default_val = item.value.value
                                elif isinstance(item.value, ast.Call):
                                    # Field(...) - extract default keyword
                                    for kw in item.value.keywords:
                                        if kw.arg == "default" and isinstance(
                                            kw.value, ast.Constant
                                        ):
                                            default_val = kw.value.value
                            fields.append({"name": field_name, "default": default_val})
                    config_classes[node.name] = {
                        "fields": fields,
                        "docstring": docstring,
                    }

            # Map enum values to config classes by matching vendor_type
            config_map = {
                "OPENAI": "OpenAIConfig",
                "ANTHROPIC": "AnthropicConfig",
                "GOOGLE": "GoogleConfig",
                "GEMINI": "GoogleConfig",
                "GROQ": "GroqConfig",
                "COHERE": "CohereConfig",
                "MISTRAL": "MistralConfig",
                "OLLAMA": "OllamaConfig",
                "TOOL": "ToolVendorConfig",
                "AGAC_PROVIDER": "AgacProviderConfig",
            }

            for enum_name, enum_val in enum_values.items():
                config_cls_name = config_map.get(enum_name, "")
                config_info = config_classes.get(config_cls_name, {})
                vendors[enum_val] = {
                    "id": enum_val,
                    "enum_name": enum_name,
                    "enum_value": enum_val,
                    "config_class": config_cls_name,
                    "fields": config_info.get("fields", []),
                    "docstring": config_info.get("docstring", ""),
                }

        except (OSError, SyntaxError, UnicodeDecodeError) as e:
            logger.debug("Could not scan vendors from %s: %s", vendor_file, e)

        return vendors

    def scan_error_types(self) -> dict[str, Any]:
        """Scan for error/exception class hierarchy via AST parsing."""
        error_types: dict[str, Any] = {}
        errors_dir = Path(__file__).resolve().parent.parent.parent / "errors"

        if not errors_dir.exists():
            return error_types

        # Category mapping based on file names
        category_map = {
            "base.py": "base",
            "common.py": "common",
            "configuration.py": "configuration",
            "validation.py": "validation",
            "processing.py": "processing",
            "external_services.py": "external_services",
            "filesystem.py": "filesystem",
            "resources.py": "resources",
            "operations.py": "operations",
            "preflight.py": "preflight",
        }

        for py_file in errors_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue

            category = category_map.get(py_file.name, py_file.stem)
            errors_list = []
            base_class = None

            try:
                source = py_file.read_text()
                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if not isinstance(node, ast.ClassDef):
                        continue

                    # Get parent class name
                    parent_name = None
                    for base in node.bases:
                        if isinstance(base, ast.Name):
                            parent_name = base.id
                            break

                    docstring = ast.get_docstring(node) or ""

                    error_info = {
                        "name": node.name,
                        "parent": parent_name,
                        "docstring": docstring,
                        "source_file": py_file.name,
                        "line": node.lineno,
                    }
                    errors_list.append(error_info)

                    # First class in non-base files is the category's base class
                    if base_class is None and category != "base":
                        base_class = node.name

                if errors_list:
                    error_types[category] = {
                        "id": category,
                        "base_class": base_class or errors_list[0]["name"],
                        "source_file": py_file.name,
                        "errors": errors_list,
                        "error_count": len(errors_list),
                    }

            except (OSError, SyntaxError, UnicodeDecodeError) as e:
                logger.debug("Could not scan error types from %s: %s", py_file, e)
                continue

        return error_types

    def scan_event_types(self) -> dict[str, Any]:
        """Scan for event type definitions via AST parsing."""
        event_types: dict[str, Any] = {}
        events_file = (
            Path(__file__).resolve().parent.parent.parent / "logging" / "events" / "types.py"
        )

        if not events_file.exists():
            return event_types

        try:
            source = events_file.read_text()
            tree = ast.parse(source)

            # First extract EventCategories class values
            categories_map = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "EventCategories":
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name) and isinstance(
                                    item.value, ast.Constant
                                ):
                                    categories_map[target.id] = item.value.value

            # Then extract event dataclasses
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                # Check if it inherits from BaseEvent
                is_event = any(
                    (isinstance(b, ast.Name) and b.id == "BaseEvent") for b in node.bases
                )
                if not is_event:
                    continue

                docstring = ast.get_docstring(node) or ""

                # Extract fields (annotations on the class body)
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        field_name = item.target.id
                        field_type = ast.unparse(item.annotation) if item.annotation else "Any"
                        fields.append({"name": field_name, "type": field_type})

                # Extract event code from the code property
                event_code = ""
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "code":
                        for stmt in ast.walk(item):
                            if isinstance(stmt, ast.Return) and isinstance(
                                stmt.value, ast.Constant
                            ):
                                event_code = str(stmt.value.value)

                # Determine category from __post_init__ body
                category = "unknown"
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__post_init__":
                        for stmt in ast.walk(item):
                            if (
                                isinstance(stmt, ast.Assign)
                                and len(stmt.targets) == 1
                                and isinstance(stmt.targets[0], ast.Attribute)
                                and stmt.targets[0].attr == "category"
                            ):
                                # EventCategories.WORKFLOW → "workflow"
                                if isinstance(stmt.value, ast.Attribute):
                                    cat_key = stmt.value.attr
                                    category = str(categories_map.get(cat_key, cat_key.lower()))

                event_info = {
                    "name": node.name,
                    "code": event_code,
                    "docstring": docstring,
                    "fields": fields,
                    "line": node.lineno,
                }

                if category not in event_types:
                    event_types[category] = {
                        "id": category,
                        "events": [],
                    }
                event_types[category]["events"].append(event_info)

            # Add counts
            for cat_data in event_types.values():
                cat_data["event_count"] = len(cat_data["events"])

        except (OSError, SyntaxError, UnicodeDecodeError) as e:
            logger.debug("Could not scan event types from %s: %s", events_file, e)

        return event_types

    def scan_examples(self) -> dict[str, Any]:
        """Scan for example projects in the examples/ directory."""
        examples: dict[str, Any] = {}
        examples_dir = self.project_root.parent / "examples"

        if not examples_dir.exists():
            # Try sibling
            examples_dir = self.project_root / "examples"
        if not examples_dir.exists():
            # Try parent's parent (common layout)
            examples_dir = self.project_root.parent.parent / "examples"
        if not examples_dir.exists():
            return examples

        for example_dir in sorted(examples_dir.iterdir()):
            if not example_dir.is_dir():
                continue

            # Must have agent_actions.yml to be a valid example
            config_file = example_dir / "agent_actions.yml"
            if not config_file.exists():
                continue

            example_name = example_dir.name

            # Parse agent_actions.yml for description
            description = ""
            try:
                config_content = yaml.safe_load(config_file.read_text())
                if isinstance(config_content, dict):
                    description = config_content.get("description", "")
            except Exception as e:
                logger.debug(
                    "Failed to parse YAML config for example %s: %s", example_name, e, exc_info=True
                )

            # Scan for workflows
            workflow_dir = example_dir / "agent_workflow"
            workflows = []
            if workflow_dir.exists():
                for wf_dir in workflow_dir.iterdir():
                    if wf_dir.is_dir():
                        workflows.append(wf_dir.name)

            # Check for other artifacts
            has_prompts = (example_dir / "prompt_store").exists()
            has_schemas = (example_dir / "schema").exists()
            has_tools = (example_dir / "tools").exists()

            # Count schemas and prompts
            schema_count = 0
            if has_schemas:
                schema_count = len(list((example_dir / "schema").glob("*.yml")))

            prompt_count = 0
            if has_prompts:
                prompt_count = len(list((example_dir / "prompt_store").glob("*.md")))

            tool_count = 0
            if has_tools:
                tool_count = len(list((example_dir / "tools").glob("*.py")))

            examples[example_name] = {
                "id": example_name,
                "name": example_name,
                "path": str(example_dir.relative_to(examples_dir.parent)),
                "description": description,
                "has_workflows": bool(workflows),
                "workflows": workflows,
                "workflow_count": len(workflows),
                "has_prompts": has_prompts,
                "prompt_count": prompt_count,
                "has_schemas": has_schemas,
                "schema_count": schema_count,
                "has_tools": has_tools,
                "tool_count": tool_count,
            }

        return examples

    def scan_data_loaders(self) -> dict[str, Any]:
        """Scan for data loader implementations via AST parsing."""
        loaders: dict[str, Any] = {}
        loaders_dir = Path(__file__).resolve().parent.parent.parent / "input" / "loaders"

        if not loaders_dir.exists():
            return loaders

        for py_file in loaders_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue

            try:
                source = py_file.read_text()
                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if not isinstance(node, ast.ClassDef):
                        continue

                    # Check if it has BaseLoader, ISourceDataLoader, or ABC parent
                    parent_names = []
                    for base in node.bases:
                        if isinstance(base, ast.Name):
                            parent_names.append(base.id)
                        elif isinstance(base, ast.Subscript):
                            # BaseLoader[T] pattern
                            if isinstance(base.value, ast.Name):
                                parent_names.append(base.value.id)

                    is_loader = any(
                        n in ("BaseLoader", "ISourceDataLoader", "IDataLoader")
                        for n in parent_names
                    )
                    if not is_loader:
                        continue

                    docstring = ast.get_docstring(node) or ""

                    # Try to extract supported file types from supports_filetype method
                    supported_types = []
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == "supports_filetype":
                            for stmt in ast.walk(item):
                                if isinstance(stmt, ast.Constant) and isinstance(stmt.value, str):
                                    val = stmt.value
                                    if val.startswith(".") or val in (
                                        "json",
                                        "csv",
                                        "tsv",
                                        "xml",
                                        "txt",
                                        "yaml",
                                        "yml",
                                    ):
                                        supported_types.append(val)

                    # Extract methods
                    methods = []
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                            methods.append(item.name)

                    loaders[node.name] = {
                        "id": node.name,
                        "name": node.name,
                        "source_file": py_file.name,
                        "docstring": docstring,
                        "supported_types": supported_types,
                        "base_class": parent_names[0] if parent_names else "",
                        "methods": methods,
                        "line": node.lineno,
                    }

            except (OSError, SyntaxError, UnicodeDecodeError) as e:
                logger.debug("Could not scan data loaders from %s: %s", py_file, e)
                continue

        return loaders

    def scan_processing_states(self) -> dict[str, Any]:
        """Scan for processing state/status enums and dataclasses."""
        processing_types: dict[str, Any] = {}
        types_file = Path(__file__).resolve().parent.parent.parent / "processing" / "types.py"

        if not types_file.exists():
            return processing_types

        try:
            source = types_file.read_text()
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                docstring = ast.get_docstring(node) or ""

                # Check if Enum
                is_enum = any((isinstance(b, ast.Name) and b.id == "Enum") for b in node.bases)

                if is_enum:
                    values = []
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name):
                                    val = None
                                    comment = ""
                                    if isinstance(item.value, ast.Constant):
                                        val = item.value.value
                                    # Extract inline comment from source
                                    if hasattr(item, "end_lineno"):
                                        line = source.splitlines()[item.lineno - 1]
                                        if "#" in line:
                                            comment = line.split("#", 1)[1].strip()
                                    values.append(
                                        {
                                            "name": target.id,
                                            "value": val,
                                            "description": comment,
                                        }
                                    )

                    processing_types[node.name] = {
                        "id": node.name,
                        "type": "enum",
                        "docstring": docstring,
                        "values": values,
                        "value_count": len(values),
                    }
                    continue

                # Check if dataclass (has @dataclass decorator)
                is_dataclass = any(
                    (isinstance(d, ast.Name) and d.id == "dataclass") for d in node.decorator_list
                )

                if is_dataclass:
                    fields = []
                    factory_methods = []

                    for item in node.body:
                        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                            field_name = item.target.id
                            field_type = ast.unparse(item.annotation) if item.annotation else "Any"
                            fields.append({"name": field_name, "type": field_type})

                        elif isinstance(item, ast.FunctionDef):
                            # Collect classmethod factories
                            is_classmethod = any(
                                (isinstance(d, ast.Name) and d.id == "classmethod")
                                for d in item.decorator_list
                            )
                            if is_classmethod:
                                method_doc = ast.get_docstring(item) or ""
                                factory_methods.append(
                                    {
                                        "name": item.name,
                                        "docstring": method_doc,
                                    }
                                )

                    processing_types[node.name] = {
                        "id": node.name,
                        "type": "dataclass",
                        "docstring": docstring,
                        "fields": fields,
                        "field_count": len(fields),
                        "factory_methods": factory_methods,
                    }

        except (OSError, SyntaxError, UnicodeDecodeError) as e:
            logger.debug("Could not scan processing states from %s: %s", types_file, e)

        return processing_types
