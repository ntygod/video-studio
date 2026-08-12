from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

from app.application.commands import (
    CancelRegenerationPlanCommand,
    CommandBus,
    CommandContext,
    CreateRegenerationPlanCommand,
    PersistGeneratedArtifactCommand,
    StartRegenerationPlanCommand,
)
from app.application.regeneration_plan_service import (
    advance_regeneration_plan,
    regeneration_preview_snapshot_sha256,
)
from app.application.regeneration_preview_service import (
    preview_regeneration_cascade,
)
from app.store import UnitOfWork
from app.store.regeneration_repository import (
    NONTERMINAL_PLAN_STATUSES,
)


class RecordingJobEngine:
    def __init__(self):
        self.submitted: list[str] = []
        self._lock = Lock()

    def submit(self, job_id: str) -> None:
        with self._lock:
            self.submitted.append(job_id)


def _artifact(client, project_id: str, name: str):
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={
            "kind": "generated",
            "name": name,
            "payload": {"body": name},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _generated_from(
    app,
    project_id: str,
    name: str,
    input_version_id: str,
):
    with UnitOfWork(app.state.database) as uow:
        source_job = uow.jobs.create(
            {
                "project_id": project_id,
                "job_type": "generate",
                "payload": {
                    "capability": "llm",
                    "prompt": f"生成{name}",
                    "prompt_version": "claim-test@1",
                    "schema_id": "freeform",
                    "artifact_kind": "generated",
                    "artifact_name": name,
                    "input_version_ids": [input_version_id],
                    "context": {},
                    "parameters": {},
                },
            }
        )
    return CommandBus(app.state.database).execute(
        PersistGeneratedArtifactCommand(
            project_id=project_id,
            payload={"body": name},
            kind="generated",
            name=name,
            input_version_ids=[input_version_id],
            dependency_metadata={"job_id": source_job["id"]},
            provenance={
                "prompt_version": "claim-test@1",
                "parameters": {},
            },
        ),
        CommandContext(
            actor_type="job",
            actor_id=source_job["id"],
            idempotency_key=f"job:{source_job['id']}:artifact:1",
        ),
    ).result


def _started_stale_plan(app, client, project):
    source = _artifact(client, project["id"], "并发输入")
    output = _generated_from(
        app,
        project["id"],
        "并发输出",
        source["current_version"]["id"],
    )
    advanced = client.post(
        f"/api/artifacts/{source['id']}/versions",
        json={"payload": {"body": "输入 v2"}},
    )
    assert advanced.status_code == 201, advanced.text

    with UnitOfWork(app.state.database) as uow:
        preview = preview_regeneration_cascade(
            uow,
            project["id"],
            [source["id"]],
            include_downstream=True,
        )
    snapshot = regeneration_preview_snapshot_sha256(preview)
    plan = CommandBus(app.state.database).execute(
        CreateRegenerationPlanCommand(
            project_id=project["id"],
            artifact_ids=[source["id"]],
            include_downstream=True,
            expected_snapshot_sha256=snapshot,
        ),
        CommandContext(
            idempotency_key=f"claim-plan:{project['id']}:{snapshot}"
        ),
    ).result
    CommandBus(app.state.database).execute(
        StartRegenerationPlanCommand(
            plan_id=plan["id"],
            expected_snapshot_sha256=plan["snapshot_sha256"],
        ),
        CommandContext(
            idempotency_key=f"claim-plan-start:{plan['id']}"
        ),
    )
    with UnitOfWork(app.state.database) as uow:
        started = uow.regeneration_plans.get(plan["id"])
    step = next(
        item
        for item in started["steps"]
        if item["artifact_id"] == output["id"]
    )
    assert step["status"] == "ready"
    return started, step


def test_step_claim_is_atomic_and_expired_lease_can_be_reclaimed(
    app,
    client,
    project,
):
    _plan, step = _started_stale_plan(app, client, project)
    barrier = Barrier(2)

    def claim(owner: str):
        barrier.wait()
        with UnitOfWork(app.state.database) as uow:
            return uow.regeneration_plans.claim_step(
                step["id"],
                owner=owner,
                lease_seconds=10,
                now=100.0,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("coordinator-a", "coordinator-b")))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    first = winners[0]
    assert first["claim_attempt"] == 1
    assert first["claimed"] is True

    with UnitOfWork(app.state.database) as uow:
        too_early = uow.regeneration_plans.claim_step(
            step["id"],
            owner="coordinator-c",
            lease_seconds=10,
            now=109.0,
        )
    assert too_early is None

    with UnitOfWork(app.state.database) as uow:
        reclaimed = uow.regeneration_plans.claim_step(
            step["id"],
            owner="coordinator-c",
            lease_seconds=10,
            now=111.0,
        )
    assert reclaimed is not None
    assert reclaimed["claim_attempt"] == 2
    assert reclaimed["claim_owner"] == "coordinator-c"
    assert reclaimed["_claim_token"] != first["_claim_token"]


def test_two_coordinators_dispatch_exactly_one_child_job(
    app,
    client,
    project,
):
    plan, step = _started_stale_plan(app, client, project)
    barrier = Barrier(2)
    engine = RecordingJobEngine()

    def advance(owner: str):
        barrier.wait()
        return advance_regeneration_plan(
            app.state.database,
            plan["id"],
            engine,
            coordinator_id=owner,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                advance,
                ("coordinator-a", "coordinator-b"),
            )
        )

    assert all(result["status"] == "running" for result in results)
    with UnitOfWork(app.state.database) as uow:
        stored = uow.regeneration_plans.get(plan["id"])
        jobs = [
            job
            for job in uow.jobs.list(project["id"])
            if (job.get("payload") or {}).get(
                "_regeneration_plan_id"
            )
            == plan["id"]
        ]
    stored_step = next(
        item for item in stored["steps"] if item["id"] == step["id"]
    )
    assert stored_step["status"] == "queued"
    assert stored_step["claimed"] is False
    assert stored_step["claim_attempt"] == 1
    assert len(jobs) == 1
    assert engine.submitted == [jobs[0]["id"]]


def test_cancel_clears_claim_and_late_owner_cannot_complete(
    app,
    client,
    project,
):
    plan, step = _started_stale_plan(app, client, project)
    with UnitOfWork(app.state.database) as uow:
        claimed = uow.regeneration_plans.claim_step(
            step["id"],
            owner="coordinator-a",
            lease_seconds=120,
        )
    assert claimed is not None

    canceled = CommandBus(app.state.database).execute(
        CancelRegenerationPlanCommand(plan_id=plan["id"]),
        CommandContext(
            idempotency_key=f"claim-plan-cancel:{plan['id']}"
        ),
    ).result
    assert canceled["status"] == "canceled"

    with UnitOfWork(app.state.database) as uow:
        late = uow.regeneration_plans.complete_step_claim(
            step["id"],
            claimed["_claim_token"],
            "succeeded",
            result={"version_id": "too-late"},
        )
        stored = uow.regeneration_plans.get_step(step["id"])
    assert late is None
    assert stored["status"] == "canceled"
    assert stored["claimed"] is False


def test_terminal_plan_status_cannot_be_resurrected_by_stale_refresh(
    app,
    client,
    project,
):
    plan, _step = _started_stale_plan(app, client, project)
    with UnitOfWork(app.state.database) as uow:
        terminal = uow.regeneration_plans.set_plan_status(
            plan["id"],
            "failed",
            error="terminal",
            expected_statuses=NONTERMINAL_PLAN_STATUSES,
        )
    assert terminal["status"] == "failed"

    with UnitOfWork(app.state.database) as uow:
        stale = uow.regeneration_plans.set_plan_status(
            plan["id"],
            "running",
            expected_statuses=NONTERMINAL_PLAN_STATUSES,
        )
    assert stale["status"] == "failed"
    assert stale["error"] == "terminal"
