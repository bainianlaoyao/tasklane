from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Sequence

from .attach import SubmittedRun, attach_submitted_run, format_scheduler_event_line, submit_task
from .models import CommandTask, RESOURCE_CLASSES, ResourceClass


@dataclass(frozen=True)
class SubmitArgs:
    cwd: str
    project: str | None
    resource: ResourceClass
    run_name: str | None
    notes: str | None
    labels: list[str]
    env: list[str]
    detach: bool
    command: list[str]


def parse_submit_args(argv: Sequence[str]) -> SubmitArgs:
    parser = argparse.ArgumentParser(description="Submit a command to the Prefect scheduler.")
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--project")
    parser.add_argument("--resource", required=True, choices=RESOURCE_CLASSES)
    parser.add_argument("--run-name")
    parser.add_argument("--notes")
    parser.add_argument("--label", dest="labels", action="append", default=[])
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    namespace = parser.parse_args(list(argv))

    command = list(namespace.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("missing command after --")

    return SubmitArgs(
        cwd=namespace.cwd,
        project=namespace.project,
        resource=namespace.resource,
        run_name=namespace.run_name,
        notes=namespace.notes,
        labels=list(namespace.labels),
        env=list(namespace.env),
        detach=bool(namespace.detach),
        command=command,
    )


def _parse_env_overrides(entries: Sequence[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for entry in entries:
        key, sep, value = entry.partition("=")
        if not sep:
            raise ValueError(f"Invalid env override: {entry}")
        env[key] = value
    return env


def build_command_task(args: SubmitArgs) -> CommandTask:
    metadata = {
        "resource_class": args.resource,
        "labels": args.labels,
    }
    return CommandTask(
        cwd=args.cwd,
        project=args.project,
        command=args.command,
        env_overrides=_parse_env_overrides(args.env),
        metadata=metadata,
        run_name=args.run_name,
        notes=args.notes,
    )

def print_submitted_event(submitted: SubmittedRun) -> None:
    print(
        format_scheduler_event_line(
            "submitted",
            run_id=submitted.flow_run_id,
            queue=submitted.queue_name,
            resource=submitted.resource_class,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_submit_args(sys.argv[1:] if argv is None else argv)
    task = build_command_task(args)
    submitted = submit_task(task)
    print_submitted_event(submitted)
    if args.detach:
        return 0
    return attach_submitted_run(submitted, out=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
