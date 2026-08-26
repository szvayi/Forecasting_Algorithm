from fastapi.testclient import TestClient

from src.api.platform_store import PlatformStore
from src.api.runtime import ForecastRuntimeManager


def test_platform_store_config_roundtrip(tmp_path):
    store = PlatformStore(str(tmp_path / "platform_state.db"))
    config = store.create_config(
        name="Weekly Core SPUs",
        purpose="Ops review",
        mode="smart",
        selection_type="all",
        selection_payload={},
    )
    fetched = store.get_config(config["id"])
    assert fetched is not None
    assert fetched["name"] == "Weekly Core SPUs"
    assert fetched["selection_type"] == "all"
    assert fetched["selection_payload"] == {}


def test_fastapi_app_has_platform_routes():
    from src.api.app import app

    paths = {route.path for route in app.routes}
    assert "/api/forecast-jobs" in paths
    assert "/api/forecast-configs" in paths
    assert "/api/forecast-schedules" in paths
    assert "/api/linux-ops" in paths


def test_linux_ops_api_uses_snapshot_helper(tmp_path, monkeypatch):
    import src.api.app as app_module

    original_store = app_module.store
    monkeypatch.setattr(app_module, "store", PlatformStore(str(tmp_path / "platform_state.db")))

    def stub_snapshot(store, current_run=None, **kwargs):
        return {
            "captured_at": "2026-04-01T00:00:00Z",
            "current_run": None,
            "services": [],
            "next_schedule": None,
            "schedules": [],
            "logs": {"source": {"kind": "service", "label": "Service logs"}, "entries": []},
        }

    monkeypatch.setattr(app_module, "collect_linux_ops_snapshot", stub_snapshot)

    client = TestClient(app_module.app)
    response = client.get("/api/linux-ops")
    assert response.status_code == 200
    assert response.json()["logs"]["source"]["label"] == "Service logs"

    monkeypatch.setattr(app_module, "store", original_store)


def test_frontend_entry_hides_manual_and_sql_controls():
    from src.api.app import app

    client = TestClient(app)
    response = client.get("/control-platform")

    assert response.status_code == 200
    assert 'data-selection="manual"' not in response.text
    assert 'data-selection="sql"' not in response.text
    assert 'id="manualInput"' not in response.text
    assert 'id="sqlInput"' not in response.text


def test_compatibility_analysis_status_idle_state(tmp_path, monkeypatch):
    import src.api.app as app_module

    original_store = app_module.store
    monkeypatch.setattr(app_module, "store", PlatformStore(str(tmp_path / "platform_state.db")))

    client = TestClient(app_module.app)
    response = client.get("/api/analysis-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] is None
    assert payload["status"] == "idle"
    assert payload["scope_min_weeks"] == 108
    assert payload["scope_total_spus"] == 0
    assert payload["scope_eligible_spus"] == 0
    assert payload["scope_excluded_spus"] == 0

    monkeypatch.setattr(app_module, "store", original_store)


def test_selection_api_rejects_manual_and_sql_modes():
    from src.api.app import app

    client = TestClient(app)

    manual_response = client.post("/api/spu-selection/resolve", json={"selection_type": "manual"})
    sql_response = client.post("/api/spu-selection/resolve", json={"selection_type": "sql"})

    assert manual_response.status_code == 422
    assert sql_response.status_code == 422


def test_create_config_and_schedule_via_api(tmp_path, monkeypatch):
    import src.api.app as app_module

    original_store = app_module.store
    test_store = PlatformStore(str(tmp_path / "platform_state.db"))
    monkeypatch.setattr(app_module, "store", test_store)

    client = TestClient(app_module.app)
    config_resp = client.post(
        "/api/forecast-configs",
        json={
            "name": "Weekly Core SPUs",
            "purpose": "Ops review",
            "mode": "smart",
            "selection_type": "all",
        },
    )
    assert config_resp.status_code == 200
    config = config_resp.json()
    assert config["selection_payload"] == {}

    schedule_resp = client.post(
        "/api/forecast-schedules",
        json={
            "config_id": config["id"],
            "weekday": 0,
            "hour": 9,
            "minute": 0,
            "timezone": "Asia/Shanghai",
            "enabled": True,
        },
    )
    assert schedule_resp.status_code == 200
    assert schedule_resp.json()["config_id"] == config["id"]

    monkeypatch.setattr(app_module, "store", original_store)


def test_create_job_api_with_stubbed_manager(monkeypatch):
    import src.api.app as app_module

    class StubManager:
        def create_run(self, mode, selection_type, selection_payload, config_id=None):
            return {
                "id": "run_test_001",
                "mode": mode,
                "selection_type": selection_type,
                "selection_payload": selection_payload,
                "selected_spus": ["SPU001", "SPU002"],
                "status": "queued",
                "progress": 0,
                "processed_count": 0,
                "total_count": 2,
                "success_count": 0,
                "current_spu": None,
                "summary": {},
            }

    monkeypatch.setattr(app_module, "manager", StubManager())
    client = TestClient(app_module.app)
    response = client.post(
        "/api/forecast-jobs",
        json={"mode": "smart", "selection_type": "all"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run_test_001"
    assert payload["run"]["selection_payload"] == {}


def test_manager_create_run_emits_immediate_queue_feedback(monkeypatch, tmp_path):
    import src.api.runtime as runtime_module

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    manager = runtime_module.ForecastRuntimeManager(store=store, db_url="sqlite:///demo")
    thread_started = {"value": False}

    class DummyThread:
        def __init__(self, target, args=(), daemon=False):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            thread_started["value"] = True

    monkeypatch.setattr(runtime_module.threading, "Thread", DummyThread)

    run = manager.create_run(
        mode="smart",
        selection_type="all",
        selection_payload={},
        config_id=None,
        trigger_source="manual",
    )

    logs = store.get_logs(run["id"], limit=10)

    assert thread_started["value"] is True
    assert run["status"] == "queued"
    assert run["current_spu"] == "等待启动"
    assert logs and "accepted and queued" in logs[0]["message"]


def test_compatibility_status_and_logs_endpoints(tmp_path, monkeypatch):
    import src.api.app as app_module

    original_store = app_module.store
    test_store = PlatformStore(str(tmp_path / "platform_state.db"))
    monkeypatch.setattr(app_module, "store", test_store)

    run = test_store.create_run(
        config_id=None,
        trigger_source="manual",
        mode="smart",
        selection_type="all",
        selection_payload={},
        selected_spus=["SPU001"],
    )
    test_store.update_run(
        run["id"],
        status="running",
        progress=45,
        processed_count=3,
        total_count=8,
        success_count=2,
        current_spu="SPU001",
    )
    test_store.add_log(run["id"], "info", "Run started")

    client = TestClient(app_module.app)
    status_resp = client.get("/api/analysis-status")
    logs_resp = client.get("/api/analysis-logs")
    spus_resp = client.get("/api/completed-spus")

    assert status_resp.status_code == 200
    assert status_resp.json()["progress"] == 45
    assert logs_resp.status_code == 200
    assert logs_resp.json()["logs"][0]["message"] == "Run started"
    assert spus_resp.status_code == 200
    assert spus_resp.json()["completed_spus"] == []

    monkeypatch.setattr(app_module, "store", original_store)


def test_compatibility_start_analysis_defaults_to_all(monkeypatch):
    import src.api.app as app_module

    class StubManager:
        def create_run(self, mode, selection_type, selection_payload, config_id=None, trigger_source="manual"):
            assert mode == "smart"
            assert selection_type == "all"
            assert selection_payload == {}
            assert config_id is None
            assert trigger_source == "manual"
            return {
                "id": "run_legacy_001",
                "mode": mode,
                "status": "queued",
                "trigger_source": trigger_source,
                "progress": 0,
                "current_spu": "等待启动",
            }

    monkeypatch.setattr(app_module, "manager", StubManager())
    client = TestClient(app_module.app)
    response = client.post("/api/start-analysis", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run_legacy_001"
    assert payload["mode"] == "smart"
    assert payload["trigger_source"] == "manual"
    assert payload["status"] == "queued"
    assert payload["message"] == "Analysis queued."


def test_stop_analysis_uses_latest_run(tmp_path, monkeypatch):
    import src.api.app as app_module

    original_store = app_module.store
    test_store = PlatformStore(str(tmp_path / "platform_state.db"))
    monkeypatch.setattr(app_module, "store", test_store)

    run = test_store.create_run(
        config_id=None,
        trigger_source="schedule",
        mode="smart",
        selection_type="all",
        selection_payload={},
        selected_spus=["SPU001"],
    )
    test_store.update_run(run["id"], status="running", total_count=1)

    class StubManager:
        def stop_run(self, run_id):
            assert run_id == run["id"]
            test_store.update_run(run_id, status="stopping")
            return test_store.get_run(run_id)

    monkeypatch.setattr(app_module, "manager", StubManager())

    client = TestClient(app_module.app)
    response = client.post("/api/stop-analysis")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == run["id"]
    assert payload["status"] == "stopping"

    monkeypatch.setattr(app_module, "store", original_store)


def test_results_api_with_stubbed_manager(monkeypatch):
    import src.api.app as app_module

    class StubManager:
        def get_results(self, **filters):
            assert filters["run_id"] == "run_123"
            assert filters["limit"] == 25
            return [
                {
                    "spu": "SPU001",
                    "run_date": "2026-03-20",
                    "forecast_target_date": "2026-03-27",
                    "spu_forecast_value": 123.4,
                    "winner_algo": "Prophet",
                    "validation_wmape": 0.12,
                    "run_id": "run_123",
                    "config_id": None,
                }
            ]

    monkeypatch.setattr(app_module, "manager", StubManager())
    client = TestClient(app_module.app)
    response = client.get("/api/forecast-results", params={"run_id": "run_123", "limit": 25})
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["spu"] == "SPU001"
    assert payload[0]["winner_algo"] == "Prophet"


def test_project_management_dashboard_route():
    from src.api.app import app

    client = TestClient(app)
    response = client.get("/pm")
    assert response.status_code == 200
    assert "pm-dashboard.js" in response.text


def test_manager_rejects_manual_and_sql_selection_types(tmp_path):
    store = PlatformStore(str(tmp_path / "platform_state.db"))
    manager = ForecastRuntimeManager(store=store, db_url="sqlite:///ignored.db")

    for selection_type in ("manual", "sql"):
        try:
            manager.resolve_selection(selection_type, {})
            assert False, "Expected ValueError"
        except ValueError as exc:
            assert "standard all selection workflow" in str(exc)


def test_all_selection_applies_unified_scope_rules(monkeypatch, tmp_path):
    import pandas as pd
    import src.api.runtime as runtime_module

    weekly_dates = list(pd.date_range("2024-01-07", periods=12, freq="W"))
    df = pd.DataFrame(
        {
            "date": weekly_dates * 5,
            "spu": ["SPU001"] * 12 + ["SPU002"] * 12 + ["SPU003"] * 12 + ["SPU004"] * 12 + ["SPU005"] * 12,
            "sales": (
                [5] * 12
                + [5] * 8 + [0] * 4
                + [5] * 11 + [3]
                + [5, 0, 5, 0, 5, 0, 5, 0, 5, 0, 5, 0]
                + [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
            ),
            "sku": ["SKU001"] * 60,
        }
    )

    monkeypatch.setattr(runtime_module, "get_data_from_db", lambda _db_url: df)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_MIN_WEEKS", 1)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_RECENT_WEEKS", 4)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_RECENT_NON_ZERO_WEEKS", 8)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_RECENT_WINDOW_WEEKS", 12)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_MAX_ZERO_RATIO_26W", 0.25)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_MIN_RECENT4_TOTAL_SALES", 4.0)

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    manager = ForecastRuntimeManager(store=store, db_url="sqlite:///ignored.db")

    result = manager.resolve_selection("all", {})

    assert result["selected_spus"] == ["SPU001", "SPU003"]
    assert result["count"] == 2
    assert result["scope_total_spus"] == 5
    assert result["scope_eligible_spus"] == 2
    assert result["scope_excluded_spus"] == 3


def test_all_selection_ignores_trailing_empty_weeks(monkeypatch, tmp_path):
    import pandas as pd
    import src.api.runtime as runtime_module

    weekly_dates = list(pd.date_range("2024-01-07", periods=16, freq="W"))
    sales = [5] * 12 + [0, 0, 0, 0]
    df = pd.DataFrame(
        {
            "date": weekly_dates,
            "spu": ["SPU001"] * 16,
            "sales": sales,
            "sku": ["SKU001"] * 16,
        }
    )

    monkeypatch.setattr(runtime_module, "get_data_from_db", lambda _db_url: df)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_MIN_WEEKS", 1)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_RECENT_WEEKS", 4)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_RECENT_NON_ZERO_WEEKS", 8)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_RECENT_WINDOW_WEEKS", 12)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_MAX_ZERO_RATIO_26W", 0.5)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_MIN_RECENT4_TOTAL_SALES", 4.0)

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    manager = ForecastRuntimeManager(store=store, db_url="sqlite:///ignored.db")

    result = manager.resolve_selection("all", {})

    assert result["selected_spus"] == ["SPU001"]
    assert result["count"] == 1
