#!/usr/bin/env python3
"""Explicit, lock-protected recovery for orphaned forecast run state."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.platform_store import ACTIVE_RUN_STATUSES, PlatformStore
from src.api.run_lock import DEFAULT_EXECUTION_LOCK_PATH, RunLock, RunLockBusy


DEFAULT_PLATFORM_DB = PROJECT_ROOT / "data" / "platform_state.db"
DEFAULT_REASON = "Explicit recovery closed an orphaned active run after acquiring the execution lock."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Back up and repair orphaned active forecast runs. The shared execution lock "
            "is held from before backup until all recovery checks finish."
        )
    )
    parser.add_argument(
        "--platform-db",
        default=str(DEFAULT_PLATFORM_DB),
        help="Source SQLite platform state database.",
    )
    parser.add_argument(
        "--backup-path",
        help="New backup file path. Existing files are never overwritten.",
    )
    parser.add_argument(
        "--lock-file",
        default=DEFAULT_EXECUTION_LOCK_PATH,
        help="Shared non-blocking forecast execution lock.",
    )
    parser.add_argument("--reason", default=DEFAULT_REASON, help="Audit reason stored on recovered runs.")
    return parser


def _integrity_check(connection: sqlite3.Connection, label: str) -> str:
    rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
    if rows != ["ok"]:
        raise RuntimeError(f"{label} integrity_check failed: {'; '.join(rows)}")
    return "ok"


def _source_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)


def _default_backup_path(source: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = source.with_name(f"{source.stem}.recovery-{stamp}-{os.getpid()}{source.suffix or '.db'}")
    suffix = 1
    while candidate.exists():
        candidate = source.with_name(
            f"{source.stem}.recovery-{stamp}-{os.getpid()}-{suffix}{source.suffix or '.db'}"
        )
        suffix += 1
    return candidate


def _online_backup(source: Path, backup: Path) -> tuple[str, str]:
    backup.parent.mkdir(parents=True, exist_ok=True)
    temporary_handle = tempfile.NamedTemporaryFile(
        prefix=f".{backup.name}.",
        suffix=".tmp",
        dir=str(backup.parent),
        delete=False,
    )
    temporary_path = Path(temporary_handle.name)
    temporary_handle.close()
    try:
        with closing(_source_connection(source)) as source_connection:
            source_integrity = _integrity_check(source_connection, "source")
            with closing(sqlite3.connect(str(temporary_path), timeout=30)) as backup_connection:
                source_connection.backup(backup_connection)
                backup_integrity = _integrity_check(backup_connection, "backup")
                backup_connection.commit()

        with open(temporary_path, "r+b") as backup_file:
            backup_file.flush()
            os.fsync(backup_file.fileno())

        # A hard link publishes the already-verified inode atomically and fails
        # if another process created the final path first.
        os.link(temporary_path, backup)
        return source_integrity, backup_integrity
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _active_run_count(path: Path) -> int:
    placeholders = ",".join("?" for _ in ACTIVE_RUN_STATUSES)
    with closing(_source_connection(path)) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'forecast_job_run'"
        ).fetchone()
        if not table_exists:
            return 0
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM forecast_job_run WHERE status IN ({placeholders})",
                tuple(ACTIVE_RUN_STATUSES),
            ).fetchone()[0]
        )


def _recover(args: argparse.Namespace) -> dict:
    source = Path(args.platform_db).expanduser().resolve()
    reason = str(args.reason or "").strip()

    with RunLock(args.lock_file):
        if not source.is_file():
            raise FileNotFoundError(f"platform state database not found: {source}")
        backup = (
            Path(args.backup_path).expanduser().resolve()
            if args.backup_path
            else _default_backup_path(source)
        )
        if os.path.normcase(str(source)) == os.path.normcase(str(backup)):
            raise ValueError("backup path must differ from the source database")
        if backup.exists():
            raise FileExistsError(f"backup path already exists: {backup}")
        if not reason:
            raise ValueError("recovery reason must not be empty")
        source_integrity, backup_integrity = _online_backup(source, backup)
        active_before = _active_run_count(source)
        store: Optional[PlatformStore] = None
        try:
            store = PlatformStore(str(source))
            recovered_runs = store.close_orphaned_active_runs(reason)
            constraint_ready = store.ensure_active_run_constraint(raise_on_conflict=True)
        finally:
            if store is not None:
                store.engine.dispose()
        active_after = _active_run_count(source)
        with closing(_source_connection(source)) as source_connection:
            source_integrity_after = _integrity_check(source_connection, "recovered source")
        if active_after != 0 or not constraint_ready:
            raise RuntimeError(
                f"recovery verification failed: active_after={active_after}, "
                f"constraint_ready={constraint_ready}"
            )

    return {
        "status": "recovered",
        "platform_db": str(source),
        "backup_path": str(backup),
        "lock_file": os.path.abspath(os.fspath(args.lock_file)),
        "source_integrity_before": source_integrity,
        "source_integrity_after": source_integrity_after,
        "backup_integrity": backup_integrity,
        "active_runs_before": active_before,
        "active_runs_closed": recovered_runs,
        "active_runs_after": active_after,
        "active_constraint_ready": bool(constraint_ready),
        "reason": reason,
    }


def main() -> int:
    args = build_parser().parse_args()
    try:
        summary = _recover(args)
    except RunLockBusy as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": "lock_busy",
                    "error": str(exc),
                    "lock_file": os.path.abspath(os.fspath(args.lock_file)),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc) or exc.__class__.__name__,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
