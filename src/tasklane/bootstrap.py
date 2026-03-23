from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .state import SchedulerState, default_db_path, default_logs_dir, default_tasklane_home


DEFAULT_POLL_INTERVAL = 0.2


def build_bootstrap_preview_lines() -> list[str]:
    home = default_tasklane_home()
    db_path = default_db_path()
    logs_dir = default_logs_dir()
    return [
        f"tasklane home: {home}",
        f"sqlite db: {db_path}",
        f"log dir: {logs_dir}",
        "tasklane daemon --poll-interval 0.2",
    ]


def apply_bootstrap() -> SchedulerState:
    return SchedulerState.initialize()


def parse_bootstrap_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize local Tasklane state.")
    parser.add_argument("--apply", action="store_true", help="Create local sqlite state and log directories.")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_bootstrap_args(sys.argv[1:] if argv is None else argv)
    if args.apply:
        state = apply_bootstrap()
        print(f"initialized sqlite db: {state.db_path}")
        print(f"initialized log dir: {state.logs_dir}")
    else:
        for line in build_bootstrap_preview_lines():
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
