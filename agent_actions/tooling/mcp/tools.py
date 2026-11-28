"""The tools the MCP server offers: each one runs an `agac` command in the project.

A tool call becomes one `agac` process, so it runs exactly what the command line
runs, under the same run lock, and a crash in it cannot take the server down.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# What a reply may hold. A run of a large workflow prints far more than a model can use.
MAX_OUTPUT_CHARS = 60_000
DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_RECORD_LIMIT = 20

# `agac run` and `agac retry` end with these when nothing went wrong with the command
# itself: finished, finished with failed records, paused for a batch.
RUN_OUTCOMES = {
    0: "success",
    3: "finished, and some records are failed or exhausted",
    4: "paused: a batch is open, or the run stopped before every action ended",
}
EXIT_MEANINGS = {
    **RUN_OUTCOMES,
    1: "failed",
    2: "usage error: nothing ran",
    5: "stopped by a provider's quota or billing",
}

STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}
INTEGER = {"type": "integer", "minimum": 1}
STRINGS = {"type": "array", "items": {"type": "string"}}

WORKFLOW = {**STRING, "description": "The workflow name: its config file name, no extension"}
SANDBOX_READ = {
    **BOOLEAN,
    "description": (
        "Read what sandbox runs stored (default true). False reads what real runs stored"
    ),
}
SANDBOX_RUN = {
    **BOOLEAN,
    "description": (
        "Run offline on the mock: no model call, no API key, no cost (default true). "
        "False is a real run that calls models and costs money; the server refuses it "
        "unless it was started with --allow-real-runs"
    ),
}
NAMED_SCENARIOS = ("happy", "chaos")
SCENARIO = {
    **STRING,
    "description": (
        "With sandbox: 'happy', 'chaos', or the path of a scenario file. Default: "
        "sandbox.<workflow>.yml, else sandbox.yml, else happy"
    ),
}


class ToolRefused(Exception):
    """A call the server will not make, with the reason to show the caller."""


@dataclass(frozen=True)
class Context:
    """What every tool call runs in."""

    project_root: Path
    allow_real_runs: bool = False
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict[str, dict[str, Any]]
    # Builds the `agac` arguments from the call's arguments.
    command: Callable[[dict[str, Any]], list[str]]
    required: tuple[str, ...] = ("workflow",)
    # Changes real output or costs money when `sandbox` is false.
    real_when_not_sandbox: bool = False
    # Has no sandbox form: every call is a real one.
    always_real: bool = False
    ok_exit_codes: frozenset[int] = frozenset({0})
    # Shapes the command's output before it is returned.
    shape: Callable[[str, dict[str, Any]], str] | None = None
    # The command prints JSON on standard output: a success returns that alone,
    # without the notices the command prints beside it.
    prints_json: bool = False
    read_only: bool = True
    # Can replace or remove what earlier calls stored (MCP's destructiveHint).
    destructive: bool = False
    # Reaches outside the project: model providers or the project's databases.
    open_world: bool = False

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.read_only,
                "openWorldHint": self.open_world,
            },
        }


def _flag(name: str, value: Any) -> list[str]:
    """`--name=value`, so a value is never read as another option."""
    return [] if value is None else [f"--{name}={value}"]


def _switch(name: str, on: Any) -> list[str]:
    return [f"--{name}"] if on else []


def _sandbox(args: dict[str, Any]) -> list[str]:
    return _switch("sandbox", args.get("sandbox", True))


def _scenario(args: dict[str, Any]) -> list[str]:
    return _flag("scenario", args.get("scenario")) if args.get("sandbox", True) else []


def _base(command: list[str], args: dict[str, Any]) -> list[str]:
    return [*command, *_flag("workflow", args["workflow"]), *_sandbox(args)]


def _run(args: dict[str, Any]) -> list[str]:
    argv = [*_base(["run"], args), *_scenario(args)]
    for action in args.get("rerun") or []:
        argv += _flag("rerun", action)
    argv += _flag("where", args.get("where"))
    argv += _flag("records", args.get("_records_file"))
    argv += _switch("dry-run", args.get("dry_run"))
    argv += _switch("fresh", args.get("fresh"))
    argv += _switch("abandon-in-flight", args.get("abandon_in_flight"))
    argv += _flag("record-limit", args.get("record_limit"))
    argv += _flag("file-limit", args.get("file_limit"))
    argv += _flag("user-code", args.get("user_code"))
    # A dry run starts nothing to wait for. A real batch can take hours, longer than a
    # client waits for one reply: by default it returns at exit code 4, to be called again.
    if args.get("wait", args.get("sandbox", True)) and not args.get("dry_run"):
        argv += ["--wait"]
    return argv


def _retry(args: dict[str, Any]) -> list[str]:
    return [
        *_base(["retry"], args),
        *_scenario(args),
        *_flag("from", args.get("from_action")),
        *_flag("record", args.get("record")),
        *_switch("all", args.get("all")),
        *_flag("max-passes", args.get("max_passes")),
        *_switch("dry-run", args.get("dry_run")),
    ]


def _records(args: dict[str, Any]) -> list[str]:
    return [
        *_base(["records"], args),
        *_flag("action", args.get("action")),
        *_flag("source-guid", args.get("source_guid")),
        *_flag("field", args.get("field")),
        *_switch("snapshots", args.get("failed_inputs")),
    ]


def _first_records(output: str, args: dict[str, Any]) -> str:
    """The first `limit` records of a JSON list, with how many there are in all."""
    return _some_records(output, args, newest=False)


def _newest_records(output: str, args: dict[str, Any]) -> str:
    """The last `limit` items of a JSON list stored oldest first, such as traces."""
    return _some_records(output, args, newest=True)


def _some_records(output: str, args: dict[str, Any], *, newest: bool) -> str:
    limit = args.get("limit") or DEFAULT_RECORD_LIMIT
    offset = args.get("offset") or 0
    start = output.find("[")
    try:
        records = json.loads(output[start:]) if start >= 0 else None
    except ValueError:
        return output
    if not isinstance(records, list) or (len(records) <= limit and not offset):
        return output
    if newest:
        kept = records[-limit:]
        which = f"the last {limit} (newest)"
    elif offset:
        kept = records[offset : offset + limit]
        which = (
            f"records {offset + 1} to {offset + len(kept)}"
            if kept
            else f"none: 'offset' {offset} is past the end"
        )
    else:
        kept = records[:limit]
        which = f"the first {limit}"
    return (
        f"{len(records)} records in all; {which} are shown. "
        + ("Raise 'limit'" if newest else "Page with 'offset', raise 'limit'")
        + ", or narrow with 'action', 'source_guid', 'record' or 'field'.\n"
        + json.dumps(kept, indent=1, ensure_ascii=False)
    )


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="run_workflow",
        description=(
            "Run a workflow with `agac run`, or resume it. By default the run is a sandbox "
            "run: the offline mock answers each LLM action with data that matches its "
            "schema, so it tests the wiring (guards, retries, repair, routing, loops, "
            "batch) in seconds at no cost, and writes only sandbox output. Give 'rerun' to "
            "answer actions again; with 'where' or 'records', only the matching records "
            "are answered again and the rest keep their answers ('dry_run' counts them "
            "first)."
        ),
        properties={
            "workflow": WORKFLOW,
            "sandbox": SANDBOX_RUN,
            "scenario": SCENARIO,
            "rerun": {
                **STRINGS,
                "description": "Actions to answer again, with every action that reads them",
            },
            "where": {
                **STRING,
                "description": (
                    "With one 'rerun' action: a guard condition on the records that action "
                    'stored, e.g. classify.category == "billing". Only matching records '
                    "are answered again"
                ),
            },
            "records": {
                **STRINGS,
                "description": "With one 'rerun' action: the source_guids to answer again",
            },
            "dry_run": {
                **BOOLEAN,
                "description": "With 'where' or 'records': print the count and ids, run nothing",
            },
            "fresh": {
                **BOOLEAN,
                "description": (
                    "Clear this workflow's stored results and status first. Refused while "
                    "a batch is open, unless abandon_in_flight is also true"
                ),
            },
            "abandon_in_flight": {
                **BOOLEAN,
                "description": (
                    "With fresh: drop a batch that is not collected yet, giving up its results"
                ),
            },
            "wait": {
                **BOOLEAN,
                "description": (
                    "Wait for batch jobs and collect them (default: true in the sandbox, "
                    "false in a real run, which returns exit code 4 while a batch is open)"
                ),
            },
            "record_limit": {**INTEGER, "description": "At most this many records a file"},
            "file_limit": {**INTEGER, "description": "At most this many input files"},
            "user_code": {**STRING, "description": "The folder that holds the project's tools"},
        },
        command=_run,
        real_when_not_sandbox=True,
        ok_exit_codes=frozenset(RUN_OUTCOMES),
        read_only=False,
        destructive=True,
        open_world=True,
    ),
    Tool(
        name="retry_workflow",
        description=(
            "Retry the failed or exhausted records with `agac retry`, from one action "
            "through the actions after it. A sandbox retry (the default) repairs the "
            "records of sandbox runs with the mock. 'dry_run' shows the plan."
        ),
        properties={
            "workflow": WORKFLOW,
            "sandbox": SANDBOX_RUN,
            "scenario": SCENARIO,
            "from_action": {
                **STRING,
                "description": "Action to retry from (default: the earliest failure)",
            },
            "record": {**STRING, "description": "Only this record, by source_guid"},
            "all": {
                **BOOLEAN,
                "description": "Retry again while a pass closes an open failure",
            },
            "max_passes": {**INTEGER, "description": "With 'all': stop after this many passes"},
            "dry_run": {**BOOLEAN, "description": "Show what would be retried, run nothing"},
        },
        command=_retry,
        real_when_not_sandbox=True,
        ok_exit_codes=frozenset(RUN_OUTCOMES),
        read_only=False,
        open_world=True,
    ),
    Tool(
        name="sandbox_check",
        description=(
            "Run the workflow in the sandbox from the start and compare the result with "
            "sandbox_expected.<workflow>.yml (exit code, scenario counts, per-action "
            "status and record counts). The end-to-end test of a workflow: it calls no "
            "model. Exit 0: each value holds. 1: a value does not hold. 2: the check "
            "could not run."
        ),
        properties={
            "workflow": WORKFLOW,
            "scenario": SCENARIO,
            "expected": {**STRING, "description": "Another expectations file"},
        },
        command=lambda args: [
            "sandbox",
            "check",
            *_flag("workflow", args["workflow"]),
            *_flag("scenario", args.get("scenario")),
            *_flag("expected", args.get("expected")),
        ],
        ok_exit_codes=frozenset({0, 1}),
        read_only=False,
        destructive=True,
    ),
    Tool(
        name="inspect_workflow",
        description=(
            "Validate a workflow before running it and list its actions with their "
            "dependencies (`agac inspect`). With 'action', show one action as the run "
            "sees it after the config is expanded: kind, model, guard, retry, the fields "
            "it reads and writes, what reads it, its prompt and schema; with view "
            "'context', the variables its prompt can use. Runs nothing."
        ),
        properties={
            "workflow": WORKFLOW,
            "sandbox": SANDBOX_READ,
            "scenario": SCENARIO,
            "action": {**STRING, "description": "Show this action in detail"},
            "view": {
                **STRING,
                "enum": ["action", "context"],
                "description": "With 'action': 'action' (default) or 'context'",
            },
        },
        command=lambda args: [
            *_base(["inspect"], args),
            *_scenario(args),
            *([args.get("view") or "action", "--", args["action"]] if args.get("action") else []),
        ],
    ),
    Tool(
        name="workflow_status",
        description="The status of each action and of the last run, as JSON (`agac status`).",
        properties={"workflow": WORKFLOW, "sandbox": SANDBOX_READ},
        command=lambda args: [*_base(["status"], args), "--json"],
        prints_json=True,
    ),
    Tool(
        name="dispositions",
        description=(
            "What happened to each record at each action: success, failed, exhausted, "
            "filtered, guard-skipped. Counts per action as JSON, or with 'quarantined' "
            "the failed, exhausted and unprocessed records with their reasons. With "
            "'record' (a source_guid), follow that one record through the workflow: its "
            "disposition and reason at each action in run order, the actions it never "
            "reached, and the guard that filtered or skipped it. Use it to find why a "
            "record is missing from an action's output."
        ),
        properties={
            "workflow": WORKFLOW,
            "sandbox": SANDBOX_READ,
            "action": {**STRING, "description": "Only this action"},
            "quarantined": {
                **BOOLEAN,
                "description": "List the failed, exhausted and unprocessed records",
            },
            "record": {**STRING, "description": "Follow this record (its source_guid)"},
        },
        command=lambda args: [
            *_base(["dispositions"], args),
            *_flag("action", args.get("action")),
            *_flag("record", args.get("record")),
            *(["--quarantined"] if args.get("quarantined") else ["--json"]),
        ],
        prints_json=True,
    ),
    Tool(
        name="records",
        description=(
            "The records an action stored, as JSON (`agac records`). Each record holds "
            "`source_guid` and `content`, with the fields of every action so far and the "
            "staged row under `content.source`. Use 'field' for one value a record, and "
            "'failed_inputs' for the input each failed record was processed with."
        ),
        properties={
            "workflow": WORKFLOW,
            "sandbox": SANDBOX_READ,
            "action": {**STRING, "description": "Only this action's records"},
            "source_guid": {**STRING, "description": "Only the records of this source record"},
            "field": {
                **STRING,
                "description": "One value a record: a dotted path such as content.summary",
            },
            "failed_inputs": {
                **BOOLEAN,
                "description": "The input of each failed or exhausted record instead",
            },
            "limit": {
                **INTEGER,
                "description": f"How many records to return (default {DEFAULT_RECORD_LIMIT})",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Skip this many records first, to page through them",
            },
        },
        command=_records,
        shape=_first_records,
    ),
    Tool(
        name="traces",
        description=(
            "The prompt, the context and the response each record of an action was run "
            "with, as JSON (`agac traces`), newest last; a cut keeps the newest. Use it to "
            "see why an answer is what it is."
        ),
        properties={
            "workflow": WORKFLOW,
            "sandbox": SANDBOX_READ,
            "action": {**STRING, "description": "The action whose traces to read"},
            "record": {**STRING, "description": "Only this record, by source_guid"},
            "limit": {
                **INTEGER,
                "description": f"How many traces to return (default {DEFAULT_RECORD_LIMIT})",
            },
        },
        required=("workflow", "action"),
        command=lambda args: [
            *_base(["traces"], args),
            *_flag("action", args["action"]),
            *_flag("record", args.get("record")),
            "--json",
        ],
        shape=_newest_records,
    ),
    Tool(
        name="usage",
        description=(
            "The model calls and tokens each action used, and an estimated cost when the "
            "project sets prices, as JSON (`agac usage`)."
        ),
        properties={"workflow": WORKFLOW, "sandbox": SANDBOX_READ},
        command=lambda args: [*_base(["usage"], args), "--json"],
        prints_json=True,
    ),
    Tool(
        name="expect_report",
        description=(
            "The verdicts the `expect:` rules of a run stored: pass rates per action and "
            "rule, as JSON (`agac expect report`)."
        ),
        properties={
            "workflow": WORKFLOW,
            "sandbox": SANDBOX_READ,
            "action": {**STRING, "description": "Only this action"},
        },
        command=lambda args: [
            "expect",
            "report",
            *_flag("workflow", args["workflow"]),
            *_sandbox(args),
            *_flag("action", args.get("action")),
            "--json",
        ],
        prints_json=True,
    ),
    Tool(
        name="workflow_schema",
        description=(
            "The input and output fields of each action, as JSON (`agac schema`). Use it "
            "to learn which fields a guard, a prompt or a `where` filter can read."
        ),
        properties={"workflow": WORKFLOW},
        command=lambda args: ["schema", *_flag("workflow", args["workflow"]), "--json"],
        prints_json=True,
    ),
    Tool(
        name="export_outputs",
        description=(
            "Write the workflow's declared `outputs:` to their database tables again, "
            "from what the last real run stored (`agac export`). Calls no model, but "
            "writes to the project's databases, so the server refuses it unless it was "
            "started with --allow-real-runs."
        ),
        properties={
            "workflow": WORKFLOW,
            "action": {**STRING, "description": "Write only this action's table"},
        },
        command=lambda args: [
            "export",
            *_flag("workflow", args["workflow"]),
            *_flag("action", args.get("action")),
        ],
        always_real=True,
        read_only=False,
        destructive=True,
        open_world=True,
    ),
)


def tools_by_name() -> dict[str, Tool]:
    return {tool.name: tool for tool in TOOLS}


def list_workflows(root: Path) -> list[dict[str, str]]:
    """Each workflow of the project: its name and its config file."""
    found = []
    for config in sorted(root.glob("agent_workflow/*/agent_config/*.y*ml")):
        found.append({"workflow": config.stem, "config": str(config.relative_to(root))})
    return found


def check_arguments(tool: Tool, args: dict[str, Any]) -> None:
    """Refuse arguments the tool's schema does not allow, naming what is wrong."""
    unknown = sorted(set(args) - set(tool.properties))
    if unknown:
        raise ToolRefused(
            f"{tool.name} takes no argument named {', '.join(unknown)}. "
            f"It takes: {', '.join(tool.properties)}"
        )
    missing = [name for name in tool.required if args.get(name) in (None, "")]
    if missing:
        raise ToolRefused(f"{tool.name} needs {', '.join(missing)}")
    kinds: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "boolean": bool,
        "integer": int,
        "array": list,
    }
    for name, value in args.items():
        wanted = tool.properties[name]["type"]
        least = tool.properties[name].get("minimum")
        right = isinstance(value, kinds[wanted]) and not (
            wanted == "integer" and isinstance(value, bool)
        )
        if wanted == "array" and right:
            right = all(isinstance(item, str) for item in value)
        if not right:
            raise ToolRefused(f"{tool.name}: '{name}' must be {_a(wanted)}")
        allowed = tool.properties[name].get("enum")
        if allowed is not None and value not in allowed:
            raise ToolRefused(f"{tool.name}: '{name}' must be one of {', '.join(allowed)}")
        if least is not None and value < least:
            raise ToolRefused(f"{tool.name}: '{name}' must be {least} or more")
        if name == "records" and any(
            not item.strip() or item.lstrip().startswith("#") or "\n" in item or "\r" in item
            for item in value
        ):
            raise ToolRefused(
                f"{tool.name}: each id in 'records' must be one line, not blank, not starting "
                "with #"
            )
        texts = value if isinstance(value, list) else [value]
        if any(isinstance(text, str) and not _printable(text) for text in texts):
            raise ToolRefused(f"{tool.name}: '{name}' holds a NUL or an unpaired surrogate")


def _printable(text: str) -> bool:
    if "\x00" in text:
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def refuse_a_file_outside_the_project(tool: Tool, args: dict[str, Any], context: Context) -> None:
    """Refuse a path that is not a sandbox file or a folder of the project.

    The CLI shows the line a YAML file fails on, so through a scenario or expectations
    path any other file could be read; `user_code` imports the Python files it names.
    """
    root = context.project_root.resolve()
    for name in ("scenario", "expected"):
        value = args.get(name)
        if value is None or (name == "scenario" and value in NAMED_SCENARIOS):
            continue
        path = _inside(root, value)
        if (
            path is None
            or not path.name.startswith("sandbox")
            or path.suffix not in (".yml", ".yaml")
        ):
            raise ToolRefused(
                f"{tool.name}: '{name}' must be a sandbox*.yml file of the project, outside "
                "agent_io" + (", or 'happy' or 'chaos'" if name == "scenario" else "")
            )
    if args.get("user_code") is not None and _inside(root, args["user_code"]) is None:
        raise ToolRefused(f"{tool.name}: 'user_code' must be a folder of the project")


def _inside(root: Path, value: str) -> Path | None:
    """*value* resolved against *root*, or None when it leaves the project or is agent_io."""
    path = (root / value).resolve()
    if path != root and root not in path.parents:
        return None
    return None if "agent_io" in path.relative_to(root).parts else path


def _a(kind: str) -> str:
    return {"array": "a list of strings", "integer": "a whole number"}.get(kind, f"a {kind}")


def refuse_a_real_call(tool: Tool, args: dict[str, Any], context: Context) -> None:
    """Refuse a call that costs money or writes real output, unless the server allows it."""
    real = tool.always_real or (tool.real_when_not_sandbox and args.get("sandbox") is False)
    if real and not context.allow_real_runs:
        how = (
            "It has no sandbox form."
            if tool.always_real
            else "Leave 'sandbox' out (or true) for an offline run that costs nothing."
        )
        raise ToolRefused(
            f"{tool.name} would act on real data: a real run calls models and costs money, "
            f"and an export writes to the project's databases. {how} To allow real calls, "
            "the person who set this server up starts it with: agac mcp --allow-real-runs"
        )


@dataclass
class Outcome:
    text: str
    is_error: bool
    exit_code: int | None = None
    argv: list[str] = field(default_factory=list)


def call_tool(
    tool: Tool, args: dict[str, Any], context: Context, request_id: Any = None
) -> Outcome:
    """Run *tool* with *args* and return what `agac` printed.

    *request_id* names the call to ``stop_call``, which stops the command it runs.
    """
    # Some clients send null for an argument they leave out.
    args = {name: value for name, value in args.items() if value is not None}
    check_arguments(tool, args)
    refuse_a_real_call(tool, args, context)
    refuse_a_file_outside_the_project(tool, args, context)
    with tempfile.TemporaryDirectory(prefix="agac-mcp-") as scratch:
        call = dict(args)
        if call.get("records") is not None and tool.name == "run_workflow":
            listed = Path(scratch) / "records.txt"
            listed.write_text("\n".join(call["records"]) + "\n", encoding="utf-8")
            call["_records_file"] = str(listed)
        argv = tool.command(call)
        return _run_agac(tool, argv, args, context, request_id)


# The command each running call started, by the id of its request.
_running: dict[Any, subprocess.Popen[str]] = {}
_stopped: set[Any] = set()
_running_lock = threading.Lock()
# How long a stopped command has to end on its own before it is killed.
STOP_GRACE_SECONDS = 10


def stop_call(request_id: Any) -> bool:
    """Stop the command the call *request_id* runs; False when it runs none."""
    with _running_lock:
        process = _running.get(request_id)
        if process is None:
            return False
        _stopped.add(request_id)
    _stop(process)
    return True


def _stop(process: subprocess.Popen[str]) -> None:
    """Ask the command to stop, as Ctrl-C would, then kill it if it does not."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()


def _execute(
    command: list[str], *, timeout: float, request_id: Any = None, **options: Any
) -> subprocess.CompletedProcess[str]:
    """Run *command* to its end, as ``subprocess.run`` does, where ``stop_call`` reaches it."""
    process = subprocess.Popen(  # nosec B603
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **options,
    )
    if request_id is not None:
        with _running_lock:
            _running[request_id] = process
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop(process)
        process.communicate()
        raise
    finally:
        if request_id is not None:
            with _running_lock:
                _running.pop(request_id, None)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _run_agac(
    tool: Tool, argv: list[str], args: dict[str, Any], context: Context, request_id: Any = None
) -> Outcome:
    shown = "agac " + " ".join(argv)
    env = {
        **os.environ,
        "NO_COLOR": "1",
        "TERM": "dumb",
        "COLUMNS": "160",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    command = [sys.executable, "-m", "agent_actions.cli.main", *argv]
    try:
        done = _execute(
            command,
            cwd=context.project_root,
            env=env,
            encoding="utf-8",
            errors="replace",
            timeout=context.timeout_seconds,
            request_id=request_id,
        )
    except subprocess.TimeoutExpired:
        return Outcome(
            f"$ {shown}\nStopped: no result after {context.timeout_seconds} seconds. A run "
            "keeps what it stored: call the tool again to resume it.",
            is_error=True,
            argv=argv,
        )
    with _running_lock:
        stopped = request_id is not None and request_id in _stopped
        _stopped.discard(request_id)
    if stopped:
        return Outcome(
            f"$ {shown}\nStopped: the client cancelled the call. A run keeps what it "
            "stored: call the tool again to resume it.",
            is_error=True,
            exit_code=done.returncode,
            argv=argv,
        )
    output = (done.stdout + done.stderr).strip()
    if done.returncode == 0 and (tool.prints_json or tool.shape is not None):
        output = _from_first_bracket(done.stdout)
        if tool.shape is not None:
            output = tool.shape(output, args)
    meaning = EXIT_MEANINGS.get(done.returncode, "")
    if tool.name == "sandbox_check":
        meaning = {
            0: "each expected value holds",
            1: "a value does not hold, or the run wrote no result",
            2: "the expectations file is not valid, or the check could not run",
        }.get(done.returncode, meaning)
    header = f"$ {shown}\nexit code {done.returncode}" + (f" ({meaning})" if meaning else "")
    return Outcome(
        f"{header}\n\n{_capped(output)}",
        is_error=done.returncode not in tool.ok_exit_codes,
        exit_code=done.returncode,
        argv=argv,
    )


def _from_first_bracket(stdout: str) -> str:
    """*stdout* from the line its JSON starts on: a notice printed before it is left out."""
    lines = stdout.splitlines()
    for number, line in enumerate(lines):
        if line.lstrip().startswith(("{", "[")):
            return "\n".join(lines[number:]).strip()
    return stdout.strip()


def _capped(output: str) -> str:
    """*output*, with its middle left out when it is longer than a reply may be."""
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    head = MAX_OUTPUT_CHARS // 5
    tail = MAX_OUTPUT_CHARS - head
    left_out = len(output) - head - tail
    return (
        f"{output[:head]}\n\n[... {left_out} characters left out; narrow the call to see "
        f"them ...]\n\n{output[-tail:]}"
    )
