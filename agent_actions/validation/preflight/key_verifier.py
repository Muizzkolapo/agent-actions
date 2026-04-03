"""Lightweight API key verification via vendor probes.

Each probe makes a single cheap SDK call (e.g. models.list()) to confirm the
key is accepted by the vendor.  Called only when --verify-keys is passed.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single vendor key probe."""

    vendor: str
    ok: bool
    error: str | None = None


# ── Per-vendor probe functions ────────────────────────────────────────
# Each takes an API key string, makes one lightweight call, and returns
# a ProbeResult.  SDK imports are lazy (inside the function body) to
# avoid loading unused vendor SDKs.


def _probe_openai(api_key: str) -> ProbeResult:
    try:
        from openai import AuthenticationError, OpenAI

        client = OpenAI(api_key=api_key, timeout=_PROBE_TIMEOUT_SECONDS)
        # models.list() consumes no tokens.
        client.models.list()
        return ProbeResult(vendor="openai", ok=True)
    except AuthenticationError as e:
        return ProbeResult(vendor="openai", ok=False, error=str(e))
    except Exception as e:
        # Network / timeout / rate-limit — not an auth issue.
        logger.warning("Could not verify openai key: %s (proceeding)", e)
        return ProbeResult(vendor="openai", ok=True)


def _probe_anthropic(api_key: str) -> ProbeResult:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key, timeout=_PROBE_TIMEOUT_SECONDS)
        client.models.list(limit=1)
        return ProbeResult(vendor="anthropic", ok=True)
    except anthropic.AuthenticationError as e:
        return ProbeResult(vendor="anthropic", ok=False, error=str(e))
    except Exception as e:
        logger.warning("Could not verify anthropic key: %s (proceeding)", e)
        return ProbeResult(vendor="anthropic", ok=True)


def _probe_groq(api_key: str) -> ProbeResult:
    try:
        from groq import AuthenticationError, Groq

        client = Groq(api_key=api_key, timeout=_PROBE_TIMEOUT_SECONDS)
        client.models.list()
        return ProbeResult(vendor="groq", ok=True)
    except AuthenticationError as e:
        return ProbeResult(vendor="groq", ok=False, error=str(e))
    except Exception as e:
        logger.warning("Could not verify groq key: %s (proceeding)", e)
        return ProbeResult(vendor="groq", ok=True)


def _probe_mistral(api_key: str) -> ProbeResult:
    try:
        from mistralai import Mistral

        client = Mistral(api_key=api_key, timeout_ms=_PROBE_TIMEOUT_SECONDS * 1000)
        client.models.list()
        return ProbeResult(vendor="mistral", ok=True)
    except Exception as e:
        err_str = str(e).lower()
        if "401" in err_str or "unauthorized" in err_str or "authentication" in err_str:
            return ProbeResult(vendor="mistral", ok=False, error=str(e))
        logger.warning("Could not verify mistral key: %s (proceeding)", e)
        return ProbeResult(vendor="mistral", ok=True)


def _probe_gemini(api_key: str) -> ProbeResult:
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        # Fetch one model to validate the key.
        next(iter(client.models.list(config={"page_size": 1})))
        return ProbeResult(vendor="gemini", ok=True)
    except Exception as e:
        err_str = str(e).lower()
        if "401" in err_str or "403" in err_str or "api key" in err_str:
            return ProbeResult(vendor="gemini", ok=False, error=str(e))
        logger.warning("Could not verify gemini key: %s (proceeding)", e)
        return ProbeResult(vendor="gemini", ok=True)


# ── Registry ──────────────────────────────────────────────────────────

_PROBE_REGISTRY: dict[str, callable] = {
    "openai": _probe_openai,
    "anthropic": _probe_anthropic,
    "groq": _probe_groq,
    "mistral": _probe_mistral,
    "gemini": _probe_gemini,
    "google": _probe_gemini,
}


# ── Public API ────────────────────────────────────────────────────────


def verify_keys(
    vendor_keys: dict[str, str],
) -> list[ProbeResult]:
    """Probe each vendor+key pair in parallel.

    Args:
        vendor_keys: Mapping of vendor name → resolved API key value.
            Should already be deduplicated by the caller.

    Returns:
        List of ProbeResult for vendors where a probe function exists.
        Vendors without a registered probe are silently skipped.
    """
    tasks: dict[str, tuple[str, str]] = {}  # vendor → (vendor, key)
    for vendor, key in vendor_keys.items():
        if vendor in _PROBE_REGISTRY:
            tasks[vendor] = (vendor, key)

    if not tasks:
        return []

    results: list[ProbeResult] = []
    logger.info("Verifying API keys for %d vendor(s)...", len(tasks))

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {
            pool.submit(_PROBE_REGISTRY[vendor], key): vendor for vendor, (_, key) in tasks.items()
        }
        for future in as_completed(futures, timeout=_PROBE_TIMEOUT_SECONDS + 2):
            vendor = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                # Future-level timeout or unexpected error — treat as non-auth.
                logger.warning("Could not verify %s key: %s (proceeding)", vendor, e)
                results.append(ProbeResult(vendor=vendor, ok=True))

    return results
