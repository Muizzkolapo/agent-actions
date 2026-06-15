"""Lightweight API key verification via vendor probes.

Each probe makes a single cheap SDK call (e.g. models.list()) to confirm the
key is accepted by the vendor.  Called only when --verify-keys is passed.
"""

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single vendor key probe."""

    vendor: str
    ok: bool
    error: str | None = None
    skipped: bool = False


# ── Per-vendor probe functions ────────────────────────────────────────
# Each takes an API key string, makes one lightweight call, and returns
# a ProbeResult.  SDK imports are lazy (inside the function body) to
# avoid loading unused vendor SDKs.

_INFRA_ERROR_PREFIX = "Infrastructure error during key verification"


def _classify_sdk_exception(
    vendor: str,
    exc: Exception,
    auth_types: tuple[type, ...],
    transient_types: tuple[type, ...],
) -> ProbeResult:
    """Classify an SDK exception into auth failure, transient, or infrastructure error."""
    if isinstance(exc, auth_types):
        return ProbeResult(vendor=vendor, ok=False, error=str(exc))
    if isinstance(exc, transient_types):
        logger.warning("Could not verify %s key: %s (proceeding — transient)", vendor, exc)
        return ProbeResult(vendor=vendor, ok=True)
    return ProbeResult(vendor=vendor, ok=False, error=f"{_INFRA_ERROR_PREFIX}: {exc}")


def _probe_openai(api_key: str) -> ProbeResult:
    try:
        from openai import AuthenticationError, OpenAI

        client = OpenAI(api_key=api_key, timeout=_PROBE_TIMEOUT_SECONDS)
        client.models.list()
        return ProbeResult(vendor="openai", ok=True)
    except ImportError:
        return ProbeResult(
            vendor="openai",
            ok=False,
            error="openai package not installed — run: pip install openai",
        )
    except Exception as e:
        from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

        return _classify_sdk_exception(
            "openai",
            e,
            (AuthenticationError,),
            (APIConnectionError, APITimeoutError, RateLimitError),
        )


def _probe_anthropic(api_key: str) -> ProbeResult:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key, timeout=_PROBE_TIMEOUT_SECONDS)
        client.models.list(limit=1)
        return ProbeResult(vendor="anthropic", ok=True)
    except ImportError:
        return ProbeResult(
            vendor="anthropic",
            ok=False,
            error="anthropic package not installed — run: pip install anthropic",
        )
    except Exception as e:
        import anthropic

        return _classify_sdk_exception(
            "anthropic",
            e,
            (anthropic.AuthenticationError,),
            (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError),
        )


def _probe_groq(api_key: str) -> ProbeResult:
    try:
        from groq import AuthenticationError, Groq

        client = Groq(api_key=api_key, timeout=_PROBE_TIMEOUT_SECONDS)
        client.models.list()
        return ProbeResult(vendor="groq", ok=True)
    except ImportError:
        return ProbeResult(
            vendor="groq",
            ok=False,
            error="groq package not installed — run: pip install groq",
        )
    except Exception as e:
        from groq import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

        return _classify_sdk_exception(
            "groq", e, (AuthenticationError,), (APIConnectionError, APITimeoutError, RateLimitError)
        )


def _probe_gemini(api_key: str) -> ProbeResult:
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        next(iter(client.models.list(config={"page_size": 1})))
        return ProbeResult(vendor="gemini", ok=True)
    except ImportError:
        return ProbeResult(
            vendor="gemini",
            ok=False,
            error="google-genai package not installed — run: pip install google-genai",
        )
    except Exception as e:
        err_str = str(e).lower()
        if "401" in err_str or "403" in err_str or "api key" in err_str:
            return ProbeResult(vendor="gemini", ok=False, error=str(e))
        # Build transient type tuple from optional Google SDK exceptions
        transient_types: list[type] = []
        try:
            from google.api_core.exceptions import ServiceUnavailable
            from google.auth.exceptions import TransportError

            transient_types.extend([ServiceUnavailable, TransportError])
        except ImportError:
            pass
        if (transient_types and isinstance(e, tuple(transient_types))) or (
            "timeout" in err_str or "connection" in err_str
        ):
            logger.warning("Could not verify gemini key: %s (proceeding — transient)", e)
            return ProbeResult(vendor="gemini", ok=True)
        return ProbeResult(vendor="gemini", ok=False, error=f"{_INFRA_ERROR_PREFIX}: {e}")


# ── Registry ──────────────────────────────────────────────────────────

_PROBE_REGISTRY: dict[str, Callable[[str], ProbeResult]] = {
    "openai": _probe_openai,
    "anthropic": _probe_anthropic,
    "groq": _probe_groq,
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
        futures: dict[Future[ProbeResult], str] = {
            pool.submit(_PROBE_REGISTRY[vendor], key): vendor for vendor, (_, key) in tasks.items()
        }
        for future in as_completed(futures, timeout=_PROBE_TIMEOUT_SECONDS + 2):
            vendor = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                logger.warning("Could not verify %s key: %s (skipping verification)", vendor, e)
                results.append(ProbeResult(vendor=vendor, ok=True, skipped=True))

    return results
