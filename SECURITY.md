# Security Policy

## Trust Boundaries

Agent Actions executes user-authored YAML workflows that can load arbitrary
Python modules (UDFs), call LLM APIs, and read/write local files.

### Single-Tenant (Default)

In the default mode the operator and the workflow author are the same person.
All file system, network, and code-execution permissions are inherited from
the shell that runs `agac`.

### Multi-Tenant / Shared Environments

If you run workflows authored by others (e.g., a shared CI server):

* **UDF code runs with the same privileges as the `agac` process.**
  Only execute workflows from trusted repositories.  Consider running
  `agac` inside a container or VM with minimal permissions.
* **API data sources** can reach any HTTP(S) endpoint the host can reach.
  Only the URL scheme is validated (must be `http` or `https`).  Network-level
  restrictions (firewall rules, container networking) are the appropriate
  control for limiting outbound access.
* **HITL approval server** binds to `127.0.0.1` and uses per-session CSRF
  tokens.  Do not expose it to untrusted networks.

## Security Controls

| Area | Control | Location |
|------|---------|----------|
| CSRF | Per-session token + Origin validation + JSON-only POST | `llm/providers/hitl/server.py` |
| Path traversal | Resolved-path containment check | `tooling/docs/server.py` |
| XML bombs | `defusedxml` replaces `xml.etree.ElementTree` | `input/loaders/xml.py`, `file_reader.py` |
| Eval safety | AST validation + restricted builtins | `input/preprocessing/parsing/parser.py` |
| Context redaction | Sensitive-key pattern redaction on `/api/context` | `llm/providers/hitl/server.py` |
| CSP | Per-request nonce, no `unsafe-inline` for scripts | `llm/providers/hitl/server.py` |

## Deployment Hardening Checklist

1. Pin dependencies with a lockfile (`uv.lock`).
2. Run `agac` as a non-root user with minimal filesystem permissions.
3. If the HITL server is needed, ensure only localhost can reach it.
4. Review UDF code before adding it to a workflow.
5. Set `AGAC_LOG_LEVEL=WARNING` in production to avoid leaking data in logs.

## Reporting Vulnerabilities

If you discover a security issue, please report it privately via
[GitHub Security Advisories](https://github.com/Muizzkolapo/agent-actions/security/advisories/new)
or email the maintainer directly.  Do not open a public issue.
