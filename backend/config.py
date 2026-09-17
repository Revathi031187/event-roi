from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_plan_model: str = "gemini-2.5-flash"
    gemini_synth_model: str = "gemini-2.5-flash"

    databricks_host: str = ""
    databricks_token: str = ""
    genie_space_id: str = "01f137f8ed74188983eabc78abf23274"

    demo_mode: bool = False
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:3000"]
    temp_dir: str = os.path.join(os.path.dirname(__file__), "temp")

    # ── Langfuse observability ───────────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://us.cloud.langfuse.com"
    langfuse_environment: str = "development"
    langfuse_judge_sample_rate: float = 0.2

    class Config:
        env_file = ".env"

    @property
    def langfuse_enabled(self) -> bool:
        """Tracing is opt-in: both keys must be present. Missing keys => fail
        open, app behaves exactly as it did before this integration."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


settings = Settings()
os.makedirs(settings.temp_dir, exist_ok=True)
