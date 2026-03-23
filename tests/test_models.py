from pydantic import ValidationError

from prefect_command_scheduler.models import CommandTask


def test_command_task_accepts_minimal_valid_payload() -> None:
    task = CommandTask(
        cwd=r"D:\Data\DEV\freqtrade-a-share-30m",
        command=["uv", "run", "python", "script.py"],
        metadata={"resource_class": "gpu-exclusive"},
    )

    assert task.project is None
    assert task.metadata["resource_class"] == "gpu-exclusive"
    assert task.command[-1] == "script.py"


def test_command_task_accepts_gpu_host_exclusive_resource_class() -> None:
    task = CommandTask(
        cwd=r"D:\Data\DEV\freqtrade-a-share-30m",
        command=["uv", "run", "python", "script.py"],
        metadata={"resource_class": "gpu-host-exclusive"},
    )

    assert task.resource_class == "gpu-host-exclusive"


def test_command_task_requires_resource_class() -> None:
    try:
        CommandTask(
            cwd=r"D:\Data\DEV\freqtrade-a-share-30m",
            command=["uv", "run", "python", "script.py"],
            metadata={},
        )
    except ValidationError as exc:
        assert "resource_class" in str(exc)
    else:
        raise AssertionError("Expected validation to fail without resource_class")


def test_command_task_rejects_empty_command() -> None:
    try:
        CommandTask(
            cwd=r"D:\Data\DEV\freqtrade-a-share-30m",
            command=[],
            metadata={"resource_class": "cpu-light"},
        )
    except ValidationError as exc:
        assert "command" in str(exc)
    else:
        raise AssertionError("Expected validation to fail for empty command")
