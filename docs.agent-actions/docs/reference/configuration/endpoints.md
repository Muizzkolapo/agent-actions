---
title: Endpoints
sidebar_position: 4
---

# Endpoints: bring your own OpenAI-compatible server

agac works with your endpoint if it gives OpenAI structured output. Declare the endpoint once in `agent_actions.yml`, then select it from any action with `model_vendor: <name>`. No code change is necessary to add a provider.

The endpoint MUST:

1. accept `POST <url>/chat/completions` with the OpenAI request body;
2. accept `response_format: {"type": "json_schema", "json_schema": {...}}`;
3. return `choices[0].message.content` as JSON text that matches the schema.

Servers that expose this API include vLLM, SGLang, llama.cpp and llamafile, Ollama, LM Studio, OpenRouter, Azure OpenAI and the Vertex AI OpenAI route. A server that does not speak this API is out of scope: put an adapter in front of it (vLLM, TGI, a LiteLLM proxy), or call it from a `tool` action.

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
| `url` | yes | The base URL, `http` or `https`, or exactly one `${ENV_VAR}` that holds it. A URL that ends in `/chat/completions` is refused. |
| `auth` | yes | `none`, or a mapping with exactly one of `env: NAME` (an environment variable) or `command: [argv, ...]` (a program whose output is the secret, run without a shell from the project root; parallel records run it once; after a 401 it runs once more, then the record fails). |
| `auth.header` | no | The header that carries the secret. Default `Authorization`. With another header, agac sends no `Authorization` header unless `headers:` declares one. |
| `auth.prefix` | no | Text before the secret. Default `Bearer ` for `Authorization`, empty otherwise. |
| `auth.refresh_seconds` | no | `command` only: run the command again after this many seconds. Default 3000. |
| `headers` | no | Extra headers. A value can read a variable with `${NAME}`. A literal value is refused when the header name contains `authorization`, `key`, `token` or `secret`. |
| `timeout_seconds` | no | Request timeout. Default 120. |

An endpoint name MUST be lowercase (`a-z`, `0-9`, `-`, `_`) and MUST NOT be a built-in vendor name such as `openai` or `llamafile`. A project can declare any number of endpoints.

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

The action keeps everything agac gives a built-in vendor: prompt templates, context scope, schema compilation, retries on rate limits and network faults, token usage, prompt traces, dispositions, `expect:` rules and `agac retry`. Events and errors name the endpoint.

## Rules

**Structured output only.** An endpoint action MUST have `json_mode: true` (the default) and a schema. Preflight refuses `json_mode: false` and a missing schema. A reply that does not match the schema fails the record with the reason `parse_error`; the run log names the endpoint, the schema and the mismatch.

**The credential comes from the endpoint.** `api_key` or `base_url` written on an endpoint action is refused. A value inherited from `defaults:` or `default_agent_config:` is ignored for endpoint actions, so a project that mixes endpoints and built-in vendors keeps its project-wide `api_key`. An endpoint with `auth: none` needs no `api_key` anywhere.

**Online only.** `run_mode: batch` on an endpoint action is refused: `vendor '<name>' does not support run_mode: batch`.

**Secrets are masked by value.** The credential agac reads for an endpoint (the `env` value, the command output, and a `${NAME}` header value whose header name or variable name contains `authorization`, `key`, `token` or `secret`) is masked as `[REDACTED]` in log messages, events, record reasons and the CLI's error block, including a server's error body that echoes the request headers. A value shorter than 8 characters is masked only by the key-shape rules. A `${NAME}` value in another header (a region, an API version) is not treated as a secret.

## Verify an endpoint

A server cannot report whether it honours `json_schema`; only a request proves it. `agac run --verify-keys` sends one small request to each endpoint the workflow uses, with the first `model_name` named for it, `max_tokens: 16` and a one-field schema. A credential the server refuses, a server that cannot be reached, and a reply that does not match the schema are errors:

- `endpoint 'azure-gpt' refused the credential (HTTP 401)` (or 403)
- `endpoint 'lab-vllm' does not honour response_format json_schema; agac supports only endpoints with OpenAI structured output` (a reply that is not the probe's object, or a server that rejects the request with HTTP 400 or 422, the usual way a server declines `response_format`)
- `endpoint 'lab-vllm' answered HTTP 404: ...` (any other status the server answered with, 5xx included)
- `endpoint 'lab-vllm' could not be reached: ...` (no answer at all)

The probe costs one model call per endpoint, so it runs only under `--verify-keys`, never on a plain `agac run`. A pass proves the server honours a small schema, not every schema; the check on each reply at run time stays the guard.

## Preflight

Before the first request, preflight refuses an endpoint action whose url, credential or header variable is unset, or whose auth command is not on `PATH`:

```
Action 'classify': endpoint 'azure-gpt' reads AZURE_OPENAI_KEY, which is not set
Action 'classify': endpoint 'openrouter' reads its url from OPENROUTER_URL, which is not set
Action 'classify': endpoint 'vertex-gemini' auth command 'gcloud' is not on PATH
```

Every mistake in the block itself is refused when the project loads, with the endpoint name and the key in the message, for example `endpoints.lab-vllm: unknown key 'format'`.
