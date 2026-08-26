from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from src.api.platform_store import PlatformStore, utcnow_iso


ACTIVE_RUN_STATUSES = {"queued", "running", "stopping"}

SYSTEMD_UNITS = [
    {
        "label": "Forecast Dashboard V2 API",
        "unit": "forecast-dashboard-v2.service",
        "log_path": "/var/log/forecast-dashboard-v2.log",
    },
    {
        "label": "Weekly Forecast Job",
        "unit": "forecast-weekly.service",
        "log_path": "/var/log/forecast-weekly.log",
    },
    {
        "label": "Weekly Forecast Timer",
        "unit": "forecast-weekly.timer",
        "log_path": None,
    },
]

WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or "Asia/Shanghai")
    except Exception:
        return ZoneInfo("Asia/Shanghai")


def format_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def compute_next_run_at(
    weekday: int,
    hour: int,
    minute: int,
    timezone_name: str = "Asia/Shanghai",
    now: Optional[datetime] = None,
) -> datetime:
    tz = _resolve_timezone(timezone_name)
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (weekday - candidate.weekday()) % 7
    if days_ahead == 0 and candidate <= current:
        days_ahead = 7
    return candidate + timedelta(days=days_ahead)


def tail_text_file(path: Optional[str], limit: int = 80) -> list[str]:
    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = deque(fh, maxlen=limit)
    return [line.rstrip("\n") for line in lines]


def _run_systemctl(unit: str) -> dict[str, Any]:
    if platform.system() != "Linux" or shutil.which("systemctl") is None:
        return {
            "unit": unit,
            "available": False,
            "active_state": "unavailable",
            "sub_state": "unavailable",
            "unit_file_state": "unknown",
            "status_text": "systemctl unavailable on this host",
        }

    props = [
        "Description",
        "LoadState",
        "ActiveState",
        "SubState",
        "UnitFileState",
        "Result",
        "FragmentPath",
        "ExecMainPID",
        "MainPID",
        "ActiveEnterTimestamp",
        "InactiveEnterTimestamp",
        "NextElapseUSecRealtime",
        "LastTriggerUSecRealtime",
    ]
    command = ["systemctl", "show", unit]
    command.extend(f"--property={prop}" for prop in props)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception as exc:
        return {
            "unit": unit,
            "available": False,
            "active_state": "unknown",
            "sub_state": "unknown",
            "unit_file_state": "unknown",
            "status_text": f"systemctl query failed: {exc}",
        }

    if result.returncode != 0:
        return {
            "unit": unit,
            "available": False,
            "active_state": "unknown",
            "sub_state": "unknown",
            "unit_file_state": "unknown",
            "status_text": result.stderr.strip() or result.stdout.strip() or "systemctl query failed",
        }

    data: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value

    active_state = data.get("ActiveState", "unknown")
    sub_state = data.get("SubState", "unknown")
    unit_file_state = data.get("UnitFileState", "unknown")
    status_text = f"{active_state} / {sub_state}"
    if data.get("Result"):
        status_text = f"{status_text} ({data['Result']})"

    return {
        "unit": unit,
        "available": True,
        "description": data.get("Description"),
        "load_state": data.get("LoadState", "unknown"),
        "active_state": active_state,
        "sub_state": sub_state,
        "unit_file_state": unit_file_state,
        "result": data.get("Result"),
        "fragment_path": data.get("FragmentPath"),
        "exec_main_pid": data.get("ExecMainPID") or data.get("MainPID"),
        "active_enter_timestamp": data.get("ActiveEnterTimestamp"),
        "inactive_enter_timestamp": data.get("InactiveEnterTimestamp"),
        "next_elapse_realtime": data.get("NextElapseUSecRealtime"),
        "last_trigger_realtime": data.get("LastTriggerUSecRealtime"),
        "status_text": status_text,
    }


def build_schedule_overview(
    store: PlatformStore,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    configs = {config["id"]: config for config in store.list_configs()}
    schedules: list[dict[str, Any]] = []
    next_candidates: list[dict[str, Any]] = []

    for schedule in store.list_schedules():
        config = configs.get(schedule["config_id"], {})
        enabled = bool(schedule.get("enabled"))
        timezone_name = schedule.get("timezone", "Asia/Shanghai")
        next_run_at = None
        next_run_text = "已停用"
        if enabled:
            next_run_dt = compute_next_run_at(
                weekday=int(schedule["weekday"]),
                hour=int(schedule["hour"]),
                minute=int(schedule["minute"]),
                timezone_name=timezone_name,
                now=now,
            )
            next_run_at = next_run_dt.isoformat()
            next_run_text = format_dt(next_run_dt)
            next_candidates.append(
                {
                    "config_id": schedule["config_id"],
                    "config_name": config.get("name") or schedule["config_id"],
                    "next_run_at": next_run_at,
                    "next_run_text": next_run_text,
                    "sort_key": next_run_dt,
                }
            )

        schedules.append(
            {
                "schedule_id": schedule["id"],
                "config_id": schedule["config_id"],
                "config_name": config.get("name") or schedule["config_id"],
                "enabled": enabled,
                "weekday": int(schedule["weekday"]),
                "weekday_label": WEEKDAY_LABELS[int(schedule["weekday"])],
                "hour": int(schedule["hour"]),
                "minute": int(schedule["minute"]),
                "timezone": timezone_name,
                "last_triggered_at": schedule.get("last_triggered_at"),
                "next_run_at": next_run_at,
                "next_run_text": next_run_text,
            }
        )

    next_schedule = None
    if next_candidates:
        upcoming = min(next_candidates, key=lambda item: item["sort_key"])
        next_schedule = {
            key: value
            for key, value in upcoming.items()
            if key != "sort_key"
        }

    return {
        "schedules": schedules,
        "next_schedule": next_schedule,
    }


def _normalize_run_row(run: dict[str, Any]) -> dict[str, Any]:
    if not run:
        return {}
    return {
        "run_id": run.get("id"),
        "status": run.get("status"),
        "progress": run.get("progress"),
        "processed_count": run.get("processed_count"),
        "total_count": run.get("total_count"),
        "success_count": run.get("success_count"),
        "current_spu": run.get("current_spu"),
        "mode": run.get("mode"),
        "trigger_source": run.get("trigger_source"),
        "error_message": run.get("error_message"),
        "created_at": run.get("created_at"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "updated_at": run.get("updated_at"),
        "summary": run.get("summary") or {},
    }


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"true", "1", "yes", "on"}


def _parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    value = str(raw).strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        parts = value.split()
        if parts and parts[0][:3].lower() in {
            "mon",
            "tue",
            "wed",
            "thu",
            "fri",
            "sat",
            "sun",
        }:
            parts = parts[1:]
        timezone_token = parts[-1].upper() if len(parts) >= 3 else ""
        if timezone_token.isalpha():
            parts = parts[:-1]
        try:
            parsed = datetime.strptime(" ".join(parts), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        timezone_offsets = {
            "UTC": 0,
            "GMT": 0,
            "CST": 8,
            "CET": 1,
            "CEST": 2,
            "EST": -5,
            "EDT": -4,
            "MST": -7,
            "MDT": -6,
            "PST": -8,
            "PDT": -7,
            "AKST": -9,
            "AKDT": -8,
            "HST": -10,
        }
        if timezone_token:
            offset_hours = timezone_offsets.get(timezone_token)
            if offset_hours is None:
                return None
            parsed = parsed.replace(tzinfo=timezone(timedelta(hours=offset_hours)))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_env_float(names: tuple[str, ...], default: float) -> float:
    for name in names:
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return float(default)


def _timer_summary(timer: dict[str, Any]) -> dict[str, Any]:
    unit_file_state = str(timer.get("unit_file_state") or "").lower()
    return {
        "unit": "forecast-weekly.timer",
        "next_run_at": timer.get("next_elapse_realtime"),
        "active": timer.get("active_state") == "active",
        "enabled": unit_file_state in {
            "enabled",
            "enabled-runtime",
            "linked",
            "linked-runtime",
        },
    }


def _weekly_run_health(
    *,
    internal_scheduler_enabled: bool,
    timer_snapshot: dict[str, Any],
    weekly_service_snapshot: dict[str, Any],
    next_timer: dict[str, Any],
    last_scheduled_run: Optional[dict[str, Any]],
    active_runs: list[dict[str, Any]],
    captured_at: datetime,
    store_error: Optional[str],
) -> dict[str, Any]:
    degraded_reasons: list[str] = []
    unknown_reasons: list[str] = []

    if internal_scheduler_enabled:
        degraded_reasons.append("internal scheduler is enabled while systemd is authoritative")

    if not weekly_service_snapshot.get("available"):
        unknown_reasons.append("forecast-weekly.service state is unavailable")
    else:
        service_active_state = str(weekly_service_snapshot.get("active_state") or "").lower()
        service_result = str(weekly_service_snapshot.get("result") or "").lower()
        if service_active_state == "failed":
            degraded_reasons.append("forecast-weekly.service is failed")
        if service_result not in {"", "success"}:
            degraded_reasons.append(
                f"forecast-weekly.service result is {service_result}"
            )

    if not timer_snapshot.get("available"):
        unknown_reasons.append("forecast-weekly.timer state is unavailable")
    else:
        if not next_timer["active"]:
            degraded_reasons.append("forecast-weekly.timer is not active")
        if not next_timer["enabled"]:
            degraded_reasons.append("forecast-weekly.timer is not enabled")
        if not next_timer["next_run_at"]:
            degraded_reasons.append("forecast-weekly.timer has no next run time")

    if store_error:
        lowered = store_error.lower()
        if "locked" in lowered or "busy" in lowered or "timeout" in lowered:
            degraded_reasons.append(f"platform state database unavailable: {store_error}")
        else:
            unknown_reasons.append(f"platform state could not be inspected: {store_error}")

    try:
        stale_minutes = max(int(os.getenv("ACTIVE_RUN_STALE_MINUTES", "90")), 10)
    except ValueError:
        stale_minutes = 90
    for run in active_runs:
        reference = _parse_timestamp(
            run.get("updated_at") or run.get("started_at") or run.get("created_at")
        )
        if reference is not None and captured_at - reference > timedelta(minutes=stale_minutes):
            degraded_reasons.append(
                f"active run {run.get('id')} is stale beyond {stale_minutes} minutes"
            )

    if last_scheduled_run is None:
        unknown_reasons.append("no scheduled run history is available")
    else:
        status = str(last_scheduled_run.get("status") or "").lower()
        processed = int(last_scheduled_run.get("processed_count") or 0)
        total = int(last_scheduled_run.get("total_count") or 0)
        error_message = str(last_scheduled_run.get("error_message") or "")
        if status == "completed" and processed == total:
            max_age_days = max(
                _safe_env_float(
                    (
                        "FORECAST_WEEKLY_RUN_MAX_AGE_DAYS",
                        "FORECAST_SCHEDULE_HEALTH_MAX_AGE_DAYS",
                    ),
                    8.0,
                ),
                0.0,
            )
            completed_at = _parse_timestamp(
                last_scheduled_run.get("finished_at")
                or last_scheduled_run.get("updated_at")
                or last_scheduled_run.get("created_at")
            )
            if completed_at is None:
                unknown_reasons.append("latest completed scheduled run has no parseable timestamp")
            elif captured_at - completed_at > timedelta(days=max_age_days):
                degraded_reasons.append(
                    f"latest completed scheduled run is older than {max_age_days:g} days"
                )
        elif status in ACTIVE_RUN_STATUSES:
            unknown_reasons.append(
                f"latest scheduled run {last_scheduled_run.get('run_id')} is still {status}"
            )
        else:
            degraded_reasons.append(
                f"latest scheduled run ended as {status or 'unknown'} with {processed}/{total} processed"
            )
        if any(token in error_message.lower() for token in ("lock", "busy", "timeout", "timed out")):
            degraded_reasons.append(
                f"latest scheduled run reported an execution lock or timeout error: {error_message}"
            )

    last_timer_trigger = _parse_timestamp(timer_snapshot.get("last_trigger_realtime"))
    if last_timer_trigger is not None:
        scheduled_created_at = _parse_timestamp(
            last_scheduled_run.get("created_at") if last_scheduled_run else None
        )
        if scheduled_created_at is None:
            degraded_reasons.append(
                "forecast-weekly.timer triggered but no corresponding scheduled run exists"
            )
        elif scheduled_created_at < last_timer_trigger - timedelta(minutes=5):
            degraded_reasons.append(
                "forecast-weekly.timer last trigger is newer than the latest scheduled run"
            )

    if degraded_reasons:
        status = "degraded"
        reasons = degraded_reasons + unknown_reasons
    elif unknown_reasons:
        status = "unknown"
        reasons = unknown_reasons
    else:
        status = "healthy"
        reasons = []
    return {
        "status": status,
        "healthy": status == "healthy",
        "reasons": reasons,
        "max_completed_run_age_days": max(
            _safe_env_float(
                (
                    "FORECAST_WEEKLY_RUN_MAX_AGE_DAYS",
                    "FORECAST_SCHEDULE_HEALTH_MAX_AGE_DAYS",
                ),
                8.0,
            ),
            0.0,
        ),
    }


def _normalize_log_rows(rows: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "source": source,
                "timestamp": row.get("created_at"),
                "level": row.get("level", "info"),
                "message": row.get("message", ""),
            }
        )
    return normalized


def collect_linux_ops_snapshot(
    store: PlatformStore,
    current_run: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
    log_tail_limit: int = 120,
    systemctl_reader: Optional[Callable[[str], dict[str, Any]]] = None,
    file_tailer: Optional[Callable[[Optional[str], int], list[str]]] = None,
) -> dict[str, Any]:
    systemctl_reader = systemctl_reader or _run_systemctl
    file_tailer = file_tailer or tail_text_file
    store_error = None
    try:
        schedule_overview = build_schedule_overview(store, now=now)
    except Exception as exc:
        store_error = str(exc) or exc.__class__.__name__
        schedule_overview = {"schedules": [], "next_schedule": None}
    active_run = current_run if current_run and current_run.get("status") in ACTIVE_RUN_STATUSES else None

    try:
        recent_runs = store.list_runs(limit=500)
    except Exception as exc:
        recent_runs = []
        store_error = store_error or str(exc) or exc.__class__.__name__
    scheduled_runs = [run for run in recent_runs if run.get("trigger_source") == "schedule"]
    last_scheduled_run = _normalize_run_row(scheduled_runs[0]) if scheduled_runs else None
    active_runs = [run for run in recent_runs if run.get("status") in ACTIVE_RUN_STATUSES]

    if active_run:
        log_rows = store.get_logs(active_run["id"], limit=log_tail_limit)
        log_entries = _normalize_log_rows(log_rows, source=f"run:{active_run['id']}")
        log_source = {
            "kind": "run",
            "label": "运行日志",
            "run_id": active_run["id"],
            "status": active_run.get("status"),
        }
    else:
        log_entries: list[dict[str, Any]] = []
        for unit in SYSTEMD_UNITS:
            if not unit["log_path"]:
                continue
            lines = file_tailer(unit["log_path"], limit=max(20, log_tail_limit // 2))
            if not lines:
                continue
            for line in lines:
                log_entries.append(
                    {
                        "source": unit["unit"],
                        "timestamp": None,
                        "level": "info",
                        "message": line,
                    }
                )
        if len(log_entries) > log_tail_limit:
            log_entries = log_entries[-log_tail_limit:]
        log_source = {
            "kind": "service",
            "label": "服务日志",
            "run_id": None,
            "status": "idle",
        }

    services = []
    for unit in SYSTEMD_UNITS:
        service_snapshot = systemctl_reader(unit["unit"])
        services.append(
            {
                **service_snapshot,
                "label": unit["label"],
                "log_path": unit["log_path"],
            }
        )

    timer_snapshot = next(
        (service for service in services if service.get("unit") == "forecast-weekly.timer"),
        {
            "unit": "forecast-weekly.timer",
            "available": False,
            "active_state": "unknown",
            "unit_file_state": "unknown",
            "next_elapse_realtime": None,
        },
    )
    weekly_service_snapshot = next(
        (service for service in services if service.get("unit") == "forecast-weekly.service"),
        {
            "unit": "forecast-weekly.service",
            "available": False,
            "active_state": "unknown",
            "result": None,
        },
    )
    next_timer = _timer_summary(timer_snapshot)
    captured_at = now or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    else:
        captured_at = captured_at.astimezone(timezone.utc)
    internal_scheduler_enabled = _env_enabled("FORECAST_INTERNAL_SCHEDULER_ENABLED")

    return {
        "captured_at": utcnow_iso(),
        "scheduler_authority": "systemd",
        "internal_scheduler_enabled": internal_scheduler_enabled,
        "current_run": _normalize_run_row(active_run) if active_run else None,
        "last_scheduled_run": last_scheduled_run,
        "services": services,
        "next_timer": next_timer,
        "next_schedule": schedule_overview["next_schedule"],
        "schedules": schedule_overview["schedules"],
        "weekly_run_health": _weekly_run_health(
            internal_scheduler_enabled=internal_scheduler_enabled,
            timer_snapshot=timer_snapshot,
            weekly_service_snapshot=weekly_service_snapshot,
            next_timer=next_timer,
            last_scheduled_run=last_scheduled_run,
            active_runs=active_runs,
            captured_at=captured_at,
            store_error=store_error,
        ),
        "logs": {
            "source": log_source,
            "entries": log_entries,
        },
    }
