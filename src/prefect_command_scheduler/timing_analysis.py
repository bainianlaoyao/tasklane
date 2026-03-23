from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .models import ResourceClass


HOST_EXCLUSIVE_RESOURCES = frozenset({"cpu-exclusive", "gpu-host-exclusive"})
GPU_SLOT_RESOURCES = frozenset({"gpu-exclusive", "gpu-host-exclusive"})


@dataclass(frozen=True)
class ObservedRun:
    name: str
    resource_class: ResourceClass
    started_at: datetime
    finished_at: datetime

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


@dataclass(frozen=True)
class TimingAnalysis:
    counts_by_resource: dict[ResourceClass, int]
    host_exclusive_serial_ok: bool
    gpu_serial_ok: bool
    cpu_light_parallel_ok: bool
    cpu_light_overlaps_host_exclusive: bool
    gpu_exclusive_overlaps_cpu_exclusive: bool
    errors: list[str]


def _overlaps(left: ObservedRun, right: ObservedRun) -> bool:
    return left.started_at < right.finished_at and right.started_at < left.finished_at


def _count_by_resource(runs: Iterable[ObservedRun]) -> dict[ResourceClass, int]:
    counts: dict[ResourceClass, int] = {
        "gpu-exclusive": 0,
        "gpu-host-exclusive": 0,
        "cpu-exclusive": 0,
        "cpu-light": 0,
    }
    for run in runs:
        counts[run.resource_class] += 1
    return counts


def analyze_timing_expectations(
    runs: list[ObservedRun],
    *,
    expected_counts: dict[ResourceClass, int] | None = None,
) -> TimingAnalysis:
    ordered = sorted(runs, key=lambda run: (run.started_at, run.finished_at, run.name))
    errors: list[str] = []
    counts = _count_by_resource(ordered)

    if expected_counts is not None:
        for resource_class, expected_count in expected_counts.items():
            actual_count = counts.get(resource_class, 0)
            if actual_count != expected_count:
                errors.append(
                    f"Expected {expected_count} runs for {resource_class}, observed {actual_count}."
                )

    host_exclusive_runs = [run for run in ordered if run.resource_class in HOST_EXCLUSIVE_RESOURCES]
    host_exclusive_serial_ok = True
    for index, current in enumerate(host_exclusive_runs):
        for later in host_exclusive_runs[index + 1 :]:
            if _overlaps(current, later):
                host_exclusive_serial_ok = False
                errors.append(
                    "Host-exclusive runs overlapped: "
                    f"{current.name} ({current.resource_class}) with "
                    f"{later.name} ({later.resource_class})."
                )

    gpu_slot_runs = [run for run in ordered if run.resource_class in GPU_SLOT_RESOURCES]
    gpu_serial_ok = True
    for index, current in enumerate(gpu_slot_runs):
        for later in gpu_slot_runs[index + 1 :]:
            if _overlaps(current, later):
                gpu_serial_ok = False
                errors.append(
                    "GPU-slot runs overlapped: "
                    f"{current.name} ({current.resource_class}) with "
                    f"{later.name} ({later.resource_class})."
                )

    cpu_light_runs = [run for run in ordered if run.resource_class == "cpu-light"]
    cpu_light_parallel_ok = False
    if len(cpu_light_runs) >= 2:
        cpu_light_parallel_ok = any(
            _overlaps(current, later)
            for index, current in enumerate(cpu_light_runs)
            for later in cpu_light_runs[index + 1 :]
        )
    if len(cpu_light_runs) >= 2 and not cpu_light_parallel_ok:
        errors.append("CPU-light runs never overlapped, but they were expected to run in parallel.")

    cpu_light_overlaps_host_exclusive = any(
        _overlaps(light, host)
        for light in cpu_light_runs
        for host in host_exclusive_runs
    )
    if cpu_light_runs and host_exclusive_runs and not cpu_light_overlaps_host_exclusive:
        errors.append(
            "CPU-light runs never overlapped with host-exclusive runs, so cross-queue parallelism was not observed."
        )

    gpu_exclusive_runs = [run for run in ordered if run.resource_class == "gpu-exclusive"]
    cpu_exclusive_runs = [run for run in ordered if run.resource_class == "cpu-exclusive"]
    gpu_exclusive_overlaps_cpu_exclusive = any(
        _overlaps(gpu, cpu)
        for gpu in gpu_exclusive_runs
        for cpu in cpu_exclusive_runs
    )
    if gpu_exclusive_runs and cpu_exclusive_runs and not gpu_exclusive_overlaps_cpu_exclusive:
        errors.append(
            "GPU-exclusive runs never overlapped with cpu-exclusive runs, so normal GPU/CPU parallelism was not observed."
        )

    return TimingAnalysis(
        counts_by_resource=counts,
        host_exclusive_serial_ok=host_exclusive_serial_ok,
        gpu_serial_ok=gpu_serial_ok,
        cpu_light_parallel_ok=cpu_light_parallel_ok,
        cpu_light_overlaps_host_exclusive=cpu_light_overlaps_host_exclusive,
        gpu_exclusive_overlaps_cpu_exclusive=gpu_exclusive_overlaps_cpu_exclusive,
        errors=errors,
    )
