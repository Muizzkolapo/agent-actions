# Tools Provider Manifest

## Overview

Helpers for parsing OpenAI-style tools definitions and providing a client interface
for tool-aware workflows.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `client.py` | Module | Client that resolves OpenAI tool definitions and executes them. `ToolClient.invoke` hands a tool of an `as:` include its record under the short names of its instance (`_with_short_names`, from `_include.names`): `data["write"]` holds the output of the same instance's `write`, and the final name of a renamed namespace is left out; a list of records (FILE granularity) is passed as it is. | `llm.providers`, `tools` |
