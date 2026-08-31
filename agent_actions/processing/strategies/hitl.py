"""FILE-granularity HITL processing strategy."""

from __future__ import annotations

import logging
import os
from hashlib import sha256
from pathlib import Path
from typing import Any

from agent_actions.errors import (
    AgentActionsError,
    ConfigurationError,
    SchemaValidationError,
    mark_action_fatal,
)
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.processing.record_helpers import carry_framework_fields
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.utils.tools_resolver import resolve_tools_path
from agent_actions.workflow.pipeline_file_mode import extract_tool_input

logger = logging.getLogger(__name__)

# The server also emits "timeout" and "error"; those mean no review happened.
_DECISION_STATUSES = frozenset({"approved", "rejected"})


class HITLStrategy:
    """Strategy for FILE-granularity HITL invocation.

    Invokes HITL once with the full array and applies the single file-level
    decision payload to every record so downstream stages retain full dataset
    cardinality.

    Conforms to the ``ProcessingStrategy`` protocol so it can be used
    with ``UnifiedProcessor.process()``.  Enrichment is handled by the
    processor, not by this strategy.
    """

    def invoke(
        self,
        records: list[dict[str, Any]],
        context: ProcessingContext,
    ) -> list[ProcessingResult]:
        """Invoke a FILE-mode HITL action and broadcast the decision.

        Records are already cascade-filtered by UnifiedProcessor — only
        processable records arrive here.

        ``context.source_data`` must contain the pre-context-scope records
        that passed the guard and cascade filters (set by UnifiedProcessor
        before invoking the strategy).  These are used to build structured
        output.
        """
        original_data = context.source_data or []
        try:
            # Inject HITL state persistence metadata into agent config
            hitl_agent_config = dict(context.agent_config)
            if context.output_directory:
                hitl_state_dir = str(Path(context.output_directory) / "hitl")
                # Derive a collision-proof, filesystem-safe key from the full
                # input path AND agent name.  Including the agent name ensures
                # multiple FILE-mode HITL actions on the same file get distinct
                # state files.  The hex hash avoids separator collisions and
                # platform-invalid characters (e.g. Windows drive-letter colons).
                identity = f"{context.file_path or 'default'}:{context.agent_name}"
                file_stem = sha256(identity.encode()).hexdigest()[:16]
                hitl_agent_config["_hitl_state_dir"] = hitl_state_dir
                hitl_agent_config["_hitl_file_stem"] = file_stem

            context_scope = context.agent_config.get("context_scope") or {}
            filtered_records = [extract_tool_input(r, context_scope) for r in records]

            # An explicit `observe: []` gates every field on purpose — do not
            # advise the author to check refs they deliberately left empty.
            declared_refs = bool(context_scope.get("observe"))
            empty_count = sum(1 for r in filtered_records if not r)
            if empty_count and declared_refs:
                logger.warning(
                    "[%s] %d/%d records have no visible fields after observe filtering — "
                    "check context_scope.observe references match upstream namespaces",
                    context.agent_name,
                    empty_count,
                    len(filtered_records),
                )

            if os.environ.get("AGAC_HITL_AUTO_APPROVE") == "true":
                logger.warning(
                    "[%s] AGAC_HITL_AUTO_APPROVE=true — bypassing human review and "
                    "auto-approving all %d records. No human approved this data. "
                    "Unset the variable to restore the approval gate.",
                    context.agent_name,
                    len(filtered_records),
                )
                raw_response: Any = {
                    "hitl_status": "approved",
                    "user_comment": "auto-approved (smoke test)",
                }
                executed = True
            else:
                raw_response, executed = run_dynamic_agent(
                    agent_config=hitl_agent_config,
                    agent_name=context.agent_name,
                    context=filtered_records,
                    formatted_prompt="",
                    tools_path=resolve_tools_path(hitl_agent_config),
                    skip_guard_eval=True,
                )

            # Unwrap single-item list from invocation service
            if isinstance(raw_response, list) and len(raw_response) == 1:
                decision_payload = raw_response[0]
            elif isinstance(raw_response, list):
                raise ValueError(
                    "FILE mode HITL must return a single decision payload, "
                    f"got {len(raw_response)} items"
                )
            else:
                decision_payload = raw_response

            if not isinstance(decision_payload, dict):
                raise ValueError(
                    "FILE mode HITL must return an object payload, "
                    f"got {type(decision_payload).__name__}"
                )

            # Detect timeout — partial reviews are persisted on disk; raise so
            # the agent is marked failed and re-runs will resume from state.
            if decision_payload.get("hitl_status") == "timeout":
                reviewed = sum(
                    1 for r in (decision_payload.get("record_reviews") or []) if r is not None
                )
                raise AgentActionsError(
                    f"HITL review timed out ({reviewed}/{len(records)} records reviewed). "
                    "Partial reviews saved. Re-run workflow to resume.",
                    context={
                        "agent_name": context.agent_name,
                        "record_count": len(records),
                    },
                )

            # Broadcasting a non-decision would stamp every record reviewed and
            # let the run succeed while guards discard the whole dataset.
            status = decision_payload.get("hitl_status")
            if status not in _DECISION_STATUSES:
                detail = decision_payload.get("user_comment") or "no detail reported"
                raise AgentActionsError(
                    f"HITL review did not produce a decision (hitl_status={status!r}, "
                    f"detail: {detail}). None of these {len(records)} records were "
                    "reviewed. Re-run the workflow to review them.",
                    context={
                        "agent_name": context.agent_name,
                        "record_count": len(records),
                        "hitl_status": status,
                    },
                )

            record_reviews = (
                decision_payload.get("record_reviews")
                if isinstance(decision_payload.get("record_reviews"), list)
                else None
            )
            # Per-record reviews overwrite the broadcast status, so the same
            # allowlist has to hold here or a non-decision reaches records anyway.
            for idx, review in enumerate(record_reviews or []):
                if not isinstance(review, dict):
                    continue
                per_record_status = review.get("hitl_status")
                if per_record_status is not None and per_record_status not in _DECISION_STATUSES:
                    raise AgentActionsError(
                        f"HITL review for record {idx} is not a decision "
                        f"(hitl_status={per_record_status!r}). None of these "
                        f"{len(records)} records were recorded. Re-run the workflow "
                        "to review them.",
                        context={
                            "agent_name": context.agent_name,
                            "record_count": len(records),
                            "record_index": idx,
                            "hitl_status": per_record_status,
                        },
                    )
            # Only propagate HITL decision metadata. Keep source business fields
            # (for example `status`) intact.
            decision_common = {
                key: value
                for key, value in decision_payload.items()
                if key in {"hitl_status", "user_comment", "timestamp"}
            }

            structured_data = []
            if original_data:
                for idx, item in enumerate(original_data):
                    hitl_output = dict(decision_common)
                    if record_reviews and idx < len(record_reviews):
                        review_payload = record_reviews[idx]
                        if isinstance(review_payload, dict):
                            for key in ("hitl_status", "user_comment"):
                                if key in review_payload:
                                    hitl_output[key] = review_payload[key]

                    record = RecordEnvelope.build(context.agent_name, hitl_output, item)
                    carry_framework_fields(item, record)
                    structured_data.append(record)

            # HITL FILE mode is always 1:1 — identity source_mapping ensures the
            # enricher extends parent lineage rather than truncating to [node_id].
            result = ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                data=structured_data,
                source_guid=None,
                raw_response=raw_response,
                executed=executed,
                source_mapping={i: i for i in range(len(structured_data))},
            )

            return [result]
        except (ConfigurationError, SchemaValidationError) as e:
            # Same knobs, same meaning as under record granularity.
            mark_action_fatal(e)
            raise
        except AgentActionsError:
            raise
        except Exception:
            logger.exception("Unexpected error in FILE mode HITL processing")
            raise
