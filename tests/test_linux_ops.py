from datetime import datetime

from src.api.linux_ops import build_schedule_overview, collect_linux_ops_snapshot
from src.api.platform_store import PlatformStore


def test_build_schedule_overview_includes_next_run_text(tmp_path):
    store = PlatformStore(str(tmp_path / "platform_state.db"))
    config = store.create_config(
        name="Weekly Core SPUs",
        purpose="Linux weekly run",
        mode="smart",
        selection_type="all",
        selection_payload={},
    )
    store.create_or_update_schedule(
        config_id=config["id"],
        weekday=0,
        hour=9,
        minute=0,
        timezone="Asia/Shanghai",
        enabled=True,
    )

    overview = build_schedule_overview(
        store,
        now=datetime(2026, 4, 1, 8, 0),
    )

    assert overview["next_schedule"] is not None
    assert overview["next_schedule"]["config_name"] == "Weekly Core SPUs"
    assert overview["schedules"][0]["next_run_text"]


def test_collect_linux_ops_snapshot_uses_run_logs_when_active(tmp_path):
    store = PlatformStore(str(tmp_path / "platform_state.db"))
    run = store.create_run(
        config_id=None,
        trigger_source="manual",
        mode="smart",
        selection_type="all",
        selection_payload={},
        selected_spus=["SPU001"],
    )
    store.update_run(run["id"], status="running", progress=10, total_count=1)
    store.add_log(run["id"], "info", "Run started")

    snapshot = collect_linux_ops_snapshot(
        store,
        current_run=store.get_run(run["id"]),
        systemctl_reader=lambda unit: {
            "unit": unit,
            "available": True,
            "active_state": "active",
            "sub_state": "running",
            "unit_file_state": "enabled",
            "status_text": "active / running",
        },
        file_tailer=lambda path, limit: [],
    )

    assert snapshot["logs"]["source"]["kind"] == "run"
    assert snapshot["logs"]["entries"][0]["message"] == "Run started"
    assert len(snapshot["services"]) == 3
    assert snapshot["services"][0]["label"] == "Forecast Dashboard V2 API"
    assert snapshot["services"][0]["log_path"] == "/var/log/forecast-dashboard-v2.log"


def test_collect_linux_ops_snapshot_exposes_service_metadata(tmp_path):
    store = PlatformStore(str(tmp_path / "platform_state.db"))

    snapshot = collect_linux_ops_snapshot(
        store,
        current_run=None,
        systemctl_reader=lambda unit: {
            "unit": unit,
            "available": True,
            "active_state": "inactive",
            "sub_state": "dead",
            "unit_file_state": "enabled",
            "status_text": "inactive / dead",
        },
        file_tailer=lambda path, limit: [],
    )

    assert snapshot["services"][1]["label"] == "Weekly Forecast Job"
    assert snapshot["services"][1]["log_path"] == "/var/log/forecast-weekly.log"


def test_collect_linux_ops_snapshot_falls_back_to_service_logs(tmp_path):
    store = PlatformStore(str(tmp_path / "platform_state.db"))

    snapshot = collect_linux_ops_snapshot(
        store,
        current_run=None,
        systemctl_reader=lambda unit: {
            "unit": unit,
            "available": True,
            "active_state": "inactive",
            "sub_state": "dead",
            "unit_file_state": "enabled",
            "status_text": "inactive / dead",
        },
        file_tailer=lambda path, limit: [f"log from {path}"] if path else [],
    )

    assert snapshot["logs"]["source"]["kind"] == "service"
    assert snapshot["logs"]["entries"]
    assert snapshot["logs"]["entries"][0]["message"].startswith("log from ")
