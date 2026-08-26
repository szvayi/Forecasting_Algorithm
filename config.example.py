# repair_package_v1_2_fix/config.example.py
# This file serves as an example. It's recommended to use environment variables
# for sensitive information in production, or a dedicated config management system.

# Flask application configuration
# Debug mode should be False in production
DEBUG = True
HOST = "0.0.0.0"
PORT = 5000

# Database connection URL (example, replace with your actual DB)
# E.g., "postgresql://user:password@host:port/dbname"
DATABASE_URL="postgresql+psycopg2://ai_reader:ai_reader_pwd@192.168.1.226:5432/finedatalink"

# API Key for your LLM service (e.g., DeepSeek, OpenAI, Gemini)
# IMPORTANT: DO NOT hardcode sensitive API keys directly in production code.
# Use environment variables or a secure secret management system.
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "REPLACE_WITH_YOUR_API_KEY")

# Add other configuration parameters here as needed
# For example, logging level, external service URLs, etc.
# LOG_LEVEL = "INFO"


