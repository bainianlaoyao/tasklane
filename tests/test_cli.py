import sys
from uuid import uuid4

import pytest

from tasklane.attach import SubmittedRun
from tasklane.cli import build_command_task, main, parse_submit_args


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
    submitted = SubmittedRun(
        flow_run_id=str(uuid4()),
        run_name=task.run_name or "exp-001",
        queue_name="gpu",
        resource_class="gpu-exclusive",
    )
    captured: dict[str, object] = {}

    def fake_submit_task(task_arg):  # noqa: ANN001
        captured["task"] = task_arg
        return submitted

    def fake_attach_submitted_run(submitted_run, *, out, poll_interval=1.0):  # noqa: ANN001
        captured["submitted"] = submitted_run
        captured["poll_interval"] = poll_interval
        return 0

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


def test_main_skips_attach_in_detach_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted = SubmittedRun(
        flow_run_id=str(uuid4()),
        run_name="exp-001",
        queue_name="gpu",
        resource_class="gpu-exclusive",
    )
    monkeypatch.setattr("tasklane.cli.submit_task", lambda task: submitted)

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
