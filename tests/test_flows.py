from io import StringIO

import pytest

import prefect_command_scheduler.flows as flows
from prefect_command_scheduler.attach import COMMAND_STDERR_PREFIX, COMMAND_STDOUT_PREFIX, SCHEDULER_EVENT_PREFIX
from prefect_command_scheduler.flows import build_execution_markdown, build_result_markdown, run_command
from prefect_command_scheduler.models import CommandTask
from prefect.exceptions import CancelledRun


def test_build_execution_markdown_contains_command_and_metadata() -> None:
    task = CommandTask(
        cwd=r"E:\freqtrade",
        project="tabicl",
        command=["uv", "run", "python", "job.py"],
        env_overrides={"TABICL_DEVICE": "cuda"},
        metadata={"resource_class": "gpu-exclusive", "labels": ["tabicl", "gpu"]},
        run_name="exp-001",
        notes="smoke",
    )

    markdown = build_execution_markdown(task, git_context={"git_sha": "abc123", "git_dirty": True})

    assert "uv run python job.py" in markdown
    assert "`gpu-exclusive`" in markdown
    assert "`abc123`" in markdown
    assert "smoke" in markdown


def test_build_result_markdown_contains_exit_status_and_duration() -> None:
    markdown = build_result_markdown(
        {
            "status": "completed",
            "exit_code": 0,
            "started_at": "2026-03-22T00:00:00+00:00",
            "finished_at": "2026-03-22T00:05:00+00:00",
            "duration_seconds": 300.0,
        }
    )

    assert "`completed`" in markdown
    assert "`0`" in markdown
    assert "`300.0`" in markdown


def test_run_command_streams_logs_and_emits_scheduler_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    task = CommandTask(
        cwd=r"E:\freqtrade",
        command=["python", "job.py"],
        metadata={"resource_class": "gpu-exclusive"},
    )
    info_messages: list[str] = []
    warning_messages: list[str] = []

    class FakeLogger:
        def info(self, message: str) -> None:
            info_messages.append(message)

        def warning(self, message: str) -> None:
            warning_messages.append(message)

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = StringIO("out-1\nout-2\n")
            self.stderr = StringIO("err-1\n")
            self.returncode = 0
            self.poll_calls = 0
            self.pid = 1234

        def poll(self):  # noqa: ANN001
            self.poll_calls += 1
            if self.poll_calls == 1:
                return None
            return self.returncode

    class NoopConcurrency:
        def __enter__(self) -> None:
            return None

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(flows, "get_run_logger", lambda: FakeLogger())
    monkeypatch.setattr(flows, "concurrency", lambda *args, **kwargs: NoopConcurrency())
    monkeypatch.setattr(flows.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    result = run_command.fn(task)

    assert result["exit_code"] == 0
    assert info_messages[0].startswith(SCHEDULER_EVENT_PREFIX)
    assert f"{COMMAND_STDOUT_PREFIX}out-1" in info_messages
    assert f"{COMMAND_STDOUT_PREFIX}out-2" in info_messages
    assert warning_messages == [f"{COMMAND_STDERR_PREFIX}err-1"]
    assert any("finished" in message for message in info_messages if message.startswith(SCHEDULER_EVENT_PREFIX))


def test_run_command_terminates_child_process_when_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    task = CommandTask(
        cwd=r"E:\freqtrade",
        command=["python", "job.py"],
        metadata={"resource_class": "gpu-exclusive"},
    )

    class FakeLogger:
        def info(self, message: str) -> None:  # noqa: ARG002
            return None

        def warning(self, message: str) -> None:  # noqa: ARG002
            return None

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = StringIO("")
            self.stderr = StringIO("")
            self.returncode = None
            self.terminated = False
            self.killed = False
            self.poll_calls = 0
            self.pid = 1234

        def poll(self):  # noqa: ANN001
            self.poll_calls += 1
            raise KeyboardInterrupt

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

    class NoopConcurrency:
        def __enter__(self) -> None:
            return None

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    fake_process = FakeProcess()
    monkeypatch.setattr(flows, "get_run_logger", lambda: FakeLogger())
    monkeypatch.setattr(flows, "concurrency", lambda *args, **kwargs: NoopConcurrency())
    monkeypatch.setattr(flows.subprocess, "Popen", lambda *args, **kwargs: fake_process)

    with pytest.raises(KeyboardInterrupt):
        run_command.fn(task)

    assert fake_process.terminated is True


def test_run_command_terminates_child_process_when_flow_run_is_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    task = CommandTask(
        cwd=r"E:\freqtrade",
        command=["python", "job.py"],
        metadata={"resource_class": "gpu-exclusive"},
    )

    class FakeLogger:
        def info(self, message: str) -> None:  # noqa: ARG002
            return None

        def warning(self, message: str) -> None:  # noqa: ARG002
            return None

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = StringIO("")
            self.stderr = StringIO("")
            self.returncode = None
            self.terminated = False
            self.killed = False
            self.poll_calls = 0
            self.pid = 1234

        def poll(self):  # noqa: ANN001
            self.poll_calls += 1
            return None

        def wait(self) -> int:
            raise AssertionError("wait should not be reached after cancellation detection")

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

    class NoopConcurrency:
        def __enter__(self) -> None:
            return None

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeClient:
        def read_flow_run(self, flow_run_id: str):  # noqa: ANN001
            assert flow_run_id == "flow-run-123"
            return type("FlowRun", (), {"state_name": "Cancelled"})()

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    fake_process = FakeProcess()
    monkeypatch.setattr(flows, "get_run_logger", lambda: FakeLogger())
    monkeypatch.setattr(flows, "concurrency", lambda *args, **kwargs: NoopConcurrency())
    monkeypatch.setattr(flows.subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(flows, "get_client", lambda sync_client=False: FakeClient())
    monkeypatch.setattr(flows.runtime.flow_run, "id", "flow-run-123")
    monkeypatch.setattr(flows.time, "sleep", lambda _: None)

    with pytest.raises(CancelledRun):
        run_command.fn(task)

    assert fake_process.terminated is True
