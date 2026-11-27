# MCP Manifest

## Overview

A Model Context Protocol server for one project. An AI assistant starts `agac mcp`
and calls tools that each run one `agac` command. Standard library only.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `server.py` | Module | `McpServer`: JSON-RPC 2.0 on standard input and output, one message a line. Answers `initialize` (the client's protocol version when known, else the newest) and `ping`; other methods come from `handle(method, handler)`. A notification gets no reply. `RpcError(code, message)` is a handler's protocol error. | `json`, `__version__` |
| `tools.py` | Module | The tools (`TOOLS`) and how each is run. `call_tool` checks the arguments against the tool's schema, refuses a real run, retry or export unless `Context.allow_real_runs` (`ToolRefused`), and runs one `agac` subprocess in the project root with options written `--name=value`. A scenario or expectations path must be a `sandbox*.yml` file of the project and `user_code` a project folder, outside `agent_io`. A list of record ids (one line each) is passed in a temporary file. A real run does not wait for a batch unless asked. Output over `MAX_OUTPUT_CHARS` is cut; a JSON list of records is cut to `limit`. A run's exit codes 0, 3 and 4 are outcomes, not errors. `list_workflows` reads the project folder. | `subprocess`, `cli.main` |
| `app.py` | Module | `build_server(context)`: registers `tools/list`, `tools/call`, `resources/list` and `resources/read`, and the instructions an assistant reads first. Resources are the files that define the project's workflows (`PROJECT_FILES`; a read matches its URI against those patterns and refuses a symlink) and the bundled skill guides. | `server`, `tools`, `skills/` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `list_workflows()` | `agent_config/{workflow}.yml` | Reads | — |
| `build_server()` resources | `agent_actions.yml`, `agent_config/{workflow}.yml`, `prompt_store/*.md`, `schema/**/*.yml`, `tools/**/*.py`, `sandbox*.yml` | Reads | — |
| `call_tool()` | `agent_io/target/{action}/`, `agent_io/store/` | Reads and writes, through the `agac` command each tool runs | — |

## Dependencies

| Module | Direction | Description |
|--------|-----------|-------------|
| `cli` | inbound | `agac mcp` builds and serves the server |
| `cli` | outbound | Each tool runs `python -m agent_actions.cli.main` as a subprocess |
| `skills` | outbound | The bundled skill guides are served as resources |

## Notes

- Standard output carries only the protocol. A subprocess's output is captured and returned in the tool result.
- `.env` and stored data are never resources.
