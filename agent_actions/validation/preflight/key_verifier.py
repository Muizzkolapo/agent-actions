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
class ProbeTarget:
    """One vendor endpoint to probe with one resolved key."""

    vendor: str
    api_key: str
    base_url: str | None = None


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single vendor key probe."""

    vendor: str
    ok: bool
    error: str | None = None
    skipped: bool = False
    base_url: str | None = None


# ── Per-vendor probe functions ────────────────────────────────────────
# SDK imports stay inside each probe so unused vendor SDKs are never loaded.

_INFRA_ERROR_PREFIX = "Infrastructure error during key verification"


def _classify_sdk_exception(
    vendor: str,
    exc: Exception,
    auth_types: tuple[type, ...],
    transient_types: tuple[type, ...],
    base_url: str | None = None,
) -> ProbeResult:
    """Classify an SDK exception into auth failure, transient, or infrastructure error."""
    if isinstance(exc, auth_types):
        return ProbeResult(vendor=vendor, ok=False, error=str(exc), base_url=base_url)
    if isinstance(exc, transient_types):
        logger.warning("Could not verify %s key: %s (proceeding — transient)", vendor, exc)
        return ProbeResult(vendor=vendor, ok=True, base_url=base_url)
    return ProbeResult(
        vendor=vendor, ok=False, error=f"{_INFRA_ERROR_PREFIX}: {exc}", base_url=base_url
    )


def _probe_openai(target: ProbeTarget) -> ProbeResult:
    try:
        from openai import AuthenticationError, OpenAI

        client = OpenAI(
            api_key=target.api_key, base_url=target.base_url, timeout=_PROBE_TIMEOUT_SECONDS
        )
        client.models.list()
        return ProbeResult(vendor="openai", ok=True, base_url=target.base_url)
    except ImportError:
        return ProbeResult(
            vendor="openai",
            ok=False,
            error="openai package not installed — run: pip install openai",
            base_url=target.base_url,
        )
    except Exception as e:
        from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

        return _classify_sdk_exception(
            "openai",
            e,
            (AuthenticationError,),
            (APIConnectionError, APITimeoutError, RateLimitError),
            base_url=target.base_url,
        )


def _probe_anthropic(target: ProbeTarget) -> ProbeResult:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=target.api_key, timeout=_PROBE_TIMEOUT_SECONDS)
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


def _probe_groq(target: ProbeTarget) -> ProbeResult:
    try:
        from groq import AuthenticationError, Groq

        client = Groq(api_key=target.api_key, timeout=_PROBE_TIMEOUT_SECONDS)
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


def _probe_gemini(target: ProbeTarget) -> ProbeResult:
    try:
        from google import genai

        client = genai.Client(api_key=target.api_key)
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

_PROBE_REGISTRY: dict[str, Callable[[ProbeTarget], ProbeResult]] = {
    "openai": _probe_openai,
    "anthropic": _probe_anthropic,
    "groq": _probe_groq,
    "gemini": _probe_gemini,
}


# ── Public API ────────────────────────────────────────────────────────


def verify_keys(
    targets: list[ProbeTarget],
) -> list[ProbeResult]:
    """Probe each target in parallel.

    Targets whose vendor has no registered probe are silently skipped.
    Duplicate targets are probed once.
    """
    tasks = [t for t in dict.fromkeys(targets) if t.vendor in _PROBE_REGISTRY]

    if not tasks:
        return []

    results: list[ProbeResult] = []
    logger.info("Verifying API keys for %d endpoint(s)...", len(tasks))

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures: dict[Future[ProbeResult], ProbeTarget] = {
            pool.submit(_PROBE_REGISTRY[t.vendor], t): t for t in tasks
        }
        seen: set[ProbeTarget] = set()
        try:
            for future in as_completed(futures, timeout=_PROBE_TIMEOUT_SECONDS + 2):
                target = futures[future]
                seen.add(target)
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.warning(
                        "Could not verify %s key: %s (skipping verification)", target.vendor, e
                    )
                    results.append(
                        ProbeResult(
                            vendor=target.vendor, ok=True, skipped=True, base_url=target.base_url
                        )
                    )
        except TimeoutError:
            for future, target in futures.items():
                if target in seen:
                    continue
                if future.done():
                    try:
                        results.append(future.result())
                    except Exception:
                        results.append(
                            ProbeResult(
                                vendor=target.vendor,
                                ok=True,
                                skipped=True,
                                base_url=target.base_url,
                            )
                        )
                else:
                    logger.warning("Key verification timed out for %s (skipping)", target.vendor)
                    results.append(
                        ProbeResult(
                            vendor=target.vendor, ok=True, skipped=True, base_url=target.base_url
                        )
                    )

    return results
