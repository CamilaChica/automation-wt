import os

# Ensure safe isolated local test environment configuration for unittest discovery.
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WT_ENV", "development")
os.environ.setdefault("WT_AUTH_ENV", "development")
os.environ.setdefault("RENDER", "false")
os.environ.setdefault("USE_ASYNC_REPOS", "false")
os.environ.setdefault("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/test_db")
os.environ.setdefault("LLM_LIVE_ENABLED", "false")
