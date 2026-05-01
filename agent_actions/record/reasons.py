"""Canonical reason string constants for record lifecycle events.

Every reason/skip/cascade/filter string that flows through disposition writes,
tombstone metadata, ProcessingResult factories, or telemetry events must be
defined here.  Production code imports from this module instead of using bare
string literals.

Test files may still use bare strings — that is intentional so tests break
visibly if a constant value changes.
"""

# -- Guard outcomes ----------------------------------------------------------
GUARD_SKIP = "guard_skip"
GUARD_PREFILTER_SKIP = "guard_prefilter_skip"
GUARD_FILTER = "guard_filter"
LLM_LAYER_GUARD_SKIP = "llm_layer_guard_skip"
LLM_LAYER_GUARD_FILTER = "llm_layer_guard_filter"

# -- Cascade / upstream ------------------------------------------------------
UPSTREAM_UNPROCESSED = "upstream_unprocessed"

# -- Batch -------------------------------------------------------------------
BATCH_NOT_RETURNED = "batch_not_returned"

# -- Exhaustion --------------------------------------------------------------
RETRY_EXHAUSTED = "retry_exhausted"

# -- Disposition fallbacks ---------------------------------------------------
UNPROCESSED = "unprocessed"
PARSE_ERROR = "parse_error"

# -- Action-level skip reasons -----------------------------------------------
GUARD_FILTERED_ALL = "All records guard-filtered — no output produced"

# -- FILTER_PHASE values (batch preparator) -----------------------------------
FILTER_PHASE_UPSTREAM = "upstream_unprocessed"
FILTER_PHASE_UNIFIED = "unified"
