"""Canonical reason string constants for record lifecycle events.

Every reason/skip/cascade/filter string that flows through disposition writes,
tombstone metadata, ProcessingResult factories, or telemetry events must be
defined here.  Production code imports from this module instead of using bare
string literals.
"""

# -- Success -----------------------------------------------------------------
SUCCESS = "success"

# -- Guard outcomes ----------------------------------------------------------
GUARD_SKIP = "guard_skip"
GUARD_PREFILTER_SKIP = "guard_prefilter_skip"
GUARD_FILTER = "guard_filter"
LLM_LAYER_GUARD_SKIP = "llm_layer_guard_skip"
LLM_LAYER_GUARD_FILTER = "llm_layer_guard_filter"

# -- Cascade / upstream ------------------------------------------------------
UPSTREAM_UNPROCESSED = "upstream_unprocessed"
OBSERVE_FIELD_MISSING = "observe_field_missing"
SOURCE_UNRESOLVED = "source_unresolved"
ALL_VERSIONS_FILTERED = "all_versions_filtered"

# -- Prep failures -----------------------------------------------------------
PREP_FAILED = "prep_failed"

# -- Batch -------------------------------------------------------------------
BATCH_NOT_RETURNED = "batch_not_returned"

# -- Tool (FILE mode) -------------------------------------------------------
TOOL_MISSING_RECORD = "tool_missing_record"
# Success reason for a many-to-one contributor: consumed as intended, its
# content lives in the collapsed output rather than an own output record.
COLLAPSED_INTO_OUTPUT = "collapsed_into_output"

# -- Empty output ------------------------------------------------------------
EMPTY_OUTPUT = "empty_output"

# -- Exhaustion --------------------------------------------------------------
RETRY_EXHAUSTED = "retry_exhausted"
EXPECTATIONS_EXHAUSTED = "expectations_exhausted"

# -- Disposition fallbacks ---------------------------------------------------
UNPROCESSED = "unprocessed"
PARSE_ERROR = "parse_error"

# -- Action-level halt markers -----------------------------------------------
# Node-level disposition ``detail``; read on the next run to tell a deliberate
# halt from a transient failure worth retrying.
HALTED_ON_EXHAUSTED = "halted_on_exhausted"

# -- Action-level skip reasons -----------------------------------------------
GUARD_FILTERED_ALL = "All records guard-filtered — no output produced"
