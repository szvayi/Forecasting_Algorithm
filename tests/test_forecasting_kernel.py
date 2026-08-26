from types import SimpleNamespace

import pandas as pd


def test_kernel_process_single_spu_is_local(monkeypatch):
    import src.forecasting.kernel as kernel

    monkeypatch.setattr(
        kernel.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(AssertionError("legacy kernel should not be imported")),
    )
    kernel._load_legacy_kernel.cache_clear()

    class DummyProfiler:
        def __init__(self, verbose=False):
            self.verbose = verbose

        def analyze(self, spu, series, original_series, exog_series):
            return SimpleNamespace(spu=spu)

        def print_profile(self, profile):
            return None

        def update_with_results(self, profile, train, test, all_results, winner, forecast_values, total_time):
            profile.winner_algo = winner["name"]
            profile.winner_wmape = winner["wmape"]
            profile.total_time = total_time
            profile.forecast_values = list(forecast_values)
            return profile

        def print_model_competition(self, profile):
            return None

        def print_forecast_summary(self, profile, future_dates, forecast_values):
            return None

    def fake_run_all_models(
        train,
        test,
        mode="smart",
        train_exog=None,
        test_exog=None,
        verbose=False,
        log_fn=None,
        screening=None,
        model_policy=None,
        **kwargs,
    ):
        return (
            [
                {
                    "name": "FakeModel",
                    "wmape": 0.1234,
                    "forecast": [10.0] * len(test),
                    "params": {"alpha": 1},
                }
            ],
            [{"name": "FakeModel", "wmape": 0.1234, "forecast": [10.0] * len(test), "params": {"alpha": 1}}],
        )

    monkeypatch.setattr(kernel, "SPUProfiler", DummyProfiler)
    monkeypatch.setattr(kernel, "run_all_models", fake_run_all_models)
    monkeypatch.setattr(kernel, "predict_future", lambda *args, **kwargs: [12.0] * 16)
    monkeypatch.setattr(
        kernel,
        "safe_predictions",
        lambda preds, fallback, model_name, history_series=None: pd.Series(preds).to_numpy(),
    )

    def fake_dynamic_shares(*args, **kwargs):
        future_dates = args[-1]
        index = pd.DatetimeIndex(future_dates)
        frame = pd.DataFrame({"SKU1": [1.0] * len(index)}, index=index)
        return ([r"{}"] * len(index), frame)

    monkeypatch.setattr(kernel, "calculate_dynamic_shares", fake_dynamic_shares)
    monkeypatch.setattr(kernel, "calculate_principal_dynamic_shares", fake_dynamic_shares)
    monkeypatch.setattr(kernel, "extract_seasonal_factors_52week", lambda *args, **kwargs: "{}")
    monkeypatch.setattr(kernel, "clean_params_for_db", lambda params: "{\"alpha\": 1}")
    monkeypatch.setattr(kernel, "get_current_week_end", lambda: pd.Timestamp("2025-04-01"))

    df_spu = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-05", periods=14, freq="W"),
            "spu": ["SPU001"] * 14,
            "sku": ["SKU1"] * 14,
            "principal_names": ["P1"] * 14,
            "sales": list(range(1, 15)),
        }
    )

    result_df, message, viz, profile = kernel.process_single_spu(
        "SPU001",
        df_spu,
        mode="smart",
        exog_cols=[],
        collect_viz=True,
        verbose=False,
    )

    assert result_df is not None
    assert "FakeModel" in message
    assert result_df["winner_algo"].iloc[0] == "FakeModel"
    assert profile.winner_algo == "FakeModel"
    assert viz is not None
    assert "sku_future_df" in viz


def test_kernel_keeps_legacy_save_and_main_facade(monkeypatch):
    import src.forecasting.kernel as kernel

    calls = {}

    def fake_save_to_database(*args, **kwargs):
        calls["save"] = (args, kwargs)
        return None

    def fake_main(*args, **kwargs):
        calls["main"] = (args, kwargs)
        return "kernel-main"

    fake_root = SimpleNamespace(
        process_single_spu=None,
        save_to_database=fake_save_to_database,
        main=fake_main,
    )

    monkeypatch.setattr(kernel.importlib, "import_module", lambda name: fake_root)
    kernel._load_legacy_kernel.cache_clear()

    assert kernel.save_to_database([1, 2, 3], "sqlite:///demo") is None
    assert kernel.main() == "kernel-main"
    assert "save" in calls
    assert "main" in calls


def test_kernel_get_data_from_db_uses_local_query_path(monkeypatch):
    import src.forecasting.kernel as kernel

    class StubConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class StubEngine:
        def __init__(self):
            self.connection = StubConnection()
            self.disposed = False

        def connect(self):
            return self.connection

        def dispose(self):
            self.disposed = True

    engine = StubEngine()
    observed = {}

    monkeypatch.setattr(kernel, "create_engine", lambda db_url, pool_pre_ping=True: engine)
    monkeypatch.setattr(
        kernel.pd,
        "read_sql",
        lambda query, con: (
            observed.update({"query": str(query), "connection": con})
            or pd.DataFrame([{"DATE": "2025-01-01", "SPU": "SPU001", "SALES": 10}])
        ),
    )
    monkeypatch.setattr(
        kernel.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(AssertionError("legacy import should not be used")),
    )
    kernel._load_legacy_kernel.cache_clear()

    df = kernel.get_data_from_db("sqlite:///demo")

    assert list(df.columns) == ["date", "spu", "sales"]
    assert "select report_date as date" in observed["query"].lower()
    assert observed["connection"] is engine.connection
    assert engine.disposed is True


def test_kernel_training_query_keeps_expected_identifiers():
    import src.forecasting.kernel as kernel

    query = kernel._build_training_data_query()

    assert "查询订单利润_msku_cny_5年版" in query
    assert "查询订单利润_msku_cny_商品基础信息_5年版" in query
    assert "sum(a.volume) as 销量" in query
    assert "sum(销量) as sales" in query
    assert "?" not in query


def test_kernel_does_not_import_root_engine_or_utils():
    import inspect
    import src.forecasting.kernel as kernel

    source = inspect.getsource(kernel)
    assert "from algorithm_engine import" not in source
    assert "from config_and_utils import" not in source


def test_kernel_skips_sparse_validation_windows(monkeypatch):
    import src.forecasting.kernel as kernel

    class DummyProfiler:
        def __init__(self, verbose=False):
            self.verbose = verbose

        def analyze(self, spu, series, original_series, exog_series):
            return SimpleNamespace(spu=spu)

        def update_with_results(self, profile, train, test, all_results, winner, forecast_values, total_time):
            profile.winner_algo = winner["name"]
            profile.winner_wmape = winner["wmape"]
            return profile

    monkeypatch.setattr(kernel, "SPUProfiler", DummyProfiler)
    monkeypatch.setattr(kernel, "clean_series", lambda series: series)
    monkeypatch.setattr(kernel, "get_current_week_end", lambda: pd.Timestamp("2025-06-01"))

    df_spu = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-05", periods=20, freq="W"),
            "spu": ["SPU001"] * 20,
            "sku": ["SKU1"] * 20,
            "principal_names": ["P1"] * 20,
            "sales": [10] * 12 + [0, 0, 0, 0, 10, 0, 0, 0],
        }
    )

    result_df, message, viz, profile = kernel.process_single_spu(
        "SPU001",
        df_spu,
        mode="smart",
        exog_cols=[],
        collect_viz=False,
        verbose=False,
    )

    assert result_df is not None
    assert "policy=conservative" in message
    assert viz is None
    assert profile is not None


def test_kernel_near_tie_prefers_stable_ensemble():
    import src.forecasting.kernel as kernel

    winner = {"name": "LowSignalMedian", "wmape": 0.3000, "quality_score": 0.2600}
    finalists = [
        winner,
        {"name": "Ensemble-Weighted", "wmape": 0.3090, "quality_score": 0.2400},
        {"name": "AutoARIMA", "wmape": 0.3350, "quality_score": 0.2500},
    ]
    screening = {"zero_ratio": 0.35, "recent_mean": 5.0}

    chosen, reason = kernel._prefer_stable_ensemble_near_tie(
        winner=winner,
        finalists=finalists,
        screening=screening,
        validation_non_zero_points=10,
        low_signal_window=False,
    )

    assert chosen["name"] == "Ensemble-Weighted"
    assert reason is not None


def test_kernel_dual_metric_guardrail_replaces_unbalanced_winner():
    import src.forecasting.kernel as kernel

    winner = {"name": "LowSignalMedian", "wmape": 0.3020, "quality_score": 0.4200}
    finalists = [
        winner,
        {"name": "Ensemble-Weighted", "wmape": 0.3080, "quality_score": 0.2100},
        {"name": "AutoARIMA", "wmape": 0.3350, "quality_score": 0.2600},
    ]

    chosen, reason = kernel._apply_dual_metric_guardrail(
        winner=winner,
        finalists=finalists,
        low_signal_window=False,
    )

    assert chosen["name"] == "Ensemble-Weighted"
    assert reason is not None
