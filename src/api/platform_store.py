import json
import logging
import os
import time
import uuid
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError, OperationalError


ACTIVE_RUN_STATUSES = ("queued", "running", "stopping")
ACTIVE_RUN_INDEX = "uq_forecast_job_run_single_active"
SCHEDULE_SLOT_INDEX = "uq_forecast_job_run_schedule_slot"
SQLITE_BUSY_TIMEOUT_MS = 30_000
SQLITE_LOCK_RETRY_ATTEMPTS = 4
logger = logging.getLogger(__name__)


class ActiveRunConflict(RuntimeError):
    """Raised when a queued/running/stopping run already owns the active slot."""

    def __init__(
        self,
        message: str = "Another forecast run is already active.",
        active_run: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.active_run = active_run


class ScheduleSlotConflict(ActiveRunConflict):
    """Raised when a schedule slot was already claimed by an earlier run."""


def _is_sqlite_lock_error(exc: OperationalError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "locked" in message or "busy" in message


def _retry_sqlite_locked(method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        for attempt in range(SQLITE_LOCK_RETRY_ATTEMPTS):
            try:
                return method(*args, **kwargs)
            except OperationalError as exc:
                if not _is_sqlite_lock_error(exc) or attempt + 1 >= SQLITE_LOCK_RETRY_ATTEMPTS:
                    raise
                time.sleep(0.05 * (2**attempt))
        raise AssertionError("unreachable")

    return wrapper


def utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class PlatformStore:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.active_run_constraint_ready = False
        self.active_run_constraint_error: Optional[str] = None
        self.schedule_slot_constraint_ready = False
        self.schedule_slot_constraint_error: Optional[str] = None
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )
        event.listen(self.engine, "connect", self._configure_sqlite_connection)
        self._ensure_schema()

    @staticmethod
    def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    @_retry_sqlite_locked
    def _ensure_schema(self) -> None:
        ddl_statements = [
            """
            CREATE TABLE IF NOT EXISTS forecast_job_config (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                purpose TEXT,
                mode TEXT NOT NULL,
                selection_type TEXT NOT NULL,
                selection_payload_json TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS forecast_job_schedule (
                id TEXT PRIMARY KEY,
                config_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                weekday INTEGER NOT NULL,
                hour INTEGER NOT NULL,
                minute INTEGER NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                last_triggered_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS forecast_job_run (
                id TEXT PRIMARY KEY,
                config_id TEXT,
                schedule_id TEXT,
                schedule_slot TEXT,
                trigger_source TEXT NOT NULL,
                mode TEXT NOT NULL,
                selection_type TEXT NOT NULL,
                selection_payload_json TEXT NOT NULL,
                selected_spus_json TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                processed_count INTEGER NOT NULL DEFAULT 0,
                total_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                current_spu TEXT,
                error_message TEXT,
                summary_json TEXT,
                started_at TEXT,
                finished_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS forecast_job_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS forecast_job_run_spu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                spu TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                winner_algo TEXT,
                validation_wmape REAL,
                updated_at TEXT NOT NULL,
                UNIQUE(run_id, spu)
            )
            """,
        ]
        with self.engine.begin() as conn:
            for ddl in ddl_statements:
                conn.execute(text(ddl))
            run_columns = {
                str(row[1])
                for row in conn.exec_driver_sql("PRAGMA table_info(forecast_job_run)").all()
            }
            if "schedule_id" not in run_columns:
                conn.exec_driver_sql("ALTER TABLE forecast_job_run ADD COLUMN schedule_id TEXT")
            if "schedule_slot" not in run_columns:
                conn.exec_driver_sql("ALTER TABLE forecast_job_run ADD COLUMN schedule_slot TEXT")
        self.ensure_schedule_slot_constraint(raise_on_conflict=False)
        self.ensure_active_run_constraint(raise_on_conflict=False)

    @_retry_sqlite_locked
    def ensure_schedule_slot_constraint(self, raise_on_conflict: bool = True) -> bool:
        with self.engine.begin() as conn:
            duplicate = conn.execute(
                text(
                    """
                    SELECT schedule_id, schedule_slot, COUNT(*) AS duplicate_count
                    FROM forecast_job_run
                    WHERE schedule_id IS NOT NULL AND schedule_slot IS NOT NULL
                    GROUP BY schedule_id, schedule_slot
                    HAVING COUNT(*) > 1
                    LIMIT 1
                    """
                )
            ).mappings().first()
            if duplicate:
                message = (
                    "Schedule-slot constraint is not installed because duplicate claims exist for "
                    f"schedule_id={duplicate['schedule_id']} slot={duplicate['schedule_slot']}; "
                    "explicit repair is required."
                )
                self.schedule_slot_constraint_ready = False
                self.schedule_slot_constraint_error = message
                logger.error(message)
                if raise_on_conflict:
                    raise ScheduleSlotConflict(message)
                return False
            conn.execute(
                text(
                    f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS {SCHEDULE_SLOT_INDEX}
                    ON forecast_job_run (schedule_id, schedule_slot)
                    WHERE schedule_id IS NOT NULL AND schedule_slot IS NOT NULL
                    """
                )
            )
        self.schedule_slot_constraint_ready = True
        self.schedule_slot_constraint_error = None
        return True

    @_retry_sqlite_locked
    def ensure_active_run_constraint(self, raise_on_conflict: bool = True) -> bool:
        """Install the single-active-run index without rewriting existing history."""
        with self.engine.begin() as conn:
            active_count = int(
                conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM forecast_job_run
                        WHERE status IN ('queued', 'running', 'stopping')
                        """
                    )
                ).scalar_one()
            )
            if active_count > 1:
                message = (
                    "Active-run constraint is not installed because the database contains "
                    f"{active_count} active records; run explicit stale-run recovery first."
                )
                self.active_run_constraint_ready = False
                self.active_run_constraint_error = message
                logger.error(message)
                if raise_on_conflict:
                    raise ActiveRunConflict(message)
                return False
            try:
                conn.execute(
                    text(
                        f"""
                        CREATE UNIQUE INDEX IF NOT EXISTS {ACTIVE_RUN_INDEX}
                        ON forecast_job_run ((1))
                        WHERE status IN ('queued', 'running', 'stopping')
                        """
                    )
                )
            except IntegrityError as exc:
                message = (
                    "Active-run constraint could not be installed safely; "
                    "run explicit stale-run recovery first."
                )
                self.active_run_constraint_ready = False
                self.active_run_constraint_error = message
                if raise_on_conflict:
                    raise ActiveRunConflict(message) from exc
                logger.error(message)
                return False
            if not self._active_index_definition_is_valid(conn):
                message = (
                    "Active-run constraint is missing or has an unexpected definition; "
                    "explicit repair is required."
                )
                self.active_run_constraint_ready = False
                self.active_run_constraint_error = message
                logger.error(message)
                if raise_on_conflict:
                    raise ActiveRunConflict(message)
                return False
        self.active_run_constraint_ready = True
        self.active_run_constraint_error = None
        return True

    @staticmethod
    def _active_index_definition_is_valid(conn) -> bool:
        definition = conn.execute(
            text(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'index' AND name = :index_name
                """
            ),
            {"index_name": ACTIVE_RUN_INDEX},
        ).scalar_one_or_none()
        if not definition:
            return False
        normalized = "".join(str(definition).lower().split())
        return (
            normalized.startswith("createuniqueindex")
            and f"index{ACTIVE_RUN_INDEX.lower()}" in normalized
            and "onforecast_job_run((1))" in normalized
            and "wherestatusin('queued','running','stopping')" in normalized
        )

    @_retry_sqlite_locked
    def close_orphaned_active_runs(
        self,
        reason: str = "Explicit recovery closed an orphaned active run.",
    ) -> int:
        """Close active records and install the active constraint in one transaction.

        Callers must first prove that the external execution lock is free.
        """
        now = utcnow_iso()
        with self.engine.begin() as conn:
            orphan_ids = list(
                conn.execute(
                    text(
                        """
                        SELECT id FROM forecast_job_run
                        WHERE status IN ('queued', 'running', 'stopping')
                        ORDER BY created_at ASC
                        """
                    )
                ).scalars()
            )
            if orphan_ids:
                conn.execute(
                    text(
                        """
                        UPDATE forecast_job_run
                        SET status = 'failed', error_message = :reason,
                            finished_at = :finished_at, updated_at = :updated_at
                        WHERE status IN ('queued', 'running', 'stopping')
                        """
                    ),
                    {"reason": reason, "finished_at": now, "updated_at": now},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO forecast_job_log (run_id, level, message, created_at)
                        VALUES (:run_id, 'warning', :message, :created_at)
                        """
                    ),
                    [
                        {
                            "run_id": run_id,
                            "message": reason,
                            "created_at": now,
                        }
                        for run_id in orphan_ids
                    ],
                )
            conn.execute(
                text(
                    f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS {ACTIVE_RUN_INDEX}
                    ON forecast_job_run ((1))
                    WHERE status IN ('queued', 'running', 'stopping')
                    """
                )
            )
            if not self._active_index_definition_is_valid(conn):
                self.active_run_constraint_ready = False
                self.active_run_constraint_error = (
                    "Active-run constraint has an unexpected definition; explicit repair is required."
                )
                raise ActiveRunConflict(self.active_run_constraint_error)
        self.active_run_constraint_ready = True
        self.active_run_constraint_error = None
        return len(orphan_ids)

    @staticmethod
    def _json_load(raw: Optional[str], fallback: Any) -> Any:
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return fallback

    @staticmethod
    def _hydrate_config(row: Dict[str, Any]) -> Dict[str, Any]:
        row["selection_payload"] = PlatformStore._json_load(
            row.pop("selection_payload_json", "{}"), {}
        )
        row["is_active"] = bool(row["is_active"])
        return row

    @staticmethod
    def _hydrate_schedule(row: Dict[str, Any]) -> Dict[str, Any]:
        row["enabled"] = bool(row["enabled"])
        return row

    @staticmethod
    def _hydrate_run(row: Dict[str, Any]) -> Dict[str, Any]:
        row["selection_payload"] = PlatformStore._json_load(
            row.pop("selection_payload_json", "{}"), {}
        )
        row["selected_spus"] = PlatformStore._json_load(
            row.pop("selected_spus_json", "[]"), []
        )
        row["summary"] = PlatformStore._json_load(row.pop("summary_json", "{}"), {})
        return row

    @_retry_sqlite_locked
    def create_config(
        self,
        name: str,
        purpose: str,
        mode: str,
        selection_type: str,
        selection_payload: Dict[str, Any],
        is_active: bool = True,
    ) -> Dict[str, Any]:
        config_id = uuid.uuid4().hex
        now = utcnow_iso()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO forecast_job_config
                    (id, name, purpose, mode, selection_type, selection_payload_json, is_active, created_at, updated_at)
                    VALUES
                    (:id, :name, :purpose, :mode, :selection_type, :selection_payload_json, :is_active, :created_at, :updated_at)
                    """
                ),
                {
                    "id": config_id,
                    "name": name,
                    "purpose": purpose,
                    "mode": mode,
                    "selection_type": selection_type,
                    "selection_payload_json": json.dumps(selection_payload, ensure_ascii=False),
                    "is_active": 1 if is_active else 0,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        return self.get_config(config_id)

    @_retry_sqlite_locked
    def list_configs(self) -> List[Dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text("SELECT * FROM forecast_job_config ORDER BY updated_at DESC")
            ).mappings().all()
        return [self._hydrate_config(dict(row)) for row in rows]

    @_retry_sqlite_locked
    def get_config(self, config_id: str) -> Optional[Dict[str, Any]]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text("SELECT * FROM forecast_job_config WHERE id = :id"),
                {"id": config_id},
            ).mappings().first()
        return self._hydrate_config(dict(row)) if row else None

    @_retry_sqlite_locked
    def create_or_update_schedule(
        self,
        config_id: str,
        weekday: int,
        hour: int,
        minute: int,
        timezone: str = "Asia/Shanghai",
        enabled: bool = True,
    ) -> Dict[str, Any]:
        now = utcnow_iso()
        with self.engine.begin() as conn:
            existing = conn.execute(
                text("SELECT id FROM forecast_job_schedule WHERE config_id = :config_id"),
                {"config_id": config_id},
            ).scalar_one_or_none()
            if existing:
                conn.execute(
                    text(
                        """
                        UPDATE forecast_job_schedule
                        SET weekday = :weekday,
                            hour = :hour,
                            minute = :minute,
                            timezone = :timezone,
                            enabled = :enabled,
                            updated_at = :updated_at
                        WHERE config_id = :config_id
                        """
                    ),
                    {
                        "config_id": config_id,
                        "weekday": weekday,
                        "hour": hour,
                        "minute": minute,
                        "timezone": timezone,
                        "enabled": 1 if enabled else 0,
                        "updated_at": now,
                    },
                )
            else:
                conn.execute(
                    text(
                        """
                        INSERT INTO forecast_job_schedule
                        (id, config_id, enabled, weekday, hour, minute, timezone, created_at, updated_at)
                        VALUES
                        (:id, :config_id, :enabled, :weekday, :hour, :minute, :timezone, :created_at, :updated_at)
                        """
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "config_id": config_id,
                        "enabled": 1 if enabled else 0,
                        "weekday": weekday,
                        "hour": hour,
                        "minute": minute,
                        "timezone": timezone,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        return self.get_schedule_by_config(config_id)

    @_retry_sqlite_locked
    def list_schedules(self) -> List[Dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text("SELECT * FROM forecast_job_schedule ORDER BY updated_at DESC")
            ).mappings().all()
        return [self._hydrate_schedule(dict(row)) for row in rows]

    @_retry_sqlite_locked
    def get_schedule_by_config(self, config_id: str) -> Optional[Dict[str, Any]]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text("SELECT * FROM forecast_job_schedule WHERE config_id = :config_id"),
                {"config_id": config_id},
            ).mappings().first()
        return self._hydrate_schedule(dict(row)) if row else None

    @_retry_sqlite_locked
    def mark_schedule_triggered(self, schedule_id: str, triggered_at: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE forecast_job_schedule
                    SET last_triggered_at = :last_triggered_at, updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                {
                    "id": schedule_id,
                    "last_triggered_at": triggered_at,
                    "updated_at": utcnow_iso(),
                },
            )

    def create_run(
        self,
        config_id: Optional[str],
        trigger_source: str,
        mode: str,
        selection_type: str,
        selection_payload: Dict[str, Any],
        selected_spus: List[str],
        schedule_id: Optional[str] = None,
        schedule_slot: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.claim_run(
            config_id=config_id,
            trigger_source=trigger_source,
            mode=mode,
            selection_type=selection_type,
            selection_payload=selection_payload,
            selected_spus=selected_spus,
            schedule_id=schedule_id,
            schedule_slot=schedule_slot,
            run_id=run_id,
        )

    def claim_run(
        self,
        config_id: Optional[str],
        trigger_source: str,
        mode: str,
        selection_type: str,
        selection_payload: Dict[str, Any],
        selected_spus: List[str],
        schedule_id: Optional[str] = None,
        schedule_slot: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.active_run_constraint_ready:
            raise ActiveRunConflict(
                self.active_run_constraint_error
                or "Active-run constraint is unavailable; run explicit stale-run recovery first."
            )
        if (schedule_id is None) != (schedule_slot is None):
            raise ValueError("schedule_id and schedule_slot must be provided together")
        if schedule_id is not None and not self.schedule_slot_constraint_ready:
            raise ScheduleSlotConflict(
                self.schedule_slot_constraint_error
                or "Schedule-slot constraint is unavailable; explicit repair is required."
            )

        run_id = str(run_id or uuid.uuid4().hex)
        now = utcnow_iso()
        payload = {
            "id": run_id,
            "config_id": config_id,
            "schedule_id": schedule_id,
            "schedule_slot": schedule_slot,
            "trigger_source": trigger_source,
            "mode": mode,
            "selection_type": selection_type,
            "selection_payload_json": json.dumps(selection_payload, ensure_ascii=False),
            "selected_spus_json": json.dumps(selected_spus, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }
        insert_statement = text(
            """
            INSERT INTO forecast_job_run
            (id, config_id, schedule_id, schedule_slot, trigger_source, mode, selection_type,
             selection_payload_json, selected_spus_json, status, created_at, updated_at)
            VALUES
            (:id, :config_id, :schedule_id, :schedule_slot, :trigger_source, :mode,
             :selection_type, :selection_payload_json, :selected_spus_json,
             'queued', :created_at, :updated_at)
            """
        )
        select_statement = text("SELECT * FROM forecast_job_run WHERE id = :id")

        for attempt in range(SQLITE_LOCK_RETRY_ATTEMPTS):
            commit_started = False
            try:
                with self.engine.connect() as conn:
                    transaction = conn.begin()
                    try:
                        conn.execute(insert_statement, payload)
                        row = conn.execute(
                            select_statement,
                            {"id": run_id},
                        ).mappings().one()
                        commit_started = True
                        transaction.commit()
                    except BaseException:
                        if transaction.is_active:
                            transaction.rollback()
                        raise
                # Hydration uses the row read on the inserting connection before
                # commit. There is no SQLite RETURNING dependency and no
                # post-commit SELECT that could cause the INSERT to be replayed.
                return self._hydrate_run(dict(row))
            except IntegrityError as exc:
                self._raise_claim_conflict(schedule_id, schedule_slot, exc)
            except OperationalError as exc:
                if (
                    commit_started
                    or not _is_sqlite_lock_error(exc)
                    or attempt + 1 >= SQLITE_LOCK_RETRY_ATTEMPTS
                ):
                    raise
                time.sleep(0.05 * (2**attempt))
        raise AssertionError("unreachable")

    def _raise_claim_conflict(
        self,
        schedule_id: Optional[str],
        schedule_slot: Optional[str],
        exc: IntegrityError,
    ) -> None:
        if schedule_id is not None and schedule_slot is not None:
            try:
                scheduled_run = self.get_run_by_schedule_slot(schedule_id, schedule_slot)
            except Exception:
                scheduled_run = None
            if scheduled_run is not None:
                raise ScheduleSlotConflict(
                    "This schedule slot was already claimed by an earlier forecast run.",
                    active_run=scheduled_run,
                ) from exc
        try:
            active_run = self.get_current_run()
        except Exception:
            active_run = None
        raise ActiveRunConflict(
            "Another forecast run is already queued, running, or stopping.",
            active_run=active_run,
        ) from exc

    @_retry_sqlite_locked
    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        payload = dict(fields)
        if "summary" in payload:
            payload["summary_json"] = json.dumps(payload.pop("summary"), ensure_ascii=False)
        payload["updated_at"] = utcnow_iso()
        assignments = ", ".join(f"{key} = :{key}" for key in payload.keys())
        payload["id"] = run_id
        with self.engine.begin() as conn:
            conn.execute(
                text(f"UPDATE forecast_job_run SET {assignments} WHERE id = :id"),
                payload,
            )

    @_retry_sqlite_locked
    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text("SELECT * FROM forecast_job_run WHERE id = :id"),
                {"id": run_id},
            ).mappings().first()
        return self._hydrate_run(dict(row)) if row else None

    @_retry_sqlite_locked
    def get_run_by_schedule_slot(
        self,
        schedule_id: str,
        schedule_slot: str,
    ) -> Optional[Dict[str, Any]]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT * FROM forecast_job_run
                    WHERE schedule_id = :schedule_id AND schedule_slot = :schedule_slot
                    LIMIT 1
                    """
                ),
                {"schedule_id": schedule_id, "schedule_slot": schedule_slot},
            ).mappings().first()
        return self._hydrate_run(dict(row)) if row else None

    @_retry_sqlite_locked
    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text("SELECT * FROM forecast_job_run ORDER BY created_at DESC LIMIT :limit"),
                {"limit": limit},
            ).mappings().all()
        return [self._hydrate_run(dict(row)) for row in rows]

    @_retry_sqlite_locked
    def get_current_run(self) -> Optional[Dict[str, Any]]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT * FROM forecast_job_run
                    WHERE status IN ('queued', 'running', 'stopping')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
            ).mappings().first()
        return self._hydrate_run(dict(row)) if row else None

    @_retry_sqlite_locked
    def add_log(self, run_id: str, level: str, message: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO forecast_job_log (run_id, level, message, created_at)
                    VALUES (:run_id, :level, :message, :created_at)
                    """
                ),
                {
                    "run_id": run_id,
                    "level": level,
                    "message": message,
                    "created_at": utcnow_iso(),
                },
            )

    @_retry_sqlite_locked
    def get_logs(self, run_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT run_id, level, message, created_at
                    FROM forecast_job_log
                    WHERE run_id = :run_id
                    ORDER BY id DESC
                    LIMIT :limit
                    """
                ),
                {"run_id": run_id, "limit": limit},
            ).mappings().all()
        return list(reversed([dict(row) for row in rows]))

    @_retry_sqlite_locked
    def upsert_run_spu(
        self,
        run_id: str,
        spu: str,
        status: str,
        message: Optional[str] = None,
        winner_algo: Optional[str] = None,
        validation_wmape: Optional[float] = None,
    ) -> None:
        with self.engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT id FROM forecast_job_run_spu WHERE run_id = :run_id AND spu = :spu"
                ),
                {"run_id": run_id, "spu": spu},
            ).scalar_one_or_none()
            payload = {
                "run_id": run_id,
                "spu": spu,
                "status": status,
                "message": message,
                "winner_algo": winner_algo,
                "validation_wmape": validation_wmape,
                "updated_at": utcnow_iso(),
            }
            if existing:
                payload["id"] = existing
                conn.execute(
                    text(
                        """
                        UPDATE forecast_job_run_spu
                        SET status = :status,
                            message = :message,
                            winner_algo = :winner_algo,
                            validation_wmape = :validation_wmape,
                            updated_at = :updated_at
                        WHERE id = :id
                        """
                    ),
                    payload,
                )
            else:
                conn.execute(
                    text(
                        """
                        INSERT INTO forecast_job_run_spu
                        (run_id, spu, status, message, winner_algo, validation_wmape, updated_at)
                        VALUES
                        (:run_id, :spu, :status, :message, :winner_algo, :validation_wmape, :updated_at)
                        """
                    ),
                    payload,
                )

    @_retry_sqlite_locked
    def get_run_spus(self, run_id: str) -> List[Dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT spu, status, message, winner_algo, validation_wmape, updated_at
                    FROM forecast_job_run_spu
                    WHERE run_id = :run_id
                    ORDER BY updated_at DESC, spu ASC
                    """
                ),
                {"run_id": run_id},
            ).mappings().all()
        return [dict(row) for row in rows]
