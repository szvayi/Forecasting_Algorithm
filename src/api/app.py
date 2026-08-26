import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.api.platform_store import ActiveRunConflict, PlatformStore, ScheduleSlotConflict
from src.api.linux_ops import ACTIVE_RUN_STATUSES, build_schedule_overview, collect_linux_ops_snapshot
from src.api.run_lock import DEFAULT_EXECUTION_LOCK_PATH, RunLockBusy
from src.api.runtime import DEFAULT_SCOPE_MIN_WEEKS, ForecastRuntimeManager, VALID_MODES


project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
frontend_root = os.path.join(project_root, "frontend")
static_root = os.path.join(project_root, "static")
dashboard_v2_path = os.path.join(project_root, "forecast_dashboard_v2.html")
platform_db = os.path.join(project_root, "data", "platform_state.db")
weekly_schedule_path = os.path.join(project_root, "data", "weekly_schedule.json")
db_url = os.getenv("SALES_FORECAST_DB_URL", "").strip()

store = PlatformStore(platform_db)
manager = ForecastRuntimeManager(
    store=store,
    db_url=db_url,
    execution_lock_path=DEFAULT_EXECUTION_LOCK_PATH,
)
HISTORY_WINDOW_HOURS = int(os.getenv("FORECAST_HISTORY_WINDOW_HOURS", "24"))
CONFLICT_EXCEPTIONS = (ActiveRunConflict, ScheduleSlotConflict, RunLockBusy)


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"true", "1", "yes", "on"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    internal_scheduler_enabled = _env_enabled("FORECAST_INTERNAL_SCHEDULER_ENABLED")
    if internal_scheduler_enabled:
        manager.start_scheduler()
    try:
        yield
    finally:
        try:
            if internal_scheduler_enabled:
                manager.stop_scheduler()
        finally:
            shutdown_active_runs = getattr(manager, "shutdown_active_runs", None)
            if shutdown_active_runs is not None:
                shutdown_active_runs(
                    reason="API process shutdown terminalized a locally owned forecast run.",
                    join_timeout=5.0,
                )


app = FastAPI(
    title="Forecast Platform API",
    description="Configurable forecast execution platform",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=static_root), name="static")


class SelectionResolveRequest(BaseModel):
    selection_type: str = Field(default="all", pattern="^all$")


class JobCreateRequest(BaseModel):
    mode: str = "smart"
    selection_type: str = Field(default="all", pattern="^all$")
    config_id: Optional[str] = None


class LegacyStartRequest(BaseModel):
    mode: str = "smart"
    selection_type: str = Field(default="all", pattern="^all$")
    config_id: Optional[str] = None


class ConfigCreateRequest(BaseModel):
    name: str
    purpose: str = ""
    mode: str = "smart"
    selection_type: str = Field(default="all", pattern="^all$")
    is_active: bool = True


class ScheduleUpsertRequest(BaseModel):
    config_id: str
    weekday: int = Field(ge=0, le=6)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    timezone: str = "Asia/Shanghai"
    enabled: bool = True


class WeeklyScheduleRequest(BaseModel):
    weekday: int = Field(ge=0, le=6)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    timezone: str = "Asia/Shanghai"
    enabled: bool = True


def _selection_payload(request: Any):
    return {}


def _default_weekly_schedule() -> dict[str, Any]:
    return {
        "weekday": 0,
        "hour": 1,
        "minute": 0,
        "timezone": "Asia/Shanghai",
        "enabled": True,
        "display_text": "每周一 01:00",
        "linux_timer_sync_required": True,
    }


def _hydrate_weekly_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = int(payload.get("weekday", 0))
    hour = int(payload.get("hour", 1))
    minute = int(payload.get("minute", 0))
    enabled = bool(payload.get("enabled", True))
    return {
        "weekday": weekday,
        "hour": hour,
        "minute": minute,
        "timezone": payload.get("timezone", "Asia/Shanghai"),
        "enabled": enabled,
        "display_text": f"{weekdays[weekday]} {hour:02d}:{minute:02d}",
        "linux_timer_sync_required": True,
    }


def _read_weekly_schedule() -> dict[str, Any]:
    if not os.path.exists(weekly_schedule_path):
        return _default_weekly_schedule()
    try:
        with open(weekly_schedule_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return _default_weekly_schedule()
    return _hydrate_weekly_schedule(raw)


def _write_weekly_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    os.makedirs(os.path.dirname(weekly_schedule_path), exist_ok=True)
    schedule = _hydrate_weekly_schedule(payload)
    with open(weekly_schedule_path, "w", encoding="utf-8") as fh:
        json.dump(schedule, fh, ensure_ascii=False, indent=2)
    return schedule


def _preferred_run(run_id: Optional[str] = None):
    if run_id:
        return store.get_run(run_id)
    runs = [run for run in store.list_runs(limit=200) if not _is_history_run(run)]
    for preferred_status in ("running", "queued", "stopping"):
        for run in runs:
            if run["status"] == preferred_status:
                return run
    return runs[0] if runs else None


def _preferred_active_run(run_id: Optional[str] = None):
    run = _preferred_run(run_id)
    if run and run.get("status") in ACTIVE_RUN_STATUSES:
        return run
    return None


def _parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    # Normalize sqlite/ISO variants:
    # - "2026-04-13T03:21:52Z"
    # - "2026-04-13 03:21:50"
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    if " " in value and "T" not in value:
        value = value.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _run_reference_time(run: dict[str, Any]) -> Optional[datetime]:
    for key in ("updated_at", "finished_at", "started_at", "created_at"):
        parsed = _parse_timestamp(run.get(key))
        if parsed is not None:
            return parsed
    return None


def _is_history_run(run: dict[str, Any]) -> bool:
    reference = _run_reference_time(run)
    if reference is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HISTORY_WINDOW_HOURS)
    return reference < cutoff


def _legacy_status_payload(run: Optional[dict[str, Any]]):
    if not run:
        return {
            "run_id": None,
            "status": "idle",
            "progress": 0,
            "processed_count": 0,
            "total_count": 0,
            "success_count": 0,
            "current_spu": None,
            "mode": "smart",
            "trigger_source": None,
            "error": None,
            "error_message": None,
            "scope_min_weeks": DEFAULT_SCOPE_MIN_WEEKS,
            "scope_total_spus": 0,
            "scope_eligible_spus": 0,
            "scope_excluded_spus": 0,
        }
    error_message = run.get("error_message")
    summary = run.get("summary", {}) or {}
    selected_spus = run.get("selected_spus", []) or []
    if run.get("selection_type") == "all" and "scope_total_spus" not in summary:
        try:
            resolved = manager.resolve_selection("all", {})
            summary = {
                **summary,
                "scope_total_spus": resolved.get("scope_total_spus", len(selected_spus)),
                "scope_eligible_spus": resolved.get("scope_eligible_spus", len(selected_spus)),
                "scope_excluded_spus": resolved.get("scope_excluded_spus", 0),
                "scope_min_weeks": DEFAULT_SCOPE_MIN_WEEKS,
            }
        except Exception:
            pass
    scope_eligible_spus = summary.get("scope_eligible_spus", len(selected_spus))
    scope_total_spus = summary.get("scope_total_spus", scope_eligible_spus)
    return {
        "run_id": run["id"],
        "status": run["status"],
        "progress": run["progress"],
        "processed_count": run["processed_count"],
        "total_count": run["total_count"],
        "success_count": run["success_count"],
        "current_spu": run["current_spu"],
        "mode": run["mode"],
        "trigger_source": run.get("trigger_source"),
        "error": error_message,
        "error_message": error_message,
        "scope_min_weeks": summary.get("scope_min_weeks", DEFAULT_SCOPE_MIN_WEEKS),
        "scope_total_spus": scope_total_spus,
        "scope_eligible_spus": scope_eligible_spus,
        "scope_excluded_spus": summary.get(
            "scope_excluded_spus",
            max(scope_total_spus - scope_eligible_spus, 0),
        ),
    }


def _legacy_log_payloads(run_id: str, limit: int = 200):
    rows = store.get_logs(run_id, limit=limit)
    return [
        {
            "timestamp": row["created_at"],
            "type": row["level"],
            "message": row["message"],
        }
        for row in rows
    ]

@app.get("/")
async def root():
    if not os.path.exists(dashboard_v2_path):
        raise HTTPException(status_code=404, detail="forecast_dashboard_v2.html not found.")
    return FileResponse(dashboard_v2_path)


@app.get("/control-platform")
async def control_platform():
    path = os.path.join(frontend_root, "index.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Frontend entry file not found.")
    return FileResponse(path)

@app.get("/pm")
async def project_management_dashboard():
    path = os.path.join(frontend_root, "pm_dashboard.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Project management dashboard file not found.")
    return FileResponse(path)

@app.get("/design-review")
async def design_review_page():
    path = os.path.join(frontend_root, "design_review.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Design review page file not found.")
    return FileResponse(path)


@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/api/spu-selection/resolve")
async def resolve_spu_selection(request: SelectionResolveRequest):
    try:
        return manager.resolve_selection(request.selection_type, _selection_payload(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/forecast-jobs")
async def create_forecast_job(request: JobCreateRequest):
    if request.mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail="mode must be one of fast, smart, full")
    try:
        run = manager.create_run(
            mode=request.mode,
            selection_type=request.selection_type,
            selection_payload=_selection_payload(request),
            config_id=request.config_id,
        )
        return {"run_id": run["id"], "run": run}
    except CONFLICT_EXCEPTIONS as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/forecast-jobs")
async def list_forecast_jobs(limit: int = 20, include_history: bool = True):
    runs = store.list_runs(limit=max(limit, 1))
    if include_history:
        return runs[:limit]
    return [run for run in runs if not _is_history_run(run)][:limit]


@app.get("/api/forecast-jobs/history")
async def list_forecast_job_history(limit: int = 50):
    runs = store.list_runs(limit=max(limit * 5, 100))
    history_runs = [run for run in runs if _is_history_run(run)]
    return history_runs[:limit]


@app.get("/api/forecast-jobs/{run_id}")
async def get_forecast_job(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@app.get("/api/forecast-jobs/{run_id}/spus")
async def get_forecast_job_spus(run_id: str):
    return store.get_run_spus(run_id)


@app.get("/api/forecast-jobs/{run_id}/logs")
async def get_forecast_job_logs(run_id: str, limit: int = 200):
    return store.get_logs(run_id, limit=limit)


@app.post("/api/forecast-jobs/{run_id}/stop")
async def stop_forecast_job(run_id: str):
    try:
        return manager.stop_run(run_id)
    except CONFLICT_EXCEPTIONS as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/forecast-results")
async def get_forecast_results(
    run_id: Optional[str] = None,
    config_id: Optional[str] = None,
    spu: Optional[str] = None,
    run_date: Optional[str] = None,
    limit: int = 500,
):
    try:
        return manager.get_results(
            run_id=run_id,
            config_id=config_id,
            spu=spu,
            run_date=run_date,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/forecast-configs")
async def create_forecast_config(request: ConfigCreateRequest):
    if request.mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail="mode must be one of fast, smart, full")
    try:
        resolved = manager.resolve_selection(request.selection_type, _selection_payload(request))
        return store.create_config(
            name=request.name,
            purpose=request.purpose,
            mode=request.mode,
            selection_type=resolved["selection_type"],
            selection_payload=resolved["selection_payload"],
            is_active=request.is_active,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/forecast-configs")
async def list_forecast_configs():
    return store.list_configs()


@app.post("/api/forecast-configs/{config_id}/run")
async def run_forecast_config(config_id: str):
    try:
        run = manager.run_from_config(config_id)
        return {"run_id": run["id"], "run": run}
    except CONFLICT_EXCEPTIONS as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/forecast-schedules")
async def upsert_forecast_schedule(request: ScheduleUpsertRequest):
    config = store.get_config(request.config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found.")
    return store.create_or_update_schedule(
        config_id=request.config_id,
        weekday=request.weekday,
        hour=request.hour,
        minute=request.minute,
        timezone=request.timezone,
        enabled=request.enabled,
    )


@app.get("/api/forecast-schedules")
async def list_forecast_schedules():
    return build_schedule_overview(store)["schedules"]


@app.get("/api/linux-ops")
async def get_linux_ops(run_id: Optional[str] = None):
    return collect_linux_ops_snapshot(store, current_run=_preferred_active_run(run_id))


@app.get("/api/weekly-schedule")
async def get_weekly_schedule():
    return _read_weekly_schedule()


@app.post("/api/weekly-schedule")
async def save_weekly_schedule(request: WeeklyScheduleRequest):
    return _write_weekly_schedule(request.model_dump())


@app.post("/api/start-analysis")
async def compatibility_start_analysis(request: LegacyStartRequest):
    if request.mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail="mode must be one of fast, smart, full")
    try:
        if request.config_id:
            run = manager.run_from_config(request.config_id, trigger_source="manual")
        else:
            run = manager.create_run(
                mode=request.mode,
                selection_type=request.selection_type or "all",
                selection_payload=_selection_payload(request),
                config_id=None,
                trigger_source="manual",
            )
        return {
            "message": "Analysis queued.",
            "status": run.get("status", "queued"),
            "mode": run["mode"],
            "run_id": run["id"],
            "trigger_source": run.get("trigger_source"),
            "progress": run.get("progress"),
            "current_spu": run.get("current_spu"),
        }
    except CONFLICT_EXCEPTIONS as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/stop-analysis")
async def compatibility_stop_analysis(run_id: Optional[str] = None):
    run = _preferred_run(run_id)
    if not run:
        raise HTTPException(status_code=400, detail="No analysis run found.")
    try:
        updated = manager.stop_run(run["id"])
        return {
            "message": "Analysis stop requested.",
            "status": updated["status"],
            "run_id": updated["id"],
        }
    except CONFLICT_EXCEPTIONS as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/analysis-status")
async def compatibility_analysis_status(run_id: Optional[str] = None):
    return _legacy_status_payload(_preferred_run(run_id))


@app.get("/api/analysis-logs")
async def compatibility_analysis_logs(run_id: Optional[str] = None, limit: int = 200):
    run = _preferred_run(run_id)
    if not run:
        return {"logs": []}
    return {"run_id": run["id"], "logs": _legacy_log_payloads(run["id"], limit=limit)}


@app.get("/api/completed-spus")
async def compatibility_completed_spus(run_id: Optional[str] = None):
    run = _preferred_run(run_id)
    if not run:
        return {"completed_spus": []}
    spus = store.get_run_spus(run["id"])
    completed = [
        {
            "spu": row["spu"],
            "status": row["status"],
            "message": row.get("message"),
            "winner_algo": row.get("winner_algo"),
            "validation_wmape": row.get("validation_wmape"),
            "updated_at": row.get("updated_at"),
        }
        for row in spus
        if row["status"] in {"completed", "failed"}
    ]
    return {"run_id": run["id"], "completed_spus": completed}


@app.get("/api/runs/latest")
async def latest_run():
    run = _preferred_run()
    if not run:
        return {"run": None}
    return {"run": run}
