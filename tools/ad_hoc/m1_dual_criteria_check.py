import json
import os
import sys
import time

import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.api.platform_store import PlatformStore
from src.api.runtime import ForecastRuntimeManager
from src.database.repositories import get_database_engine, query_forecast_results


def main() -> None:
    db_url = os.getenv(
        "SALES_FORECAST_DB_URL",
        "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink",
    )

    engine = get_database_engine(db_url)
    try:
        sample = pd.read_sql(
            text(
                """
                select spu
                from finedatalink.sales_forecast_history
                where spu is not null and trim(spu) <> ''
                order by run_date desc nulls last
                limit 1
                """
            ),
            con=engine,
        )
    finally:
        engine.dispose()

    if sample.empty:
        raise RuntimeError("No SPU found in sales_forecast_history for e2e run.")
    spu = str(sample.iloc[0]["spu"]).strip()
    if not spu:
        raise RuntimeError("Resolved SPU is empty.")

    os.environ["SPU_LIST"] = spu

    store = PlatformStore(os.path.join("data", "platform_state_e2e.db"))
    manager = ForecastRuntimeManager(store=store, db_url=db_url)

    run = manager.create_run(mode="fast", selection_type="all", selection_payload={})
    run_id = run["id"]

    final_run = None
    for _ in range(360):
        time.sleep(2)
        current = store.get_run(run_id)
        if not current:
            continue
        if current["status"] in {"completed", "failed", "stopped"}:
            final_run = current
            break
    if final_run is None:
        final_run = store.get_run(run_id)

    run_spus = store.get_run_spus(run_id)
    logs = store.get_logs(run_id, limit=500)
    rows = query_forecast_results(db_url, run_id=run_id, limit=50)

    core_called = any(item.get("status") == "completed" and item.get("winner_algo") for item in run_spus)
    db_written = len(rows) > 0

    report = {
        "run_id": run_id,
        "selected_spu_for_test": spu,
        "final_status": (final_run or {}).get("status"),
        "processed_count": (final_run or {}).get("processed_count"),
        "success_count": (final_run or {}).get("success_count"),
        "core_called": core_called,
        "db_written": db_written,
        "run_spu_count": len(run_spus),
        "db_rows_for_run_id": len(rows),
        "sample_log_tail": [x.get("message") for x in logs[:12]],
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
