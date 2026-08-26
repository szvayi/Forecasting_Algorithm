#!/usr/bin/env python3
"""
Legacy launcher for forecast_dashboard_v2.

This module intentionally re-exports the production FastAPI app so historical
commands such as `uvicorn src.api.app_test:app` keep serving the same shared
state store as the primary application.
"""

import uvicorn

from src.api.app import app


if __name__ == "__main__":
    uvicorn.run("src.api.app_test:app", host="0.0.0.0", port=8000, reload=False)
