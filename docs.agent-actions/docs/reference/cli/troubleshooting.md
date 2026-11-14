---
title: Troubleshooting
description: Error messages, logging levels and debug methods
sidebar_position: 7
---

# Troubleshooting

Agent Actions gives error messages that tell you what to do. It also has many debug options.

## Logging Levels

| Environment Variable | Level | Shows |
|---------------------|-------|-------|
| (default) | `INFO` | Progress and status updates |
| `AGENT_ACTIONS_LOG_LEVEL=WARNING` | `WARNING` | Only warnings and errors |
| `AGENT_ACTIONS_LOG_LEVEL=DEBUG` | `DEBUG` | Full exception chains, context and tracebacks |

## Debug Mode

To see the full context of an error, set the `AGENT_ACTIONS_LOG_LEVEL` environment variable:

```bash
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow
```

Debug mode shows:
- Full exception chains that show where errors started
- Context information (file paths, action names, operations)
- Complete Python tracebacks

For complex problems, send the debug output to a file: `AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow > debug.log 2>&1`

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GEMINI_API_KEY` | Google Gemini API key |
| `GROQ_API_KEY` | Groq API key |
| `COHERE_API_KEY` | Cohere API key |
| `OLLAMA_API_KEY` | Ollama Cloud API key |

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Usage error (invalid arguments) |
| `130` | The user interrupted the command (Ctrl+C) |

## Debug Procedure {/* #debugging-process */}

1. Read the console output at the default level (`INFO`) to see the execution flow.
2. Use `AGENT_ACTIONS_LOG_LEVEL=DEBUG` to investigate specific errors.
3. Examine the exception chains to find the root causes.
4. Examine the context information (file paths, action names, operations).

## See Also

- [run Command](./run): Run workflows
- [schema Command](./schema): Validate field references before execution
