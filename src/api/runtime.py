import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from src.api.linux_ops import compute_next_run_at
from src.api.platform_store import (
    ActiveRunConflict,
    PlatformStore,
    ScheduleSlotConflict,
    utcnow_iso,
)
from src.api.run_lock import RunLock, RunLockBusy
from src.database.repositories import query_forecast_results, save_to_database
from src.forecasting.execution_bridge import get_data_from_db, process_single_spu


VALID_MODES = {"fast", "smart", "full"}


def _safe_env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return int(default)
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        logging.getLogger(__name__).warning("Invalid integer env %s=%r, fallback to %s.", name, raw, default)
        return int(default)


DEFAULT_SCOPE_MIN_WEEKS = _safe_env_int("SCOPE_MIN_WEEKS", 108)
DEFAULT_SCOPE_RECENT_WEEKS = 4
DEFAULT_SCOPE_RECENT_NON_ZERO_WEEKS = 8
DEFAULT_SCOPE_RECENT_WINDOW_WEEKS = 12
DEFAULT_SCOPE_MAX_ZERO_RATIO_26W = 0.25
DEFAULT_SCOPE_MIN_RECENT4_TOTAL_SALES = 4.0
ACTIVE_RUN_STATUSES = {"queued", "running", "stopping"}
SCHEDULER_POLL_SECONDS = 30
SCHEDULER_RECOVERY_WAIT_SECONDS = 5
DEFAULT_SPU_TIMEOUT_SECONDS = int(os.getenv("SPU_EXEC_TIMEOUT_SECONDS", "1800"))
ACTIVE_RUN_STALE_MINUTES = int(os.getenv("ACTIVE_RUN_STALE_MINUTES", "90"))

logger = logging.getLogger(__name__)
_NATIVE_THREAD_TYPE = threading.Thread


def normalize_spu_values(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip()
    return normalized[(normalized != "") & (normalized != "-")]


def _latest_active_week_buckets(weekly_sales: pd.DataFrame, count: int) -> List[pd.Timestamp]:
    weekly_totals = weekly_sales.groupby("week_bucket")["sales"].sum().sort_index()
    active_buckets = weekly_totals[weekly_totals > 0].index.tolist()
    return active_buckets[-count:]


class ForecastRuntimeManager:
    def __init__(
        self,
        store: PlatformStore,
        db_url: str,
        execution_lock_path: Optional[str] = None,
    ):
        self.store = store
        self.db_url = db_url
        self.execution_lock_path = execution_lock_path
        self._runs: Dict[str, threading.Event] = {}
        self._worker_threads: Dict[str, threading.Thread] = {}
        self._lifecycle_guard = threading.RLock()
        self._accepting_runs = True
        self._scheduler_stop = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None
        self._scheduler_seen_keys: set[str] = set()
        self._schedule_run_lock = threading.Lock()

    def start_scheduler(self) -> None:
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        if self._scheduler_thread and not self._scheduler_thread.is_alive():
            logger.warning("Scheduler thread was not alive; restarting a fresh scheduler loop.")
        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        logger.info("Forecast scheduler loop started.")

    def stop_scheduler(self) -> None:
        self._scheduler_stop.set()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=5)
            if self._scheduler_thread.is_alive():
                logger.warning("Scheduler loop did not stop within timeout.")

    def _append_log_with_retries(
        self,
        run_id: str,
        level: str,
        message: str,
        attempts: int = 3,
    ) -> None:
        last_error: Optional[BaseException] = None
        for attempt in range(max(attempts, 1)):
            try:
                self.store.add_log(run_id, level, message)
                return
            except BaseException as exc:
                last_error = exc
                if attempt + 1 < max(attempts, 1):
                    time.sleep(0.1 * (attempt + 1))
        raise RuntimeError(f"Failed to persist lifecycle audit for run {run_id}") from last_error

    def _terminalize_owned_run(
        self,
        run_id: str,
        reason: str,
        attempts: int = 3,
        audit_if_terminal: bool = True,
    ) -> Dict[str, Any]:
        last_error: Optional[BaseException] = None
        updated_to_failed = False
        current: Optional[Dict[str, Any]] = None
        for attempt in range(max(attempts, 1)):
            try:
                with self._lifecycle_guard:
                    current = self.store.get_run(run_id)
                    if current is None:
                        return {}
                    if current.get("status") in ACTIVE_RUN_STATUSES:
                        self.store.update_run(
                            run_id,
                            status="failed",
                            error_message=reason,
                            finished_at=utcnow_iso(),
                        )
                        updated_to_failed = True
                    current = self.store.get_run(run_id)
                    if current and current.get("status") in ACTIVE_RUN_STATUSES:
                        raise RuntimeError(
                            f"Run {run_id} remained active after terminal write: {current.get('status')}"
                        )
                break
            except BaseException as exc:
                last_error = exc
                if attempt + 1 < max(attempts, 1):
                    time.sleep(0.1 * (attempt + 1))
        else:
            raise RuntimeError(f"Failed to terminalize run {run_id}") from last_error

        if updated_to_failed or audit_if_terminal:
            self._append_log_with_retries(run_id, "error", reason, attempts=attempts)
        return current or {}

    def shutdown_active_runs(
        self,
        reason: str,
        join_timeout: float = 5.0,
    ) -> List[Dict[str, Any]]:
        """Stop and terminalize only worker runs owned by this manager."""
        with self._lifecycle_guard:
            self._accepting_runs = False
            owned = list(self._runs.items())
            threads = dict(self._worker_threads)

        for _run_id, stop_event in owned:
            stop_event.set()

        deadline = time.monotonic() + max(float(join_timeout), 0.0)
        current_thread = threading.current_thread()
        for run_id, _stop_event in owned:
            worker = threads.get(run_id)
            if worker is None or worker is current_thread or not worker.is_alive():
                continue
            remaining = max(deadline - time.monotonic(), 0.0)
            if remaining <= 0:
                break
            worker.join(timeout=remaining)

        terminal_runs: List[Dict[str, Any]] = []
        for run_id, _stop_event in owned:
            with self._lifecycle_guard:
                current = self.store.get_run(run_id)
            if current and current.get("status") in ACTIVE_RUN_STATUSES:
                current = self._terminalize_owned_run(
                    run_id,
                    reason,
                    attempts=3,
                    audit_if_terminal=True,
                )
            elif current:
                self._append_log_with_retries(run_id, "warning", reason, attempts=3)
            if current and current.get("status") in ACTIVE_RUN_STATUSES:
                raise RuntimeError(
                    f"Local run {run_id} is still active after shutdown: {current.get('status')}"
                )
            if current:
                terminal_runs.append(current)

        with self._lifecycle_guard:
            for run_id, _stop_event in owned:
                self._runs.pop(run_id, None)
                self._worker_threads.pop(run_id, None)
        return terminal_runs

    def resolve_selection(self, selection_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        selection_type = (selection_type or "").lower()
        if selection_type != "all":
            raise ValueError("Only the standard all selection workflow is supported in the engineering workflow.")
        if selection_type == "all":
            all_spus, total_spus = self._load_all_spus_with_scope()
            selection_payload = dict(payload or {})
            max_spus = selection_payload.get("max_spus")
            if max_spus is not None:
                try:
                    max_spus = int(max_spus)
                except (TypeError, ValueError) as exc:
                    raise ValueError("max_spus must be a non-negative integer or null") from exc
                if max_spus < 0:
                    raise ValueError("max_spus must be a non-negative integer or null")
            selected_spus = all_spus if max_spus is None else all_spus[:max_spus]
            return {
                "selection_type": "all",
                "selection_payload": selection_payload,
                "selected_spus": selected_spus,
                "count": len(selected_spus),
                "invalid_items": [],
                "preview": selected_spus[:50],
                "scope_total_spus": total_spus,
                "scope_eligible_spus": len(all_spus),
                "scope_excluded_spus": max(total_spus - len(all_spus), 0),
            }
        raise ValueError(f"Unsupported selection type: {selection_type}")

    def create_run(
        self,
        mode: str,
        selection_type: str,
        selection_payload: Dict[str, Any],
        config_id: Optional[str] = None,
        trigger_source: str = "manual",
        schedule_id: Optional[str] = None,
        schedule_slot: Optional[str] = None,
    ) -> Dict[str, Any]:
        if mode not in VALID_MODES:
            raise ValueError("mode must be one of fast, smart, full")
        with self._lifecycle_guard:
            if not self._accepting_runs:
                raise ActiveRunConflict("Forecast runtime is shutting down and rejects new runs.")

        lock_lease: Optional[RunLock] = None
        if self.execution_lock_path:
            lock_lease = RunLock(self.execution_lock_path)
            try:
                lock_lease.acquire()
            except RunLockBusy as exc:
                raise ActiveRunConflict(
                    f"Another forecast execution holds the run lock: {self.execution_lock_path}"
                ) from exc

        run_id = uuid.uuid4().hex
        run: Optional[Dict[str, Any]] = None
        stop_event: Optional[threading.Event] = None
        thread: Optional[threading.Thread] = None
        worker_owns_lease = False
        try:
            with self._lifecycle_guard:
                if not self._accepting_runs:
                    raise ActiveRunConflict("Forecast runtime is shutting down and rejects new runs.")
                run = self.store.claim_run(
                    config_id=config_id,
                    trigger_source=trigger_source,
                    mode=mode,
                    selection_type=(selection_type or "").lower(),
                    selection_payload=dict(selection_payload or {}),
                    selected_spus=[],
                    schedule_id=schedule_id,
                    schedule_slot=schedule_slot,
                    run_id=run_id,
                )
                stop_event = threading.Event()
                self.store.update_run(run_id, current_spu="等待启动")
                self._append_log(
                    run_id,
                    "info",
                    f"Run {run_id} accepted and queued in {mode} mode.",
                )
                run["current_spu"] = "等待启动"
                thread = threading.Thread(
                    target=self._execute_run,
                    args=(run_id, stop_event, lock_lease),
                    daemon=True,
                )
                self._runs[run_id] = stop_event
                self._worker_threads[run_id] = thread
                thread.start()
                worker_owns_lease = isinstance(thread, _NATIVE_THREAD_TYPE)
                if lock_lease is not None and not worker_owns_lease:
                    # Test doubles that do not execute their target cannot own
                    # a lease. Real workers release it in _execute_run.finally.
                    lock_lease.release()
                    lock_lease = None
                    self._worker_threads.pop(run_id, None)
            return run
        except BaseException as exc:
            if (
                lock_lease is not None
                and thread is not None
                and isinstance(thread, _NATIVE_THREAD_TYPE)
                and thread.ident is not None
            ):
                worker_owns_lease = True
            if stop_event is not None:
                stop_event.set()
            committed_run = run or self.store.get_run(run_id)
            if committed_run is not None:
                self._mark_run_failed_until_persisted(run_id, exc)
            if not worker_owns_lease:
                with self._lifecycle_guard:
                    self._runs.pop(run_id, None)
                    self._worker_threads.pop(run_id, None)
            if lock_lease is not None and not worker_owns_lease:
                lock_lease.release()
            raise

    def _mark_run_failed(self, run_id: str, exc: BaseException) -> None:
        message = str(exc) or exc.__class__.__name__
        try:
            self._terminalize_owned_run(
                run_id,
                message,
                attempts=3,
                audit_if_terminal=True,
            )
        except BaseException:
            logger.exception("Failed to persist terminal state for run %s.", run_id)
            raise

    def _mark_run_failed_until_persisted(self, run_id: str, exc: BaseException) -> None:
        attempt = 0
        while True:
            attempt += 1
            try:
                self._mark_run_failed(run_id, exc)
                return
            except BaseException:
                logger.error(
                    "Run %s terminal write is still failing (attempt %s); execution lock remains held.",
                    run_id,
                    attempt,
                )
                time.sleep(min(0.5 * attempt, 5.0))

    def _finish_stopped_if_requested(
        self,
        run_id: str,
        stop_event: threading.Event,
        message: str,
    ) -> bool:
        if not stop_event.is_set():
            return False
        should_log = False
        with self._lifecycle_guard:
            current = self.store.get_run(run_id)
            if current and current.get("status") in ACTIVE_RUN_STATUSES:
                self.store.update_run(
                    run_id,
                    status="stopped",
                    finished_at=utcnow_iso(),
                )
                should_log = True
        if should_log:
            self._append_log_with_retries(run_id, "warning", message, attempts=3)
        return True

    def stop_run(self, run_id: str) -> Dict[str, Any]:
        with self._lifecycle_guard:
            stop_event = self._runs.get(run_id)
            run = self.store.get_run(run_id)
            if not run:
                raise ValueError("Run not found.")
            if run.get("status") in ACTIVE_RUN_STATUSES:
                if not stop_event:
                    raise ActiveRunConflict(
                        "Run is owned by another process; acquire the execution lock "
                        "and use explicit recovery.",
                        active_run=run,
                    )
                stop_event.set()
                self.store.update_run(run_id, status="stopping")
                self.store.add_log(run_id, "warning", "Stop requested by user.")
                run = self.store.get_run(run_id) or run
        return run

    def _owns_execution_lock(self, run_lock: Optional[RunLock]) -> bool:
        if (
            not isinstance(run_lock, RunLock)
            or not run_lock.is_held
            or not self.execution_lock_path
        ):
            return False
        expected_path = os.path.normcase(
            os.path.abspath(os.fspath(self.execution_lock_path))
        )
        return os.path.normcase(run_lock.path) == expected_path

    def reconcile_stale_runs(
        self,
        run_lock: Optional[RunLock] = None,
        limit: int = 200,
    ) -> int:
        """Close stale runs only while the matching execution lease is held."""
        if not self._owns_execution_lock(run_lock):
            return 0
        now_utc = datetime.now(timezone.utc)
        stale_count = 0
        stale_after = timedelta(minutes=max(ACTIVE_RUN_STALE_MINUTES, 10))
        for run in self.store.list_runs(limit=max(limit, 1)):
            status = str(run.get("status") or "").lower()
            if status not in ACTIVE_RUN_STATUSES:
                continue
            ref = (
                self._parse_iso_utc(run.get("updated_at"))
                or self._parse_iso_utc(run.get("started_at"))
                or self._parse_iso_utc(run.get("created_at"))
            )
            if ref is None:
                continue
            if now_utc - ref < stale_after:
                continue
            if not self._owns_execution_lock(run_lock):
                return stale_count
            message = (
                "Auto-closed stale active run; "
                f"last_update={run.get('updated_at') or run.get('started_at') or run.get('created_at')}"
            )
            self.store.update_run(
                run["id"],
                status="failed",
                error_message=message,
                finished_at=utcnow_iso(),
            )
            self.store.add_log(run["id"], "warning", message)
            stale_count += 1
        if self._owns_execution_lock(run_lock):
            self.store.ensure_active_run_constraint(raise_on_conflict=False)
        return stale_count

    def run_from_config(
        self,
        config_id: str,
        trigger_source: str = "manual",
        schedule_id: Optional[str] = None,
        schedule_slot: Optional[str] = None,
    ) -> Dict[str, Any]:
        config = self.store.get_config(config_id)
        if not config:
            raise ValueError("Config not found.")
        return self.create_run(
            mode=config["mode"],
            selection_type=config["selection_type"],
            selection_payload=config["selection_payload"],
            config_id=config_id,
            trigger_source=trigger_source,
            schedule_id=schedule_id,
            schedule_slot=schedule_slot,
        )

    def get_results(self, **filters: Any) -> List[Dict[str, Any]]:
        return query_forecast_results(self.db_url, **filters)

    def _append_log(self, run_id: str, level: str, message: str) -> None:
        self.store.add_log(run_id, level, message)

    def _resolve_selection_with_heartbeat(
        self,
        run_id: str,
        selection_type: str,
        selection_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        error: Dict[str, BaseException] = {}
        done = threading.Event()
        started = time.time()

        def _worker() -> None:
            try:
                result["resolved"] = self.resolve_selection(selection_type, selection_payload)
            except BaseException as exc:  # pragma: no cover
                error["exc"] = exc
            finally:
                done.set()

        self.store.update_run(run_id, current_spu="Resolving selection scope")
        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()

        while not done.wait(timeout=15):
            elapsed = int(time.time() - started)
            self._append_log(run_id, "info", f"Selection scope resolving ({elapsed}s elapsed).")

        worker.join(timeout=1)
        if "exc" in error:
            raise error["exc"]
        return result.get("resolved", {})

    def _load_source_data_with_heartbeat(self, run_id: str) -> pd.DataFrame:
        result: Dict[str, Any] = {}
        error: Dict[str, BaseException] = {}
        done = threading.Event()
        started = time.time()

        def _worker() -> None:
            try:
                result["df"] = get_data_from_db(self.db_url)
            except BaseException as exc:  # pragma: no cover
                error["exc"] = exc
            finally:
                done.set()

        self._append_log(run_id, "info", "Starting source SQL query.")
        self.store.update_run(run_id, current_spu="SQL query running")
        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()

        while not done.wait(timeout=15):
            elapsed = int(time.time() - started)
            self._append_log(run_id, "info", f"SQL query still running ({elapsed}s elapsed).")

        worker.join(timeout=1)
        elapsed = time.time() - started
        if "exc" in error:
            raise error["exc"]
        df = result.get("df", pd.DataFrame())
        self._append_log(run_id, "info", f"SQL query finished in {elapsed:.1f}s, rows={len(df)}.")
        return df

    def _load_all_spus(self) -> List[str]:
        eligible_spus, _total_spus = self._load_all_spus_with_scope()
        return eligible_spus

    def _load_all_spus_with_scope(self) -> tuple[List[str], int]:
        if not str(self.db_url or "").strip():
            return [], 0
        df = get_data_from_db(self.db_url)
        if df.empty:
            return [], 0
        df.columns = [str(col).lower() for col in df.columns]
        if "date" not in df.columns or "spu" not in df.columns:
            all_spus = sorted(normalize_spu_values(df["spu"]).unique().tolist())
            return all_spus, len(all_spus)

        # The default "all" scope is restricted to SPUs with at least 108
        # weekly observations, and each of the latest 4 weekly buckets must
        # have non-zero sales so Linux scheduled runs skip recently inactive SPUs.
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["spu"] = normalize_spu_values(df["spu"])
        df["sales"] = pd.to_numeric(df.get("sales"), errors="coerce").fillna(0.0)
        df = df.dropna(subset=["spu", "date"])
        all_spus = sorted(df["spu"].unique().tolist())
        weekly_sales = (
            df.assign(week_bucket=df["date"].dt.to_period("W").dt.start_time)
            .groupby(["spu", "week_bucket"], as_index=False)["sales"]
            .sum()
        )
        weekly_counts = weekly_sales.groupby("spu")["week_bucket"].nunique()
        recent_week_buckets = _latest_active_week_buckets(weekly_sales, DEFAULT_SCOPE_RECENT_WEEKS)
        if len(recent_week_buckets) < DEFAULT_SCOPE_RECENT_WEEKS:
            return [], len(all_spus)
        recent_window_buckets = _latest_active_week_buckets(weekly_sales, DEFAULT_SCOPE_RECENT_WINDOW_WEEKS)
        recent_26_buckets = _latest_active_week_buckets(weekly_sales, 26)

        recent_sales = (
            weekly_sales[weekly_sales["week_bucket"].isin(recent_week_buckets)]
            .pivot(index="spu", columns="week_bucket", values="sales")
            .reindex(columns=recent_week_buckets, fill_value=0.0)
            .fillna(0.0)
        )
        active_recent_spus = recent_sales.index[(recent_sales > 0).all(axis=1)]
        recent_window_sales = (
            weekly_sales[weekly_sales["week_bucket"].isin(recent_window_buckets)]
            .pivot(index="spu", columns="week_bucket", values="sales")
            .reindex(columns=recent_window_buckets, fill_value=0.0)
            .fillna(0.0)
        )
        recent_non_zero_counts = (recent_window_sales > 0).sum(axis=1)
        recent_4_totals = recent_sales.sum(axis=1)
        recent_26_sales = (
            weekly_sales[weekly_sales["week_bucket"].isin(recent_26_buckets)]
            .pivot(index="spu", columns="week_bucket", values="sales")
            .reindex(columns=recent_26_buckets, fill_value=0.0)
            .fillna(0.0)
        )
        recent_26_zero_ratio = (recent_26_sales <= 0).sum(axis=1) / max(len(recent_26_buckets), 1)
        eligible_spus = active_recent_spus[
            (weekly_counts.reindex(active_recent_spus, fill_value=0) >= DEFAULT_SCOPE_MIN_WEEKS)
            & (recent_non_zero_counts.reindex(active_recent_spus, fill_value=0) >= DEFAULT_SCOPE_RECENT_NON_ZERO_WEEKS)
            & (recent_4_totals.reindex(active_recent_spus, fill_value=0.0) >= DEFAULT_SCOPE_MIN_RECENT4_TOTAL_SALES)
            & (recent_26_zero_ratio.reindex(active_recent_spus, fill_value=1.0) <= DEFAULT_SCOPE_MAX_ZERO_RATIO_26W)
        ].tolist()
        return sorted(eligible_spus), len(all_spus)

    def _execute_run(
        self,
        run_id: str,
        stop_event: threading.Event,
        lock_lease: Optional[RunLock] = None,
    ) -> None:
        try:
            run = self.store.get_run(run_id)
            if not run:
                return
            if self._finish_stopped_if_requested(
                run_id,
                stop_event,
                "Run stopped before execution started.",
            ):
                return
            with self._lifecycle_guard:
                if stop_event.is_set():
                    pass
                else:
                    self.store.update_run(
                        run_id,
                        status="running",
                        started_at=utcnow_iso(),
                        current_spu="解析SPU范围",
                        progress=0,
                    )
            if self._finish_stopped_if_requested(
                run_id,
                stop_event,
                "Run stopped before execution started.",
            ):
                return
            self._append_log(run_id, "info", f"Run {run_id} started in {run['mode']} mode.")
            self._append_log(
                run_id,
                "info",
                f"Resolving selection scope for {run['selection_type']} mode.",
            )
            resolved = self._resolve_selection_with_heartbeat(
                run_id,
                run["selection_type"],
                run.get("selection_payload", {}),
            )
            if self._finish_stopped_if_requested(
                run_id,
                stop_event,
                "Run stopped after scope resolution.",
            ):
                return
            self.store.update_run(
                run_id,
                selected_spus_json=json.dumps(resolved["selected_spus"], ensure_ascii=False),
                total_count=resolved.get("count", len(resolved["selected_spus"])),
                processed_count=0,
                success_count=0,
                summary={
                    "scope_total_spus": resolved.get("scope_total_spus", len(resolved["selected_spus"])),
                    "scope_eligible_spus": resolved.get("scope_eligible_spus", len(resolved["selected_spus"])),
                    "scope_excluded_spus": resolved.get("scope_excluded_spus", 0),
                    "scope_min_weeks": DEFAULT_SCOPE_MIN_WEEKS,
                },
            )
            run["summary"] = {
                "scope_total_spus": resolved.get("scope_total_spus", len(resolved["selected_spus"])),
                "scope_eligible_spus": resolved.get("scope_eligible_spus", len(resolved["selected_spus"])),
                "scope_excluded_spus": resolved.get("scope_excluded_spus", 0),
                "scope_min_weeks": DEFAULT_SCOPE_MIN_WEEKS,
            }
            self._append_log(
                run_id,
                "info",
                f"Selection resolved: {resolved['count']} SPUs selected.",
            )
            self._append_log(run_id, "info", "Loading source dataset.")
            df_all = self._load_source_data_with_heartbeat(run_id)
            if self._finish_stopped_if_requested(
                run_id,
                stop_event,
                "Run stopped after source loading.",
            ):
                return
            if df_all.empty:
                raise RuntimeError("No source data was returned from the database.")
            self._append_log(run_id, "info", "Normalizing source columns and data types.")
            self.store.update_run(run_id, current_spu="Preparing source data")
            df_all.columns = [str(col).lower() for col in df_all.columns]
            df_all["sales"] = pd.to_numeric(df_all["sales"], errors="coerce").fillna(0)
            df_all["date"] = pd.to_datetime(df_all["date"], format="mixed")
            df_all["spu"] = df_all["spu"].astype(str)
            df_all["sku"] = df_all["sku"].astype(str)
            selected_spus = list(resolved["selected_spus"])
            df_all = df_all[df_all["spu"].isin(selected_spus)].copy()
            self._append_log(
                run_id,
                "info",
                f"Source scope filter applied: selected_spus={len(selected_spus)}, rows_after_filter={len(df_all)}.",
            )
            spus = sorted(df_all["spu"].unique().tolist())
            total_spus = len(spus)
            exog_cols = [col for col in df_all.columns if col in ["ad_cost", "price"]]
            self.store.update_run(run_id, total_count=total_spus)
            self._append_log(
                run_id,
                "info",
                f"Execution plan ready: total_spus={total_spus}, exog_cols={','.join(exog_cols) if exog_cols else 'none'}.",
            )
            successful = 0
            failures: List[Dict[str, str]] = []
            all_results: List[pd.DataFrame] = []
            policy_counts: Dict[str, int] = {"standard": 0, "conservative": 0, "unknown": 0}

            for index, spu in enumerate(spus, start=1):
                if self._finish_stopped_if_requested(
                    run_id,
                    stop_event,
                    "Run stopped before completion.",
                ):
                    return
                self.store.update_run(
                    run_id,
                    current_spu=spu,
                    processed_count=index - 1,
                    success_count=successful,
                    progress=int((index - 1) / max(total_spus, 1) * 100),
                )
                self.store.upsert_run_spu(run_id, spu, "running", message="Processing")
                self._append_log(run_id, "info", f"Processing SPU {spu} ({index}/{total_spus}).")
                self._append_log(run_id, "info", f"[SPU {spu}] 模型竞赛准备开始。")
                self._append_log(run_id, "info", f"[SPU {spu}] Model competition starting.")
                df_spu = df_all[df_all["spu"] == spu].copy()
                spu_timed_out = {"value": False}
                spu_result: Dict[str, Any] = {}
                spu_error: Dict[str, BaseException] = {}

                def _spu_log(line: str, current_spu: str = spu) -> None:
                    if spu_timed_out["value"]:
                        return
                    self._append_log(run_id, "info", f"[SPU {current_spu}] {line}")

                def _spu_worker() -> None:
                    try:
                        spu_result["payload"] = process_single_spu(
                            spu,
                            df_spu,
                            mode=run["mode"],
                            exog_cols=exog_cols,
                            collect_viz=False,
                            verbose=False,
                            log_fn=_spu_log,
                        )
                    except BaseException as exc:  # pragma: no cover
                        spu_error["exc"] = exc

                worker = threading.Thread(target=_spu_worker, daemon=True)
                worker.start()
                timeout_seconds = max(int(DEFAULT_SPU_TIMEOUT_SECONDS), 60)
                worker.join(timeout=timeout_seconds)
                if self._finish_stopped_if_requested(
                    run_id,
                    stop_event,
                    "Run stopped during SPU execution.",
                ):
                    return
                if worker.is_alive():
                    spu_timed_out["value"] = True
                    timeout_message = f"SPU execution timeout after {timeout_seconds}s"
                    failures.append({"spu": spu, "reason": timeout_message})
                    self.store.upsert_run_spu(run_id, spu, "failed", message=timeout_message)
                    self._append_log(
                        run_id,
                        "warning",
                        f"[SPU {spu}] {timeout_message}. Marked failed and continue.",
                    )
                    self.store.update_run(
                        run_id,
                        processed_count=index,
                        success_count=successful,
                        progress=int(index / max(total_spus, 1) * 100),
                    )
                    continue
                if "exc" in spu_error:
                    raise spu_error["exc"]
                result_df, message, _viz, _profile = spu_result.get(
                    "payload",
                    (None, "SPU worker returned no payload", None, None),
                )
                if result_df is not None:
                    all_results.append(result_df)
                    successful += 1
                    winner_algo = str(result_df["winner_algo"].iloc[0])
                    wmape = float(result_df["validation_wmape"].iloc[0])
                    if "policy=conservative" in (message or ""):
                        policy_counts["conservative"] += 1
                    elif "policy=standard" in (message or ""):
                        policy_counts["standard"] += 1
                    else:
                        policy_counts["unknown"] += 1
                    self.store.upsert_run_spu(
                        run_id,
                        spu,
                        "completed",
                        message=message,
                        winner_algo=winner_algo,
                        validation_wmape=wmape,
                    )
                else:
                    failures.append({"spu": spu, "reason": message})
                    self.store.upsert_run_spu(run_id, spu, "failed", message=message)
                self.store.update_run(
                    run_id,
                    processed_count=index,
                    success_count=successful,
                    progress=int(index / max(total_spus, 1) * 100),
                )

            summary: Dict[str, Any] = {
                "total_spus": total_spus,
                "successful_spus": successful,
                "failed_spus": len(failures),
                "failed_details": failures[:20],
                "policy_standard_spus": policy_counts["standard"],
                "policy_conservative_spus": policy_counts["conservative"],
                "policy_unknown_spus": policy_counts["unknown"],
                "scope_total_spus": run.get("summary", {}).get("scope_total_spus", total_spus),
                "scope_eligible_spus": run.get("summary", {}).get("scope_eligible_spus", total_spus),
                "scope_excluded_spus": run.get("summary", {}).get("scope_excluded_spus", 0),
                "scope_min_weeks": DEFAULT_SCOPE_MIN_WEEKS,
            }
            if self._finish_stopped_if_requested(
                run_id,
                stop_event,
                "Run stopped before result persistence.",
            ):
                return
            if all_results:
                final = pd.concat(all_results, ignore_index=True)
                persist_results = self._payload_bool(
                    run.get("selection_payload", {}).get("persist_results"),
                    default=True,
                )
                if persist_results:
                    save_to_database(
                        final,
                        self.db_url,
                        run_id=run_id,
                        config_id=run.get("config_id"),
                    )
                if "validation_wmape" in final.columns:
                    average_wmape = float(final["validation_wmape"].mean())
                    by_spu = final.groupby("spu")["validation_wmape"].mean().sort_values()
                    summary["average_wmape"] = average_wmape
                    summary["top_spus"] = by_spu.head(5).index.tolist()
                    summary["bottom_spus"] = by_spu.tail(5).index.tolist()
                if persist_results:
                    self._append_log(
                        run_id,
                        "success",
                        f"Saved {len(final)} forecast rows to the database.",
                    )
                else:
                    self._append_log(
                        run_id,
                        "info",
                        f"Result persistence disabled; processed {len(final)} forecast rows without saving.",
                    )
            completed = False
            with self._lifecycle_guard:
                current = self.store.get_run(run_id)
                if (
                    current
                    and current.get("status") in ACTIVE_RUN_STATUSES
                    and not stop_event.is_set()
                ):
                    self.store.update_run(
                        run_id,
                        status="completed",
                        progress=100,
                        processed_count=total_spus,
                        success_count=successful,
                        finished_at=utcnow_iso(),
                        summary=summary,
                    )
                    completed = True
            if completed:
                self._append_log(run_id, "success", "Run completed.")
            else:
                self._finish_stopped_if_requested(
                    run_id,
                    stop_event,
                    "Run stopped before completion was persisted.",
                )
        except BaseException as exc:
            self._mark_run_failed_until_persisted(run_id, exc)
        finally:
            try:
                if lock_lease is not None:
                    lock_lease.release()
            except BaseException:
                logger.exception("Failed to release execution lock for run %s.", run_id)
            finally:
                with self._lifecycle_guard:
                    self._runs.pop(run_id, None)
                    self._worker_threads.pop(run_id, None)

    @staticmethod
    def _payload_bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"false", "0", "no", "off"}:
                return False
            if normalized in {"true", "1", "yes", "on"}:
                return True
        return bool(value)

    def _scheduler_loop(self) -> None:
        while not self._scheduler_stop.is_set():
            try:
                self._poll_schedules()
            except Exception:
                logger.exception("Scheduler poll failed unexpectedly; continuing after recovery wait.")
                self._scheduler_stop.wait(SCHEDULER_RECOVERY_WAIT_SECONDS)
                continue
            self._scheduler_stop.wait(SCHEDULER_POLL_SECONDS)

    def _poll_schedules(self) -> None:
        now_utc = datetime.now(timezone.utc)
        for schedule in self.store.list_schedules():
            if not schedule["enabled"]:
                continue
            due_slot = self._current_due_slot(schedule, now_utc)
            if due_slot is None:
                continue
            if self._already_triggered_for_slot(schedule, due_slot):
                continue
            schedule_slot = (
                due_slot.astimezone(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
            dedupe_key = f"{schedule['id']}:{schedule_slot}"
            if dedupe_key in self._scheduler_seen_keys:
                continue
            self._scheduler_seen_keys.add(dedupe_key)
            try:
                run = self.run_from_config(
                    schedule["config_id"],
                    trigger_source="schedule",
                    schedule_id=schedule["id"],
                    schedule_slot=schedule_slot,
                )
                self.store.mark_schedule_triggered(schedule["id"], schedule_slot)
                if run.get("trigger_source") == "schedule":
                    logger.info(
                        "Schedule %s triggered config %s at slot %s, run_id=%s.",
                        schedule["id"],
                        schedule["config_id"],
                        due_slot.isoformat(),
                        run.get("id"),
                    )
                else:
                    logger.warning(
                        "Schedule %s skipped new run for config %s because active run_id=%s status=%s.",
                        schedule["id"],
                        schedule["config_id"],
                        run.get("id"),
                        run.get("status"),
                    )
            except ScheduleSlotConflict as exc:
                try:
                    self.store.mark_schedule_triggered(schedule["id"], schedule_slot)
                except Exception:
                    self._scheduler_seen_keys.discard(dedupe_key)
                    logger.exception(
                        "Schedule slot %s was already claimed but trigger state could not be updated.",
                        schedule_slot,
                    )
                    continue
                existing_run = exc.active_run or {}
                logger.info(
                    "Schedule %s slot %s was already claimed by run_id=%s; no duplicate created.",
                    schedule["id"],
                    schedule_slot,
                    existing_run.get("id"),
                )
            except ActiveRunConflict:
                self._scheduler_seen_keys.discard(dedupe_key)
                logger.info(
                    "Schedule %s slot %s deferred because another run is active.",
                    schedule["id"],
                    schedule_slot,
                )
            except Exception:
                self._scheduler_seen_keys.discard(dedupe_key)
                logger.exception(
                    "Failed to trigger schedule %s for config %s.",
                    schedule["id"],
                    schedule["config_id"],
                )

    def _find_active_run_for_config(self, config_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not config_id:
            return None
        for run in self.store.list_runs(limit=200):
            if run.get("config_id") != config_id:
                continue
            if run.get("status") in ACTIVE_RUN_STATUSES:
                return run
        return None

    @staticmethod
    def _resolve_timezone(timezone_name: Optional[str]) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_name or "Asia/Shanghai")
        except Exception:
            return ZoneInfo("Asia/Shanghai")

    @staticmethod
    def _parse_iso_utc(raw: Optional[str]) -> Optional[datetime]:
        if not raw:
            return None
        try:
            normalized = raw.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _already_triggered_for_slot(self, schedule: Dict[str, Any], due_slot_utc: datetime) -> bool:
        last_triggered_at = self._parse_iso_utc(schedule.get("last_triggered_at"))
        return bool(last_triggered_at and last_triggered_at >= due_slot_utc)

    def _current_due_slot(self, schedule: Dict[str, Any], now_utc: datetime) -> Optional[datetime]:
        timezone_name = str(schedule.get("timezone") or "Asia/Shanghai")
        tz = self._resolve_timezone(timezone_name)
        now_local = now_utc.astimezone(tz)
        current_slot = compute_next_run_at(
            weekday=int(schedule["weekday"]),
            hour=int(schedule["hour"]),
            minute=int(schedule["minute"]),
            timezone_name=timezone_name,
            now=now_local - timedelta(days=7),
        )
        current_slot_utc = current_slot.astimezone(timezone.utc)
        if current_slot_utc > now_utc:
            return None
        if now_utc - current_slot_utc >= timedelta(days=7):
            return None
        return current_slot_utc
