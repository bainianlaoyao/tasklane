from tasklane.models import CommandTask
from tasklane.routing import route_task


def test_gpu_exclusive_routes_to_gpu_deployment() -> None:
    task = CommandTask(
        cwd=r"E:\freqtrade",
        command=["uv", "run", "python", "gpu_job.py"],
        metadata={"resource_class": "gpu-exclusive"},
    )

    route = route_task(task)

    assert route.deployment_name == "command-executor/gpu-exclusive"
    assert route.work_queue_name == "gpu"
    assert route.concurrency_slots == ("gpu-0",)


def test_gpu_host_exclusive_routes_to_gpu_deployment_with_host_lock() -> None:
    task = CommandTask(
        cwd=r"E:\freqtrade",
        command=["uv", "run", "python", "gpu_job.py"],
        metadata={"resource_class": "gpu-host-exclusive"},
    )

    route = route_task(task)

    assert route.deployment_name == "command-executor/gpu-host-exclusive"
    assert route.work_queue_name == "gpu"
    assert route.concurrency_slots == ("gpu-0", "host-exclusive")


def test_cpu_light_routes_to_lightweight_queue() -> None:
    task = CommandTask(
        cwd=r"D:\Data\DEV\freqtrade-a-share-30m",
        command=["uv", "run", "python", "light_job.py"],
        metadata={"resource_class": "cpu-light"},
    )

    route = route_task(task)

    assert route.deployment_name == "command-executor/cpu-light"
    assert route.work_queue_name == "cpu-light"
    assert route.concurrency_slots == ("cpu-light",)
