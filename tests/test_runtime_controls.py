import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import inspect

from app.application.agent.durable_loop import (
    AGENT_PLAN_KIND,
    AGENT_TASK_TYPE,
)
from app.application.task_runtime import TaskRuntime
from app.store import Database, UnitOfWork
from app.store.repositories import ConflictError
from app.store.task_runtime_extensions import RuntimeAdmissionFull


def _task(*, available_at=None):
    definition = {
        "key": "execute",
        "type": AGENT_TASK_TYPE,
        "max_attempts": 1,
    }
    if available_at is not None:
        definition["available_at"] = available_at
    return definition


def _state(database):
    with UnitOfWork(database) as uow:
        return uow.task_runtime.admission_state(AGENT_PLAN_KIND)


def test_agent_admission_rejects_over_capacity_and_cancel_releases(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    with UnitOfWork(app.state.database) as uow:
        uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 1)

    first = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id="first",
        idempotency_key="admission:first",
        tasks=[_task(available_at=time.time() + 3600)],
    )
    assert _state(app.state.database)["active_count"] == 1

    with pytest.raises(RuntimeAdmissionFull) as rejected:
        runtime.create_plan(
            project_id=project["id"],
            kind=AGENT_PLAN_KIND,
            subject_type="test",
            subject_id="second",
            idempotency_key="admission:second",
            tasks=[_task(available_at=time.time() + 3600)],
        )
    assert rejected.value.capacity == 1
    assert rejected.value.active_count == 1

    runtime.cancel(first["id"], reason="release admission test")
    assert _state(app.state.database)["active_count"] == 0

    second = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id="second",
        idempotency_key="admission:second",
        tasks=[_task(available_at=time.time() + 3600)],
    )
    assert second["status"] == "queued"
    assert _state(app.state.database)["active_count"] == 1
    runtime.cancel(second["id"], reason="cleanup")


def test_agent_admission_is_exclusive_across_process_transactions(
    app,
    project,
):
    with UnitOfWork(app.state.database) as uow:
        uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 1)
    barrier = Barrier(2)

    def create(index: int):
        barrier.wait()
        runtime = TaskRuntime(app.state.database)
        try:
            plan = runtime.create_plan(
                project_id=project["id"],
                kind=AGENT_PLAN_KIND,
                subject_type="test",
                subject_id=f"concurrent-{index}",
                idempotency_key=f"admission:concurrent:{index}",
                tasks=[_task(available_at=time.time() + 3600)],
            )
        except RuntimeAdmissionFull as exc:
            return "rejected", exc.capacity, exc.active_count
        return "accepted", plan["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, [1, 2]))

    accepted = [item for item in results if item[0] == "accepted"]
    rejected = [item for item in results if item[0] == "rejected"]
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert rejected[0][1:] == (1, 1)
    state = _state(app.state.database)
    assert state["active_count"] == 1
    TaskRuntime(app.state.database).cancel(
        accepted[0][1],
        reason="cleanup",
    )


def test_admission_capacity_cannot_shrink_below_active_reservations(
    app,
    project,
):
    runtime = TaskRuntime(app.state.database)
    with UnitOfWork(app.state.database) as uow:
        uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 2)
    plans = [
        runtime.create_plan(
            project_id=project["id"],
            kind=AGENT_PLAN_KIND,
            subject_type="test",
            subject_id=f"shrink-{index}",
            idempotency_key=f"admission:shrink:{index}",
            tasks=[_task(available_at=time.time() + 3600)],
        )
        for index in range(2)
    ]

    with UnitOfWork(app.state.database) as uow:
        with pytest.raises(ConflictError, match="active reservations: 2"):
            uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 1)

    assert _state(app.state.database)["capacity"] == 2
    for plan in plans:
        runtime.cancel(plan["id"], reason="cleanup")


def test_agent_admission_releases_when_plan_succeeds(app, project):
    runtime = TaskRuntime(app.state.database)
    with UnitOfWork(app.state.database) as uow:
        uow.task_runtime.configure_admission(AGENT_PLAN_KIND, 1)

    plan = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id="complete",
        idempotency_key="admission:complete",
        tasks=[_task()],
    )
    claim = runtime.claim_next(
        "admission-worker",
        kinds={AGENT_PLAN_KIND},
        lease_seconds=10,
    )
    assert claim is not None
    runtime.complete(claim, result={"ok": True})

    assert runtime.get_plan(plan["id"])["status"] == "succeeded"
    assert _state(app.state.database)["active_count"] == 0


def test_agent_structural_events_use_semantic_dedupe_identity(
    app,
    project,
):
    runtime = TaskRuntimf(app.state.database)
    plan = runtime.create_plan(
        project_id=project["id"],
        kind=AGENT_PLAN_KIND,
        subject_type="test",
        subject_id="events",
        idempotency_key="events:dedupe",
        tasks=[_task(available_at=time.time() + 3600)],
    )
    payload = {
        "turn_id": "turn-1",
        "type": "step.start",
        "step_id": "stable-step-1",
        "tool": "write_artifact",
    }
    first = runtime.append_event(
        plan["id"],
        "agent.step.start",
        payload=payload,
    )
    replay = runtime.append_event(
        plan["id"],
        "agent.step.start",
        payload={**payload, "args_preview": "replayed"},
    )

    assert first["id"] == replay["id"]
    assert first["seq"] == replay["seq"]
    assert replay["deduplicated"] is True
    stored = [
        event
        for event¥¸ÉÕ¹Ñ¥µ”¹•Ù•¹ÑÌ¡Á±…¹l‰¥‰t¤(€€€€€€€¥˜•Ù•¹Ñl‰•Ù•¹Ñ}ÑåÁ”‰t€ôô€‰…•¹Ğ¹ÍÑ•À¹ÍÑ…ÉĞˆ(€€€€€€€…¹•Ù•¹Ñl‰Á…å±½…‰t¹•Ğ ‰ÍÑ•Á}¥ˆ¤€ôô€‰ÍÑ…‰±”µÍÑ•À´Äˆ(€€€t(€€€…ÍÍ•ÉĞ±•¸¡ÍÑ½É•¤€ôô€Ä(€€€ÉÕ¹Ñ¥µ”¹…¹•°¡Á±…¹l‰¥‰t°É•…Í½¸ô‰±•…¹ÕÀˆ¤(()‘•˜Ñ•ÍÑ}ÑÕÉ¹}…Á¥}É•ÑÕÉ¹Í|ĞÈå}İ¥Ñ¡½ÕÑ}Á…ÉÑ¥…±}µ•ÍÍ…•}İ¡•¹}…•¹Ñ}™Õ±° (€€€…ÁÀ°(€€€±¥•¹Ğ°(€€€ÁÉ½©•Ğ°(¤è(€€€ÉÕ¹Ñ¥µ”€ôQ…Í­IÕ¹Ñ¥µ˜¡…ÁÀ¹ÍÑ…Ñ”¹‘…Ñ…‰…Í”¤(€€€İ¥Ñ U¹¥Ñ=™]½É¬¡…ÁÀ¹ÍÑ…Ñ”¹‘…Ñ…‰…Í”¤…ÌÕ½Üè(€€€€€€€Õ½Ü¹Ñ…Í­}ÉÕ¹Ñ¥µ”¹½¹™¥ÕÉ•}…‘µ¥ÍÍ¥½¸¡9Q}A19}-%9°€Ä¤((€€€‰±½­•È€ôÉÕ¹Ñ¥µ”¹É•…Ñ•}Á±…¸ (€€€€€€€ÁÉ½©•Ñ}¥õÁÉ½©•Ñl‰¥‰t°(€€€€€€€­¥¹õ9Q}A19}-%9°(€€€€€€€ÍÕ‰©•Ñ}ÑåÁ”ô‰Ñ•ÍĞˆ°(€€€€€€€ÍÕ‰©•Ñ}¥ô‰…Á¤µ‰±½­•Èˆ°(€€€€€€€¥‘•µÁ½Ñ•¹å}­•äô‰…‘µ¥ÍÍ¥½¸é…Á¤µ‰±½­•Èˆ°(€€€€€€€Ñ…Í­Ìõm}Ñ…Í¬¡…Ù…¥±…‰±•}…ĞõÑ¥µ”¹Ñ¥µ” ¤€¬€ÌØÀÀ¥t°(€€€€¤(€€€½¹Ù•ÉÍ…Ñ¥½¸€ô±¥•¹Ğ¹Á½ÍĞ (€€€€€€€˜ˆ½…Á¤½ÁÉ½©•ÑÌ½íÁÉ½©•Ñl¥uô½½¹Ù•ÉÍ…Ñ¥½¹Ìˆ°(€€€€€€€©Í½¸õì‰Ñ¥Ñ±”ˆè€‹–º{¦3š.Kîp‰ô°(€€€€¤¹©Í½¸ ¤((€€€É•ÍÁ½¹Í”€ô±¥•¹Ğ¹Á½ÍĞ (€€€€€€€˜ˆ½…Á¤½½¹Ù•ÉÍ…Ñ¥½¹Ì½í½¹Ù•ÉÍ…Ñ¥½¹l¥uô½ÑÕÉ¹Ìˆ°(€€€€€€€©Í½¸õì‰½¹Ñ•¹Ğˆè€‹¢şgš‚–âãš"Gî“š"@‰ô°(€€€€¤(€€€…ÍÍ•ÉĞÉ•ÍÁ½¹Í”¹ÍÑ…ÑÕÍ}½‘”€ôô€ĞÈä(€€€…ÍÍ•ÉĞÉ•ÍÁ½¹Í”¹¡•…‘•ÉÍl‰É•ÑÉäµ…™Ñ•È‰t€ôô€ˆÈˆ(€€€…ÍÍ•ÉĞÉ•ÍÁ½¹Í”¹©Í½¸ ¥l‰…Á…¥Ñä‰t€ôô€Ä(€€€İ¥Ñ U¹¥Ñ=™]½É¬¡…ÁÀ¹ÍÑ…Ñ”¹‘…Ñ…‰…Í”¤…ÌÕ½Üè(€€€€€€€µ•ÍÍ…•Ì€ôÕ½Ü¹½¹Ù•ÉÍ…Ñ¥½¹Ì¹±¥ÍÑ}µ•ÍÍ…•Ì¡½¹Ù•ÉÍ…Ñ¥½¹l‰¥‰t¤(€€€…ÍÍ•ÉĞµ•ÍÍ…•Ì€ôômt(€€€ÉÕ¹Ñ¥µ”¹…¹•°¡‰±½­•Él‰¥‰t°É•…Í½¸ô‰±•…¹ÕÀˆ¤(()‘•˜Ñ•ÍÑ}™É•Í¡}‘…Ñ…‰…Í•}¥¹ÍÑ…±±Í}ÉÕ¹Ñ¥µ•}½¹ÑÉ½±}Ñ…‰±•Ì¡ÑµÁ}Á…Ñ ¤è(€€€‘…Ñ…‰…Í”€ô…Ñ…‰…Í” (€€€€€€€˜‰ÍÅ±¥Ñ”è¼¼½ì¡ÑµÁ}Á…Ñ €¼€ÉÕ¹Ñ¥µ”µ½¹ÑÉ½±Ì¹‘ˆœ¤¹…Í}Á½Í¥à ¥ôˆ(€€€€€¤(€€€ÑÉäè(€€€€€€€‘…Ñ…‰…Í”¹É•…Ñ•}Í¡•µ„ ¤(€€€€€€€¥¹ÍÁ•Ñ½È€ô¥¹ÍÁ•Ğ¡‘…Ñ…‰…Í”¹•¹¥¹”¤(€€€€€€€Ñ…‰±•Ì€ôÍ•Ğ¡¥¹ÍÁ•Ñ½È¹•Ñ}Ñ…‰±•}¹…µ•Ì ¤¤(€€€€€€€…ÍÍ•ÉĞì(€€€€€€€€€€€€‰ÉÕ¹Ñ¥µ•}…‘µ¥ÍÍ¥½¹}‰Õ­•ÑÌˆ°(€€€€€€€€€€€€‰ÉÕ¹Ñ¥µ•}…‘µ¥ÍÍ¥½¹}É•Í•ÉÙ…Ñ¥½¹Ìˆ°(€€€€€€€€€€€€‰ÉÕ¹Ñ¥µ•}•Ù•¹Ñ}‘•‘ÕÁ•Ìˆ°(€€€€€€€ô€ğôÑ…‰±•Ì(€€€€€€€É•Í•ÉÙ…Ñ¥½¹}¥¹‘•á•Ì€ôì(€€€€€€€€€€€¥Ñ•µl‰¹…µ”‰t(€€€€€€€€€€€™½È¥Ñ•´¥¸¥¹ÍÁ•Ñ½È¹•Ñ}¥¹‘•á•Ì (€€€€€€€€€€€€€€€€‰ÉÕ¹Ñ¥µ•}…‘µ¥ÍÍ¥½¹}É•Í•ÉÙ…Ñ¥½¹Ìˆ(€€€€€€€€€€€€¤(€€€€€€€ô(€€€€€€€…ÍÍ•ÉĞ€‰ÕÅ}ÉÕ¹Ñ¥µ•}…‘µ¥ÍÍ¥½¹}…Ñ¥Ù•}Í±½Ğˆ¥¸É•Í•ÉÙ…Ñ¥½¹}¥¹‘•á•Ì(€€€€€€€İ¥Ñ U¹¥Ñ=™]½É¬¡‘…Ñ…‰…Í”¤…ÌÕ½Üè(€€€€€€€€€€€ÍÑ…Ñ”€ôÕ½Ü¹Ñ…Í­}ÉÕ¹Ñ¥µ”¹…‘µ¥ÍÍ¥½¹}ÍÑ…Ñ”¡9Q}A19}-%9¤(€€€€€€€…ÍÍ•ÉĞÍÑ…Ñ•l‰…Á…¥Ñä‰t€ôô€ÄÀ(€€€€€€€…ÍÍ•ÉĞÍÑ…Ñ•l‰…Ñ¥Ù•}½Õ¹Ğ‰t€ôô€À(€€€™¥¹…±±äè(€€€€€€€‘…Ñ…‰…Í”¹•¹¥¹”¹‘¥ÍÁ½Í” ¤