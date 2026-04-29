"""FILE-granularity HITL processing strategy."""

from __future__ import annotations

import logging
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from agent_actions.errors import AgentActionsError
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.processing.record_helpers import carry_framework_fields
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.record.envelope import RecordEnvelope

logger = logging.getLogger(__name__)


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

        ``context.source_data`` must contain the pre-context-scope records
        that passed the guard filter (set by UnifiedProcessor before
        invoking the strategy).  These are used to build structured output.
        """
        original_data = context.source_data
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

            raw_response, executed = run_dynamic_agent(
                agent_config=hitl_agent_config,
                agent_name=context.agent_name,
                context=records,
                formatted_prompt="",
                tools_path=cast(str | None, hitl_agent_config.get("tools_path")),
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

            record_reviews = (
                decision_payload.get("record_reviews")
                if isinstance(decision_payload.get("record_reviews"), list)
                else None
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
        except AgentActionsError:
            raise
        except Exception:
            logger.exception("Unexpected error in FILE mode HITL processing")
            raise
