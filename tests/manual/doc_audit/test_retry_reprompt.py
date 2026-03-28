#!/usr/bin/env python3
"""Doc-vs-code audit: retry and reprompt modules.

Docs under audit:
  - docs/reference/execution/retry.md
  - docs/reference/validation/reprompting.md

Run standalone:
    python tests/manual/doc_audit/test_retry_reprompt.py

Run via module:
    python -m tests.manual.doc_audit retry_reprompt
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

# --- path fixup for standalone execution ---
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# --- project imports ---
from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.llm.batch.services.reprompt_ops import (
    apply_exhausted_reprompt_metadata,
    process_reprompt_results,
    validate_results,
)
from agent_actions.llm.batch.services.retry_ops import (
    build_exhausted_recovery,
    process_retry_results,
)
from agent_actions.llm.batch.services.retry_serialization import (
    deserialize_results,
    serialize_results,
)
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.processing.recovery.reprompt import (
    RepromptService,
)
from agent_actions.processing.recovery.response_validator import (
    ComposedValidator,
)
from agent_actions.processing.recovery.retry import (
    RetryService,
    classify_error,
    create_retry_service_from_config,
    is_retriable_error,
)
from agent_actions.processing.recovery.validation import (
    _REGISTRY_LOCK,
    _VALIDATION_REGISTRY,
    get_validation_function,
    list_validation_functions,
    reprompt_validation,
)
from agent_actions.processing.types import (
    RecoveryMetadata,
    RepromptMetadata,
    RetryMetadata,
)

# --- harness + helpers ---
from tests.manual.doc_audit.harness import DocAudit
from tests.manual.doc_audit.helpers import (
    AlwaysFail,
    AlwaysPass,
    RaisingValidator,
    SimpleValidator,
    br,
    clear_registry,
    register_test_udf,
)

# =========================================================================
# RETRY DOC: Exponential backoff
# =========================================================================


def check_RETRY_DOC_exponential_backoff():
    """Doc: 'automatically with exponential backoff'.
    Verify delays grow exponentially: delay = base * 2^(attempt-1), capped.
    """
    timestamps: list[float] = []

    def fail():
        timestamps.append(time.monotonic())
        raise NetworkError("down")

    with patch(
        "agent_actions.processing.recovery.retry.random.uniform", side_effect=lambda a, b: b
    ):
        svc = RetryService(max_attempts=4, base_delay=0.05, max_delay=0.20)
        svc.execute(fail)

    gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    tolerance = 0.05
    assert abs(gaps[0] - 0.05) < tolerance, f"gap[0]={gaps[0]:.3f}, expected ~0.05"
    assert abs(gaps[1] - 0.10) < tolerance, f"gap[1]={gaps[1]:.3f}, expected ~0.10"
    assert abs(gaps[2] - 0.20) < tolerance, f"gap[2]={gaps[2]:.3f}, expected ~0.20 (cap)"


# =========================================================================
# RETRY DOC: Options table — defaults
# =========================================================================


def check_RETRY_DOC_default_enabled_true():
    svc = create_retry_service_from_config({})
    assert svc is not None, "enabled should default to True"


def check_RETRY_DOC_default_max_attempts_3():
    svc = create_retry_service_from_config({})
    assert svc.max_attempts == 3


def check_RETRY_DOC_disabled_returns_none():
    assert create_retry_service_from_config({"enabled": False}) is None
    assert create_retry_service_from_config(None) is None


def check_RETRY_DOC_max_attempts_range_1_to_10():
    """Doc: 'Maximum attempts (1-10)'.
    Runtime validates >= 1. Schema enforces <= 10 (separate layer).
    """
    try:
        RetryService(max_attempts=0)
        raise AssertionError("max_attempts=0 should raise")
    except ValueError:
        pass

    svc = RetryService(max_attempts=15)
    assert svc.max_attempts == 15, "runtime allows >10 (schema layer enforces upper bound)"


# =========================================================================
# RETRY DOC: Retryable errors table
# =========================================================================


def check_RETRY_DOC_rate_limits_retryable():
    assert is_retriable_error(RateLimitError("429")) is True
    assert classify_error(RateLimitError("429")) == "rate_limit"


def check_RETRY_DOC_network_issues_retryable():
    assert is_retriable_error(NetworkError("timeout")) is True
    assert classify_error(NetworkError("connection timeout")) == "timeout"
    assert classify_error(NetworkError("DNS failure")) == "network_error"


def check_RETRY_DOC_server_errors_retryable():
    """Doc: 'Server Errors (HTTP 502, 503, 504) → Retryable: Yes'.
    error_wrapper wraps these as NetworkError.
    """
    mapping = VendorErrorMapping(vendor_name="TestVendor", status_code_error_types=(Exception,))
    for code in (500, 502, 503, 504):
        exc = Exception(f"server error {code}")
        exc.status_code = code  # type: ignore[attr-defined]
        wrapped = wrap_vendor_error(exc, model_name="test", mapping=mapping)
        assert isinstance(wrapped, NetworkError), f"HTTP {code} should → NetworkError"
        assert is_retriable_error(wrapped), f"HTTP {code} should be retriable"


def check_RETRY_DOC_invalid_request_not_retryable():
    assert is_retriable_error(VendorAPIError("bad key", vendor="x")) is False


def check_RETRY_DOC_non_retriable_reraises_immediately():
    calls = 0

    def bad():
        nonlocal calls
        calls += 1
        raise VendorAPIError("invalid", vendor="v")

    svc = RetryService(max_attempts=3, base_delay=0.001)
    try:
        svc.execute(bad)
    except VendorAPIError:
        pass
    assert calls == 1, f"called {calls} times, should be 1"


# =========================================================================
# RETRY DOC: Exhaustion behavior
# =========================================================================


def check_RETRY_DOC_exhaustion_return_last():
    svc = RetryService(max_attempts=2, base_delay=0.001, max_delay=0.001)
    result = svc.execute(lambda: (_ for _ in ()).throw(NetworkError("x")))
    assert result.exhausted is True
    assert result.response is None
    assert result.attempts == 2
    assert result.needed_retry is True


def check_RETRY_DOC_exhaustion_raise_in_config():
    from agent_actions.config.schema import RetryConfig

    cfg = RetryConfig(on_exhausted="raise")
    assert cfg.on_exhausted == "raise"
    try:
        RetryConfig(on_exhausted="ignore")  # type: ignore[arg-type]
        raise AssertionError("invalid on_exhausted should be rejected")
    except Exception:
        pass


# =========================================================================
# RETRY DOC: Provider error normalization
# =========================================================================


def check_RETRY_DOC_provider_error_normalization():
    mapping = VendorErrorMapping(vendor_name="TestVendor", status_code_error_types=(Exception,))

    exc_429 = Exception("rate limited")
    exc_429.status_code = 429  # type: ignore[attr-defined]
    assert isinstance(wrap_vendor_error(exc_429, "model", mapping), RateLimitError)

    exc_502 = Exception("bad gateway")
    exc_502.status_code = 502  # type: ignore[attr-defined]
    assert isinstance(wrap_vendor_error(exc_502, "model", mapping), NetworkError)

    exc_400 = Exception("bad request")
    exc_400.status_code = 400  # type: ignore[attr-defined]
    assert isinstance(wrap_vendor_error(exc_400, "model", mapping), VendorAPIError)


# =========================================================================
# REPROMPT DOC: Automatic retries
# =========================================================================


def check_REPROMPT_DOC_retries_up_to_max():
    svc = RepromptService(validator=AlwaysFail(), max_attempts=3, on_exhausted="return_last")
    calls = 0

    def llm(prompt):
        nonlocal calls
        calls += 1
        return {"data": calls}, True

    result = svc.execute(llm, original_prompt="test")
    assert calls == 3
    assert result.exhausted is True
    assert result.attempts == 3


# =========================================================================
# REPROMPT DOC: Custom validation
# =========================================================================


def check_REPROMPT_DOC_custom_validation_decorator():
    clear_registry()

    @reprompt_validation("BISAC code must be a valid category")
    def check_valid_bisac(response: dict) -> bool:
        codes = response.get("bisac_codes", [])
        return all(code.startswith(("FIC", "NON", "JUV")) for code in codes)

    func, msg = get_validation_function("check_valid_bisac")
    assert msg == "BISAC code must be a valid category"
    assert func({"bisac_codes": ["FIC001", "NON002"]}) is True
    assert func({"bisac_codes": ["INVALID"]}) is False
    clear_registry()


def check_REPROMPT_DOC_feedback_appended_to_prompt():
    validator = SimpleValidator(pass_on_attempt=2, feedback="missing field 'name'")
    prompts: list[str] = []

    def llm(prompt):
        prompts.append(prompt)
        return {"data": 1}, True

    svc = RepromptService(validator=validator, max_attempts=3)
    svc.execute(llm, original_prompt="extract names")

    assert len(prompts) == 2
    assert prompts[0] == "extract names"
    assert "missing field 'name'" in prompts[1], "feedback must be in retry prompt"
    assert "extract names" in prompts[1], "original prompt preserved"
    assert "Your response failed validation" in prompts[1]


# =========================================================================
# REPROMPT DOC: Exhaustion behavior
# =========================================================================


def check_REPROMPT_DOC_on_exhausted_return_last():
    svc = RepromptService(validator=AlwaysFail(), max_attempts=2, on_exhausted="return_last")
    result = svc.execute(lambda p: ({"bad": True}, True), original_prompt="x")
    assert result.passed is False
    assert result.exhausted is True
    assert result.response == {"bad": True}


def check_REPROMPT_DOC_on_exhausted_raise():
    svc = RepromptService(validator=AlwaysFail(), max_attempts=2, on_exhausted="raise")
    raised = False
    try:
        svc.execute(lambda p: ({"bad": True}, True), original_prompt="x")
    except RuntimeError as e:
        raised = True
        assert "exhausted" in str(e).lower()
    assert raised


def check_REPROMPT_DOC_default_max_attempts_2():
    from agent_actions.config.schema import RepromptConfig

    assert RepromptConfig().max_attempts == 2


def check_REPROMPT_DOC_default_on_exhausted_return_last():
    from agent_actions.config.schema import RepromptConfig

    assert RepromptConfig().on_exhausted == "return_last"


# =========================================================================
# REPROMPT DOC: Retry vs Reprompt
# =========================================================================


def check_REPROMPT_DOC_retry_vs_reprompt_different_errors():
    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise NetworkError("timeout")
        return "ok"

    RetryService(max_attempts=3, base_delay=0.001, max_delay=0.001).execute(flaky)

    prompts: list[str] = []
    validator = SimpleValidator(pass_on_attempt=2, feedback="fix format")
    RepromptService(validator=validator, max_attempts=3).execute(
        lambda p: (prompts.append(p) or ({"r": 1}, True)),  # type: ignore[func-returns-value]
        original_prompt="do stuff",
    )
    assert prompts[0] != prompts[1], "reprompt must modify the prompt"
    assert "fix format" in prompts[1]


def check_REPROMPT_DOC_retry_then_reprompt_same_record():
    attempt = 0

    def transport():
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise RateLimitError("429")
        return {"incomplete": True}

    retry_result = RetryService(max_attempts=3, base_delay=0.001, max_delay=0.001).execute(
        transport
    )
    assert retry_result.attempts == 2

    call = 0
    validator = SimpleValidator(pass_on_attempt=2, feedback="add 'complete' field")

    def llm(prompt):
        nonlocal call
        call += 1
        return (retry_result.response if call == 1 else {"complete": True}), True

    reprompt_result = RepromptService(validator=validator, max_attempts=3).execute(llm, "task")
    assert reprompt_result.passed is True

    recovery = RecoveryMetadata(
        retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="rate_limit"),
        reprompt=RepromptMetadata(attempts=2, passed=True, validation="simple_test_validator"),
    )
    assert not recovery.is_empty()
    assert recovery.to_dict()["retry"]["reason"] == "rate_limit"
    assert recovery.to_dict()["reprompt"]["passed"] is True


# =========================================================================
# REPROMPT DOC: Graceful degradation
# =========================================================================


def check_REPROMPT_DOC_validator_exception_continues():
    svc = RepromptService(validator=RaisingValidator(), max_attempts=2, on_exhausted="return_last")
    result = svc.execute(lambda p: ("response", True), original_prompt="x")
    assert result.passed is False
    assert result.exhausted is True
    assert result.attempts == 2


# =========================================================================
# BATCH: Recovery metadata
# =========================================================================


def check_BATCH_DOC_recovery_metadata_structure():
    rm = RecoveryMetadata(
        retry=RetryMetadata(
            attempts=3,
            failures=2,
            succeeded=True,
            reason="network_error",
            timestamp="2024-01-01T00:00:00Z",
        ),
        reprompt=RepromptMetadata(attempts=2, passed=True, validation="check_format"),
    )
    d = rm.to_dict()
    assert d["retry"]["attempts"] == 3
    assert d["retry"]["failures"] == 2
    assert d["retry"]["succeeded"] is True
    assert d["retry"]["reason"] == "network_error"
    assert d["retry"]["timestamp"] == "2024-01-01T00:00:00Z"
    assert d["reprompt"]["attempts"] == 2
    assert d["reprompt"]["passed"] is True
    assert d["reprompt"]["validation"] == "check_format"


def check_BATCH_DOC_serialization_roundtrip():
    original = [
        br(
            "r1",
            {"v": 1},
            recovery=RecoveryMetadata(
                retry=RetryMetadata(
                    attempts=3,
                    failures=2,
                    succeeded=True,
                    reason="missing",
                    timestamp="2024-06-01T10:00:00Z",
                ),
                reprompt=RepromptMetadata(attempts=1, passed=True, validation="my_val"),
            ),
        )
    ]
    roundtripped = deserialize_results(json.loads(json.dumps(serialize_results(original))))
    r = roundtripped[0]
    assert r.recovery_metadata.retry.attempts == 3
    assert r.recovery_metadata.retry.reason == "missing"
    assert r.recovery_metadata.reprompt.passed is True
    assert r.recovery_metadata.reprompt.validation == "my_val"


# =========================================================================
# BATCH: Missing record retry
# =========================================================================


def check_BATCH_build_exhausted_recovery():
    result = build_exhausted_recovery({"a", "b"}, {"a": 3, "b": 2}, retry_attempts=3)
    assert result["a"].retry.succeeded is False
    assert result["a"].retry.failures == 3
    assert result["a"].retry.reason == "missing"
    assert result["b"].retry.failures == 2


def check_BATCH_process_retry_merges_and_updates_missing():
    merged, still_missing, counts, _ = process_retry_results(
        results=[br("b", {"v": 2}, success=True)],
        accumulated_results=[br("a", {"v": 1})],
        context_map={"a": {}, "b": {}, "c": {}},
        record_failure_counts={"b": 1, "c": 1},
        missing_ids={"b", "c"},
    )
    assert "b" not in still_missing
    assert "c" in still_missing
    b = [r for r in merged if r.custom_id == "b"][0]
    assert b.recovery_metadata.retry.succeeded is True


# =========================================================================
# BATCH: Reprompt validation
# =========================================================================


def check_BATCH_validate_results_uses_udf():
    clear_registry()
    register_test_udf("check_x", passes=False, feedback="missing x")
    results = [br("a", {"y": 1}), br("b", {"y": 2}, success=False)]
    failed, vname = validate_results(results, {"reprompt": {"validation": "check_x"}})
    assert vname == "check_x"
    assert len(failed) == 1
    assert failed[0].custom_id == "a"
    clear_registry()


def check_BATCH_validate_results_skips_passed():
    clear_registry()
    register_test_udf("v", passes=False, feedback="fail")
    passed_meta = RecoveryMetadata(reprompt=RepromptMetadata(1, True, "v"))
    results = [br("a", {}, recovery=passed_meta), br("b", {})]
    failed, _ = validate_results(results, {"reprompt": {"validation": "v"}})
    assert len(failed) == 1
    assert failed[0].custom_id == "b"
    clear_registry()


def check_BATCH_reprompt_merge_preserves_retry_metadata():
    retry_meta = RecoveryMetadata(
        retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="missing")
    )
    merged = process_reprompt_results(
        [br("a", {"new": 1})], [br("a", {"old": 1}, recovery=retry_meta)]
    )
    a = {r.custom_id: r for r in merged}["a"]
    assert a.content == {"new": 1}
    assert a.recovery_metadata.retry.attempts == 2


def check_BATCH_apply_exhausted_reprompt_return_last():
    updated = apply_exhausted_reprompt_metadata(
        [br("a", {}), br("b", {})], {"a"}, "my_check", 3, "return_last"
    )
    a = [r for r in updated if r.custom_id == "a"][0]
    assert a.recovery_metadata.reprompt.passed is False
    assert a.recovery_metadata.reprompt.attempts == 3
    assert a.recovery_metadata.reprompt.validation == "my_check"
    b = [r for r in updated if r.custom_id == "b"][0]
    assert b.recovery_metadata is None or b.recovery_metadata.reprompt is None


def check_BATCH_apply_exhausted_reprompt_raise():
    try:
        apply_exhausted_reprompt_metadata([br("x", {})], {"x"}, "strict", 2, "raise")
        raise AssertionError("should raise")
    except RuntimeError as e:
        assert "exhausted" in str(e).lower()
        assert "strict" in str(e)


# =========================================================================
# VALIDATORS
# =========================================================================


def check_VALIDATOR_composed_short_circuits():
    composed = ComposedValidator([AlwaysFail("first bad"), AlwaysPass()])
    assert composed.validate({}) is False
    assert composed.feedback_message == "first bad"


def check_VALIDATOR_composed_second_fails():
    composed = ComposedValidator([AlwaysPass(), AlwaysFail("second bad")])
    assert composed.validate({}) is False
    assert composed.feedback_message == "second bad"


# =========================================================================
# UDF REGISTRY
# =========================================================================


def check_UDF_registry_thread_safety():
    clear_registry()
    errors: list[str] = []

    def register(n):
        try:
            with _REGISTRY_LOCK:
                _VALIDATION_REGISTRY[f"udf_{n}"] = (lambda r: True, f"msg_{n}")
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=register, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(list_validation_functions()) == 20
    clear_registry()


# =========================================================================
# Public API
# =========================================================================


def run_audit() -> DocAudit:
    """Execute all audit tests and return the populated harness."""
    audit = DocAudit(name="retry_reprompt")

    audit.section("RETRY DOC: Exponential backoff")
    audit.run_test(
        "Doc: 'automatically with exponential backoff'", check_RETRY_DOC_exponential_backoff
    )

    audit.section("RETRY DOC: Configuration defaults")
    audit.run_test("Doc: enabled defaults to true", check_RETRY_DOC_default_enabled_true)
    audit.run_test("Doc: max_attempts defaults to 3", check_RETRY_DOC_default_max_attempts_3)
    audit.run_test("Doc: enabled=false disables retry", check_RETRY_DOC_disabled_returns_none)
    audit.run_test("Doc: max_attempts range 1-10", check_RETRY_DOC_max_attempts_range_1_to_10)

    audit.section("RETRY DOC: Retryable errors table")
    audit.run_test("Doc: Rate Limits → Retryable: Yes", check_RETRY_DOC_rate_limits_retryable)
    audit.run_test("Doc: Network Issues → Retryable: Yes", check_RETRY_DOC_network_issues_retryable)
    audit.run_test(
        "Doc: Server Errors (502/503/504) → Retryable: Yes", check_RETRY_DOC_server_errors_retryable
    )
    audit.run_test(
        "Doc: Invalid Request → Retryable: No", check_RETRY_DOC_invalid_request_not_retryable
    )
    audit.run_test(
        "Doc: non-retriable re-raised immediately (1 call)",
        check_RETRY_DOC_non_retriable_reraises_immediately,
    )

    audit.section("RETRY DOC: Exhaustion behavior")
    audit.run_test(
        "Doc: return_last → exhausted result, workflow continues",
        check_RETRY_DOC_exhaustion_return_last,
    )
    audit.run_test(
        "Doc: raise → config schema accepts raise/return_last",
        check_RETRY_DOC_exhaustion_raise_in_config,
    )

    audit.section("RETRY DOC: Provider error normalization")
    audit.run_test(
        "Doc: all providers normalized to RateLimitError/NetworkError",
        check_RETRY_DOC_provider_error_normalization,
    )

    audit.section("REPROMPT DOC: Automatic retries")
    audit.run_test(
        "Doc: retry failed validations up to configurable limit",
        check_REPROMPT_DOC_retries_up_to_max,
    )

    audit.section("REPROMPT DOC: Custom validation")
    audit.run_test(
        "Doc: @reprompt_validation decorator + feedback",
        check_REPROMPT_DOC_custom_validation_decorator,
    )
    audit.run_test(
        "Doc: feedback appended to prompt on retry", check_REPROMPT_DOC_feedback_appended_to_prompt
    )

    audit.section("REPROMPT DOC: Exhaustion behavior")
    audit.run_test(
        "Doc: return_last → last response returned", check_REPROMPT_DOC_on_exhausted_return_last
    )
    audit.run_test("Doc: raise → RuntimeError raised", check_REPROMPT_DOC_on_exhausted_raise)
    audit.run_test("Doc: max_attempts default is 2", check_REPROMPT_DOC_default_max_attempts_2)
    audit.run_test(
        "Doc: on_exhausted default is return_last",
        check_REPROMPT_DOC_default_on_exhausted_return_last,
    )

    audit.section("REPROMPT DOC: Retry vs Reprompt")
    audit.run_test(
        "Doc: retry same request, reprompt modifies prompt",
        check_REPROMPT_DOC_retry_vs_reprompt_different_errors,
    )
    audit.run_test(
        "Doc: both trigger for same record", check_REPROMPT_DOC_retry_then_reprompt_same_record
    )

    audit.section("REPROMPT DOC: Graceful degradation")
    audit.run_test(
        "Doc: validator exception → continue, don't abort",
        check_REPROMPT_DOC_validator_exception_continues,
    )

    audit.section("BATCH: Recovery metadata")
    audit.run_test(
        "Recovery metadata structure matches doc", check_BATCH_DOC_recovery_metadata_structure
    )
    audit.run_test(
        "Serialization round-trip preserves all fields", check_BATCH_DOC_serialization_roundtrip
    )

    audit.section("BATCH: Missing record retry")
    audit.run_test(
        "build_exhausted_recovery per-record metadata", check_BATCH_build_exhausted_recovery
    )
    audit.run_test(
        "process_retry_results merges + updates missing",
        check_BATCH_process_retry_merges_and_updates_missing,
    )

    audit.section("BATCH: Reprompt validation")
    audit.run_test("validate_results uses registered UDF", check_BATCH_validate_results_uses_udf)
    audit.run_test(
        "validate_results skips already-passed records", check_BATCH_validate_results_skips_passed
    )
    audit.run_test(
        "reprompt merge preserves retry metadata",
        check_BATCH_reprompt_merge_preserves_retry_metadata,
    )
    audit.run_test(
        "apply_exhausted return_last sets metadata",
        check_BATCH_apply_exhausted_reprompt_return_last,
    )
    audit.run_test(
        "apply_exhausted raise throws RuntimeError", check_BATCH_apply_exhausted_reprompt_raise
    )

    audit.section("VALIDATORS")
    audit.run_test(
        "ComposedValidator short-circuits on first failure", check_VALIDATOR_composed_short_circuits
    )
    audit.run_test(
        "ComposedValidator second-fails reports correct feedback",
        check_VALIDATOR_composed_second_fails,
    )

    audit.section("UDF REGISTRY")
    audit.run_test("Thread-safe under concurrent registration", check_UDF_registry_thread_safety)

    return audit


def main() -> int:
    return run_audit().summary()


# =========================================================================
# Pytest entry point — collected by `uv run pytest` / CI
# =========================================================================


def test_doc_audit_retry_reprompt() -> None:
    """Run the full doc-vs-code audit; fail if any check fails."""
    audit = run_audit()
    assert audit.failed == 0, (
        f"Doc audit failed: {audit.failed} failures out of {audit.total} checks. "
        f"Failing checks: {[n for n, c in audit.errors if c == 'FAIL']}"
    )


if __name__ == "__main__":
    sys.exit(main())
