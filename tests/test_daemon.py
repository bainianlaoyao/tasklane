from __future__ import annotations

from pathlib import Path

from tasklane.models import CommandTask
from tasklane.scheduler import Scheduler
from tasklane.state import SchedulerState


def test_run_once_executes_child_and_streams_output_to_log(tmp_path: Path) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    run = state.create_run(
        CommandTask(
            cwd=str(tmp_path),
            command=["python", "-c", "print('hello from tasklane')"],
            metadata={"resource_class": "cpu-light", "labels": []},
        )
    )

    scheduler = Scheduler(state)
    scheduler.run_once()

    updated = state.get_run(run.run_id)
    assert updated.status == "completed"
    assert "hello from tasklane" in updated.log_path.read_text(encoding="utf-8")
