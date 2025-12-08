"""Loop correlation utilities for processors."""

from .loop_id_generator import LoopIdGenerator

# Backward compatibility alias
LoopCorrelator = LoopIdGenerator

__all__ = ['LoopIdGenerator', 'LoopCorrelator']
