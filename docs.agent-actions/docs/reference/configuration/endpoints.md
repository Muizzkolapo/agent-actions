---
title: Endpoints
sidebar_position: 4
---

# Endpoints: bring your own OpenAI-compatible server

agac works with your endpoint if the endpoint gives OpenAI structured output. Declare the endpoint one time in `agent_actions.yml`. Then select it from any action with `model_vendor: <name>`. You do not need a code change to add a provider.

The endpoint MUST:

1. Accept `POST <url>/chat/completions` with the OpenAI request body.
2. Accept `response_format: {"type": "json_schema", "json_schema": {...}}`.
3. Return `choices[0].message.content` as JSON text that matches the schema.

Servers that expose this API include vLLM, SGLang, llama.cpp and llamafile, Ollama, LM Studio, OpenRouter, Azure OpenAI and the Vertex AI OpenAI route. A server that does not speak this API is out of scope. For such a server, put an adapter in front of it (vLLM, TGI, a LiteLLM proxy). Or call the server from a `tool` action.

## Declare an endpoint

```yaml
# agent_actions.yml
endpoints:
  lab-vllm:
    url: http://gpu-box:8000/v1      # the base URL; /chat/completions is appended
    auth: none
  azure-gpt:
    url: https://my-resource.openai.azure.com/openai/v1
    auth:
      env: AZURE_OPENAI_KEY          # the secret is read from this variable
      header: api-key                # default Authorization
    headers:
      api-version: "2024-10-21"
  openrouter:
    url: ${OPENROUTER_URL}           # a url can be one ${ENV_VAR}
    auth: { env: OPENROUTER_API_KEY }
```

| Key | Required | Meaning |
|-----|----------|---------|
| `url` | yes | The base URL, `http` or `https`, or exactly one `${ENV_VAR}` that holds the URL. agac refuses a URL that ends in `/chat/completions`. |
| `auth` | yes | `none`, or a mapping with exactly one of `env: NAME` (an environment variable) or `command: [argv, ...]`. The `command` value is a program whose output is the secret. agac runs it without a shell from the project root. Parallel records run it one time. After a 401, it runs one more time, then the record fails. |
| `auth.header` | no | The header that carries the secret. Default `Authorization`. If you set another header, agac sends no `Authorization` header unless `headers:` declares one. |
| `auth.prefix` | no | The text before the secret. Default `Bearer ` for `Authorization`. For other headers, the default is empty. |
| `auth.refresh_seconds` | no | For `command` only: agac runs the command again after this number of seconds. Default 3000. |
| `headers` | no | Extra headers. A value can read a variable with `${NAME}`. If the header name contains `authorization`, `key`, `token` or `secret`, agac refuses a literal value. |
| `timeout_seconds` | no | The request timeout. Default 120. The [`request_timeout`](./index.md#request-timeout) of an action has priority over this value. |

An endpoint name MUST be lowercase (`a-z`, `0-9`, `-`, `_`). An endpoint name MUST NOT be a built-in vendor name, for example `openai` or `llamafile`. A project can declare any number of endpoints.

## Use an endpoint

```yaml
# agent_workflow/triage/agent_config/triage.yml
name: triage
defaults:
  model_vendor: lab-vllm
  model_name: Qwen2.5-7B-Instruct
actions:
  - name: extract                   # inherits lab-vllm
    schema: extract
  - name: classify
    model_vendor: openrouter        # another endpoint
    model_name: meta-llama/llama-3.3-70b-instruct
    schema: classify
  - name: review
    model_vendor: azure-gpt
    model_name: gpt-4o-mini
    schema: review
  - name: final_check
    model_vendor: openai            # a built-in vendor in the same workflow
    model_name: gpt-4o-mini
    schema: final_check
```

The action keeps all the features that agac gives a built-in vendor. These features are:

- prompt templates
- context scope
- schema compilation
- retries on rate limits and network faults
- token usage
- prompt traces
- dispositions
- `expect:` rules
- `agac retry`

Events and errors name the endpoint.

## Rules

**Structured output only.** An endpoint action MUST have `json_mode: true` (the default) and a schema. Preflight refuses `json_mode: false` and a missing schema. If a reply does not match the schema, the record fails with the reason `parse_error`. The run log names the endpoint, the schema and the mismatch.

**The credential comes from the endpoint.** An endpoint action that sets `api_key` or `base_url` is refused. If an endpoint action inherits a value from `defaults:` or `default_agent_config:`, agac ignores that value. Thus a project that mixes endpoints and built-in vendors keeps its project-wide `api_key`. An endpoint with `auth: none` needs no `api_key` anywhere.

**Online only.** agac refuses `run_mode: batch` on an endpoint action, with this error: `vendor '<name>' does not support run_mode: batch`.

**Secrets are masked by value.** agac masks the credential that it reads for an endpoint as `[REDACTED]`. The credential is:

- the `env` value
- the command output
- a `${NAME}` header value whose header name or variable name contains `authorization`, `key`, `token` or `secret`

agac masks the credential in log messages, events, record reasons and the error block of the CLI. This includes an error body from a server that echoes the request headers. Only the key-shape rules mask a value that is shorter than 8 characters. A `${NAME}` value in another header (a region, an API version) is not treated as a secret.

## Verify an endpoint

A server cannot report whether it honours `json_schema`. Only a request proves it. `agac run --verify-keys` sends one small request to each endpoint that the workflow uses. The request uses the first `model_name` named for the endpoint, `max_tokens: 16` and a one-field schema. These results are errors: a credential that the server refuses, a server that agac cannot reach, and a reply that does not match the schema:

- `endpoint 'azure-gpt' refused the credential (HTTP 401)` (or 403)
- `endpoint 'lab-vllm' does not honour response_format json_schema; agac supports only endpoints with OpenAI structured output` (a reply that is not the object of the probe, or a server that rejects the request with HTTP 400 or 422. HTTP 400 or 422 is the usual way that a server declines `response_format`.)
- `endpoint 'lab-vllm' answered HTTP 404: ...` (any other status that the server answered with, including 5xx)
- `endpoint 'lab-vllm' could not be reached: ...` (no answer at all)
- the failure of the auth command, for example `endpoint 'vertex-gemini' auth command 'gcloud' exited with 1`

The probe costs one model call for each endpoint. Thus it runs only with `--verify-keys`, and never on a plain `agac run`. A pass proves that the server honours a small schema, not every schema. The check on each reply at run time stays the guard.

## Preflight

Before the first request, preflight refuses an endpoint action in these conditions:

- The url, the credential or a header variable of the endpoint is unset.
- The auth command of the endpoint is not on `PATH`.

Examples of the error text:

```
Action 'classify': endpoint 'azure-gpt' reads AZURE_OPENAI_KEY, which is not set
Action 'classify': endpoint 'openrouter' reads its url from OPENROUTER_URL, which is not set
Action 'classify': endpoint 'vertex-gemini' auth command 'gcloud' is not on PATH
```

agac refuses each mistake in the block itself when the project loads. The message gives the endpoint name and the key, for example `endpoints.lab-vllm: unknown key 'format'`.
