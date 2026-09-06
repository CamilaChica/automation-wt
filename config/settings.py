import os
from pydantic import BaseModel, Field

class Settings(BaseModel):
    app_name: str = "Winged Tycoons RFQ-to-Quote Multi-Agent MVP"
    api_version: str = "v1"
    host: str = "127.0.0.1"
    port: int = 8000
    
    # Pricing configuration defaults
    target_margin: float = 0.20  # Default 20% markup
    min_margin_threshold: float = 0.10  # Margin below 10% triggers pricing escalation
    
    # Simulation settings
    simulated_email_delay_seconds: float = 0.5
    mock_database_file: str = "data/winged_tycoons_mvp.db"

settings = Settings()
