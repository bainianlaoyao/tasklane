from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
from pathlib import Path

import pytest

from tasklane.attach import (
    SubmittedRun,
    attach_submitted_run,
    encode_command_output_message,
    encode_scheduler_event_message,
    format_scheduler_event_line,
)
from tasklane.models import CommandTask
from tasklane.state import SchedulerState


def test_format_scheduler_event_line_is_stable() -> None:
    line = format_scheduler_event_line(
        "submitted",
        run_id="abc123",
        queue="gpu",
        resource="gpu-exclusive",
    )

    assert line == "[scheduler] submitted run_id=abc123 queue=gpu resource=gpu-exclusive"


def test_attach_submitted_run_streams_scheduler_events_and_logs(tmp_path: Path) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    created = state.create_run(
        CommandTask(
            cwd=str(tmp_path),
            command=["python", "-c", "print('ok')"],
            metadata={"resource_class": "gpu-exclusive", "labels": []},
            run_name="exp-001",
        )
    )
    created.log_path.write_text(
        "\n".join(
            [
                encode_scheduler_event_message("started", worker="local"),
                encode_command_output_message("stdout", "epoch 1/10"),
                encode_scheduler_event_message("finished", status="completed", exit_code=0),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    state.finish_run(created.run_id, status="completed", exit_code=0)
    submitted = SubmittedRun(
        run_id=created.run_id,
        run_name="exp-001",
        queue_name="gpu",
        resource_class="gpu-exclusive",
    )
    output = StringIO()

    exit_code = attach_submitted_run(submitted, out=output, poll_interval=0.01, state=state)

    assert exit_code == 0
    text = output.getvalue()
    assert "[scheduler] started worker=local" in text
    assert "epoch 1/10" in text
    assert "[scheduler] finished status=completed exit_code=0" in text


def test_attach_submitted_run_cancels_local_run_on_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    created = state.create_run(
        CommandTask(
            cwd=str(tmp_path),
            command=["python", "-c", "print('ok')"],
            metadata={"resource_class": "gpu-exclusive", "labels": []},
            run_name="exp-001",
        )
    )
    submitted = SubmittedRun(
        run_id=created.run_id,
        run_name="exp-001",
        queue_name="gpu",
        resource_class="gpu-exclusive",
    )

    @contextmanager
    def always_interrupted():
        yield lambda: True

    monkeypatch.setattr("tasklane.attach._capture_interrupt_requests", always_interrupted)
    output = StringIO()

    exit_code = attach_submitted_run(submitted, out=output, poll_interval=0.01, state=state)

    assert exit_code == 130
    assert state.get_run(created.run_id).status == "cancelled"
    assert "[scheduler] cancelling run_id=" in output.getvalue()
