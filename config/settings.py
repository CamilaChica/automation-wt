import os
import logging
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class Settings(BaseModel):
    app_name: str = "Winged Tycoons RFQ-to-Quote Multi-Agent MVP"
    api_version: str = "v1"
    host: str = "127.0.0.1"
    port: int = 8000
    
    # Pricing configuration defaults
    target_margin: float = 0.20  # Default 20% markup
    min_margin_threshold: float = 0.10  # Margin below 10% triggers pricing escalation
    auto_send_min_margin_threshold: float = 0.15
    auto_send_max_total_usd: float = 50000.0
    
    # Simulation settings
    simulated_email_delay_seconds: float = 0.5
    mock_database_file: str = "data/winged_tycoons_mvp.db"

    # AI provider keys (optional). Keep secrets out of source control.
    openai_api_key: str | None = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    anthropic_api_key: str | None = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    gemini_api_key: str | None = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))

    def validate_api_keys(self) -> None:
        """
        Non-fatal validation: log whether provider keys are present. Do NOT raise on missing keys to allow local/test runs.
        """
        missing = []
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")

        if missing:
            logger.warning(
                "Missing AI provider keys: %s. The ai_router will run in mock/local mode unless keys are provided.",
                ", ".join(missing),
            )
        else:
            logger.info("All AI provider keys present.")

settings = Settings()
# Run validation at import time but keep non-fatal behavior so tests and local usage work without keys
settings.validate_api_keys()
