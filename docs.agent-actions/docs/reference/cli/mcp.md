---
title: mcp Command
description: Start an MCP server, so that an AI assistant can run and inspect the workflows of a project
sidebar_position: 6
---

# mcp Command

The `mcp` command starts a server that speaks the [Model Context Protocol](https://modelcontextprotocol.io) (MCP). An AI assistant (Claude Code, Claude Desktop, Cursor, or any other MCP client) starts the command and calls its tools. With these tools, the assistant can validate, run, retry and check a workflow, and read the result.

```bash
agac mcp [options]
```

You do not start the command by hand. The assistant starts it and speaks to it on standard input and standard output.

## Safety

The server is safe by default:

- Each run and each retry is a [sandbox run](../../guides/sandbox.md). A sandbox run calls no model, needs no API key, and keeps its output apart from real output.
- The server refuses a real run, a real retry and an export. To permit them, start the server with `--allow-real-runs`.
- The assistant can always read the output of real runs. A read changes nothing.
- The resources never include `.env` or stored data.
- A scenario file or an expectations file must be a `.yml` file of the project, outside `agent_io`. The server refuses other paths, because the command shows the line where a YAML file fails.
- A resource is never a symbolic link.

## Options

| Option | Description |
|--------|-------------|
| `--project DIRECTORY` | The project to serve. The default is the project that holds the current directory. |
| `--allow-real-runs` | Let the assistant make real runs, real retries and exports. A real run calls models and costs money. |
| `--timeout SECONDS` | The longest time that one tool call can take. The default is 1800. |

If the directory is not in a project, the command stops and prints `No Agent Actions project at or above <directory>`.

## Connect an Assistant

**Claude Code**, from the project root:

```bash
claude mcp add agac -- agac mcp
```

**Claude Desktop, Cursor and other clients** read a JSON configuration file. Add this entry:

```json
{
  "mcpServers": {
    "agac": {
      "command": "agac",
      "args": ["mcp", "--project", "/path/to/your/project"]
    }
  }
}
```

If `agac` is installed in a virtual environment, give the full path of the command, for example `/path/to/your/project/.venv/bin/agac`.

To permit real runs, add `--allow-real-runs` to the arguments.

## Tools

Each tool runs one `agac` command in the project. The assistant gets the output of the command and its exit code.

| Tool | Command | What it does |
|------|---------|--------------|
| `list_workflows` | — | List the workflows of the project |
| `inspect_workflow` | [`inspect`](./inspect) | Validate a workflow and list its actions. It runs nothing. |
| `run_workflow` | [`run`](./run) | Run or resume a workflow. `rerun` with `where` or `records` answers some records again. `dry_run` shows the count first. |
| `retry_workflow` | [`retry`](./retry) | Retry the failed or exhausted records |
| `sandbox_check` | [`sandbox check`](./sandbox) | Run the workflow in the sandbox and compare the result with the expected outcomes |
| `workflow_status` | [`status`](./utilities#status) | The status of each action and of the last run |
| `dispositions` | [`dispositions`](./dispositions) | What happened to each record at each action |
| `records` | [`records`](./records) | The records that an action stored, or the input of each failed record |
| `traces` | [`traces`](./traces) | The prompt, the context and the response of each record of an action |
| `usage` | [`usage`](./usage) | The model calls and the tokens that each action used |
| `expect_report` | [`expect report`](./expect) | The verdicts that the `expect:` rules stored |
| `workflow_schema` | [`schema`](./schema) | The input and output fields of each action |
| `export_outputs` | [`export`](./export) | Write the declared `outputs:` to their database tables again. It needs `--allow-real-runs`. |

The tools that take `sandbox` have it set to `true` by default. To read the output of real runs, the assistant sets `sandbox` to `false`.

`records` and `traces` return the first 20 records. The `limit` argument changes the number. The server cuts an output that is longer than 60,000 characters, and tells the assistant that it did so.

A run that ends with exit code 3 (some records failed) or 4 (paused for a batch) is a result, not an error. The assistant reads the code and continues: `retry_workflow` after 3, `run_workflow` again after 4. See [Exit Codes](./run.md#exit-codes).

## Resources

The assistant can also read two groups of files:

| URI | Files |
|-----|-------|
| `agac://project/...` | The files that define the workflows: `agent_actions.yml`, the workflow configurations, prompts, schemas, tools, branches, templates and sandbox scenarios |
| `agac://skills/...` | The bundled guides that the [`skills`](./skills) command installs: how to write a workflow, context scope, guards, expectations, operations and sandbox tests |

## Example Session

A usual session of an assistant:

1. `list_workflows`, then `inspect_workflow` to validate.
2. `run_workflow` in the sandbox.
3. `dispositions` and `records` to read the result.
4. `run_workflow` with `scenario: "chaos"` to test the failure paths, then `retry_workflow`.
5. `sandbox_check` to assert the full result.

## See Also

- [Sandbox Runs](../../guides/sandbox.md)
- [skills Command](./skills)
