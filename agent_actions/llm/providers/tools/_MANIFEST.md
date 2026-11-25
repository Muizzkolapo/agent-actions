# Tools Provider Manifest

## Overview

Helpers for parsing OpenAI-style tools definitions and providing a client interface
for tool-aware workflows.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `client.py` | Module | Client that resolves OpenAI tool definitions and executes them. `ToolClient.invoke` hands a tool of an `as:` include its record under the short names of its instance (`_with_short_names`, from `_include.names`): `data["write"]` holds the output of the same instance's `write`, and the final name of a renamed namespace is left out; a list of records (FILE granularity) is passed as it is. An action carrying `_builtin` runs the built-in tool it names (`builtin.run_builtin`) on the record, with no UDF and no short names. In a sandbox run whose scenario stubs the action (`config.sandbox.scenario().stubs(name)`), `invoke` does not call `execute_user_defined_function`: `_stub` returns `agac.tool_stub.stub_output` (imported there, not at module level) and checks it against `json_output_schema` with `output_schema_errors`, as the UDF's own output is checked, so a pinned value the schema refuses raises the same `SchemaValidationError`. This is the only place the stub is read; the action stays a tool action, so its guard, context scope, dispositions, storage and lineage are the real path. Outside a sandbox run `scenario()` is None and the UDF runs. | `llm.providers`, `tools` |
| `builtin.py` | Module | Tools agac runs itself, configured by the action's internal `_builtin` key (`{tool: route, field, cases, default}` or `{tool: pick, of}`) rather than written as a UDF; their `impl` is `agac.route` / `agac.pick`, which no UDF can be named. `route` writes `{case: <case>}`: the value at `field` (`<action>.<field>[...]`) when it is a string among `cases`, else `default` when the router has a default branch, else it raises. `pick` writes the output of the first action of `of` the record holds one of, `{}` when none. `runs_udf()` tells a tool action that runs a project UDF from a built-in one, for the checks that read UDF source; `route_case_counts()` counts a router's rows per case for its progress line. `is_router()` tells a built-in route action; a route spec written by the load also holds `branches` (case → entry actions, or `filter` for the default) for `agac inspect`. `route` refuses a record that holds no value at its field (`field_value` raises `KeyError`), and one whose value is set and is no string (`TypeError` naming the type); `pick` refuses a record that holds an output of two of its actions. A loop's result (`loop` in the spec) takes the first output of `of`, its last iteration, and is not refused for holding several. | `llm.providers` |
| `builtin_spec.py` | Module | The typed `_builtin` spec of each built-in tool (`RouteSpec`: `field`, `cases` (no `default`), `default`; `PickSpec`: `of`), strict and with no unknown key; `checked_builtin` validates one, which `ActionConfig` calls at load, and also requires `impl: agac.<tool>` and every action of `of` among the dependencies. `PickSpec.loop` holds the settings the load writes for a loop's result. | `config` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `ToolClient.invoke` | `tools/{workflow}/*.py` | Runs (the UDF that `impl` names, once per record; not in a sandbox run whose scenario stubs the action) | `actions[].impl` |
| `ToolClient._stub` | `sandbox.yml`, or the file `--scenario` names | Reads (through the loaded scenario, in a sandbox run) | `actions.<tool>.stub`, `actions.<tool>.pin` |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `config` | outbound | `client.py` reads the loaded sandbox scenario with `config.sandbox.scenario()` |
| `llm/providers/agac` | outbound | `ToolClient._stub` builds a stubbed tool's record with `tool_stub.stub_output` |
| `utils` | outbound | `client.py` runs the UDF with `udf_management.tooling.execute_user_defined_function` and checks a stubbed record with `output_schema_errors` |
