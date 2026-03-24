from __future__ import annotations

from pathlib import Path

import pytest

from tasklane.models import CommandTask
from tasklane.state import SchedulerState


def test_insert_run_persists_command_task_and_log_path(tmp_path: Path) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    task = CommandTask(
        cwd=str(tmp_path),
        command=["python", "-c", "print('hi')"],
        metadata={"resource_class": "cpu-light", "labels": ["demo"]},
        project="demo",
        run_name="demo-run",
    )

    run = state.create_run(task)

    loaded = state.get_run(run.run_id)
    assert loaded is not None
    assert loaded.task.command == ["python", "-c", "print('hi')"]
    assert loaded.status == "queued"
    assert loaded.log_path.name == f"{run.run_id}.log"


def test_delete_run_removes_non_active_run_and_log_file(tmp_path: Path) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    task = CommandTask(
        cwd=str(tmp_path),
        command=["python", "-c", "print('hi')"],
        metadata={"resource_class": "cpu-light", "labels": ["demo"]},
        project="demo",
        run_name="delete-demo",
    )
    run = state.create_run(task)

    deleted = state.delete_run(run.run_id)

    assert deleted.run_id == run.run_id
    assert state.get_run(run.run_id) is None
    assert not run.log_path.exists()


def test_delete_run_rejects_running_run(tmp_path: Path) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    task = CommandTask(
        cwd=str(tmp_path),
        command=["python", "-c", "print('hi')"],
        metadata={"resource_class": "cpu-light", "labels": ["demo"]},
        project="demo",
        run_name="running-demo",
    )
    run = state.create_run(task)
    state.mark_running(run.run_id, pid=12345)

    with pytest.raises(ValueError, match="active"):
        state.delete_run(run.run_id)
