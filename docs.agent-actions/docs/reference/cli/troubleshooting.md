---
title: Troubleshooting
description: Error messages, logging, and debugging tips
sidebar_position: 7
---

# Troubleshooting

Agent Actions provides actionable error messages and multiple debugging options.

## Logging Levels

| Flag | Level | Shows |
|------|-------|-------|
| (none) | `CRITICAL` | Only critical system errors |
| `--verbose` / `-v` | `INFO` | Progress and status updates |
| `--debug` | `DEBUG` | Full exception chains, context, and tracebacks |

## Debug Mode

Use `--debug` to see full error context:

```bash
agac run -a my_workflow --debug
```

Debug mode reveals:
- Full exception chains showing where errors originated
- Context information (file paths, action names, operations)
- Complete Python tracebacks

:::tip
Redirect debug output to a file for complex issues: `agac run -a my_workflow --debug > debug.log 2>&1`
:::

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GEMINI_API_KEY` | Google Gemini API key |
| `GROQ_API_KEY` | Groq API key |
| `MISTRAL_API_KEY` | Mistral API key |
| `COHERE_API_KEY` | Cohere API key |

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Usage error (invalid arguments) |
| `130` | Interrupted by user (Ctrl+C) |

## Debugging Process

1. Start with `--verbose` to see execution flow
2. Use `--debug` to investigate specific errors
3. Check exception chains for root causes
4. Review context information (file paths, action names, operations)

## See Also

- [run Command](./run) - Execute workflows
- [schema Command](./schema) - Validate field references before execution
