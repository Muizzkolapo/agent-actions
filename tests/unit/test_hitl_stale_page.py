"""Regression assertions for VIOL-0099.

The HITL approval page must:

1. Show a session-expiry countdown banner so the user can see how much
   time the workflow-thread-side timer has left.
2. Catch network failures on submit (server gone, idle-shutdown fired)
   and render a friendly inline message telling the user to re-launch
   ``agac run --resume`` — never a bare ``Failed to fetch`` toast.

The full failure mode (real browser hitting a dead TCP port) cannot be
reproduced in pytest. These assertions pin the markup and helper
functions that drive the behaviour; the manual checklist at
``tests/manual/hitl/STALE_PAGE_VERIFY.md`` covers the live flow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.llm.providers.hitl.server import HitlServer

TEMPLATE = Path("agent_actions/llm/providers/hitl/templates/approval.html")


def _read_template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


# ── Static template assertions (cheap; no server boot) ───────────────────


def test_template_includes_countdown_banner_element() -> None:
    """The banner has a stable id so the JS can target it."""
    assert 'id="hitl-session-countdown"' in _read_template()


def test_template_includes_countdown_time_span() -> None:
    """The MM:SS text span is the rendered countdown target."""
    assert 'id="hitl-session-countdown-time"' in _read_template()


def test_template_reads_timeout_from_server_rendered_meta_tag() -> None:
    """The countdown reads its budget from a server-rendered meta tag —
    the cleanest single round-trip delivery (no extra fetch)."""
    html = _read_template()
    assert 'name="hitl-timeout"' in html
    assert "{{ hitl_timeout }}" in html


def test_template_countdown_javascript_uses_setinterval() -> None:
    """The countdown is driven by `setInterval`. The exact cadence is
    JS-side; this asserts the mechanism, not the period."""
    assert "setInterval" in _read_template()


def test_template_catches_stale_session_and_names_resume_command() -> None:
    """When fetch fails because the server is gone, the page renders a
    fixed-position banner that names the recovery command verbatim."""
    html = _read_template()
    assert "agac run --resume" in html
    assert "_hitlShowStaleSessionError" in html


def test_template_detects_failed_to_fetch_typeerror() -> None:
    """``fetch`` rejects with ``TypeError('Failed to fetch')`` when the
    server is unreachable. The helper must look for that substring."""
    assert "Failed to fetch" in _read_template()


def test_template_does_not_use_bare_alert_on_error() -> None:
    """The bare ``alert(error.message)`` pattern is the symptom we're
    replacing. The friendly banner replaces it on the submit path."""
    html = _read_template()
    # Spot-check the canonical bad-message-shape that the VIOL flagged.
    assert "alert(err.message)" not in html
    assert "alert(error.message)" not in html


# ── Server-render assertions (exercises the template-context wiring) ─────


@pytest.fixture()
def server():
    return HitlServer(
        port=0,
        instructions="Test",
        context_data={"value": 1},
        timeout=42,
    )


@pytest.fixture()
def client(server):
    server.app.config["TESTING"] = True
    return server.app.test_client()


def test_rendered_html_embeds_configured_timeout(client, server):
    """The configured ``timeout`` value reaches the rendered ``<meta>`` tag.

    The countdown JS reads from this tag; if the server forgets to pass the
    value into the template context, the page silently defaults to 'no
    countdown' and the VIOL re-opens. Pinning the round-trip here catches
    that.
    """
    resp = client.get("/")
    # Note: this fixture predates the VIOL-0038 GET-auth change. If the
    # auth fix has landed in this branch, swap to a bootstrap-query GET.
    if resp.status_code == 401:
        resp = client.get(f"/?bootstrap={server._session_token}")
    assert resp.status_code == 200
    assert b'name="hitl-timeout" content="42"' in resp.data
