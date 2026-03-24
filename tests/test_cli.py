import sys

import pytest

from tasklane.attach import SubmittedRun
from tasklane.cli import build_command_task, main, parse_submit_args
from tasklane.models import CommandTask
from tasklane.state import SchedulerState


def test_parse_submit_args_keeps_original_command_after_double_dash() -> None:
    args = parse_submit_args(
        [
            "--cwd",
            r"E:\freqtrade",
            "--project",
            "tabicl",
            "--resource",
            "gpu-exclusive",
            "--run-name",
            "exp-001",
            "--label",
            "tabicl",
            "--env",
            "TABICL_DEVICE=cuda",
            "--",
            "uv",
            "run",
            "python",
            "user_data/tabicl_pipeline/generate_random_anchor_predictions.py",
        ]
    )

    assert args.cwd == r"E:\freqtrade"
    assert args.project == "tabicl"
    assert args.resource == "gpu-exclusive"
    assert args.labels == ["tabicl"]
    assert args.env == ["TABICL_DEVICE=cuda"]
    assert args.command == [
        "uv",
        "run",
        "python",
        "user_data/tabicl_pipeline/generate_random_anchor_predictions.py",
    ]


def test_parse_submit_args_accepts_gpu_host_exclusive_resource() -> None:
    args = parse_submit_args(
        [
            "--cwd",
            r"E:\freqtrade",
            "--resource",
            "gpu-host-exclusive",
            "--",
            "python",
            "job.py",
        ]
    )

    assert args.resource == "gpu-host-exclusive"


def test_parse_submit_args_defaults_to_attached_mode() -> None:
    args = parse_submit_args(
        [
            "--cwd",
            r"E:\freqtrade",
            "--resource",
            "gpu-exclusive",
            "--",
            "python",
            "job.py",
        ]
    )

    assert args.detach is False


def test_parse_submit_args_accepts_detach_flag() -> None:
    args = parse_submit_args(
        [
            "--cwd",
            r"E:\freqtrade",
            "--resource",
            "gpu-exclusive",
            "--detach",
            "--",
            "python",
            "job.py",
        ]
    )

    assert args.detach is True


def test_main_uses_sys_argv_when_no_explicit_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["tasklane", "--help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0


def test_main_attaches_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    args = parse_submit_args(
        [
            "--cwd",
            r"E:\freqtrade",
            "--project",
            "tabicl",
            "--resource",
            "gpu-exclusive",
            "--run-name",
            "exp-001",
            "--env",
            "TABICL_DEVICE=cuda",
            "--",
            "uv",
            "run",
            "python",
            "job.py",
        ]
    )
    task = build_command_task(args)
    submitted = SubmittedRun(run_id="run-123", run_name=task.run_name or "exp-001", queue_name="gpu", resource_class="gpu-exclusive")
    captured: dict[str, object] = {}

    def fake_submit_task(task_arg, *, state=None):  # noqa: ANN001
        captured["task"] = task_arg
        captured["state"] = state
        return submitted

    def fake_attach_submitted_run(submitted_run, *, out, poll_interval=1.0, state=None):  # noqa: ANN001
        captured["submitted"] = submitted_run
        captured["poll_interval"] = poll_interval
        captured["attach_state"] = state
        return 0

    monkeypatch.setattr("tasklane.cli.SchedulerState.initialize", lambda: "state")
    monkeypatch.setattr("tasklane.cli.submit_task", fake_submit_task)
    monkeypatch.setattr("tasklane.cli.attach_submitted_run", fake_attach_submitted_run)

    result = main(
        [
            "--cwd",
            r"E:\freqtrade",
            "--project",
            "tabicl",
            "--resource",
            "gpu-exclusive",
            "--run-name",
            "exp-001",
            "--env",
            "TABICL_DEVICE=cuda",
            "--",
            "uv",
            "run",
            "python",
            "job.py",
        ]
    )

    assert result == 0
    assert captured["task"] == task
    assert captured["submitted"] == submitted
    assert captured["state"] == "state"
    assert captured["attach_state"] == "state"


def test_main_skips_attach_in_detach_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted = SubmittedRun(run_id="run-123", run_name="exp-001", queue_name="gpu", resource_class="gpu-exclusive")
    monkeypatch.setattr("tasklane.cli.SchedulerState.initialize", lambda: "state")
    monkeypatch.setattr("tasklane.cli.submit_task", lambda task, *, state=None: submitted)

    def fail_attach(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("attach should not be called in detach mode")

    monkeypatch.setattr("tasklane.cli.attach_submitted_run", fail_attach)

    result = main(
        [
            "--cwd",
            r"E:\freqtrade",
            "--resource",
            "gpu-exclusive",
            "--detach",
            "--",
            "python",
            "job.py",
        ]
    )

    assert result == 0


def test_main_runs_daemon_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeScheduler:
        def __init__(self, state, *, poll_interval: float) -> None:  # noqa: ANN001
            captured["state"] = state
            captured["poll_interval"] = poll_interval

        def run_once(self, *, limit: int) -> int:
            captured["limit"] = limit
            return 1

    monkeypatch.setattr("tasklane.cli.SchedulerState.initialize", lambda: "state")
    monkeypatch.setattr("tasklane.cli.Scheduler", FakeScheduler)

    result = main(["daemon", "--once", "--poll-interval", "0.5"])

    assert result == 0
    assert captured == {
        "state": "state",
        "poll_interval": 0.5,
        "limit": 10,
    }


def test_main_queue_subcommand_prints_table(capsys: pytest.CaptureFixture[str], tmp_path) -> None:  # noqa: ANN001
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    state.create_run(
        CommandTask(
            cwd=str(tmp_path),
            command=["uv", "run", "python", "job.py"],
            metadata={"resource_class": "cpu-light", "labels": []},
            run_name="queue-demo",
            project="demo",
        )
    )

    result = main(["queue", "--db-path", str(tmp_path / "tasklane.db")])

    assert result == 0
    output = capsys.readouterr().out
    assert "Tasklane Queue" in output
    assert "queue-demo" in output
    assert "cpu-light" in output
    assert "queued" in output


def test_main_queue_subcommand_prints_json(capsys: pytest.CaptureFixture[str], tmp_path) -> None:  # noqa: ANN001
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    state.create_run(
        CommandTask(
            cwd=str(tmp_path),
            command=["uv", "run", "python", "job.py"],
            metadata={"resource_class": "gpu-exclusive", "labels": []},
            run_name="json-demo",
            project="demo",
        )
    )

    result = main(["queue", "--db-path", str(tmp_path / "tasklane.db"), "--json"])

    assert result == 0
    output = capsys.readouterr().out
    assert '"run_name": "json-demo"' in output
    assert '"resource_class": "gpu-exclusive"' in output


def test_main_queue_subcommand_watch_refreshes_until_interrupted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:  # noqa: ANN001
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    state.create_run(
        CommandTask(
            cwd=str(tmp_path),
            command=["uv", "run", "python", "job.py"],
            metadata={"resource_class": "cpu-light", "labels": []},
            run_name="watch-demo",
            project="demo",
        )
    )
    sleeps = {"count": 0}

    def fake_sleep(_: float) -> None:
        sleeps["count"] += 1
        raise KeyboardInterrupt

    monkeypatch.setattr("tasklane.cli.time.sleep", fake_sleep)

    result = main(["queue", "--db-path", str(tmp_path / "tasklane.db"), "--watch", "--interval", "0.1"])

    assert result == 0
    assert sleeps["count"] == 1
    output = capsys.readouterr().out
    assert "watch-demo" in output
