from __future__ import annotations

from pathlib import Path

from tasklane.models import CommandTask
from tasklane.scheduler import Scheduler
from tasklane.state import SchedulerState


def make_task(tmp_path: Path, resource_class: str, run_name: str) -> CommandTask:
    return CommandTask(
        cwd=str(tmp_path),
        command=["python", "-c", "print('ok')"],
        metadata={"resource_class": resource_class, "labels": []},
        run_name=run_name,
    )


def test_claim_runnable_runs_respects_gpu_and_host_exclusive_limits(tmp_path: Path) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    gpu_run = state.create_run(make_task(tmp_path, "gpu-exclusive", "gpu"))
    host_run = state.create_run(make_task(tmp_path, "cpu-exclusive", "host"))
    waiting_run = state.create_run(make_task(tmp_path, "gpu-host-exclusive", "gpu-host"))

    scheduler = Scheduler(state)
    first = scheduler.claim_runnable_runs(limit=10)

    assert {run.run_id for run in first} == {gpu_run.run_id, host_run.run_id}
    assert state.get_run(waiting_run.run_id).status == "queued"
