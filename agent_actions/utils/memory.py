"""The process's peak resident memory, cheap enough to read at every step."""

import sys


def peak_rss_mb() -> float | None:
    """The most resident memory this process has held so far, in MB; None where unknown."""
    try:
        import resource
    except ImportError:  # Windows has no resource module.
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kilobytes, macOS bytes.
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(peak / divisor, 1)
