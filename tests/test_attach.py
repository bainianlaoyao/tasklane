from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from uuid import uuid4

import pytest

from tasklane.attach import (
    COMMAND_STDERR_PREFIX,
    COMMAND_STDOUT_PREFIX,
    SCHEDULER_EVENT_PREFIX,
    SubmittedRun,
    attach_submitted_run,
    encode_command_output_message,
    encode_scheduler_event_message,
    format_scheduler_event_line,
)


@dataclass
class FakeState:
    final: bool = False

    def is_final(self) -> bool:
        return self.final


@dataclass
class FakeFlowRun:
    id: str
    name: str
    state_name: str
    state: FakeState


@dataclass
class FakeLog:
    message: str
    timestamp: datetime


class FakeClient:
    def __init__(self, flow_runs: list[FakeFlowRun], logs_by_offset: dict[int, list[FakeLog]]) -> None:
        self._flow_runs = list(flow_runs)
        self._logs_by_offset = dict(logs_by_offset)
        self.cancelled: list[str] = []

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def read_flow_run(self, flow_run_id: str) -> FakeFlowRun:
        assert flow_run_id
        if len(self._flow_runs) == 1:
            return self._flow_runs[0]
        return self._flow_runs.pop(0)

    async def read_logs(self, *, log_filter=None, limit=None, offset=None, sort=None):  # noqa: ANN001
        assert log_filter is not None
        assert limit is not None
        assert sort is not None
        return self._logs_by_offset.get(offset or 0, [])

    async def set_flow_run_state(self, flow_run_id: str, state, force: bool = False):  # noqa: ANN001
        assert force is True
        self.cancelled.append(flow_run_id)
        return object()


def test_format_scheduler_event_line_is_stable() -> None:
    line = format_scheduler_event_line(
        "submitted",
        run_id="abc123",
        queue="gpu",
        resource="gpu-exclusive",
    )

    assert line == "[scheduler] submitted run_id=abc123 queue=gpu resource=gpu-exclusive"


def test_attach_submitted_run_streams_scheduler_events_and_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = str(uuid4())
    submitted = SubmittedRun(
        flow_run_id=run_id,
        run_name="exp-001",
        queue_name="gpu",
        resource_class="gpu-exclusive",
    )
    fake_client = FakeClient(
        flow_runs=[
            FakeFlowRun(id=run_id, name="exp-001", state_name="Scheduled", state=FakeState(final=False)),
            FakeFlowRun(id=run_id, name="exp-001", state_name="Running", state=FakeState(final=False)),
            FakeFlowRun(id=run_id, name="exp-001", state_name="Completed", state=FakeState(final=True)),
        ],
        logs_by_offset={
            0: [
                FakeLog(
                    message="Beginning flow run 'exp-001' for flow 'command-executor'",
                    timestamp=datetime.now(timezone.utc),
                ),
                FakeLog(
                    message=encode_scheduler_event_message("started", worker="local-process"),
                    timestamp=datetime.now(timezone.utc),
                ),
                FakeLog(
                    message=encode_command_output_message("stdout", "epoch 1/10"),
                    timestamp=datetime.now(timezone.utc),
                ),
                FakeLog(
                    message=encode_scheduler_event_message("finished", status="completed", exit_code=0),
                    timestamp=datetime.now(timezone.utc),
                ),
            ]
        },
    )

    monkeypatch.setattr("tasklane.attach.get_client", lambda: fake_client)
    output = StringIO()

    exit_code = attach_submitted_run(submitted, out=output, poll_interval=0.01)

    assert exit_code == 0
    text = output.getvalue()
    assert "[scheduler] waiting run_id=" in text
    assert "[scheduler] started worker=local-process" in text
    assert "epoch 1/10" in text
    assert "[scheduler] finished status=completed exit_code=0" in text
    assert "Beginning flow run" not in text


def test_attach_submitted_run_cancels_remote_run_on_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = str(uuid4())
    submitted = SubmittedRun(
        flow_run_id=run_id,
        run_name="exp-001",
        queue_name="gpu",
        resource_class="gpu-exclusive",
    )

    class InterruptingClient(FakeClient):
        async def read_flow_run(self, flow_run_id: str) -> FakeFlowRun:
            raise KeyboardInterrupt

    fake_client = InterruptingClient(flow_runs=[], logs_by_offset={})
    monkeypatch.setattr("tasklane.attach.get_client", lambda: fake_client)
    output = StringIO()

    exit_code = attach_submitted_run(submitted, out=output, poll_interval=0.01)

    assert exit_code == 130
    assert fake_client.cancelled == [run_id]
    assert "[scheduler] cancelling run_id=" in output.getvalue()
    assert SCHEDULER_EVENT_PREFIX in encode_scheduler_event_message("started")
    assert COMMAND_STDOUT_PREFIX in encode_command_output_message("stdout", "hello")
    assert COMMAND_STDERR_PREFIX in encode_command_output_message("stderr", "oops")
