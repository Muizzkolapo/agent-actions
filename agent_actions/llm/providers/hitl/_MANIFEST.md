# HITL Provider Manifest

## Overview

Human-in-the-loop provider implementation used for approval/rejection gates in
workflow execution.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | HITL provider exports. | `llm.providers`, `hitl` |
| `client.py` | Module | HITL client that validates config and blocks for reviewer response. Decodes a JSON context with `deep_json`, so a record's nesting depth does not limit it. | `llm.realtime`, `hitl` |
| `server.py` | Module | Flask server that serves approval UI plus `/api/approve`, `/api/reject`, `/api/review-record`, `/api/review-state`, and `/api/submit` for per-record decision persistence and final file-level review submission. Each server has a `session_id` served in the page and at `/api/session`; a POST whose `X-HITL-Session` (`SESSION_HEADER`) names another session is refused with 409 and changes nothing, and `/api/shutdown` requires it, so a tab left on an earlier file cannot end the next file's review. `start_and_wait` closes the socket before returning so the next file binds the same port. The context's fingerprint and `/api/context` body are encoded with `deep_json`, and `_sanitize_context` redacts on an explicit stack, so a record nested past the JSON codec's recursion limit is served whole. | `web`, `hitl` |
| `templates/approval.html` | Template | Browser UI for per-record review navigation with auto-advance decisions, Fields/JSON record views, and final review submission. Sends its session with every POST; after a submit, a timeout or a stale-session refusal it polls `/api/session` and reloads when the next file's server is up (`_hitlWaitForNextFile`). A value `JSON.stringify` cannot encode for its depth is shown as compact JSON written on an explicit stack (`jsonTextWithoutRecursion`), and a value nested more than 50 levels is shown compact rather than indented, since indented text grows with the square of the depth (`jsonTextNestsDeeperThan`). | `hitl.ui` |
