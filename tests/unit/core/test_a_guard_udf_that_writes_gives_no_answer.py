"""A guard UDF that writes to its input gives no answer, so its action stops, naming it.

The UDF is handed a read-only view of the record, and the view refuses a write by raising.
A guard whose UDF raises passes its record, so a refused write applied no guard at all:
every record went to the action, with one warning per evaluation, and an author learned
of the write only by reading the log.
"""

import pytest

from agent_actions.errors import ConfigurationError, is_action_fatal
from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.utils.udf_management.registry import udf_tool

_CONTEXTS = pytest.mark.parametrize(
    "context", [None, {"source": {}}], ids=["no_context", "with_context"]
)


def _a1(data):
    return data["a1"] if "a1" in data else data["content"]["a1"]


def guard_probe_tidies_its_input(data):
    namespace = _a1(data)
    namespace["tier"] = namespace["tier"].strip().lower()
    return namespace["tier"] == "keep"


def guard_probe_appends_to_a_slice(data):
    head = _a1(data)["items"][:1]
    head.append({"n": 2})
    return _a1(data)["tier"] == "keep"


def guard_probe_raises_while_handling_the_refusal(data):
    try:
        _a1(data)["tier"] = "keep"
    except TypeError as error:
        raise ValueError("could not tidy the record") from error
    return True


@pytest.fixture(autouse=True)
def _register_probes():
    """Registered per test: an earlier test clearing the registry would leave the guard
    naming a missing UDF, which raises before the UDF can write anything."""
    for fn in (
        guard_probe_tidies_its_input,
        guard_probe_appends_to_a_slice,
        guard_probe_raises_while_handling_the_refusal,
    ):
        udf_tool(fn)


def _item(tier: str = " Drop "):
    return {"source_guid": "g1", "content": {"a1": {"tier": tier, "items": [{"n": 1}]}}}


def _evaluate(udf, item, context):
    return GuardEvaluator().evaluate(item, None, context=context, conditional_clause=udf.__name__)


class TestARefusedWriteStopsTheAction:
    @_CONTEXTS
    def test_the_guard_raises_naming_the_udf_and_what_to_do_instead(self, context):
        item = _item()

        with pytest.raises(ConfigurationError) as raised:
            _evaluate(guard_probe_tidies_its_input, item, context)

        message = str(raised.value)
        assert "guard_probe_tidies_its_input" in message
        assert "wrote to its input" in message
        assert "return a value instead of mutating the input" in message
        assert item == _item(), "the refusal must still keep the write off the record"

    @_CONTEXTS
    def test_the_error_is_fatal_to_the_action(self, context):
        """Taken as one file's failure, the file's records would go missing while the
        action completed: the guard is wrong for every record, not for this one."""
        with pytest.raises(ConfigurationError) as raised:
            _evaluate(guard_probe_tidies_its_input, _item(), context)

        assert is_action_fatal(raised.value)

    @_CONTEXTS
    def test_a_guard_that_would_admit_the_record_stops_it_too(self, context):
        """The write comes before the answer, so the guard has no answer either way."""
        with pytest.raises(ConfigurationError, match="wrote to its input"):
            _evaluate(guard_probe_tidies_its_input, _item(" Keep "), context)

    @_CONTEXTS
    def test_a_write_to_a_slice_of_a_list_in_the_input_is_refused_the_same_way(self, context):
        """A slice of a list in the view is read-only too."""
        item = _item()

        with pytest.raises(ConfigurationError, match="guard_probe_appends_to_a_slice"):
            _evaluate(guard_probe_appends_to_a_slice, item, context)

        assert item == _item()

    @_CONTEXTS
    def test_an_error_raised_in_answer_to_the_refusal_is_the_refusal(self, context):
        """The UDF gave up because its write was refused; passing the record would hide
        the write behind an error of the author's own wording."""
        with pytest.raises(ConfigurationError, match="wrote to its input"):
            _evaluate(guard_probe_raises_while_handling_the_refusal, _item(), context)
