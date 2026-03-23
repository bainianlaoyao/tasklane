from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from urllib.error import URLError
from urllib.request import urlopen

import anyio
from prefect.client.orchestration import get_client
from prefect.settings import PREFECT_API_URL, temporary_settings

from prefect_command_scheduler.bootstrap import apply_bootstrap
from prefect_command_scheduler.models import CommandTask
from prefect_command_scheduler.timing_analysis import ObservedRun, TimingAnalysis, analyze_timing_expectations


DEFAULT_PORT = 4310
DEFAULT_SLEEP_SECONDS = 8.0
DEFAULT_POLL_INTERVAL = 0.5
DEFAULT_TIMEOUT_SECONDS = 120.0
SCENARIO_COUNTS = {
    "gpu-exclusive": 2,
    "cpu-exclusive": 3,
    "cpu-light": 2,
    "gpu-host-exclusive": 2,
}


@dataclass(frozen=True)
class ScenarioArgs:
    port: int
    sleep_seconds: float
    timeout_seconds: float
    poll_interval: float
    keep_infra: bool
    cwd: str


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]
    log_path: Path
    log_file: object


def parse_args(argv: Sequence[str]) -> ScenarioArgs:
    parser = argparse.ArgumentParser(description="Run a live Prefect timing scenario and validate scheduler ordering.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="Synthetic command duration in seconds. Use a longer duration to dominate worker startup overhead.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--keep-infra", action="store_true", help="Leave the temporary Prefect server and workers running.")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory for the synthetic commands.")
    namespace = parser.parse_args(list(argv))
    return ScenarioArgs(
        port=namespace.port,
        sleep_seconds=namespace.sleep_seconds,
        timeout_seconds=namespace.timeout_seconds,
        poll_interval=namespace.poll_interval,
        keep_infra=namespace.keep_infra,
        cwd=namespace.cwd,
    )


def build_prefect_env(port: int) -> dict[str, str]:
    env = os.environ.copy()
    env["PREFECT_API_URL"] = f"http://127.0.0.1:{port}/api"
    env["PREFECT_SERVER_API_HOST"] = "127.0.0.1"
    env["PREFECT_SERVER_API_PORT"] = str(port)
    env.setdefault("PREFECT_UI_ENABLED", "0")
    return env


def wait_for_server(port: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    return
        except URLError:
            time.sleep(0.5)
    raise RuntimeError(f"Prefect server did not become healthy on port {port} within {timeout_seconds} seconds.")


def start_process(command: Sequence[str], *, env: dict[str, str], log_dir: Path, name: str) -> ManagedProcess:
    log_path = log_dir / f"{name}.log"
    log_file = log_path.open("w", encoding="utf-8")
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        list(command),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
    )
    return ManagedProcess(name=name, process=process, log_path=log_path, log_file=log_file)


def stop_process(managed: ManagedProcess) -> None:
    try:
        if managed.process.poll() is None:
            managed.process.terminate()
            try:
                managed.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                managed.process.kill()
                managed.process.wait(timeout=5)
    finally:
        managed.log_file.close()


def build_sleep_command(label: str, sleep_seconds: float, marker_path: Path) -> list[str]:
    script = (
        "import json, sys, time; "
        "from datetime import datetime, timezone; "
        "from pathlib import Path; "
        "marker_path = Path(sys.argv[1]); "
        "label = sys.argv[2]; "
        "sleep_seconds = float(sys.argv[3]); "
        "payload = {'name': label, 'started_at': datetime.now(timezone.utc).isoformat()}; "
        "marker_path.write_text(json.dumps(payload), encoding='utf-8'); "
        "print(f'START {label}', flush=True); "
        "time.sleep(sleep_seconds); "
        "payload['finished_at'] = datetime.now(timezone.utc).isoformat(); "
        "marker_path.write_text(json.dumps(payload), encoding='utf-8'); "
        "print(f'END {label}', flush=True)"
    )
    return [sys.executable, "-c", script, str(marker_path), label, str(sleep_seconds)]


async def submit_run(
    *,
    deployment_name: str,
    task_payload: dict[str, object],
    run_name: str,
) -> str:
    async with get_client() as client:
        deployment = await client.read_deployment_by_name(f"command-executor/{deployment_name}")
        flow_run = await client.create_flow_run_from_deployment(
            deployment.id,
            parameters={"task_payload": task_payload},
            name=run_name,
        )
    return str(flow_run.id)


async def wait_for_run(run_id: str, *, timeout_seconds: float, poll_interval: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    async with get_client() as client:
        while time.monotonic() < deadline:
            flow_run = await client.read_flow_run(run_id)
            if flow_run.state and flow_run.state.is_final():
                if flow_run.state_name != "Completed":
                    raise RuntimeError(f"Flow run {flow_run.name} finished in state {flow_run.state_name}.")
                return
            await anyio.sleep(poll_interval)
    raise RuntimeError(f"Timed out waiting for flow run {run_id}.")


def load_observed_run(marker_path: Path, *, run_name: str, resource_class: str) -> ObservedRun:
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    return ObservedRun(
        name=run_name,
        resource_class=resource_class,
        started_at=datetime.fromisoformat(payload["started_at"]),
        finished_at=datetime.fromisoformat(payload["finished_at"]),
    )


def format_timeline(runs: list[ObservedRun]) -> str:
    ordered = sorted(runs, key=lambda run: (run.started_at, run.finished_at, run.name))
    if not ordered:
        return "<no runs>"
    baseline = ordered[0].started_at
    lines = [
        "name | resource | start_offset_s | finish_offset_s | duration_s",
        "--- | --- | ---: | ---: | ---:",
    ]
    for run in ordered:
        lines.append(
            f"{run.name} | {run.resource_class} | "
            f"{(run.started_at - baseline).total_seconds():.3f} | "
            f"{(run.finished_at - baseline).total_seconds():.3f} | "
            f"{run.duration_seconds:.3f}"
        )
    return "\n".join(lines)


def format_analysis(analysis: TimingAnalysis) -> str:
    return (
        "host_exclusive_serial_ok="
        f"{analysis.host_exclusive_serial_ok}, "
        "gpu_serial_ok="
        f"{analysis.gpu_serial_ok}, "
        "cpu_light_parallel_ok="
        f"{analysis.cpu_light_parallel_ok}, "
        "cpu_light_overlaps_host_exclusive="
        f"{analysis.cpu_light_overlaps_host_exclusive}, "
        "gpu_exclusive_overlaps_cpu_exclusive="
        f"{analysis.gpu_exclusive_overlaps_cpu_exclusive}"
    )


async def run_scenario(args: ScenarioArgs, marker_dir: Path) -> tuple[list[ObservedRun], TimingAnalysis]:
    prefix = datetime.now(timezone.utc).strftime("timing-%Y%m%d-%H%M%S")
    task_specs: list[tuple[str, str]] = []
    for index in range(1, 3):
        task_specs.append((f"{prefix}-gpu-exclusive-{index}", "gpu-exclusive"))
    for index in range(1, 4):
        task_specs.append((f"{prefix}-cpu-exclusive-{index}", "cpu-exclusive"))
    for index in range(1, 3):
        task_specs.append((f"{prefix}-cpu-light-{index}", "cpu-light"))
    for index in range(1, 3):
        task_specs.append((f"{prefix}-gpu-host-exclusive-{index}", "gpu-host-exclusive"))

    run_specs: list[tuple[str, str, str, Path]] = []
    for run_name, resource_class in task_specs:
        marker_path = marker_dir / f"{run_name}.json"
        task = CommandTask(
            cwd=args.cwd,
            project="timing-scenario",
            command=build_sleep_command(run_name, args.sleep_seconds, marker_path),
            metadata={"resource_class": resource_class, "labels": ["timing-scenario"]},
            run_name=run_name,
            notes="Synthetic timing verification scenario.",
        )
        run_id = await submit_run(
            deployment_name=resource_class,
            task_payload=task.model_dump(mode="json"),
            run_name=run_name,
        )
        run_specs.append((run_id, run_name, resource_class, marker_path))

    for run_id, _, _, _ in run_specs:
        await wait_for_run(
            run_id,
            timeout_seconds=args.timeout_seconds,
            poll_interval=args.poll_interval,
        )

    observed_runs = [
        load_observed_run(marker_path, run_name=run_name, resource_class=resource_class)
        for _, run_name, resource_class, marker_path in run_specs
    ]
    analysis = analyze_timing_expectations(observed_runs, expected_counts=SCENARIO_COUNTS)
    return observed_runs, analysis


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    env = build_prefect_env(args.port)
    os.environ.update(env)
    managed_processes: list[ManagedProcess] = []

    log_dir = Path(tempfile.mkdtemp(prefix="prefect-timing-scenario-"))
    marker_dir = log_dir / "markers"
    marker_dir.mkdir(parents=True, exist_ok=True)
    should_cleanup_logs = False
    try:
        try:
            server = start_process(
                ["uv", "run", "prefect", "server", "start", "--host", "127.0.0.1", "--port", str(args.port), "--no-ui"],
                env=env,
                log_dir=log_dir,
                name="server",
            )
            managed_processes.append(server)
            wait_for_server(args.port, timeout_seconds=45)

            apply_bootstrap()

            managed_processes.extend(
                [
                    start_process(
                        ["uv", "run", "prefect", "worker", "start", "--pool", "local-process", "--work-queue", "gpu", "--type", "process", "--limit", "1"],
                        env=env,
                        log_dir=log_dir,
                        name="worker-gpu",
                    ),
                    start_process(
                        ["uv", "run", "prefect", "worker", "start", "--pool", "local-process", "--work-queue", "cpu-exclusive", "--type", "process", "--limit", "1"],
                        env=env,
                        log_dir=log_dir,
                        name="worker-cpu-exclusive",
                    ),
                    start_process(
                        ["uv", "run", "prefect", "worker", "start", "--pool", "local-process", "--work-queue", "cpu-light", "--type", "process", "--limit", "2"],
                        env=env,
                        log_dir=log_dir,
                        name="worker-cpu-light",
                    ),
                ]
            )

            time.sleep(5)
            with temporary_settings(updates={PREFECT_API_URL: env["PREFECT_API_URL"]}):
                observed_runs, analysis = anyio.run(run_scenario, args, marker_dir)

            print(format_analysis(analysis))
            print()
            print(format_timeline(observed_runs))

            if analysis.errors:
                print()
                print("errors:")
                for error in analysis.errors:
                    print(f"- {error}")
                return 1
            should_cleanup_logs = not args.keep_infra
            return 0
        except Exception:
            print()
            print("log files:")
            for managed in managed_processes:
                print(f"- {managed.name}: {managed.log_path}")
            raise
        finally:
            if not args.keep_infra:
                for managed in reversed(managed_processes):
                    stop_process(managed)
    finally:
        if should_cleanup_logs:
            for child in log_dir.glob("*"):
                try:
                    child.unlink()
                except OSError:
                    pass
            try:
                log_dir.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
