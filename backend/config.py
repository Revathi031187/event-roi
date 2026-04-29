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

    class Config:
        env_file = ".env"


settings = Settings()
os.makedirs(settings.temp_dir, exist_ok=True)
