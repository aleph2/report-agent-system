"""Consume durable feedback only with a host-supplied, authorized model factory."""

from .learning import binding
from .learning_runtime import _run_optimizer_locked
from .errors import ActionRejected


async def consume_pending(workspace, model_factory, *, max_steps=40, experiment_runner=None):
    if not 1 <= max_steps <= 100:
        raise ValueError("INVALID_LEARNING_STEP_LIMIT")
    bound = binding(workspace)
    if not bound:
        raise ActionRejected("LEARNING_NOT_CONFIGURED")
    library, scope = bound
    with workspace.store.run_lock():
        claim = library.claim_feedback(scope)
        if not claim:
            return {"state": "idle"}
        workspace.store.set("learning_active_feedback", claim)
        try:
            # The factory is not even constructed/called for an empty queue.
            await _run_optimizer_locked(workspace, model_factory(), max_steps=max_steps,
                                        experiment_runner=experiment_runner)
            library.finish_claim(scope, claim["id"])
        except BaseException as exc:
            library.finish_claim(scope, claim["id"], type(exc).__name__)
            raise
        finally:
            workspace.store.set("learning_active_feedback", None)
        return {"state": "completed", "claim": claim, "job": workspace.store.get("learning_job")}


async def optimize_saved_candidate(workspace, experience_id, version, experiment_runner):
    """Explicit authorized experiment on a saved candidate, without repeating learning.

    The same capability can be selected by the native learner when its host has
    supplied an authorized experiment_runner. No implicit provider/job is created.
    """
    with workspace.store.run_lock():
        return await _optimize_saved_candidate_locked(workspace, experience_id, version, experiment_runner)


async def _optimize_saved_candidate_locked(workspace, experience_id, version, experiment_runner):
    from uuid import uuid4
    bound = binding(workspace)
    if not bound or experiment_runner is None:
        raise ActionRejected("AUTHORIZED_EXPERIMENT_RUNNER_REQUIRED")
    library, scope = bound
    candidate = next((r for r in library.list_versions(scope)
                      if r['id'] == experience_id and r['version'] == version), None)
    if candidate is None:
        raise ActionRejected("EXPERIENCE_NOT_AVAILABLE")
    prior = workspace.store.get("guidance_experiment")
    if prior:
        raise ActionRejected("GUIDANCE_EXPERIMENT_EXISTS_USE_NEW_AUTHORIZED_WORKSPACE")
    job = {"id": str(uuid4()), "state": "running", "seed_ref": {"id": experience_id, "version": version},
           "automatic_release": False, "automatic_retry": False}
    workspace.store.set("guidance_experiment", job)
    workspace.store.event("guidance_experiment_started", job)
    try:
        result = await experiment_runner(candidate)
        job.update(state="completed", result=result, quality_verified=False)
    except BaseException as exc:
        job.update(state="failed", error_type=type(exc).__name__)
        raise
    finally:
        workspace.store.set("guidance_experiment", job)
        workspace.store.set("guidance_experiment:" + job["id"], job)
        workspace.store.event("guidance_experiment_terminal", job)
    return job
