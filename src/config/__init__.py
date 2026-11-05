"""Shared configuration helpers for the forecasting platform."""

from .db import get_sales_forecast_db_url, require_sales_forecast_db_url

__all__ = ["get_sales_forecast_db_url", "require_sales_forecast_db_url"]
