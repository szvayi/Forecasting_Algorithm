from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError, OperationalError

from src.api.platform_store import PlatformStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYSTEMD_DIR = PROJECT_ROOT / "deploy" / "systemd"
WRITE_SQL_PATTERN = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b",
    re.IGNORECASE,
)


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(PROJECT_ROOT), existing_pythonpath) if part
    )
    env["PYTHONUTF8"] = "1"
    return env


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _business_table_snapshot(store: PlatformStore) -> dict[str, tuple[tuple, ...]]:
    snapshot: dict[str, tuple[tuple, ...]] = {}
    with store.engine.connect() as connection:
        table_names = connection.exec_driver_sql(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).scalars().all()
        for table_name in table_names:
            quoted_name = str(table_name).replace('"', '""')
            rows = connection.exec_driver_sql(
                f'SELECT * FROM "{quoted_name}" ORDER BY rowid'
            ).all()
            snapshot[str(table_name)] = tuple(tuple(row) for row in rows)
    return snapshot


def _get_with_write_capture(store: PlatformStore, request):
    write_statements = []

    def record_writes(_conn, _cursor, statement, _parameters, _context, _executemany):
        if WRITE_SQL_PATTERN.search(str(statement)):
            write_statements.append(str(statement))

    event.listen(store.engine, "before_cursor_execute", record_writes)
    try:
        response = request()
    finally:
        event.remove(store.engine, "before_cursor_execute", record_writes)
    return response, write_statements


def _insert_raw_run(connection, run_id: str, status: str) -> None:
    connection.exec_driver_sql(
        """
        INSERT INTO forecast_job_run
        (id, config_id, trigger_source, mode, selection_type,
         selection_payload_json, selected_spus_json, status, created_at, updated_at)
        VALUES (?, NULL, 'schedule', 'smart', 'all', '{}', '[]', ?, ?, ?)
        """,
        (run_id, status, "2026-08-21T00:00:00Z", "2026-08-21T00:00:00Z"),
    )


def _contains_flock_command(command: str) -> bool:
    return re.search(
        r"(?<![A-Za-z0-9_])flock(?![A-Za-z0-9_])",
        command,
        re.IGNORECASE,
    ) is not None


def _single_systemd_value(
    directives: dict[str, list[str]],
    key: str,
) -> str:
    values = directives.get(key, [])
    assert len(values) == 1, f"{key} must have one effective value, got {values!r}"
    return values[0]


def _parse_systemd_seconds(value: str) -> Decimal:
    text_value = value.strip()
    assert text_value, "systemd duration must not be empty"
    fragment_pattern = re.compile(
        r"\s*(\d+(?:\.\d+)?)\s*(us|ms|min|s|h|d)?",
        re.IGNORECASE,
    )
    multipliers = {
        "us": Decimal("0.000001"),
        "ms": Decimal("0.001"),
        "s": Decimal("1"),
        "min": Decimal("60"),
        "h": Decimal("3600"),
        "d": Decimal("86400"),
    }
    total = Decimal("0")
    position = 0
    while position < len(text_value):
        match = fragment_pattern.match(text_value, position)
        assert match is not None, f"unsupported systemd duration: {value!r}"
        amount = Decimal(match.group(1))
        unit = (match.group(2) or "s").lower()
        total += amount * multipliers[unit]
        position = match.end()
    return total


def _parse_systemd_boolean(value: str) -> bool:
    normalized = value.strip().lower()
    assert normalized in {"1", "yes", "true", "on", "0", "no", "false", "off"}
    return normalized in {"1", "yes", "true", "on"}


def _sqlite_locked_error() -> OperationalError:
    return OperationalError(
        "database operation",
        {},
        sqlite3.OperationalError("database is locked"),
    )


def _wait_for_terminal_run(
    store: PlatformStore,
    run_id: str,
    timeout: float = 5.0,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = store.get_run(run_id)
        if run and run["status"] in {"completed", "failed", "stopped"}:
            return run
        time.sleep(0.01)
    pytest.fail(f"run {run_id} did not reach a terminal state within {timeout}s")


def _assert_lock_reacquirable(lock_path: Path, timeout: float = 5.0) -> None:
    from src.api.run_lock import RunLock, RunLockBusy

    deadline = time.monotonic() + timeout
    while True:
        try:
            with RunLock(str(lock_path)):
                return
        except RunLockBusy:
            if time.monotonic() >= deadline:
                pytest.fail(f"execution lock was not released: {lock_path}")
            time.sleep(0.01)


def _wait_for_child_barrier(
    process: subprocess.Popen,
    barrier_path: Path,
    timeout: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if barrier_path.is_file():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            pytest.fail(
                f"child exited before barrier {barrier_path.name}: "
                f"code={process.returncode}\nstdout={stdout}\nstderr={stderr}"
            )
        time.sleep(0.01)
    pytest.fail(f"child did not reach barrier {barrier_path.name} within {timeout}s")


def _terminate_child(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)


@pytest.fixture
def isolated_app(tmp_path):
    """Import the API with isolated globals and restore them after each test."""
    import src.api.platform_store as store_module
    from src.api.runtime import ForecastRuntimeManager

    previously_loaded = sys.modules.get("src.api.app")
    test_store = store_module.PlatformStore(
        str(tmp_path / "isolated_api_state.db")
    )
    original_store_class = store_module.PlatformStore
    if previously_loaded is None:
        store_module.PlatformStore = lambda _db_path: test_store
        try:
            app_module = importlib.import_module("src.api.app")
        finally:
            store_module.PlatformStore = original_store_class
    else:
        app_module = previously_loaded

    original_app_store = app_module.store
    original_app_manager = app_module.manager
    original_app_store_class = app_module.PlatformStore
    app_module.store = test_store
    app_module.manager = ForecastRuntimeManager(store=test_store, db_url="")
    app_module.PlatformStore = original_store_class
    try:
        yield app_module
    finally:
        app_module.store = original_app_store
        app_module.manager = original_app_manager
        app_module.PlatformStore = original_app_store_class
        if previously_loaded is None:
            sys.modules.pop("src.api.app", None)


def test_run_lock_allows_only_one_holder_per_path_and_can_be_reacquired(tmp_path):
    from src.api.run_lock import RunLock, RunLockBusy

    lock_path = tmp_path / "forecast-weekly.lock"

    with RunLock(str(lock_path)):
        with pytest.raises(RunLockBusy):
            with RunLock(str(lock_path)):
                pass

    with RunLock(str(lock_path)):
        pass


def test_platform_store_claim_run_is_atomic_across_store_instances(tmp_path):
    from src.api.platform_store import ActiveRunConflict

    db_path = str(tmp_path / "platform_state.db")
    stores = [PlatformStore(db_path), PlatformStore(db_path)]
    ready = threading.Barrier(2)

    def claim(store):
        ready.wait(timeout=5)
        try:
            run = store.claim_run(
                config_id=None,
                trigger_source="schedule",
                mode="smart",
                selection_type="all",
                selection_payload={},
                selected_spus=[],
            )
        except ActiveRunConflict:
            return "conflict", None
        return "claimed", run

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, stores))

    outcomes = sorted(outcome for outcome, _run in results)
    claimed_runs = [run for outcome, run in results if outcome == "claimed"]
    persisted_runs = stores[0].list_runs(limit=10)

    assert outcomes == ["claimed", "conflict"]
    assert len(claimed_runs) == 1
    assert claimed_runs[0]["status"] == "queued"
    assert len(persisted_runs) == 1
    assert persisted_runs[0]["id"] == claimed_runs[0]["id"]


@pytest.mark.parametrize("existing_status", ["queued", "running", "stopping"])
def test_database_constraint_allows_only_one_active_run_and_reopens_after_terminal(
    tmp_path,
    existing_status,
):
    db_path = str(tmp_path / f"platform_state_{existing_status}.db")
    first_store = PlatformStore(db_path)
    second_store = PlatformStore(db_path)

    with (
        first_store.engine.connect() as first_connection,
        second_store.engine.connect() as second_connection,
    ):
        assert (
            first_connection.connection.dbapi_connection
            is not second_connection.connection.dbapi_connection
        )
        with first_connection.begin():
            _insert_raw_run(first_connection, "existing-active", existing_status)

        with pytest.raises(IntegrityError):
            with second_connection.begin():
                _insert_raw_run(second_connection, "conflicting-active", "queued")

        with first_connection.begin():
            first_connection.exec_driver_sql(
                "UPDATE forecast_job_run SET status = 'completed' WHERE id = ?",
                ("existing-active",),
            )
        with second_connection.begin():
            _insert_raw_run(second_connection, "replacement-active", "queued")

        rows = first_connection.exec_driver_sql(
            "SELECT id, status FROM forecast_job_run ORDER BY id"
        ).all()

    assert [tuple(row) for row in rows] == [
        ("existing-active", "completed"),
        ("replacement-active", "queued"),
    ]


def test_manager_create_run_uses_atomic_claim_across_store_instances(
    monkeypatch,
    tmp_path,
):
    import src.api.runtime as runtime_module
    from src.api.platform_store import ActiveRunConflict

    db_path = str(tmp_path / "platform_state.db")
    stores = [PlatformStore(db_path), PlatformStore(db_path)]
    managers = [
        runtime_module.ForecastRuntimeManager(store=store, db_url="")
        for store in stores
    ]
    ready = threading.Barrier(2)
    outcomes = []
    claim_calls = []
    global_thread_class = threading.Thread
    runtime_threading_module = runtime_module.threading
    original_claim = PlatformStore.claim_run

    class DormantJobThread:
        def __init__(self, target, args=(), daemon=False):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            pass

    class RuntimeThreadingProxy:
        Thread = DormantJobThread

        def __getattr__(self, name):
            return getattr(runtime_threading_module, name)

    def tracked_claim(store, *args, **kwargs):
        claim_calls.append(store)
        return original_claim(store, *args, **kwargs)

    def create(manager):
        ready.wait(timeout=5)
        try:
            run = manager.create_run(
                mode="smart",
                selection_type="all",
                selection_payload={},
                trigger_source="schedule",
            )
        except ActiveRunConflict:
            outcomes.append(("conflict", None))
        else:
            outcomes.append(("claimed", run))

    with monkeypatch.context() as isolated_patch:
        isolated_patch.setattr(PlatformStore, "claim_run", tracked_claim)
        isolated_patch.setattr(
            runtime_module,
            "threading",
            RuntimeThreadingProxy(),
        )
        assert threading.Thread is global_thread_class
        workers = [
            global_thread_class(target=create, args=(manager,))
            for manager in managers
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)

    assert threading.Thread is global_thread_class
    assert runtime_module.threading is runtime_threading_module

    assert all(not worker.is_alive() for worker in workers)
    assert sorted(outcome for outcome, _run in outcomes) == ["claimed", "conflict"]
    assert len(claim_calls) == 2
    active_runs = [
        run
        for run in stores[0].list_runs(limit=10)
        if run["status"] in {"queued", "running", "stopping"}
    ]
    assert len(active_runs) == 1


def test_platform_store_enables_wal_and_long_busy_timeout(tmp_path):
    db_path = str(tmp_path / "platform_state.db")
    stores = [PlatformStore(db_path), PlatformStore(db_path)]
    connection_settings = []
    initial_dbapi_connections = []
    renewed_dbapi_connections = []

    for store in stores:
        with store.engine.connect() as initial_connection:
            initial_dbapi_connections.append(
                initial_connection.connection.dbapi_connection
            )
        store.engine.dispose()
        with store.engine.connect() as renewed_connection:
            renewed_dbapi_connections.append(
                renewed_connection.connection.dbapi_connection
            )
            connection_settings.append(
                (
                    renewed_connection.exec_driver_sql("PRAGMA journal_mode").scalar_one(),
                    renewed_connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one(),
                )
            )

    assert all(
        renewed is not initial
        for initial, renewed in zip(initial_dbapi_connections, renewed_dbapi_connections)
    )
    assert [str(mode).lower() for mode, _timeout in connection_settings] == ["wal", "wal"]
    assert all(int(timeout) >= 30_000 for _mode, timeout in connection_settings)


def test_platform_store_retries_transient_sqlite_lock_and_commits_once(
    monkeypatch,
    tmp_path,
):
    store = PlatformStore(str(tmp_path / "platform_state.db"))
    real_connect = store.engine.connect
    connect_attempts = []

    def transiently_locked_connect():
        connect_attempts.append(time.monotonic())
        if len(connect_attempts) <= 2:
            raise _sqlite_locked_error()
        return real_connect()

    monkeypatch.setattr(store.engine, "connect", transiently_locked_connect)

    run = store.claim_run(
        config_id=None,
        trigger_source="schedule",
        mode="smart",
        selection_type="all",
        selection_payload={},
        selected_spus=[],
    )

    assert len(connect_attempts) == 3
    assert run["status"] == "queued"
    assert [persisted["id"] for persisted in store.list_runs(limit=10)] == [run["id"]]


def test_exhausted_sqlite_lock_retry_terminalizes_related_run(
    monkeypatch,
    tmp_path,
):
    import src.api.platform_store as store_module
    import src.api.runtime as runtime_module

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    run = store.create_run(
        config_id=None,
        trigger_source="schedule",
        mode="smart",
        selection_type="all",
        selection_payload={},
        selected_spus=[],
    )
    manager = runtime_module.ForecastRuntimeManager(store=store, db_url="")
    stop_event = threading.Event()
    manager._runs[run["id"]] = stop_event
    real_connect = store.engine.connect
    locked_attempts = {"remaining": store_module.SQLITE_LOCK_RETRY_ATTEMPTS}

    def locked_for_full_operation():
        if locked_attempts["remaining"] > 0:
            locked_attempts["remaining"] -= 1
            raise _sqlite_locked_error()
        return real_connect()

    monkeypatch.setattr(store.engine, "connect", locked_for_full_operation)

    manager._execute_run(run["id"], stop_event)

    persisted = store.get_run(run["id"])
    assert locked_attempts["remaining"] == 0
    assert persisted["status"] == "failed"
    assert persisted["finished_at"] is not None
    assert "locked" in persisted["error_message"].lower()
    assert store.get_current_run() is None
    assert manager._runs == {}


def test_schedule_slot_is_unique_after_first_run_is_terminal(tmp_path):
    from src.api.platform_store import ScheduleSlotConflict

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    schedule_id = "weekly-schedule"
    schedule_slot = "2026-08-24T01:00:00Z"
    first = store.claim_run(
        config_id=None,
        trigger_source="schedule",
        mode="smart",
        selection_type="all",
        selection_payload={},
        selected_spus=[],
        schedule_id=schedule_id,
        schedule_slot=schedule_slot,
    )
    store.update_run(
        first["id"],
        status="completed",
        finished_at="2026-08-24T01:05:00Z",
    )
    count_before = len(store.list_runs(limit=10))

    with pytest.raises(ScheduleSlotConflict):
        store.claim_run(
            config_id=None,
            trigger_source="schedule",
            mode="smart",
            selection_type="all",
            selection_payload={},
            selected_spus=[],
            schedule_id=schedule_id,
            schedule_slot=schedule_slot,
        )

    persisted = store.list_runs(limit=10)
    assert count_before == 1
    assert len(persisted) == 1
    assert persisted[0]["id"] == first["id"]
    assert persisted[0]["status"] == "completed"


@pytest.mark.parametrize(
    "path",
    [
        "/api/forecast-jobs",
        "/api/analysis-status",
    ],
)
def test_read_endpoints_do_not_reconcile_or_mutate_run_state(
    isolated_app,
    monkeypatch,
    tmp_path,
    path,
):
    app_module = isolated_app
    store = PlatformStore(str(tmp_path / "platform_state.db"))
    run = store.create_run(
        config_id=None,
        trigger_source="schedule",
        mode="smart",
        selection_type="all",
        selection_payload={},
        selected_spus=["SPU001"],
    )
    store.update_run(
        run["id"],
        status="running",
        total_count=1,
        summary={
            "scope_total_spus": 1,
            "scope_eligible_spus": 1,
            "scope_excluded_spus": 0,
        },
    )
    store.add_log(run["id"], "info", "run is still active")
    with store.engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE forecast_job_run SET updated_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00Z", run["id"]),
        )

    before_tables = _business_table_snapshot(store)
    reconciliation_calls = []
    original_reconcile = app_module.manager.reconcile_stale_runs

    def tracked_reconcile(*args, **kwargs):
        reconciliation_calls.append((args, kwargs))
        return original_reconcile(*args, **kwargs)

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module.manager, "store", store)
    monkeypatch.setattr(
        app_module.manager,
        "reconcile_stale_runs",
        tracked_reconcile,
    )
    client = TestClient(app_module.app)
    response, write_statements = _get_with_write_capture(
        store,
        lambda: client.get(path),
    )

    after_tables = _business_table_snapshot(store)
    assert response.status_code == 200, response.text
    assert write_statements == []
    assert after_tables == before_tables
    assert reconciliation_calls == []


@pytest.mark.parametrize(
    ("env_value", "expected_internal_enabled"),
    [("false", False), ("true", True)],
)
def test_linux_ops_get_uses_real_collector_without_reconciliation(
    isolated_app,
    monkeypatch,
    tmp_path,
    env_value,
    expected_internal_enabled,
):
    import src.api.linux_ops as linux_ops_module

    app_module = isolated_app
    monkeypatch.setenv("FORECAST_INTERNAL_SCHEDULER_ENABLED", env_value)
    store = PlatformStore(str(tmp_path / "platform_state.db"))
    scheduled_run = store.create_run(
        config_id=None,
        trigger_source="schedule",
        mode="smart",
        selection_type="all",
        selection_payload={},
        selected_spus=["SPU001"],
    )
    store.update_run(
        scheduled_run["id"],
        status="running",
        progress=25,
        total_count=1,
    )
    store.add_log(scheduled_run["id"], "info", "scheduled run is active")
    with store.engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE forecast_job_run SET updated_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00Z", scheduled_run["id"]),
        )
    before_tables = _business_table_snapshot(store)
    reconciliation_calls = []
    original_reconcile = app_module.manager.reconcile_stale_runs
    next_run_at = "Mon 2026-08-24 01:00:00 CST"
    systemctl_calls = []

    def systemctl_reader(unit):
        systemctl_calls.append(unit)
        is_timer = unit == "forecast-weekly.timer"
        return {
            "unit": unit,
            "available": True,
            "active_state": "active" if is_timer else "inactive",
            "sub_state": "waiting" if is_timer else "dead",
            "unit_file_state": "enabled" if is_timer else "static",
            "next_elapse_realtime": next_run_at if is_timer else None,
            "last_trigger_realtime": "Mon 2026-08-17 01:00:00 CST" if is_timer else None,
            "status_text": "active / waiting" if is_timer else "inactive / dead",
        }

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module.manager, "store", store)

    def tracked_reconcile(*args, **kwargs):
        reconciliation_calls.append((args, kwargs))
        return original_reconcile(*args, **kwargs)

    monkeypatch.setattr(
        app_module.manager,
        "reconcile_stale_runs",
        tracked_reconcile,
    )
    monkeypatch.setattr(linux_ops_module, "_run_systemctl", systemctl_reader)
    monkeypatch.setattr(linux_ops_module, "tail_text_file", lambda _path, limit: [])

    client = TestClient(app_module.app)
    response, write_statements = _get_with_write_capture(
        store,
        lambda: client.get("/api/linux-ops"),
    )

    assert response.status_code == 200, response.text
    after_tables = _business_table_snapshot(store)
    assert write_statements == []
    assert after_tables == before_tables
    assert reconciliation_calls == []
    assert systemctl_calls == [unit["unit"] for unit in linux_ops_module.SYSTEMD_UNITS]
    payload = response.json()
    assert payload["scheduler_authority"] == "systemd"
    assert payload["internal_scheduler_enabled"] is expected_internal_enabled
    assert payload["last_scheduled_run"]["run_id"] == scheduled_run["id"]
    assert payload["last_scheduled_run"]["trigger_source"] == "schedule"
    assert payload["next_timer"] == {
        "unit": "forecast-weekly.timer",
        "next_run_at": next_run_at,
        "active": True,
        "enabled": True,
    }


@pytest.mark.parametrize(
    ("env_value", "expected_events"),
    [
        (None, []),
        ("false", []),
        ("true", ["start", "stop"]),
    ],
)
def test_internal_scheduler_starts_only_when_explicitly_enabled(
    isolated_app,
    monkeypatch,
    env_value,
    expected_events,
):
    app_module = isolated_app
    events = []
    if env_value is None:
        monkeypatch.delenv("FORECAST_INTERNAL_SCHEDULER_ENABLED", raising=False)
    else:
        monkeypatch.setenv("FORECAST_INTERNAL_SCHEDULER_ENABLED", env_value)

    monkeypatch.setattr(app_module.manager, "start_scheduler", lambda: events.append("start"))
    monkeypatch.setattr(app_module.manager, "stop_scheduler", lambda: events.append("stop"))

    with TestClient(app_module.app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert events == expected_events


def test_runtime_limits_spus_and_skips_result_persistence(monkeypatch, tmp_path):
    import src.api.runtime as runtime_module

    source = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-01", "2026-08-01", "2026-08-01"]),
            "spu": ["SPU001", "SPU002", "SPU003"],
            "sku": ["SKU001", "SKU002", "SKU003"],
            "sales": [10, 20, 30],
        }
    )
    processed_spus = []
    persistence_calls = []

    def process_single_spu(spu, _df_spu, **_kwargs):
        processed_spus.append(spu)
        return (
            pd.DataFrame(
                {
                    "spu": [spu],
                    "winner_algo": ["stub"],
                    "validation_wmape": [0.1],
                }
            ),
            "stub result",
            None,
            None,
        )

    monkeypatch.setattr(runtime_module, "get_data_from_db", lambda _db_url: source.copy())
    monkeypatch.setattr(runtime_module, "process_single_spu", process_single_spu)
    monkeypatch.setattr(
        runtime_module,
        "save_to_database",
        lambda *args, **kwargs: persistence_calls.append((args, kwargs)),
    )

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    manager = runtime_module.ForecastRuntimeManager(store=store, db_url="sqlite:///unused.db")
    monkeypatch.setattr(
        manager,
        "_load_all_spus_with_scope",
        lambda: (["SPU001", "SPU002", "SPU003"], 3),
    )
    run = store.create_run(
        config_id=None,
        trigger_source="schedule",
        mode="smart",
        selection_type="all",
        selection_payload={"max_spus": 1, "persist_results": False},
        selected_spus=[],
    )
    stop_event = threading.Event()
    manager._runs[run["id"]] = stop_event

    manager._execute_run(run["id"], stop_event)

    completed = store.get_run(run["id"])
    assert processed_spus == ["SPU001"]
    assert persistence_calls == []
    assert completed["status"] == "completed"
    assert completed["processed_count"] == 1
    assert [row["spu"] for row in store.get_run_spus(run["id"])] == ["SPU001"]


@pytest.mark.parametrize(
    "selection_payload",
    [{}, {"persist_results": True}],
    ids=["options-omitted", "persist-explicitly-enabled"],
)
def test_runtime_defaults_to_all_spus_and_persists_results(
    monkeypatch,
    tmp_path,
    selection_payload,
):
    import src.api.runtime as runtime_module

    source = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-01", "2026-08-01", "2026-08-01"]),
            "spu": ["SPU001", "SPU002", "SPU003"],
            "sku": ["SKU001", "SKU002", "SKU003"],
            "sales": [10, 20, 30],
        }
    )
    processed_spus = []
    persistence_calls = []

    def process_single_spu(spu, _df_spu, **_kwargs):
        processed_spus.append(spu)
        return (
            pd.DataFrame(
                {
                    "spu": [spu],
                    "winner_algo": ["stub"],
                    "validation_wmape": [0.1],
                }
            ),
            "stub result",
            None,
            None,
        )

    monkeypatch.setattr(runtime_module, "get_data_from_db", lambda _db_url: source.copy())
    monkeypatch.setattr(runtime_module, "process_single_spu", process_single_spu)
    monkeypatch.setattr(
        runtime_module,
        "save_to_database",
        lambda *args, **kwargs: persistence_calls.append((args, kwargs)),
    )

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    manager = runtime_module.ForecastRuntimeManager(store=store, db_url="sqlite:///unused.db")
    monkeypatch.setattr(
        manager,
        "_load_all_spus_with_scope",
        lambda: (["SPU001", "SPU002", "SPU003"], 3),
    )
    run = store.create_run(
        config_id=None,
        trigger_source="schedule",
        mode="smart",
        selection_type="all",
        selection_payload=selection_payload,
        selected_spus=[],
    )
    stop_event = threading.Event()
    manager._runs[run["id"]] = stop_event

    manager._execute_run(run["id"], stop_event)

    completed = store.get_run(run["id"])
    assert processed_spus == ["SPU001", "SPU002", "SPU003"]
    assert len(persistence_calls) == 1
    assert completed["status"] == "completed"
    assert completed["processed_count"] == 3


def test_worker_baseexception_terminalizes_run_and_releases_execution_lock(
    monkeypatch,
    tmp_path,
):
    import src.api.runtime as runtime_module

    class WorkerCatastrophe(BaseException):
        pass

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    lock_path = tmp_path / "forecast-execution.lock"
    manager = runtime_module.ForecastRuntimeManager(
        store=store,
        db_url="",
        execution_lock_path=str(lock_path),
    )

    def raise_worker_catastrophe(_selection_type, _payload):
        raise WorkerCatastrophe("injected worker BaseException")

    monkeypatch.setattr(manager, "resolve_selection", raise_worker_catastrophe)

    run = manager.create_run(
        mode="smart",
        selection_type="all",
        selection_payload={},
        trigger_source="schedule",
    )
    persisted = _wait_for_terminal_run(store, run["id"])

    assert persisted["status"] == "failed"
    assert persisted["finished_at"] is not None
    assert "injected worker BaseException" in persisted["error_message"]
    assert store.get_current_run() is None
    _assert_lock_reacquirable(lock_path)


def test_single_spu_timeout_leaves_no_active_run_and_releases_lock(
    monkeypatch,
    tmp_path,
):
    import src.api.runtime as runtime_module
    from src.api.run_lock import RunLock

    source = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-01"]),
            "spu": ["SPU-TIMEOUT"],
            "sku": ["SKU-TIMEOUT"],
            "sales": [1],
        }
    )
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()
    worker_threads = []
    persistence_calls = []

    def blocking_spu_worker(spu, _df_spu, log_fn=None, **_kwargs):
        worker_threads.append(threading.current_thread())
        worker_started.set()
        if not release_worker.wait(timeout=5):
            raise TimeoutError("test did not release the blocked SPU worker")
        if log_fn is not None:
            log_fn("late worker callback after timeout")
        worker_finished.set()
        return (
            pd.DataFrame(
                {
                    "spu": [spu],
                    "winner_algo": ["late-result"],
                    "validation_wmape": [0.1],
                }
            ),
            "late result that must not be persisted",
            None,
            None,
        )

    real_max = max

    def timeout_aware_max(*values):
        # Keep the production worker and join path real while shortening only
        # the hard 60-second timeout floor for this durability test.
        if values == (1, 60):
            return 0.05
        return real_max(*values)

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    lock_path = tmp_path / "forecast-execution.lock"
    manager = runtime_module.ForecastRuntimeManager(store=store, db_url="")
    monkeypatch.setattr(
        manager,
        "_resolve_selection_with_heartbeat",
        lambda *_args, **_kwargs: {
            "selection_type": "all",
            "selection_payload": {},
            "selected_spus": ["SPU-TIMEOUT"],
            "count": 1,
            "scope_total_spus": 1,
            "scope_eligible_spus": 1,
            "scope_excluded_spus": 0,
        },
    )
    monkeypatch.setattr(
        manager,
        "_load_source_data_with_heartbeat",
        lambda _run_id: source.copy(),
    )
    monkeypatch.setattr(runtime_module, "DEFAULT_SPU_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(runtime_module, "max", timeout_aware_max, raising=False)
    monkeypatch.setattr(runtime_module, "process_single_spu", blocking_spu_worker)
    monkeypatch.setattr(
        runtime_module,
        "save_to_database",
        lambda *args, **kwargs: persistence_calls.append((args, kwargs)),
    )
    run = store.create_run(
        config_id=None,
        trigger_source="schedule",
        mode="smart",
        selection_type="all",
        selection_payload={"persist_results": False},
        selected_spus=[],
    )
    stop_event = threading.Event()
    manager._runs[run["id"]] = stop_event
    lease = RunLock(str(lock_path))
    lease.acquire()
    persisted = None
    spu_rows = None
    tables_before_worker_release = None
    persistence_before_worker_release = None

    try:
        manager._execute_run(run["id"], stop_event, lease)
        assert worker_started.is_set()
        persisted = store.get_run(run["id"])
        spu_rows = store.get_run_spus(run["id"])
        tables_before_worker_release = _business_table_snapshot(store)
        persistence_before_worker_release = list(persistence_calls)
        _assert_lock_reacquirable(lock_path)
    finally:
        release_worker.set()
        for worker_thread in worker_threads:
            worker_thread.join(timeout=2)

    assert worker_finished.is_set()
    assert worker_threads and all(not thread.is_alive() for thread in worker_threads)
    assert persisted is not None and spu_rows is not None
    assert tables_before_worker_release is not None
    assert persisted["status"] == "completed"
    assert persisted["processed_count"] == 1
    assert persisted["success_count"] == 0
    assert spu_rows[0]["status"] == "failed"
    assert "timeout" in spu_rows[0]["message"].lower()
    assert store.get_current_run() is None
    assert manager._runs == {}
    assert _business_table_snapshot(store) == tables_before_worker_release
    assert persistence_calls == persistence_before_worker_release == []


@pytest.mark.parametrize(
    ("extra_args", "expected_max_spus", "expected_persist_results"),
    [
        (["--max-spus", "1", "--no-persist-results"], 1, False),
        ([], None, True),
    ],
    ids=["sample-without-persistence", "default-persists"],
)
def test_cli_forwards_runtime_options_with_a_real_lock_path(
    monkeypatch,
    tmp_path,
    extra_args,
    expected_max_spus,
    expected_persist_results,
):
    import scripts.run_forecast_job as cli_module

    captured = {}

    class FakeStore:
        def __init__(self, _db_path):
            pass

        def get_current_run(self):
            return None

        def get_run(self, run_id):
            return {
                "id": run_id,
                "status": "completed",
                "progress": 100,
                "processed_count": 1,
                "total_count": 1,
                "error_message": None,
            }

    class FakeManager:
        def __init__(self, store, db_url):
            captured["store"] = store
            captured["db_url"] = db_url

        def create_run(self, **kwargs):
            captured["create_run"] = kwargs
            return {"id": "run-cli-test"}

    monkeypatch.setattr(cli_module, "PlatformStore", FakeStore)
    monkeypatch.setattr(cli_module, "ForecastRuntimeManager", FakeManager)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_forecast_job.py",
            "--platform-db",
            str(tmp_path / "platform_state.db"),
            "--db-url",
            _sqlite_url(tmp_path / "source.db"),
            "--lock-file",
            str(tmp_path / "forecast-weekly.lock"),
            *extra_args,
        ],
    )

    assert cli_module.main() == 0
    payload = captured["create_run"]["selection_payload"]
    assert payload.get("max_spus") == expected_max_spus
    assert payload["persist_results"] is expected_persist_results


def test_cli_busy_run_lock_skips_all_creation_paths(monkeypatch, tmp_path):
    import scripts.run_forecast_job as cli_module
    from src.api.run_lock import RunLock

    db_path = str(tmp_path / "platform_state.db")
    lock_path = str(tmp_path / "forecast-weekly.lock")
    verification_store = PlatformStore(db_path)
    forbidden_calls = []
    lock_attempts = []

    class SpyRunLock:
        def __init__(self, path):
            lock_attempts.append(path)
            self.delegate = RunLock(path)

        def __enter__(self):
            return self.delegate.__enter__()

        def __exit__(self, exc_type, exc_value, traceback):
            return self.delegate.__exit__(exc_type, exc_value, traceback)

    def forbidden_store(*args, **kwargs):
        forbidden_calls.append(("store", args, kwargs))
        raise AssertionError("CLI must not create a store while the shared run lock is busy")

    def forbidden_manager(*args, **kwargs):
        forbidden_calls.append(("manager", args, kwargs))
        raise AssertionError("CLI must not create a manager while the shared run lock is busy")

    monkeypatch.setattr(cli_module, "RunLock", SpyRunLock)
    monkeypatch.setattr(cli_module, "PlatformStore", forbidden_store)
    monkeypatch.setattr(cli_module, "ForecastRuntimeManager", forbidden_manager)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_forecast_job.py",
            "--platform-db",
            db_path,
            "--db-url",
            _sqlite_url(tmp_path / "source.db"),
            "--lock-file",
            lock_path,
        ],
    )

    with RunLock(lock_path):
        result = cli_module.main()

    assert result == 0
    assert lock_attempts == [lock_path]
    assert forbidden_calls == []
    assert verification_store.list_runs(limit=10) == []


def test_cli_is_rejected_by_a_lock_held_in_another_process(tmp_path):
    db_path = str(tmp_path / "platform_state.db")
    source_db_url = _sqlite_url(tmp_path / "source.db")
    lock_path = str(tmp_path / "forecast-weekly.lock")
    ready_path = tmp_path / "holder.ready"
    verification_store = PlatformStore(db_path)
    holder_code = """
import sys
from pathlib import Path

from src.api.run_lock import RunLock

with RunLock(sys.argv[1]):
    Path(sys.argv[2]).write_text("locked", encoding="utf-8")
    sys.stdin.readline()
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, lock_path, str(ready_path)],
        cwd=str(PROJECT_ROOT),
        env=_subprocess_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists() and time.monotonic() < deadline:
            if holder.poll() is not None:
                break
            time.sleep(0.05)
        if not ready_path.exists():
            stderr = holder.stderr.read() if holder.poll() is not None else ""
            pytest.fail(f"lock holder did not become ready: {stderr}")

        contender = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "run_forecast_job.py"),
                "--platform-db",
                db_path,
                "--db-url",
                source_db_url,
                "--lock-file",
                lock_path,
                "--poll-interval",
                "0.01",
            ],
            cwd=str(PROJECT_ROOT),
            env=_subprocess_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )

        combined_output = f"{contender.stdout}\n{contender.stderr}"
        assert contender.returncode == 0, combined_output
        assert "SKIP=" in combined_output
        assert "lock" in combined_output.lower() and "busy" in combined_output.lower()
        verification_store.engine.dispose()
        assert PlatformStore(db_path).list_runs(limit=10) == []
    finally:
        if holder.stdin is not None:
            try:
                if holder.poll() is None:
                    holder.stdin.write("\n")
                    holder.stdin.flush()
                holder.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        try:
            holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait(timeout=5)


def test_cli_sigterm_after_claim_commit_before_create_return_terminalizes_once(tmp_path):
    from src.api.run_lock import RunLock

    db_path = tmp_path / "platform_state.db"
    lock_path = tmp_path / "forecast-execution.lock"
    committed_path = tmp_path / "claim-committed.ready"
    child_code = r'''
import signal
import sys
import time
from pathlib import Path

import scripts.run_forecast_job as cli
from src.api.platform_store import PlatformStore
from src.api.runtime import ForecastRuntimeManager


db_path, lock_path, committed_path = sys.argv[1:4]
signal_state = None
original_run_while_locked = cli._run_while_locked


def capture_signal_state(args, state):
    global signal_state
    signal_state = state
    return original_run_while_locked(args, state)


class CommitBarrierStore(PlatformStore):
    def claim_run(self, **kwargs):
        run = super().claim_run(**kwargs)
        Path(committed_path).write_text(run["id"], encoding="utf-8")
        if signal_state.get("run_ready"):
            raise AssertionError("run became ready before claim_run returned")
        signal.raise_signal(signal.SIGTERM)
        if signal_state.get("signum") != int(signal.SIGTERM):
            raise AssertionError("SIGTERM handler did not record the pending signal")
        return run


def blocked_selection_scope(self):
    deadline = time.monotonic() + 10
    while self.store.get_current_run() is not None and time.monotonic() < deadline:
        time.sleep(0.005)
    if self.store.get_current_run() is not None:
        raise TimeoutError("CLI did not terminalize the pending-signal run")
    return [], 0


cli.PlatformStore = CommitBarrierStore
cli._run_while_locked = capture_signal_state
ForecastRuntimeManager._load_all_spus_with_scope = blocked_selection_scope
sys.argv = [
    "run_forecast_job.py",
    "--platform-db", db_path,
    "--db-url", "sqlite:///unused.db",
    "--lock-file", lock_path,
    "--poll-interval", "0.01",
]
sys.exit(cli.main())
'''
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            child_code,
            str(db_path),
            str(lock_path),
            str(committed_path),
        ],
        cwd=str(PROJECT_ROOT),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    combined_output = f"{result.stdout}\n{result.stderr}"
    committed_run_id = committed_path.read_text(encoding="utf-8")
    verification_store = PlatformStore(str(db_path))
    runs = verification_store.list_runs(limit=10)
    assert result.returncode == 128 + signal.SIGTERM, combined_output
    assert "SIGNAL=SIGTERM ACTION=pending" in combined_output
    assert "TERMINAL_WRITE=confirmed" in combined_output
    assert combined_output.index("LOCK=acquired") < combined_output.index(
        "TERMINAL_WRITE=confirmed"
    ) < combined_output.index("LOCK=released")
    assert len(runs) == 1
    assert runs[0]["id"] == committed_run_id
    assert runs[0]["status"] == "failed"
    assert runs[0]["finished_at"] is not None
    assert "SIGTERM" in runs[0]["error_message"]
    assert verification_store.get_current_run() is None
    with RunLock(str(lock_path)):
        pass


def test_cli_late_sigterm_after_database_completion_exits_zero_without_rewrite(tmp_path):
    from src.api.run_lock import RunLock

    db_path = tmp_path / "platform_state.db"
    lock_path = tmp_path / "forecast-execution.lock"
    completed_path = tmp_path / "completed-before-observation.ready"
    signal_request_path = tmp_path / "send-sigterm.request"
    signal_emitted_path = tmp_path / "sigterm-emitted.ready"
    child_code = r'''
import json
import signal
import sys
import threading
import time
from pathlib import Path

import pandas as pd

import scripts.run_forecast_job as cli
from src.api.platform_store import PlatformStore
from src.api.runtime import ForecastRuntimeManager


db_path, lock_path, completed_path, signal_request_path, signal_emitted_path = sys.argv[1:6]
signal_state = None
completed_gate_used = False
original_run_while_locked = cli._run_while_locked


def capture_signal_state(args, state):
    global signal_state
    signal_state = state
    return original_run_while_locked(args, state)


class CompletionObservationGateStore(PlatformStore):
    def get_run(self, run_id):
        global completed_gate_used
        run = super().get_run(run_id)
        if (
            run
            and run.get("status") == "completed"
            and threading.current_thread() is threading.main_thread()
            and not completed_gate_used
        ):
            completed_gate_used = True
            Path(completed_path).write_text(
                json.dumps(
                    {
                        "id": run["id"],
                        "status": run["status"],
                        "finished_at": run["finished_at"],
                        "updated_at": run["updated_at"],
                        "error_message": run["error_message"],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            deadline = time.monotonic() + 10
            while signal_state.get("signum") is None and time.monotonic() < deadline:
                time.sleep(0.005)
            if signal_state.get("signum") is None:
                raise TimeoutError("SIGTERM was not observed at completed-run gate")
        return run


def empty_selection_scope(self):
    return [], 0


def nonempty_source(self, _run_id):
    return pd.DataFrame(
        {"date": ["2026-08-01"], "spu": ["UNSELECTED"], "sku": ["SKU"], "sales": [1]}
    )


def emit_sigterm_on_request():
    deadline = time.monotonic() + 10
    request = Path(signal_request_path)
    while not request.exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    if not request.exists():
        return
    Path(signal_emitted_path).write_text("SIGTERM", encoding="utf-8")
    signal.raise_signal(signal.SIGTERM)


cli.PlatformStore = CompletionObservationGateStore
cli._run_while_locked = capture_signal_state
ForecastRuntimeManager._load_all_spus_with_scope = empty_selection_scope
ForecastRuntimeManager._load_source_data_with_heartbeat = nonempty_source
threading.Thread(target=emit_sigterm_on_request, daemon=True).start()
sys.argv = [
    "run_forecast_job.py",
    "--platform-db", db_path,
    "--db-url", "sqlite:///unused.db",
    "--lock-file", lock_path,
    "--poll-interval", "0.01",
]
sys.exit(cli.main())
'''
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child_code,
            str(db_path),
            str(lock_path),
            str(completed_path),
            str(signal_request_path),
            str(signal_emitted_path),
        ],
        cwd=str(PROJECT_ROOT),
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        _wait_for_child_barrier(process, completed_path)
        before_signal = json.loads(completed_path.read_text(encoding="utf-8"))
        assert before_signal["status"] == "completed"
        signal_request_path.write_text("send", encoding="utf-8")
        stdout, stderr = process.communicate(timeout=15)
    finally:
        _terminate_child(process)

    combined_output = f"{stdout}\n{stderr}"
    verification_store = PlatformStore(str(db_path))
    runs = verification_store.list_runs(limit=10)
    assert signal_emitted_path.read_text(encoding="utf-8") == "SIGTERM"
    assert process.returncode == 0, combined_output
    assert "SIGNAL=SIGTERM ACTION=terminalize" in combined_output
    assert "SIGNAL=SIGTERM ACTION=run-already-completed" in combined_output
    assert "TERMINAL_WRITE=confirmed" not in combined_output
    assert len(runs) == 1
    after_signal = runs[0]
    assert {
        key: after_signal[key]
        for key in ("id", "status", "finished_at", "updated_at", "error_message")
    } == before_signal
    assert verification_store.get_current_run() is None
    with RunLock(str(lock_path)):
        pass


def test_recovery_online_backup_integrity_and_orphan_audit(tmp_path):
    db_path = tmp_path / "platform_state.db"
    backup_path = tmp_path / "platform_state.backup.db"
    lock_path = tmp_path / "forecast-execution.lock"
    reason = "automated recovery closed test orphan"
    store = PlatformStore(str(db_path))
    orphan = store.create_run(
        config_id=None,
        trigger_source="schedule",
        mode="smart",
        selection_type="all",
        selection_payload={},
        selected_spus=[],
    )
    store.update_run(orphan["id"], status="running", started_at="2026-08-21T01:00:00Z")
    store.engine.dispose()

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "recover_forecast_state.py"),
            "--platform-db",
            str(db_path),
            "--backup-path",
            str(backup_path),
            "--lock-file",
            str(lock_path),
            "--reason",
            reason,
        ],
        cwd=str(PROJECT_ROOT),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    summary = json.loads(result.stdout.strip())
    recovered_store = PlatformStore(str(db_path))
    recovered = recovered_store.get_run(orphan["id"])
    logs = recovered_store.get_logs(orphan["id"], limit=20)
    with sqlite3.connect(str(db_path)) as source_connection:
        source_integrity = source_connection.execute("PRAGMA integrity_check").fetchone()[0]
    with sqlite3.connect(str(backup_path)) as backup_connection:
        backup_integrity = backup_connection.execute("PRAGMA integrity_check").fetchone()[0]

    assert summary["source_integrity_before"] == "ok"
    assert summary["source_integrity_after"] == "ok"
    assert summary["backup_integrity"] == "ok"
    assert summary["active_runs_before"] == 1
    assert summary["active_runs_closed"] == 1
    assert summary["active_runs_after"] == 0
    assert source_integrity == "ok"
    assert backup_integrity == "ok"
    assert recovered["status"] == "failed"
    assert recovered["finished_at"] is not None
    assert recovered_store.get_current_run() is None
    assert any(log["message"] == reason for log in logs)


def test_recovery_backup_failure_leaves_no_final_or_temporary_file(
    monkeypatch,
    tmp_path,
):
    import scripts.recover_forecast_state as recovery_module

    source_path = tmp_path / "platform_state.db"
    backup_path = tmp_path / "platform_state.backup.db"
    store = PlatformStore(str(source_path))
    store.engine.dispose()
    original_source_connection = recovery_module._source_connection

    class FailingBackupConnection:
        def __init__(self, delegate):
            self.delegate = delegate

        def execute(self, *args, **kwargs):
            return self.delegate.execute(*args, **kwargs)

        def backup(self, _target):
            raise sqlite3.OperationalError("injected online backup failure")

        def close(self):
            self.delegate.close()

    monkeypatch.setattr(
        recovery_module,
        "_source_connection",
        lambda path: FailingBackupConnection(original_source_connection(path)),
    )

    with pytest.raises(sqlite3.OperationalError, match="injected online backup failure"):
        recovery_module._online_backup(source_path, backup_path)

    assert not backup_path.exists()
    assert list(tmp_path.glob(f".{backup_path.name}.*.tmp")) == []

    monkeypatch.setattr(
        recovery_module,
        "_source_connection",
        original_source_connection,
    )
    assert recovery_module._online_backup(source_path, backup_path) == ("ok", "ok")
    assert backup_path.is_file()
    assert list(tmp_path.glob(f".{backup_path.name}.*.tmp")) == []


@pytest.mark.parametrize(
    "publish_failure",
    ["link-error", "preexisting-target", "racing-target"],
)
def test_recovery_backup_publish_failure_never_overwrites_or_leaves_temp(
    monkeypatch,
    tmp_path,
    publish_failure,
):
    import scripts.recover_forecast_state as recovery_module

    source_path = tmp_path / "platform_state.db"
    backup_path = tmp_path / "platform_state.backup.db"
    store = PlatformStore(str(source_path))
    store.engine.dispose()
    original_link = recovery_module.os.link
    competing_content = b"existing backup owned by another process"

    if publish_failure == "link-error":

        def fail_link(_temporary_path, _backup_path):
            raise OSError("injected os.link publication failure")

        monkeypatch.setattr(recovery_module.os, "link", fail_link)
        expected_exception = OSError
        expected_message = "injected os.link publication failure"
    elif publish_failure == "preexisting-target":
        backup_path.write_bytes(competing_content)
        expected_exception = FileExistsError
        expected_message = None
    else:

        def racing_link(temporary_path, final_path):
            Path(final_path).write_bytes(competing_content)
            return original_link(temporary_path, final_path)

        monkeypatch.setattr(recovery_module.os, "link", racing_link)
        expected_exception = FileExistsError
        expected_message = None

    if expected_message is None:
        expectation = pytest.raises(expected_exception)
    else:
        expectation = pytest.raises(expected_exception, match=expected_message)
    with expectation:
        recovery_module._online_backup(source_path, backup_path)

    assert list(tmp_path.glob(f".{backup_path.name}.*.tmp")) == []
    if publish_failure == "link-error":
        assert not backup_path.exists()
    else:
        assert backup_path.read_bytes() == competing_content


def test_all_fastapi_create_endpoints_return_409_without_rows_when_lock_busy(
    isolated_app,
    monkeypatch,
    tmp_path,
):
    from src.api.run_lock import RunLock
    from src.api.runtime import ForecastRuntimeManager

    app_module = isolated_app
    store = PlatformStore(str(tmp_path / "platform_state.db"))
    lock_path = tmp_path / "forecast-execution.lock"
    manager = ForecastRuntimeManager(
        store=store,
        db_url="",
        execution_lock_path=str(lock_path),
    )
    config = store.create_config(
        name="busy-lock-config",
        purpose="exercise config run endpoint",
        mode="smart",
        selection_type="all",
        selection_payload={},
        is_active=True,
    )
    monkeypatch.setenv("FORECAST_INTERNAL_SCHEDULER_ENABLED", "false")
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "manager", manager)

    requests = [
        ("/api/forecast-jobs", {"mode": "smart", "selection_type": "all"}),
        (f"/api/forecast-configs/{config['id']}/run", None),
        ("/api/start-analysis", {"mode": "smart", "selection_type": "all"}),
    ]
    with RunLock(str(lock_path)):
        with TestClient(app_module.app) as client:
            responses = [
                client.post(path, json=payload) if payload is not None else client.post(path)
                for path, payload in requests
            ]

    assert [response.status_code for response in responses] == [409, 409, 409]
    assert all("lock" in response.json()["detail"].lower() for response in responses)
    assert store.list_runs(limit=10) == []


@pytest.mark.parametrize(
    ("raw_timestamp", "expected_utc"),
    [
        ("Sun 2026-08-23 01:00:00 CEST", "2026-08-22T23:00:00+00:00"),
        ("Sun 2026-08-23 01:00:00 EDT", "2026-08-23T05:00:00+00:00"),
        ("Sun 2026-08-23 01:00:00 CST", "2026-08-22T17:00:00+00:00"),
        ("Sun 2026-08-23 01:00:00 XYZ", None),
    ],
)
def test_linux_ops_systemd_timezone_abbreviation_matrix(raw_timestamp, expected_utc):
    import src.api.linux_ops as linux_ops_module

    parsed = linux_ops_module._parse_timestamp(raw_timestamp)
    assert (parsed.isoformat() if parsed is not None else None) == expected_utc


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("service-failed", "forecast-weekly.service is failed"),
        ("stale-scheduled-run", "latest completed scheduled run is older than"),
        (
            "timer-trigger-without-run",
            "forecast-weekly.timer triggered but no corresponding scheduled run exists",
        ),
    ],
)
def test_linux_ops_reports_degraded_weekly_failure_modes(
    tmp_path,
    case,
    expected_reason,
):
    import src.api.linux_ops as linux_ops_module

    store = PlatformStore(str(tmp_path / f"{case}.db"))
    captured_at = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    if case != "timer-trigger-without-run":
        scheduled_run = store.create_run(
            config_id=None,
            trigger_source="schedule",
            mode="smart",
            selection_type="all",
            selection_payload={},
            selected_spus=["SPU001"],
        )
        finished_at = (
            "2020-01-01T00:00:00Z"
            if case == "stale-scheduled-run"
            else "2026-08-21T10:00:00Z"
        )
        store.update_run(
            scheduled_run["id"],
            status="completed",
            processed_count=1,
            total_count=1,
            success_count=1,
            progress=100,
            finished_at=finished_at,
        )
        with store.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE forecast_job_run SET created_at = ?, updated_at = ? WHERE id = ?",
                (finished_at, finished_at, scheduled_run["id"]),
            )

    def systemctl_reader(unit):
        if unit == "forecast-weekly.timer":
            return {
                "unit": unit,
                "available": True,
                "active_state": "active",
                "sub_state": "waiting",
                "unit_file_state": "enabled",
                "next_elapse_realtime": "Mon 2026-08-24 01:00:00 CST",
                "last_trigger_realtime": (
                    "Fri 2026-08-21 11:00:00 UTC"
                    if case == "timer-trigger-without-run"
                    else "Fri 2026-08-21 09:00:00 UTC"
                ),
            }
        if unit == "forecast-weekly.service":
            return {
                "unit": unit,
                "available": True,
                "active_state": "failed" if case == "service-failed" else "inactive",
                "sub_state": "failed" if case == "service-failed" else "dead",
                "unit_file_state": "static",
                "result": "exit-code" if case == "service-failed" else "success",
            }
        return {
            "unit": unit,
            "available": True,
            "active_state": "active",
            "sub_state": "running",
            "unit_file_state": "enabled",
            "result": "success",
        }

    payload = linux_ops_module.collect_linux_ops_snapshot(
        store,
        now=captured_at,
        systemctl_reader=systemctl_reader,
        file_tailer=lambda _path, limit: [],
    )

    health = payload["weekly_run_health"]
    assert health["status"] == "degraded"
    assert health["healthy"] is False
    assert any(expected_reason in reason for reason in health["reasons"])


def test_api_lifespan_shutdown_cannot_miss_racing_create(
    isolated_app,
    monkeypatch,
    tmp_path,
):
    import src.api.runtime as runtime_module

    app_module = isolated_app
    store = PlatformStore(str(tmp_path / "platform_state.db"))
    manager = runtime_module.ForecastRuntimeManager(store=store, db_url="")
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "manager", manager)
    monkeypatch.setenv("FORECAST_INTERNAL_SCHEDULER_ENABLED", "false")

    claim_entered = threading.Event()
    release_claim = threading.Event()
    lifespan_entered = threading.Event()
    request_shutdown = threading.Event()
    shutdown_started = threading.Event()
    original_claim = store.claim_run
    original_shutdown = manager.shutdown_active_runs
    create_results = []
    errors = []

    class DormantJobThread:
        def __init__(self, target, args=(), daemon=False):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            pass

        def is_alive(self):
            return False

    class RuntimeThreadingProxy:
        Thread = DormantJobThread

        def __getattr__(self, name):
            return getattr(threading, name)

    def blocked_claim(*args, **kwargs):
        run = original_claim(*args, **kwargs)
        claim_entered.set()
        if not release_claim.wait(timeout=5):
            raise TimeoutError("test did not release blocked claim")
        return run

    def tracked_shutdown(*args, **kwargs):
        shutdown_started.set()
        return original_shutdown(*args, **kwargs)

    async def host_lifespan():
        async with app_module.lifespan(app_module.app):
            lifespan_entered.set()
            await asyncio.to_thread(request_shutdown.wait, 5)

    def run_lifespan():
        try:
            asyncio.run(host_lifespan())
        except BaseException as exc:
            errors.append(exc)

    def create_run():
        try:
            create_results.append(
                manager.create_run(
                    mode="smart",
                    selection_type="all",
                    selection_payload={},
                    trigger_source="manual",
                )
            )
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(store, "claim_run", blocked_claim)
    monkeypatch.setattr(manager, "shutdown_active_runs", tracked_shutdown)
    monkeypatch.setattr(runtime_module, "threading", RuntimeThreadingProxy())
    lifespan_thread = threading.Thread(target=run_lifespan)
    lifespan_thread.start()
    assert lifespan_entered.wait(timeout=5)
    create_thread = threading.Thread(target=create_run)
    create_thread.start()
    assert claim_entered.wait(timeout=5)

    request_shutdown.set()
    assert shutdown_started.wait(timeout=5)
    release_claim.set()
    create_thread.join(timeout=5)
    lifespan_thread.join(timeout=5)

    assert not create_thread.is_alive()
    assert not lifespan_thread.is_alive()
    assert errors == []
    assert len(create_results) == 1
    persisted = store.get_run(create_results[0]["id"])
    assert persisted["status"] == "failed"
    assert persisted["finished_at"] is not None
    assert store.get_current_run() is None
    assert manager._runs == {}
    assert manager._worker_threads == {}
    with pytest.raises(Exception, match="shutting down"):
        manager.create_run(
            mode="smart",
            selection_type="all",
            selection_payload={},
        )


def _read_systemd_section(path: Path, section_name: str) -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    current_section = None
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            continue
        if current_section != section_name or "=" not in line:
            continue
        key, value = line.split("=", 1)
        directives.setdefault(key.strip(), []).append(value.strip())
    return directives


@pytest.mark.parametrize(
    "command",
    [
        "prepare;flock -n /run/lock/forecast.lock /opt/app/run.py",
        "prepare &&flock -n /run/lock/forecast.lock /opt/app/run.py",
        '"/usr/bin/flock" -n /run/lock/forecast.lock /opt/app/run.py',
        "/bin/sh -c 'prepare;/usr/bin/flock -n /run/lock/forecast.lock /opt/app/run.py'",
        'sh -c "flock -n /run/lock/forecast.lock /opt/app/run.py"',
        r"C:\tools\flock.exe -n C:\locks\forecast.lock run.cmd",
    ],
)
def test_outer_flock_detector_handles_quoted_and_shell_commands(command):
    assert _contains_flock_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "/opt/app/venv/bin/python scripts/run_forecast_job.py --lock-file /tmp/job.lock",
        "/opt/app/venv/bin/python scripts/flock_guard.py",
    ],
)
def test_outer_flock_detector_uses_executable_token_boundaries(command):
    assert _contains_flock_command(command) is False


@pytest.mark.parametrize(
    ("duration", "expected_seconds"),
    [
        ("12h", Decimal("43200")),
        ("12h 0min", Decimal("43200")),
        ("1min", Decimal("60")),
        ("1us", Decimal("0.000001")),
        ("999ms", Decimal("0.999")),
        ("1s 999ms 1us", Decimal("1.999001")),
        ("0", Decimal("0")),
    ],
)
def test_systemd_duration_parser_preserves_compound_and_subsecond_values(
    duration,
    expected_seconds,
):
    assert _parse_systemd_seconds(duration) == expected_seconds


def test_weekly_systemd_units_have_unique_effective_safety_directives():
    service = _read_systemd_section(
        SYSTEMD_DIR / "forecast-weekly.service",
        "Service",
    )
    timer = _read_systemd_section(
        SYSTEMD_DIR / "forecast-weekly.timer",
        "Timer",
    )

    assert _single_systemd_value(service, "Restart").strip().lower() == "no"
    assert (
        _parse_systemd_seconds(
            _single_systemd_value(service, "TimeoutStartSec")
        )
        == Decimal("43200")
    )
    assert len(service.get("ExecStart", [])) == 1
    exec_directives = [
        value
        for key, values in service.items()
        if key.startswith("Exec")
        for value in values
    ]
    assert exec_directives
    assert all(
        len(values) == len(set(values))
        for key, values in service.items()
        if key.startswith("Exec")
    )
    assert all(not _contains_flock_command(value) for value in exec_directives)

    assert _single_systemd_value(timer, "OnCalendar") == "Mon *-*-* 01:00:00"
    assert _parse_systemd_boolean(_single_systemd_value(timer, "Persistent")) is True
    assert (
        _parse_systemd_seconds(_single_systemd_value(timer, "AccuracySec"))
        == Decimal("60")
    )
    randomized_delay_seconds = _parse_systemd_seconds(
        _single_systemd_value(timer, "RandomizedDelaySec")
    )
    assert randomized_delay_seconds == Decimal("0")
