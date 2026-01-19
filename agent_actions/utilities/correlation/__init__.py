"""Version correlation utilities for processors."""

from .version_id_generator import VersionIdGenerator

# Backward compatibility alias
VersionCorrelator = VersionIdGenerator

__all__ = ["VersionIdGenerator", "VersionCorrelator"]
