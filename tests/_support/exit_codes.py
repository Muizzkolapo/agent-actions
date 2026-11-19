"""The exit codes a test accepts from a run or a retry that it does not expect to fail."""

from agent_actions.cli.exit_codes import EXIT_PAUSED, EXIT_RECORD_FAILURES, EXIT_SUCCESS

# The command ended with no failed action: it finished, it finished holding failed or
# exhausted records, or it paused for a batch.
RAN_TO_ITS_END = frozenset({EXIT_SUCCESS, EXIT_RECORD_FAILURES, EXIT_PAUSED})
