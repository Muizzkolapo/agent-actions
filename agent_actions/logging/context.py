"""
DEPRECATED: This module has been removed.

The CorrelationContext and ExecutionContext classes have been replaced by
EventManager.set_context() from the event-based logging system.

Migration guide:
- CorrelationContext.get_correlation_id() → get_manager().get_context("correlation_id")
- CorrelationContext.start_workflow(name) → get_manager().set_context(workflow_name=name, correlation_id=str(uuid4())[:8])
- CorrelationContext.set_agent(name, idx) → get_manager().set_context(agent_name=name, agent_index=idx)
- CorrelationContext.set_batch(batch_id) → get_manager().set_context(batch_id=batch_id)
- CorrelationContext.get_context() / set_context() / clear_context() → Use EventManager.context() context manager

For save/restore patterns, use:
    manager = get_manager()
    with manager.context():  # Automatically saves and restores context
        # ... your code ...

See agent_actions.logging.core.EventManager for the new API.
"""

# Re-export EventManager for backwards compatibility in imports
from agent_actions.logging.core import EventManager, get_manager  # noqa: F401

__all__ = ["EventManager", "get_manager"]
