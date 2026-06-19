# Module Audits — Index

Findings produced during the platform-hardening rounds. Each review records
the state of one module at the time the review was conducted. The fixes
those reviews motivated have shipped — the reviews themselves are kept here
as the historical record of *why* the changes were made.

Future module audits (track 2 of spec 554, and any later rounds) land in
this same directory and follow the same shape.

## Index

| Module | Review | Findings | Fix PR | Round |
|---|---|---|---|---|
| `agent_actions/cli/`         | [cli-review.md](cli-review.md)               | 7  P0/P1 | [#699](https://github.com/Muizzkolapo/agent-actions/pull/699) | Hardening round 1 |
| `agent_actions/utils/`       | [utils-review.md](utils-review.md)           | 6 mixed  | [#700](https://github.com/Muizzkolapo/agent-actions/pull/700) | Hardening round 1 |
| `agent_actions/config/`      | [config-review.md](config-review.md)         | 5 mixed  | [#701](https://github.com/Muizzkolapo/agent-actions/pull/701) | Hardening round 1 |
| `agent_actions/logging/`     | [logging-review.md](logging-review.md)       | 6 mixed  | [#702](https://github.com/Muizzkolapo/agent-actions/pull/702) | Hardening round 1 |
| `agent_actions/validation/`  | [validation-review.md](validation-review.md) | 5 mixed  | [#703](https://github.com/Muizzkolapo/agent-actions/pull/703) | Hardening round 1 |
| `agent_actions/guards/`      | [guards-review.md](guards-review.md)         | 4 mixed  | [#704](https://github.com/Muizzkolapo/agent-actions/pull/704) | Hardening round 1 |
| `agent_actions/prompt/`      | [prompt-review.md](prompt-review.md)         | 6 mixed  | [#708](https://github.com/Muizzkolapo/agent-actions/pull/708) | Hardening round 2 |
| `agent_actions/tooling/`     | [tooling-review.md](tooling-review.md)       | 6 mixed  | [#706](https://github.com/Muizzkolapo/agent-actions/pull/706) | Hardening round 2 |
| `agent_actions/input/`       | [input-review.md](input-review.md)           | 6 mixed  | [#710](https://github.com/Muizzkolapo/agent-actions/pull/710) | Hardening round 2 |
| `agent_actions/output/`      | [output-review.md](output-review.md)         | 6 mixed  | [#709](https://github.com/Muizzkolapo/agent-actions/pull/709) | Hardening round 2 |
| `agent_actions/errors/`      | [errors-review.md](errors-review.md)         | 4 mixed  | [#707](https://github.com/Muizzkolapo/agent-actions/pull/707) | Hardening round 2 |
| `agent_actions/models/`      | [models-review.md](models-review.md)         | 6 mixed  | [#705](https://github.com/Muizzkolapo/agent-actions/pull/705) | Hardening round 2 |

## Modules still unreviewed (track 2 of spec 554)

| Module | Status |
|---|---|
| `agent_actions/storage/`    | Queued — `audit-storage` contract |
| `agent_actions/record/`     | Queued — `audit-record` contract |
| `agent_actions/processing/` | Queued — `audit-processing` contract |
| `agent_actions/llm/`        | Queued — `audit-llm` contract |
| `agent_actions/workflow/`   | Queued — `audit-workflow` contract |

## Review shape

Each review follows roughly the same structure:

```markdown
# Code Review: agent_actions/<module>/

**Date:** YYYY-MM-DD
**Reviewer:** <who>
**Files reviewed:** <count>

## Findings

### 1. <severity> — <title>
- **File:** agent_actions/<module>/<file>.py:<line>
- **Summary:** ...
- **Failure scenario:** ...
- **Severity:** P0/P1/P2/P3
```

The earliest reviews are looser; later reviews and all track-2 audits
follow the shape defined in `harness/contracts/_AUDIT_SPEC.md`.
