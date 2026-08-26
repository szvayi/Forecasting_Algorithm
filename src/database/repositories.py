import datetime
import os
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import create_engine, text


def _make_engine(db_url: str, pool_size: int, max_overflow: int):
    connect_args = {}
    if db_url.startswith("postgresql"):
        connect_args["connect_timeout"] = 10
    return create_engine(
        db_url,
        pool_pre_ping=True,
        connect_args=connect_args,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=300,
    )


def _ensure_result_columns(conn) -> None:
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'finedatalink'
              AND table_name = 'sales_forecast_history'
            """
        )
    ).fetchall()
    existing = {row[0] for row in rows}
    ddl = {
        "run_id": "ALTER TABLE finedatalink.sales_forecast_history ADD COLUMN run_id VARCHAR(64)",
        "config_id": "ALTER TABLE finedatalink.sales_forecast_history ADD COLUMN config_id VARCHAR(64)",
        "principal_share_json": "ALTER TABLE finedatalink.sales_forecast_history ADD COLUMN principal_share_json TEXT",
    }
    for column_name, statement in ddl.items():
        if column_name not in existing:
            conn.execute(text(statement))


def save_to_database(df_spu_level, db_url, run_id: Optional[str] = None, config_id: Optional[str] = None):
    print("\nSaving forecast results to the database...")
    df_db = df_spu_level.copy()
    for col in ["run_date", "forecast_target_date", "data_end_date"]:
        if col in df_db.columns:
            df_db[col] = pd.to_datetime(df_db[col]).dt.date
    df_db["create_time"] = datetime.datetime.now()
    if "sku_share_json" in df_db.columns:
        df_db["sku_share_json"] = df_db["sku_share_json"].astype(str)
    if "principal_share_json" in df_db.columns:
        df_db["principal_share_json"] = df_db["principal_share_json"].astype(str)
    if "best_params" in df_db.columns:
        df_db["best_params"] = df_db["best_params"].astype(str)
    if "training_weeks" in df_db.columns:
        df_db["training_weeks"] = df_db["training_weeks"].astype(int)
    if "has_exog_features" in df_db.columns:
        df_db["has_exog_features"] = df_db["has_exog_features"].astype(bool)
    if run_id is not None:
        df_db["run_id"] = str(run_id)
    if config_id is not None:
        df_db["config_id"] = str(config_id)

    engine = _make_engine(db_url, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as conn:
            _ensure_result_columns(conn)
            df_db.to_sql(
                "sales_forecast_history",
                con=conn,
                schema="finedatalink",
                if_exists="append",
                index=False,
                method="multi",
                chunksize=200,
            )
        print(f"Saved {len(df_db)} rows to finedatalink.sales_forecast_history")
    except Exception:
        backup_dir = os.path.join("D:/华烨/output")
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(backup_dir, f"backup_{datetime.date.today()}.csv")
        df_spu_level.to_csv(backup_file, index=False)
        raise
    finally:
        engine.dispose()


def get_database_engine(db_url):
    return _make_engine(db_url, pool_size=5, max_overflow=10)


def test_database_connection(db_url):
    try:
        engine = get_database_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        if "engine" in locals():
            engine.dispose()


def query_forecast_results(
    db_url,
    run_id: Optional[str] = None,
    config_id: Optional[str] = None,
    spu: Optional[str] = None,
    run_date: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    clauses = []
    params: Dict[str, Any] = {"limit": limit}
    if run_id:
        clauses.append("run_id = :run_id")
        params["run_id"] = run_id
    if config_id:
        clauses.append("config_id = :config_id")
        params["config_id"] = config_id
    if spu:
        clauses.append("spu = :spu")
        params["spu"] = spu
    if run_date:
        clauses.append("run_date = :run_date")
        params["run_date"] = run_date
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    engine = get_database_engine(db_url)
    try:
        with engine.begin() as conn:
            # 兼容历史库：查询前确保 run_id/config_id 字段存在
            _ensure_result_columns(conn)
            rows = conn.execute(
                text(
                    f"""
                    SELECT spu, run_date, forecast_target_date, spu_forecast_value,
                           winner_algo, validation_wmape, run_id, config_id, principal_share_json
                    FROM finedatalink.sales_forecast_history
                    {where_clause}
                    ORDER BY run_date DESC, spu ASC, forecast_target_date ASC
                    LIMIT :limit
                    """
                ),
                params,
            ).mappings().all()
        return [dict(row) for row in rows]
    finally:
        engine.dispose()
