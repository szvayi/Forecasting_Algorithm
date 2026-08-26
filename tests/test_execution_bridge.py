def test_execution_bridge_reexports_kernel_api(monkeypatch):
    import src.forecasting.execution_bridge as bridge

    monkeypatch.setattr(bridge.forecast_kernel, "get_data_from_db", lambda db_url: f"bridge:{db_url}")
    monkeypatch.setattr(bridge.forecast_kernel, "process_single_spu", lambda *args, **kwargs: ("result", None, None, None))
    monkeypatch.setattr(bridge.forecast_kernel, "save_to_database", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge.forecast_kernel, "main", lambda: "bridge-main")

    assert bridge.get_data_from_db("sqlite:///demo") == "bridge:sqlite:///demo"
    assert bridge.process_single_spu("SPU001", {"a": 1}) == ("result", None, None, None)
    assert bridge.save_to_database([1, 2, 3], "sqlite:///demo") is None
    assert bridge.main() == "bridge-main"


def test_runtime_uses_execution_bridge(monkeypatch, tmp_path):
    import pandas as pd
    import src.api.runtime as runtime_module
    from src.api.platform_store import PlatformStore

    df = pd.DataFrame(
        {
            "date": list(pd.date_range("2024-01-07", periods=12, freq="W")) * 3,
            "spu": ["SPU001"] * 12 + ["SPU002"] * 12 + ["SPU003"] * 12,
            "sales": [10] * 12 + [10] * 8 + [0] * 4 + [0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 2],
            "sku": ["SKU001"] * 36,
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
    manager = runtime_module.ForecastRuntimeManager(store=store, db_url="sqlite:///demo")
    spus, total = manager._load_all_spus_with_scope()

    assert spus == ["SPU001"]
    assert total == 3


def test_runtime_create_run_is_non_blocking(monkeypatch, tmp_path):
    import src.api.runtime as runtime_module
    from src.api.platform_store import PlatformStore

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    manager = runtime_module.ForecastRuntimeManager(store=store, db_url="sqlite:///demo")

    called = {"resolve": 0, "thread_started": False}

    def boom(*args, **kwargs):
        called["resolve"] += 1
        raise AssertionError("resolve_selection should not be called inline")

    class DummyThread:
        def __init__(self, target, args=(), daemon=False):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            called["thread_started"] = True

    monkeypatch.setattr(manager, "resolve_selection", boom)
    monkeypatch.setattr(runtime_module.threading, "Thread", DummyThread)

    run = manager.create_run(
        mode="smart",
        selection_type="all",
        selection_payload={},
        config_id=None,
    )

    assert called["resolve"] == 0
    assert called["thread_started"] is True
    assert run["status"] == "queued"
    assert run["selected_spus"] == []


def test_runtime_captures_model_competition_logs(monkeypatch, tmp_path):
    import pandas as pd
    import src.api.runtime as runtime_module
    from src.api.platform_store import PlatformStore

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-07", periods=12, freq="W"),
            "spu": ["SPU001"] * 12,
            "sales": [10] * 12,
            "sku": ["SKU001"] * 12,
        }
    )

    def stub_process_single_spu(spu, df_spu, **kwargs):
        log_fn = kwargs.get("log_fn")
        if log_fn is not None:
            log_fn("SPU001 model competition starting, train=8 weeks, test=4 weeks.")
            log_fn("SPU001 | 运行 Prophet...")
            log_fn("SPU001 | Prophet: WMAPE=12.34%")
        result_df = pd.DataFrame(
            {
                "spu": [spu],
                "winner_algo": ["Prophet"],
                "validation_wmape": [0.1234],
            }
        )
        return result_df, "Prophet (WMAPE: 12.34%) [1.0s]", None, None

    monkeypatch.setattr(runtime_module, "get_data_from_db", lambda _db_url: df)
    monkeypatch.setattr(runtime_module, "process_single_spu", stub_process_single_spu)
    monkeypatch.setattr(runtime_module, "save_to_database", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_MIN_WEEKS", 1)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_RECENT_WEEKS", 4)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_RECENT_NON_ZERO_WEEKS", 8)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_RECENT_WINDOW_WEEKS", 12)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_MAX_ZERO_RATIO_26W", 0.25)
    monkeypatch.setattr(runtime_module, "DEFAULT_SCOPE_MIN_RECENT4_TOTAL_SALES", 4.0)

    store = PlatformStore(str(tmp_path / "platform_state.db"))
    manager = runtime_module.ForecastRuntimeManager(store=store, db_url="sqlite:///demo")
    run = store.create_run(
        config_id=None,
        trigger_source="manual",
        mode="smart",
        selection_type="all",
        selection_payload={},
        selected_spus=["SPU001"],
    )
    stop_event = runtime_module.threading.Event()
    manager._runs[run["id"]] = stop_event

    manager._execute_run(run["id"], stop_event)

    logs = store.get_logs(run["id"], limit=50)
    messages = [row["message"] for row in logs]
    assert any("[SPU SPU001] SPU001 model competition starting, train=8 weeks, test=4 weeks." in message for message in messages)
    assert any("[SPU SPU001] SPU001 | 运行 Prophet..." in message for message in messages)
    assert any("[SPU SPU001] SPU001 | Prophet: WMAPE=12.34%" in message for message in messages)
