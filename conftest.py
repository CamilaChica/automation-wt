import os


# Set import-time configuration before pytest discovers test modules.
os.environ["ENVIRONMENT"] = "development"
os.environ["WT_ENV"] = "development"
os.environ["WT_AUTH_ENV"] = "development"
os.environ["RENDER"] = "false"
os.environ["USE_ASYNC_REPOS"] = "false"
os.environ["OPERATIONAL_POSTGRES_RUNTIME_ENABLED"] = "false"
os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5433/test_db"
os.environ["LLM_LIVE_ENABLED"] = "false"