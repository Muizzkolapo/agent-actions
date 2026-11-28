---
title: MCP Servers
sidebar_position: 5
---

# MCP Servers: call a tool of an MCP server from an action

An MCP server gives tools to AI applications through the [Model Context Protocol](https://modelcontextprotocol.io). The dbt MCP server, for example, gives `get_lineage`. A `kind: mcp` action calls one tool of an MCP server for each record. You do not write a Python tool for it.

This page is about a workflow that *calls* an MCP server. To let an AI assistant run your workflows through MCP, see the [`mcp` command](../cli/mcp.md).

## Declare a server

Declare each server one time in `agent_actions.yml`, under `mcp_servers:`:

```yaml
# agent_actions.yml
mcp_servers:
  dbt:
    command: uvx                       # the program that starts the server
    args: [dbt-mcp]
    env:
      DBT_PROJECT_DIR: ./dbt
      DBT_TOKEN: ${DBT_TOKEN}          # read from the environment or .env
    cwd: dbt                           # optional: the folder to start it in
```

| Key | Required | Description |
|-----|----------|-------------|
| `command` | yes | The program that starts the server. |
| `args` | no | A list of arguments for the program. |
| `env` | no | Environment variables for the server. |
| `cwd` | no | The folder to start the server in, relative to the project root. The default is the project root. |

agac reads a `${NAME}` in `command`, `args` or `env` from the environment, or from `.env`. Thus a credential is never in a project file. If the variable is not set, the run stops before the server starts.

agac starts the server through standard input and output (stdio). It starts each server one time for a run, and all the records of the run use it. agac stops the server when the run ends. A server that is only available over HTTP is not supported.

## Call a tool

```yaml
# agent_config/report.yml
actions:
  - name: lineage
    kind: mcp
    server: dbt                        # an entry of mcp_servers:
    tool: get_lineage                  # the tool to call
    intent: "Get the lineage of each model"
    schema: lineage_output             # required, as for a tool action
    arguments:
      model: source.model_name         # a field reference
      depth: { value: 2 }              # a constant
    dependencies: [read_models]
```

| Key | Required | Description |
|-----|----------|-------------|
| `server` | yes | The name of a server under `mcp_servers:`. |
| `tool` | yes | The name of the tool to call. |
| `arguments` | no | The arguments of the tool. Each value is a field reference (`<action>.<field>`, or `source.<field>`), or a constant. A string that is not a field reference is a constant. To give a constant that looks like a field reference, write `{ value: ... }`. |
| `schema` | yes | The output schema, as for a [tool action](./index.md#tool-action-fields). |

agac adds each field reference of `arguments` to the `observe:` list of the action. Thus you do not have to write it there too.

A `kind: mcp` action is a tool action:

- It calls its tool one time for each record (`granularity: Record`). File granularity is refused.
- It runs online. `run_mode: batch` is refused.
- It takes no `prompt` and no `impl`.
- Guards, `context_scope`, retries and `on_exhausted` apply as for a tool action.

## The output

The output of the action is the answer of the tool:

- If the answer has structured content, the output is that content.
- If the answer is text that holds a JSON object, the output is that object.
- Any other answer goes under the `result` field: plain text, a JSON list, or more than one item.

The output schema checks the output as it checks the output of a tool action.

## Errors

| What occurs | Result |
|-------------|--------|
| The server is not under `mcp_servers:` | The workflow does not load. The message gives the declared servers. |
| The server does not start, or does not answer | The record fails. |
| The server has no tool with that name | The record fails. The message gives the tools of the server. |
| The tool reports an error | The record fails with the message of the tool. `agac retry` can try the record again. |

If each record of the action fails, the action fails, as with a tool action.

## Sandbox runs

A [sandbox run](../../guides/sandbox.md) starts no MCP server. The sandbox mock makes the output of a `kind: mcp` action from its output schema, as it does for an LLM action. To call the server in a sandbox run, set `stub: false` on the action in the scenario:

```yaml
# sandbox.yml
actions:
  lineage:
    stub: false                        # call the MCP server for real
```

`agac inspect -w <workflow> action <action>` shows the server and the tool of an action, and whether a sandbox run starts the server.
