"""The HITL approval page must:

1. Show a session-expiry countdown banner so the user can see how much
   time the workflow-thread-side timer has left.
2. Catch network failures on submit (server gone, idle-shutdown fired)
   and render a friendly inline message telling the user to re-launch
   ``agac run --resume`` — never a bare ``Failed to fetch`` toast.

The full failure mode (real browser hitting a dead TCP port) cannot be
reproduced in pytest. These assertions pin the markup and helper
functions that drive the behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.llm.providers.hitl.server import HitlServer

TEMPLATE = Path("agent_actions/llm/providers/hitl/templates/approval.html")


def _read_template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


# ── Static template assertions (cheap; no server boot) ───────────────────


@pytest.mark.parametrize(
    "fragments",
    [
        ['id="hitl-session-countdown"'],
        ['id="hitl-session-countdown-time"'],
        ['name="hitl-timeout"', "{{ hitl_timeout }}"],
        ["setInterval"],
        ["agac run --resume", "_hitlShowStaleSessionError"],
        ["Failed to fetch"],
    ],
    ids=[
        "countdown-banner",
        "countdown-time-span",
        "timeout-meta",
        "countdown-setinterval",
        "stale-session-hint",
        "failed-to-fetch",
    ],
)
def test_template_carries_the_countdown_and_stale_session_markup(fragments) -> None:
    html = _read_template()
    for fragment in fragments:
        assert fragment in html


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
    assert resp.status_code == 200
    assert b'name="hitl-timeout" content="42"' in resp.data
