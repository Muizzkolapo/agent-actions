# HITL Provider Manifest

## Overview

Human-in-the-loop provider implementation used for approval/rejection gates in
workflow execution.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | HITL provider exports. | `llm.providers`, `hitl` |
| `client.py` | Module | HITL client that validates config and blocks for reviewer response. | `llm.realtime`, `hitl` |
| `server.py` | Module | Flask server that serves approval UI plus `/api/approve`, `/api/reject`, `/api/review-record`, `/api/review-state`, and `/api/submit` for per-record decision persistence and final file-level review submission. | `web`, `hitl` |
| `templates/approval.html` | Template | Browser UI for per-record review navigation with auto-advance decisions, Fields/JSON record views, and final review submission. | `hitl.ui` |
