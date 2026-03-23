from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .flows import run_command_task


REPO_ROOT = Path(__file__).resolve().parents[2]
FLOW_ENTRYPOINT = "src/prefect_command_scheduler/flows.py:run_command_task"
DEFAULT_WORK_POOL = "local-process"
DEFAULT_QUEUES = ("gpu", "cpu-exclusive", "cpu-light")
DEFAULT_QUEUE_LIMITS = {
    "gpu": 1,
    "cpu-exclusive": 1,
    "cpu-light": 2,
}
DEFAULT_QUEUE_PRIORITIES = {
    "gpu": 1,
    "cpu-exclusive": 2,
    "cpu-light": 3,
}
DEFAULT_GLOBAL_LIMITS = {
    "gpu-0": 1,
    "host-exclusive": 1,
    "cpu-light": 2,
}


@dataclass(frozen=True)
class DeploymentSpec:
    name: str
    work_queue_name: str
    concurrency_limit: int
    description: str
    tags: tuple[str, ...]


def build_deployments() -> list[DeploymentSpec]:
    return [
        DeploymentSpec(
            name="gpu-exclusive",
            work_queue_name="gpu",
            concurrency_limit=1,
            description="Run arbitrary commands that require GPU access without host exclusivity.",
            tags=("command", "gpu"),
        ),
        DeploymentSpec(
            name="gpu-host-exclusive",
            work_queue_name="gpu",
            concurrency_limit=1,
            description="Run GPU commands that also need exclusive host access.",
            tags=("command", "gpu"),
        ),
        DeploymentSpec(
            name="cpu-exclusive",
            work_queue_name="cpu-exclusive",
            concurrency_limit=1,
            description="Run CPU or memory heavy commands that should not share the host.",
            tags=("command", "cpu"),
        ),
        DeploymentSpec(
            name="cpu-light",
            work_queue_name="cpu-light",
            concurrency_limit=2,
            description="Run lightweight CPU commands that can share limited concurrency.",
            tags=("command", "cpu-light"),
        ),
    ]


def build_bootstrap_commands(work_pool_name: str = DEFAULT_WORK_POOL) -> list[list[str]]:
    commands: list[list[str]] = [
        [
            "prefect",
            "work-pool",
            "create",
            work_pool_name,
            "--type",
            "process",
            "--overwrite",
            "--set-as-default",
        ]
    ]
    for queue_name in DEFAULT_QUEUES:
        commands.append(
            [
                "prefect",
                "work-queue",
                "create",
                queue_name,
                "--pool",
                work_pool_name,
                "--limit",
                str(DEFAULT_QUEUE_LIMITS[queue_name]),
                "--priority",
                str(DEFAULT_QUEUE_PRIORITIES[queue_name]),
            ]
        )
    for limit_name, limit_value in DEFAULT_GLOBAL_LIMITS.items():
        commands.append(
            [
                "prefect",
                "global-concurrency-limit",
                "create",
                limit_name,
                "--limit",
                str(limit_value),
            ]
        )
    return commands


def build_bootstrap_preview_lines(work_pool_name: str = DEFAULT_WORK_POOL) -> list[str]:
    lines = [" ".join(command) for command in build_bootstrap_commands(work_pool_name=work_pool_name)]
    for deployment in build_deployments():
        lines.append(
            "deployment "
            f"command/{deployment.name} -> queue {deployment.work_queue_name} "
            f"(pool {work_pool_name}, concurrency {deployment.concurrency_limit})"
        )
    return lines


def build_runner_deployment(
    deployment: DeploymentSpec,
    *,
    work_pool_name: str = DEFAULT_WORK_POOL,
):
    source_flow = run_command_task.from_source(
        source=str(REPO_ROOT),
        entrypoint=FLOW_ENTRYPOINT,
    )
    return source_flow.to_deployment(
        name=deployment.name,
        work_pool_name=work_pool_name,
        work_queue_name=deployment.work_queue_name,
        concurrency_limit=deployment.concurrency_limit,
        description=deployment.description,
        tags=list(deployment.tags),
    )


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
    )


def _run_idempotent(command: Sequence[str], fallback: Sequence[str] | None = None) -> None:
    result = _run_command(command)
    if result.returncode == 0:
        if result.stdout:
            print(result.stdout, end="")
        return

    combined_output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    if fallback is not None and ("already exists" in combined_output or "409" in combined_output):
        fallback_result = _run_command(fallback)
        if fallback_result.stdout:
            print(fallback_result.stdout, end="")
        if fallback_result.returncode != 0:
            if fallback_result.stderr:
                print(fallback_result.stderr, end="", file=sys.stderr)
            raise SystemExit(fallback_result.returncode)
        return

    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    raise SystemExit(result.returncode)


def apply_bootstrap(work_pool_name: str = DEFAULT_WORK_POOL) -> None:
    commands = build_bootstrap_commands(work_pool_name=work_pool_name)
    _run_idempotent(commands[0])

    for queue_name in DEFAULT_QUEUES:
        _run_idempotent(
            [
                "prefect",
                "work-queue",
                "create",
                queue_name,
                "--pool",
                work_pool_name,
                "--limit",
                str(DEFAULT_QUEUE_LIMITS[queue_name]),
                "--priority",
                str(DEFAULT_QUEUE_PRIORITIES[queue_name]),
            ],
            fallback=[
                "prefect",
                "work-queue",
                "set-concurrency-limit",
                queue_name,
                str(DEFAULT_QUEUE_LIMITS[queue_name]),
                "--pool",
                work_pool_name,
            ],
        )

    for limit_name, limit_value in DEFAULT_GLOBAL_LIMITS.items():
        _run_idempotent(
            [
                "prefect",
                "global-concurrency-limit",
                "create",
                limit_name,
                "--limit",
                str(limit_value),
            ],
            fallback=[
                "prefect",
                "global-concurrency-limit",
                "update",
                limit_name,
                "--limit",
                str(limit_value),
                "--enable",
            ],
        )

    for deployment in build_deployments():
        runner_deployment = build_runner_deployment(
            deployment,
            work_pool_name=work_pool_name,
        )
        runner_deployment.apply(work_pool_name=work_pool_name)


def parse_bootstrap_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap local Prefect resources for the command scheduler.")
    parser.add_argument("--work-pool", default=DEFAULT_WORK_POOL)
    parser.add_argument("--apply", action="store_true", help="Create/update resources in the active Prefect server.")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_bootstrap_args(sys.argv[1:] if argv is None else argv)
    if args.apply:
        apply_bootstrap(work_pool_name=args.work_pool)
    else:
        for line in build_bootstrap_preview_lines(work_pool_name=args.work_pool):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
