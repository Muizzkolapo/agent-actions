"""Tests for YAMLSyntaxErrorFormatter.

Locks in the UDFLoadError defer: even though a UDF that loads malformed YAML
at import raises yaml.YAMLError (which YAMLSyntaxErrorFormatter normally
claims via isinstance), the UDF wrapper must take precedence so the user
sees the failing module/file context.
"""

import pytest
import yaml

from agent_actions.errors import UDFLoadError
from agent_actions.logging.errors.formatters.yaml import YAMLSyntaxErrorFormatter


@pytest.fixture
def formatter():
    return YAMLSyntaxErrorFormatter()


@pytest.fixture
def yaml_err():
    try:
        yaml.safe_load("a:\n  b: : :")
    except yaml.YAMLError as e:
        return e
    raise AssertionError("expected YAMLError")


class TestUDFLoadErrorDefer:
    def test_defers_when_udf_load_error_is_outer_exception(self, formatter, yaml_err):
        exc = UDFLoadError(
            module="proj.uses_yaml",
            file="/proj/uses_yaml.py",
            error=str(yaml_err),
            cause=yaml_err,
        )
        # root here is the yaml.YAMLError (what extract_root_cause would return).
        assert not formatter.can_handle(exc, yaml_err, str(exc))

    def test_defers_when_udf_load_error_is_root_cause(self, formatter, yaml_err):
        udf = UDFLoadError(
            module="proj.uses_yaml",
            file="/proj/uses_yaml.py",
            error=str(yaml_err),
            cause=yaml_err,
        )
        wrapped = RuntimeError("workflow init failed")
        wrapped.__cause__ = udf
        assert not formatter.can_handle(wrapped, udf, str(udf))


class TestStillClaimsRealYAMLErrors:
    """Sanity: the defer must not regress the formatter's normal claims."""

    def test_claims_plain_yaml_error(self, formatter, yaml_err):
        assert formatter.can_handle(yaml_err, yaml_err, str(yaml_err))

    def test_rejects_unrelated_error(self, formatter):
        exc = ValueError("not a YAML problem")
        assert not formatter.can_handle(exc, exc, str(exc))
