#!/usr/bin/env python3
"""
Unified forecast execution entrypoint for manual and scheduled runs.

This script creates a persistent run record, delegates execution to the shared
runtime manager, and blocks until the run reaches a terminal state so Linux
schedulers can treat it as a normal job.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.api.platform_store import PlatformStore
from src.api.run_lock import DEFAULT_EXECUTION_LOCK_PATH, RunLock, RunLockBusy
from src.api.runtime import ForecastRuntimeManager, VALID_MODES


DEFAULT_PLATFORM_DB = os.path.join(PROJECT_ROOT, "data", "platform_state.db")
DEFAULT_DB_URL = os.getenv("SALES_FORECAST_DB_URL")
TERMINAL_STATUSES = {"completed", "failed", "stopped"}
ACTIVE_STATUSES = {"queued", "running", "stopping"}


class TerminationRequested(BaseException):
    def __init__(self, signum: int):
        self.signum = int(signum)
        self.signal_name = signal.Signals(signum).name
        super().__init__(f"termination requested by {self.signal_name}")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a forecast job through the shared status store.")
    parser.add_argument("--config-id", help="Existing config id to execute.")
    parser.add_argument("--mode", default="smart", choices=sorted(VALID_MODES))
    parser.add_argument("--selection-type", default="all", choices=["all", "manual", "sql"])
    parser.add_argument("--manual-spus", default="", help="Manual SPU list for selection_type=manual.")
    parser.add_argument("--sql-query", default="", help="SQL selection query for selection_type=sql.")
    parser.add_argument("--trigger-source", default="schedule", help="Recorded trigger source.")
    parser.add_argument("--platform-db", default=DEFAULT_PLATFORM_DB, help="Shared SQLite status db path.")
    parser.add_argument("--db-url", default=DEFAULT_DB_URL, help="Source database URL.")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds.")
    parser.add_argument(
        "--max-spus",
        type=_positive_int,
        default=None,
        help="Optional positive SPU sample limit; also overrides a saved config value.",
    )
    parser.add_argument(
        "--no-persist-results",
        action="store_true",
        help="Run forecasting without writing forecast results to the result database.",
    )
    parser.add_argument(
        "--lock-file",
        default=DEFAULT_EXECUTION_LOCK_PATH,
        help="Shared non-blocking execution lock held for the complete run lifecycle.",
    )
    return parser


def _selection_payload(args: argparse.Namespace) -> dict:
    return {
        "manual_spus": args.manual_spus,
        "sql_query": args.sql_query,
        **_runtime_options(args),
    }


def _runtime_options(args: argparse.Namespace) -> dict:
    return {
        "max_spus": args.max_spus,
        "persist_results": not args.no_persist_results,
    }


def _create_run(
    manager: ForecastRuntimeManager,
    store: PlatformStore,
    args: argparse.Namespace,
):
    cli_payload = _selection_payload(args)
    if not args.config_id:
        return manager.create_run(
            mode=args.mode,
            selection_type=args.selection_type,
            selection_payload=cli_payload,
            trigger_source=args.trigger_source,
        )

    config = store.get_config(args.config_id)
    if not config:
        raise ValueError(f"Config not found: {args.config_id}")
    merged_payload = dict(config.get("selection_payload") or {})
    merged_payload.update(_runtime_options(args))
    return manager.create_run(
        mode=config["mode"],
        selection_type=config["selection_type"],
        selection_payload=merged_payload,
        config_id=args.config_id,
        trigger_source=args.trigger_source,
    )


def _install_signal_handlers(state: dict) -> dict:
    previous = {}

    def request_stop(signum, _frame):
        signal_name = signal.Signals(signum).name
        if state.get("signum") is not None:
            print(f"SIGNAL={signal_name} ACTION=pending", flush=True)
            return
        state["signum"] = int(signum)
        if state.get("run_ready"):
            print(f"SIGNAL={signal_name} ACTION=terminalize", flush=True)
            raise TerminationRequested(signum)
        print(f"SIGNAL={signal_name} ACTION=pending", flush=True)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    return previous


def _restore_signal_handlers(previous: dict) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _raise_pending_termination(state: dict) -> None:
    signum = state.get("signum")
    if signum is not None:
        raise TerminationRequested(int(signum))


def _read_run_before_unlock(store: PlatformStore, run_id: str | None) -> dict | None:
    if not run_id:
        return None
    attempt = 0
    while True:
        attempt += 1
        try:
            return store.get_run(run_id)
        except BaseException as exc:
            print(
                f"ERROR=terminal read retry ATTEMPT={attempt} RUN_ID={run_id} "
                f"REASON={exc or exc.__class__.__name__}",
                flush=True,
            )
            time.sleep(min(0.5 * attempt, 5.0))


def _terminalize_before_unlock(
    manager: ForecastRuntimeManager,
    store: PlatformStore,
    run_id: str | None,
    reason: str,
) -> dict | None:
    attempt = 0
    while True:
        attempt += 1
        try:
            terminal_runs = manager.shutdown_active_runs(reason=reason, join_timeout=0.0)
            current = store.get_run(run_id) if run_id else None
            if current and current.get("status") in ACTIVE_STATUSES:
                raise RuntimeError(
                    f"run remained active after terminal write: {current.get('status')}"
                )
            terminal_status = current.get("status") if current else "no-local-active-run"
            print(
                f"TERMINAL_WRITE=confirmed RUN_ID={run_id or '-'} "
                f"STATUS={terminal_status} OWNED={len(terminal_runs)}",
                flush=True,
            )
            return current
        except BaseException as exc:
            print(
                f"ERROR=terminal write retry ATTEMPT={attempt} "
                f"RUN_ID={run_id or '-'} REASON={exc or exc.__class__.__name__}",
                flush=True,
            )
            time.sleep(min(0.5 * attempt, 5.0))


def _run_while_locked(args: argparse.Namespace, signal_state: dict) -> int:
    store = None
    manager = None
    run_id = None
    try:
        store = PlatformStore(args.platform_db)
        _raise_pending_termination(signal_state)
        manager = ForecastRuntimeManager(store=store, db_url=args.db_url)
        _raise_pending_termination(signal_state)
        run = _create_run(manager, store, args)

        run_id = run["id"]
        signal_state["run_id"] = run_id
        signal_state["run_ready"] = True
        _raise_pending_termination(signal_state)
        print(f"RUN_ID={run_id}", flush=True)

        last_status = None
        while True:
            current = store.get_run(run_id)
            if not current:
                raise RuntimeError("run disappeared from store")
            if current["status"] != last_status:
                print(
                    f"STATUS={current['status']} PROGRESS={current['progress']} "
                    f"PROCESSED={current['processed_count']} TOTAL={current['total_count']}",
                    flush=True,
                )
                last_status = current["status"]
            if current["status"] in TERMINAL_STATUSES:
                signal_state["run_ready"] = False
                if current["status"] == "completed":
                    return 0
                print(f"ERROR={current.get('error_message') or current['status']}", flush=True)
                return 1
            time.sleep(max(args.poll_interval, 0.01))
    except BaseException as exc:
        if isinstance(exc, TerminationRequested):
            current = _read_run_before_unlock(store, run_id) if store is not None else None
            if current and current.get("status") == "completed":
                signal_state["run_ready"] = False
                print(f"SIGNAL={exc.signal_name} ACTION=run-already-completed", flush=True)
                return 0
            if current and current.get("status") in {"failed", "stopped"}:
                signal_state["run_ready"] = False
                print(f"ERROR={current.get('error_message') or current['status']}", flush=True)
                return 1
            if (
                manager is not None
                and store is not None
                and current
                and current.get("status") in ACTIVE_STATUSES
            ):
                reason = f"CLI interrupted by {exc.signal_name}; run terminalized before lock release."
                terminal = _terminalize_before_unlock(manager, store, run_id, reason)
                signal_state["run_ready"] = False
                if terminal and terminal.get("status") == "completed":
                    return 0
                return 128 + exc.signum
            signal_state["run_ready"] = False
            return 128 + exc.signum

        if manager is not None and store is not None:
            current = _read_run_before_unlock(store, run_id)
            if current and current.get("status") in ACTIVE_STATUSES:
                reason = f"CLI terminated unexpectedly: {exc or exc.__class__.__name__}"
                _terminalize_before_unlock(manager, store, run_id, reason)
        signal_state["run_ready"] = False
        print(f"ERROR={exc or exc.__class__.__name__}", flush=True)
        return 1


def main() -> int:
    args = build_parser().parse_args()
    state = {"signum": None, "run_ready": False, "run_id": None}
    previous_handlers = _install_signal_handlers(state)
    try:
        try:
            with RunLock(args.lock_file):
                print(f"LOCK=acquired PATH={args.lock_file}", flush=True)
                _raise_pending_termination(state)
                exit_code = _run_while_locked(args, state)
            print(f"LOCK=released PATH={args.lock_file}", flush=True)
            return exit_code
        except TerminationRequested as exc:
            print(
                f"SIGNAL={exc.signal_name} ACTION=exit-before-run-lock",
                flush=True,
            )
            return 128 + exc.signum
    except RunLockBusy as exc:
        if state.get("signum") is not None:
            signum = int(state["signum"])
            print(
                f"SIGNAL={signal.Signals(signum).name} ACTION=exit-before-run-lock",
                flush=True,
            )
            return 128 + signum
        print(f"SKIP=lock busy PATH={args.lock_file} REASON={exc}", flush=True)
        return 0
    finally:
        _restore_signal_handlers(previous_handlers)


if __name__ == "__main__":
    sys.exit(main())
