"""Regression tests for the reprompt sibling of VIOL-0031.

``parse_reprompt_config`` and ``create_reprompt_service_from_config`` used
the same ``.get("key", default)`` antipattern as the retry path. With a
bare YAML key like ``max_attempts:`` or ``on_exhausted:`` (which parses
to ``None``), the default substitution was skipped and ``None`` flowed
into:

- ``ParsedRepromptConfig.on_exhausted`` — downstream
  ``OnExhaustedPolicy(None)`` raised ``ValueError`` in the batch retry
  service (``llm/batch/services/processing.py``).
- ``RepromptService.__init__`` validation — ``_validate_exhausted_option``
  rejected ``None`` with ``ValueError("on_exhausted must be one of ...")``.
- ``RepromptService`` numeric inits — ``max_attempts < 1`` check
  raised ``TypeError`` for ``None < 1``.

All three call sites now coalesce with ``or <default>`` so the
documented defaults survive a bare YAML key.
"""

import pytest

from agent_actions.processing.recovery.reprompt import (
    ParsedRepromptConfig,
    create_reprompt_service_from_config,
    parse_reprompt_config,
)


@pytest.mark.parametrize(
    "reprompt_config,expected",
    [
        pytest.param(
            {"validation": "check_fn", "max_attempts": None, "on_exhausted": None},
            ParsedRepromptConfig(
                validation_name="check_fn", max_attempts=2, on_exhausted="return_last"
            ),
            id="both-null",
        ),
        pytest.param(
            {"validation": "check_fn", "max_attempts": None},
            ParsedRepromptConfig(
                validation_name="check_fn", max_attempts=2, on_exhausted="return_last"
            ),
            id="max-attempts-null",
        ),
        pytest.param(
            {"validation": "check_fn", "on_exhausted": None},
            ParsedRepromptConfig(
                validation_name="check_fn", max_attempts=2, on_exhausted="return_last"
            ),
            id="on-exhausted-null",
        ),
        pytest.param(
            {"validation": "check_fn", "max_attempts": 5, "on_exhausted": "raise"},
            ParsedRepromptConfig(validation_name="check_fn", max_attempts=5, on_exhausted="raise"),
            id="explicit-values-preserved",
        ),
    ],
)
def test_parse_reprompt_config_coalesces_null_values(reprompt_config, expected):
    """Bare YAML keys (parsed as ``None``) must default to the documented
    values rather than propagating ``None`` into ``ParsedRepromptConfig``."""
    assert parse_reprompt_config(reprompt_config) == expected


class _AcceptAllValidator:
    """Minimal validator stub for the no-``validation``-key branch."""

    name = "accept_all"

    def validate(self, response, **_):
        return True, ""


@pytest.mark.parametrize(
    "reprompt_config",
    [
        pytest.param(
            {"max_attempts": None, "on_exhausted": None, "critique_after_attempt": None},
            id="all-three-null",
        ),
        pytest.param({"max_attempts": None}, id="max-attempts-null-only"),
        pytest.param({"on_exhausted": None}, id="on-exhausted-null-only"),
        pytest.param({"critique_after_attempt": None}, id="critique-after-attempt-null-only"),
    ],
)
def test_create_reprompt_service_validator_branch_coalesces_null_values(reprompt_config):
    """``create_reprompt_service_from_config`` with an external validator
    and bare YAML keys must produce a usable ``RepromptService`` instead
    of raising on ``None < 1`` (max_attempts), ``OnExhaustedPolicy(None)``
    (on_exhausted), or other ``None``-propagation crashes."""
    service = create_reprompt_service_from_config(
        reprompt_config,
        validator=_AcceptAllValidator(),
    )
    assert service is not None
    assert service.max_attempts == 2
    assert service.on_exhausted == "return_last"


def test_create_reprompt_service_validation_branch_coalesces_critique_null():
    """The post-``parse_reprompt_config`` ``RepromptService`` constructor
    also reads ``critique_after_attempt`` — a bare YAML key here must
    default to ``2`` rather than propagating ``None``."""
    service = create_reprompt_service_from_config(
        {"validation": "check_fn", "critique_after_attempt": None},
        validator=_AcceptAllValidator(),
    )
    assert service is not None
    assert service._critique_after_attempt == 2


def test_parse_reprompt_config_rejects_explicit_zero_max_attempts():
    """Explicit ``max_attempts: 0`` is invalid configuration and must be
    surfaced — the null-coalesce in the fix must distinguish ``None``
    (bare YAML, apply default) from ``0`` (explicit invalid value,
    propagate so ``RepromptService.__init__`` can raise)."""
    parsed = parse_reprompt_config({"validation": "check_fn", "max_attempts": 0})
    assert parsed is not None
    # The explicit 0 must NOT be silently rewritten to the default;
    # downstream RepromptService.__init__ enforces max_attempts >= 1.
    assert parsed.max_attempts == 0


def test_create_reprompt_service_surfaces_explicit_zero_max_attempts():
    """Constructing the service with explicit ``max_attempts: 0`` must
    raise ``ValueError`` — the coalesce fix must not mask the invariant."""
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        create_reprompt_service_from_config(
            {"max_attempts": 0},
            validator=_AcceptAllValidator(),
        )
