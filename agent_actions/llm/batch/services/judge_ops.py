"""A batch run's `llm_judge` calls, sent as a batch of their own.

The suite runs exactly as it does online, against a judge cache filled from
batches. A pass first runs it holding back each judge call it would make, sends
those as one batch and defers; once that batch returns, its verdicts seed the
cache and the pass runs again with every call a hit.
"""

from __future__ import annotations

import copy
import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent_actions.expectations.judge import (
    JudgeRequest,
    judge_request_config,
    tally_votes,
    verdict_from_reply,
)
from agent_actions.llm.providers.batch_base import UNSENT_ERROR_KEY, batch_request_cap

if TYPE_CHECKING:
    from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JudgeCollection:
    """The judge calls a pass would make, by verdict key, and the budget it started from."""

    pending: dict[str, JudgeRequest]
    budget_before: int | None


@dataclass(frozen=True)
class JudgeSubmission:
    """A judge batch in flight: each request id to the verdict key it votes on.

    ``failed`` holds the verdict of each call whose request could not be sent, as
    online fails that call alone; ``batch_id`` is None when no request could be sent.
    """

    batch_id: str | None
    requests: dict[str, str]
    budget_remaining: int | None
    failed: dict[str, list[Any]]


def judges_in_batch(agent_config: dict[str, Any]) -> bool:
    """Whether this batch action's judge calls go out as a batch; ``judge_mode: online`` opts out."""
    expect = agent_config.get("expect")
    return isinstance(expect, dict) and expect.get("judge_mode") != "online"


def collect_judgements(
    agent_config: dict[str, Any],
    results: list[BatchResult],
    *,
    verdicts: dict[str, Any],
    budget_remaining: int | None,
    context_map: dict[str, Any] | None = None,
) -> JudgeCollection:
    """Run the suite over *results* as the next step will, holding back each judge call.

    A repair policy evaluates through the repair loop's strategy; ``repair: none``
    validates in the result writer, so its items are read the way the writer reads
    them. Only the judged rules run, so no other check is called twice, and on
    copies: an evaluation may put a verdict on a result. Each record is judged
    against the context its *context_map* row kept, as the next step judges it.
    """
    from agent_actions.expectations.service import create_expectation_service_from_config
    from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
    from agent_actions.llm.batch.processing.batch_result_strategy import (
        dispatch_results,
        validated_items,
    )
    from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
    from agent_actions.output.response.config_fields import get_default
    from agent_actions.processing.evaluation import EvaluationLoop
    from agent_actions.processing.evaluation.strategies import ExpectationStrategy

    service = create_expectation_service_from_config(
        agent_config.get("expect"),
        action_name=agent_config.get("action_name") or agent_config.get("name", "unknown"),
        agent_config=agent_config,
        judge_budget_remaining=budget_remaining,
        judge_verdicts=verdicts,
        collect_judgements=True,
    )
    judged = [e for e in service.suite.expectations if e.type == "llm_judge"] if service else []
    if service is None or not judged:
        return JudgeCollection({}, budget_remaining)
    # Rules are evaluated independently, so the judged ones alone make the same calls.
    service.suite = service.suite.model_copy(update={"expectations": judged})
    budget_before = service.judge_budget_remaining
    copies = [copy.copy(result) for result in results]
    if service.repair != "none":
        # The loop's own split would log placeholder verdicts as failures.
        strategy = ExpectationStrategy(service, BatchContextMetadata.judge_contexts(context_map))
        loop = EvaluationLoop(strategy)
        for result in copies:
            if not loop._is_already_graduated(result):
                strategy.evaluate(result)
    else:
        json_mode = agent_config.get("json_mode", get_default("json_mode"))
        output_field = agent_config.get("output_field", get_default("output_field"))
        for result in copies:
            if not BatchResultReconciler.is_answered(result):
                continue
            row = (context_map or {}).get(str(result.custom_id))
            for item in validated_items(
                result.content,
                json_mode=json_mode,
                output_field=output_field,
                dispatch=dispatch_results(agent_config, row),
            ):
                service.validate(item, BatchContextMetadata.get_judge_context(row))
    return JudgeCollection(dict(service.pending_judgements), budget_before)


def _request_id(verdict_key: str, vote: int) -> str:
    # Provider-safe whatever the key holds: Anthropic takes at most 64 of [A-Za-z0-9_-].
    return f"j_{hashlib.sha256(verdict_key.encode('utf-8')).hexdigest()[:16]}_{vote}"


def submit_judge_batch(
    provider: BaseBatchClient,
    collection: JudgeCollection,
    agent_config: dict[str, Any],
    *,
    file_name: str,
    attempt: int,
    output_directory: str,
) -> JudgeSubmission:
    """Send one request per vote of each pending call, as ``<file>_judge_<attempt>``.

    A batch takes one model and at most the provider's cap of requests, so only the
    calls of the first model met go out, up to that cap; the rest are still uncached
    when the step runs again, and go out in the next round.
    """
    model = next(iter(collection.pending.values())).model
    cap = batch_request_cap(provider)
    sent: dict[str, JudgeRequest] = {}
    held = 0
    for key, request in collection.pending.items():
        if request.model != model:
            continue
        if sent and held + request.votes > cap:
            break
        sent[key] = request
        held += request.votes

    rows: list[dict[str, Any]] = []
    requests: dict[str, str] = {}
    for key, request in sent.items():
        prompt = request.prompt
        for vote in range(request.votes):
            request_id = _request_id(key, vote)
            requests[request_id] = key
            # As the online judge call: the prompt, with no record content beside it.
            rows.append({"target_id": request_id, "prompt": prompt, "content": ""})

    config = judge_request_config(agent_config, model)
    config.pop("compiled_schema", None)
    batch_name = f"{file_name}_judge_{attempt}"
    tasks = provider.prepare_tasks(rows, config)
    failed: dict[str, list[Any]] = {}
    for row in rows:
        if UNSENT_ERROR_KEY in row:
            key = requests[row["target_id"]]
            failed.setdefault(key, [False, f"judge call failed: {row[UNSENT_ERROR_KEY]}"])
    requests = {request_id: key for request_id, key in requests.items() if key not in failed}
    batch_id = None
    if requests:
        batch_id, _status = provider.submit_batch(
            tasks=tasks, batch_name=batch_name, output_directory=output_directory
        )
        logger.info(
            "Judge batch %s submitted as %s: %d request(s) for %d value(s)",
            batch_id,
            batch_name,
            len(tasks),
            len(sent) - len(failed),
        )
    for key, verdict in failed.items():
        logger.warning("Judge request for %s could not be sent: %s", key, verdict[1])
    budget_before = collection.budget_before
    return JudgeSubmission(
        batch_id=batch_id,
        requests=requests,
        # Online charges a call before it is made, so one that cannot be sent costs a unit too.
        budget_remaining=None if budget_before is None else budget_before - len(sent),
        failed=failed,
    )


def tally_judge_results(
    results: list[BatchResult], requests: dict[str, str]
) -> dict[str, list[Any]]:
    """Each verdict key's verdict, read from its votes as online reads its replies.

    A request that errored, or came back with no reply, fails the whole call, as an
    online judge call that raises does.
    """
    by_id = {str(result.custom_id): result for result in results}
    votes: dict[str, list[tuple[bool, str]]] = {}
    errors: dict[str, str] = {}
    for request_id, key in requests.items():
        result = by_id.get(request_id)
        if result is None:
            errors.setdefault(key, "the judge batch returned no reply for this request")
            continue
        if not result.success:
            errors.setdefault(key, result.error or "the judge request failed")
            continue
        payload = result.text if result.text is not None else result.content
        if payload is None:
            votes.setdefault(key, []).append((False, "judge call returned an empty response"))
            continue
        votes.setdefault(key, []).append(verdict_from_reply(payload))

    verdicts: dict[str, list[Any]] = {}
    for key in dict.fromkeys(requests.values()):
        if key in errors:
            verdicts[key] = [False, f"judge call failed: {errors[key]}"]
        else:
            passed, detail = tally_votes(votes[key])
            verdicts[key] = [passed, detail]
    return verdicts
