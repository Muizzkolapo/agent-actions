"""Version correlation utilities for processors."""

from .version_id import VersionIdGenerator

# Backward compatibility alias
VersionCorrelator = VersionIdGenerator

__all__ = ["VersionIdGenerator", "VersionCorrelator"]
