from __future__ import annotations

from pathlib import Path

from tasklane.models import CommandTask
from tasklane.scheduler import Scheduler, _ActiveRun, _LogWriter
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


def test_reconcile_active_runs_marks_console_interrupt_exit_as_cancelled(tmp_path: Path) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    created = state.create_run(make_task(tmp_path, "cpu-light", "interrupt"))
    running = state.mark_running(created.run_id, pid=12345)

    class FakeProcess:
        def poll(self) -> int:
            return 3221225786

    class FakeThread:
        def join(self, timeout: float | None = None) -> None:  # noqa: ARG002
            return None

    scheduler = Scheduler(state)
    scheduler._active_runs[running.run_id] = _ActiveRun(
        run=running,
        process=FakeProcess(),  # type: ignore[arg-type]
        stdout_thread=FakeThread(),  # type: ignore[arg-type]
        stderr_thread=FakeThread(),  # type: ignore[arg-type]
        log_writer=_LogWriter(running.log_path),
    )

    scheduler._reconcile_active_runs()

    updated = state.get_run(running.run_id)
    assert updated is not None
    assert updated.status == "cancelled"
    assert updated.exit_code == 130
    assert '"status":"cancelled"' in updated.log_path.read_text(encoding="utf-8")
