# Example configuration. Copy values into the server environment / .env
# (see ENV.md and .env.example). Do not commit real credentials.

import os

# Flask / app host settings (legacy example)
DEBUG = True
HOST = "0.0.0.0"
PORT = 5000

# Prefer SALES_FORECAST_DB_URL for the forecasting platform.
# DATABASE_URL is an accepted alias used by some NexusBI / monitor modules.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://USER:PASSWORD@HOST:5432/finedatalink",
)
SALES_FORECAST_DB_URL = os.getenv(
    "SALES_FORECAST_DB_URL",
    DATABASE_URL,
)

# LLM / external APIs — never commit real keys
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "REPLACE_WITH_YOUR_API_KEY")
