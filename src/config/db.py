"""Database URL configuration.

All production and tooling entry points should read the connection string from
the environment instead of embedding credentials in source.

Primary variable:
  SALES_FORECAST_DB_URL  e.g. postgresql+psycopg2://USER:PASSWORD@HOST:5432/finedatalink

Optional alias (used by some NexusBI / monitor modules):
  DATABASE_URL
"""

from __future__ import annotations

import os
from typing import Optional

_ENV_PRIMARY = "SALES_FORECAST_DB_URL"
_ENV_ALIAS = "DATABASE_URL"


def get_sales_forecast_db_url() -> Optional[str]:
    """Return the configured DB URL, or None if unset."""
    value = os.getenv(_ENV_PRIMARY) or os.getenv(_ENV_ALIAS)
    if value is None:
        return None
    value = value.strip()
    return value or None


def require_sales_forecast_db_url() -> str:
    """Return the DB URL or raise a clear error if missing."""
    value = get_sales_forecast_db_url()
    if not value:
        raise RuntimeError(
            "缺少数据库连接环境变量。请设置 SALES_FORECAST_DB_URL"
            "（或 DATABASE_URL），格式示例见 ENV.md / .env.example。"
        )
    return value
