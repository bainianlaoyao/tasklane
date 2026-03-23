from __future__ import annotations

from dataclasses import dataclass

from .models import CommandTask, ResourceClass


@dataclass(frozen=True)
class RouteSpec:
    resource_class: ResourceClass
    deployment_name: str
    work_queue_name: str
    concurrency_slots: tuple[str, ...]


ROUTES: dict[ResourceClass, RouteSpec] = {
    "gpu-exclusive": RouteSpec(
        resource_class="gpu-exclusive",
        deployment_name="command-executor/gpu-exclusive",
        work_queue_name="gpu",
        concurrency_slots=("gpu-0",),
    ),
    "gpu-host-exclusive": RouteSpec(
        resource_class="gpu-host-exclusive",
        deployment_name="command-executor/gpu-host-exclusive",
        work_queue_name="gpu",
        concurrency_slots=("gpu-0", "host-exclusive"),
    ),
    "cpu-exclusive": RouteSpec(
        resource_class="cpu-exclusive",
        deployment_name="command-executor/cpu-exclusive",
        work_queue_name="cpu-exclusive",
        concurrency_slots=("host-exclusive",),
    ),
    "cpu-light": RouteSpec(
        resource_class="cpu-light",
        deployment_name="command-executor/cpu-light",
        work_queue_name="cpu-light",
        concurrency_slots=("cpu-light",),
    ),
}


def route_task(task: CommandTask) -> RouteSpec:
    return ROUTES[task.resource_class]
