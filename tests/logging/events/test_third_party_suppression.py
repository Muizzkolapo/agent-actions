"""Spec 555 step 1: framework clamps noisy SDK/HTTP loggers to WARNING; module_levels overrides win."""

from __future__ import annotations

import logging

import pytest

from agent_actions.logging.config import LoggingConfig
from agent_actions.logging.factory import _THIRD_PARTY_NOISY_LOGGERS, LoggerFactory

# Source of truth lives in the factory. Importing it here means adding a
# logger over there automatically widens parametrized coverage.
NOISY_LOGGERS = list(_THIRD_PARTY_NOISY_LOGGERS)


@pytest.fixture(autouse=True)
def reset_factory_and_logger_state():
    """Reset factory and restore third-party logger levels; force root to INFO so suppression isn't a tautology."""
    LoggerFactory.reset()

    saved_root = logging.getLogger().level
    saved = {name: logging.getLogger(name).level for name in NOISY_LOGGERS}
    saved["my_custom_lib"] = logging.getLogger("my_custom_lib").level

    logging.getLogger().setLevel(logging.INFO)

    try:
        yield
    finally:
        LoggerFactory.reset()
        logging.getLogger().setLevel(saved_root)
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)


class TestThirdPartySuppression:
    """Spec 555 step 1: framework explicitly clamps SDK/HTTP loggers to WARNING."""

    @pytest.mark.parametrize("logger_name", NOISY_LOGGERS)
    def test_logger_is_explicitly_clamped(self, logger_name):
        """Each noisy logger's own ``.level`` (not inherited) is WARNING after init."""
        LoggerFactory.initialize()

        actual = logging.getLogger(logger_name).level
        assert actual == logging.WARNING, (
            f"{logger_name!r} level is {logging.getLevelName(actual)}; "
            "spec 555 step 1 requires the framework to clamp it to WARNING"
        )

    def test_info_messages_from_third_party_are_silenced(self):
        """End-to-end: an httpx INFO log is dropped; WARNING still passes."""
        LoggerFactory.initialize()

        captured: list[logging.LogRecord] = []

        class CaptureHandler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        httpx = logging.getLogger("httpx")
        handler = CaptureHandler(level=logging.DEBUG)
        httpx.addHandler(handler)
        try:
            httpx.info("HTTP GET https://api.example.com/v1/messages")
            httpx.warning("retry exhausted")
        finally:
            httpx.removeHandler(handler)

        levels = [r.levelno for r in captured]
        assert logging.INFO not in levels, "INFO from httpx leaked past suppression"
        assert logging.WARNING in levels, "WARNING from httpx must still be visible"

    def test_agent_actions_logger_not_clamped(self):
        """Suppression must not touch the framework's own logger tree."""
        LoggerFactory.initialize()

        # factory._setup_logging_bridge sets agent_actions to DEBUG so
        # event handlers see everything; clamping it would defeat that.
        assert logging.getLogger("agent_actions").level == logging.DEBUG

    def test_provider_wrapper_logger_not_affected(self):
        """Provider wrappers live under agent_actions.*, not under the SDK root."""
        LoggerFactory.initialize()

        wrapper = logging.getLogger("agent_actions.llm.providers.openai.client")
        # Should inherit from agent_actions (DEBUG), NOT from "openai" (WARNING)
        assert wrapper.getEffectiveLevel() == logging.DEBUG


class TestModuleLevelOverrides:
    """``module_levels`` in LoggingConfig is the escape hatch for suppression."""

    def test_user_can_lower_a_clamped_logger_back_to_info(self):
        """User can opt back in to INFO for a suppressed third-party logger."""
        config = LoggingConfig(module_levels={"httpx": "INFO"})
        LoggerFactory.initialize(config=config)

        assert logging.getLogger("httpx").level == logging.INFO

    def test_user_can_set_level_on_unsuppressed_logger(self):
        """module_levels also works for loggers not in the suppression list."""
        config = LoggingConfig(module_levels={"my_custom_lib": "ERROR"})
        LoggerFactory.initialize(config=config)

        assert logging.getLogger("my_custom_lib").level == logging.ERROR

    def test_warn_is_accepted_as_alias_for_warning(self):
        """Python's logging module treats WARN and WARNING as equivalent."""
        config = LoggingConfig(module_levels={"my_custom_lib": "WARN"})
        LoggerFactory.initialize(config=config)

        assert logging.getLogger("my_custom_lib").level == logging.WARNING

    def test_invalid_module_level_emits_stderr_warning(self, capsys):
        """Garbage value is rejected with stderr warning; WARNING clamp stands (start from DEBUG to prove sequence)."""
        logging.getLogger("httpx").setLevel(logging.DEBUG)

        config = LoggingConfig(module_levels={"httpx": "NOT_A_LEVEL"})
        LoggerFactory.initialize(config=config)

        captured = capsys.readouterr()
        assert "module_levels" in captured.err
        assert "httpx" in captured.err
        assert "NOT_A_LEVEL" in captured.err
        # Clamp ran AND invalid override was rejected → final state is WARNING,
        # not DEBUG (would mean clamp didn't run) and not NOT_A_LEVEL (would
        # mean the override sneaked past validation).
        assert logging.getLogger("httpx").level == logging.WARNING

    @pytest.mark.parametrize("bad_value", [True, 20, ["INFO"], None])
    def test_non_string_module_level_rejected_at_runtime(self, bad_value, capsys):
        """Non-string values (bool/int/list/None) are rejected, suppression default holds."""
        config = LoggingConfig(module_levels={"httpx": bad_value})

        LoggerFactory.initialize(config=config)

        err = capsys.readouterr().err
        assert "httpx" in err
        assert logging.getLogger("httpx").level == logging.WARNING

    def test_value_that_stringifies_to_valid_level_still_rejected(self, capsys):
        """Type-guard (not str-coercion) — a non-string whose __str__ returns 'INFO' must NOT override."""

        class StringifiesToInfo:
            def __str__(self):
                return "INFO"

        config = LoggingConfig(module_levels={"httpx": StringifiesToInfo()})
        LoggerFactory.initialize(config=config)

        err = capsys.readouterr().err
        assert "httpx" in err
        # If the helper coerced via str(), httpx would be INFO; type-guard keeps it at WARNING (clamp).
        assert logging.getLogger("httpx").level == logging.WARNING

    def test_non_string_key_rejected_without_crash(self, capsys):
        """A non-string key (e.g. int from YAML) is skipped, not propagated to getLogger."""
        config = LoggingConfig(module_levels={42: "INFO"})

        LoggerFactory.initialize(config=config)

        err = capsys.readouterr().err
        assert "42" in err
        assert "str" in err

    def test_agent_actions_root_override_refused(self, capsys):
        """Overriding ``agent_actions`` would break the events.json bridge."""
        config = LoggingConfig(module_levels={"agent_actions": "ERROR"})

        LoggerFactory.initialize(config=config)

        # Bridge wins: agent_actions stays at DEBUG so every event reaches handlers.
        assert logging.getLogger("agent_actions").level == logging.DEBUG
        captured = capsys.readouterr()
        assert "agent_actions" in captured.err

    def test_agent_actions_child_override_refused(self, capsys):
        """Children of ``agent_actions`` are guarded for the same reason."""
        config = LoggingConfig(module_levels={"agent_actions.llm.providers.openai.client": "ERROR"})

        LoggerFactory.initialize(config=config)

        wrapper = logging.getLogger("agent_actions.llm.providers.openai.client")
        # Override refused → wrapper inherits DEBUG from agent_actions, not ERROR.
        assert wrapper.getEffectiveLevel() == logging.DEBUG
        captured = capsys.readouterr()
        assert "agent_actions.llm.providers.openai.client" in captured.err


class TestResetIsolatesThirdPartyLoggers:
    """``LoggerFactory.reset()`` must restore loggers to their pre-init state."""

    def test_reset_restores_pre_init_level_not_notset(self):
        """Host app set httpx=ERROR before our init; reset() must restore ERROR, not blow it away to NOTSET."""
        logging.getLogger("httpx").setLevel(logging.ERROR)

        LoggerFactory.initialize()
        assert logging.getLogger("httpx").level == logging.WARNING

        LoggerFactory.reset()

        assert logging.getLogger("httpx").level == logging.ERROR

    def test_reset_restores_notset_when_logger_was_untouched(self):
        """If a logger was at NOTSET before init, reset() returns it to NOTSET."""
        logging.getLogger("httpx").setLevel(logging.NOTSET)

        LoggerFactory.initialize()
        LoggerFactory.reset()

        assert logging.getLogger("httpx").level == logging.NOTSET


class TestSuppressionIdempotency:
    """Force re-init must reapply suppression, not leak old state."""

    def test_force_reinit_reapplies_suppression(self):
        """After force=True the third-party levels are still clamped."""
        LoggerFactory.initialize()
        # Simulate something downstream re-enabling DEBUG on httpx
        logging.getLogger("httpx").setLevel(logging.DEBUG)

        LoggerFactory.initialize(force=True)

        assert logging.getLogger("httpx").level == logging.WARNING

    def test_force_reinit_drops_module_level_no_longer_in_config(self):
        """A logger set via module_levels in the FIRST config must be restored when the SECOND config omits it."""
        # Pre-existing host-app level we must respect.
        logging.getLogger("my_custom_lib").setLevel(logging.NOTSET)

        first = LoggingConfig(module_levels={"my_custom_lib": "ERROR"})
        LoggerFactory.initialize(config=first)
        assert logging.getLogger("my_custom_lib").level == logging.ERROR

        second = LoggingConfig()  # module_levels = {}
        LoggerFactory.initialize(config=second, force=True)

        # Without restore, my_custom_lib would still be ERROR from the prior config.
        assert logging.getLogger("my_custom_lib").level == logging.NOTSET
