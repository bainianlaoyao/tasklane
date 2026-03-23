import pytest

import prefect_command_scheduler.bootstrap as bootstrap
from prefect_command_scheduler.bootstrap import (
    DEFAULT_QUEUES,
    FLOW_ENTRYPOINT,
    REPO_ROOT,
    _run_idempotent,
    build_runner_deployment,
    build_bootstrap_commands,
    build_deployments,
    main,
)


def test_build_bootstrap_commands_covers_pool_queues_and_limits() -> None:
    commands = build_bootstrap_commands()
    joined = [" ".join(command) for command in commands]

    assert any("prefect work-pool create local-process --type process" in command for command in joined)
    assert any("prefect work-queue create gpu --pool local-process --limit 1 --priority 1" in command for command in joined)
    assert any("prefect global-concurrency-limit create gpu-0 --limit 1" in command for command in joined)
    assert any("prefect global-concurrency-limit create host-exclusive --limit 1" in command for command in joined)


def test_build_deployments_matches_resource_routes() -> None:
    deployments = build_deployments()

    assert {deployment.name for deployment in deployments} == {
        "gpu-exclusive",
        "gpu-host-exclusive",
        "cpu-exclusive",
        "cpu-light",
    }
    assert {deployment.work_queue_name for deployment in deployments} == set(DEFAULT_QUEUES)


def test_bootstrap_preview_includes_deployment_summary(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "prefect work-pool create local-process --type process" in captured.out
    assert "deployment command/gpu-exclusive -> queue gpu" in captured.out
    assert "deployment command/gpu-host-exclusive -> queue gpu" in captured.out


def test_run_idempotent_falls_back_when_prefect_reports_existing_resource_on_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> object:
        calls.append(command)
        if len(calls) == 1:
            return type(
                "Result",
                (),
                {
                    "returncode": 1,
                    "stdout": "Work queue with name: 'gpu' already exists.\n",
                    "stderr": "",
                },
            )()
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "updated\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(bootstrap, "_run_command", fake_run)

    _run_idempotent(
        ["prefect", "work-queue", "create", "gpu"],
        fallback=["prefect", "work-queue", "set-concurrency-limit", "gpu", "1"],
    )

    assert calls == [
        ["prefect", "work-queue", "create", "gpu"],
        ["prefect", "work-queue", "set-concurrency-limit", "gpu", "1"],
    ]


def test_build_runner_deployment_uses_repo_source_for_worker_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployment = build_deployments()[0]
    captured: dict[str, object] = {}

    class FakeSourceFlow:
        def to_deployment(self, **kwargs: object) -> str:
            captured["to_deployment"] = kwargs
            return "runner-deployment"

    def fake_from_source(*, source: str, entrypoint: str) -> FakeSourceFlow:
        captured["source"] = source
        captured["entrypoint"] = entrypoint
        return FakeSourceFlow()

    monkeypatch.setattr(bootstrap.run_command_task, "from_source", fake_from_source)

    result = build_runner_deployment(deployment, work_pool_name="local-process")

    assert result == "runner-deployment"
    assert captured["source"] == str(REPO_ROOT)
    assert captured["entrypoint"] == FLOW_ENTRYPOINT
    assert captured["to_deployment"] == {
        "name": deployment.name,
        "work_pool_name": "local-process",
        "work_queue_name": deployment.work_queue_name,
        "concurrency_limit": deployment.concurrency_limit,
        "description": deployment.description,
        "tags": list(deployment.tags),
    }
