import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, Field

BACKEND = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    data_dir: Path = BACKEND.parent / "data"
    fake_models: bool = False
    secure_cookie: bool = False
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    model_timeout_seconds: float = Field(default=12, gt=0, le=12)
    model_max_retries: int = Field(default=1, ge=0, le=1)
    tts_provider: Literal["tencent", "aihubmix"] = "tencent"
    aihubmix_api_key: str = ""
    aihubmix_base_url: str = "https://aihubmix.com/v1"
    aihubmix_tts_model: str = "gpt-4o-mini-tts"
    aihubmix_tts_voice: str = "coral"
    aihubmix_tts_speed: float = Field(default=0.8, ge=0.25, le=4)
    tencentcloud_secret_id: str = ""
    tencentcloud_secret_key: str = ""
    tencent_soe_app_id: str = ""
    tencent_soe_timeout_seconds: float = Field(default=10, gt=0, le=30)
    tts_region: str = "ap-shanghai"
    tts_voice_type: int = 101050
    tts_speed: float = Field(default=-1, ge=-2, le=6)
    tts_timeout_seconds: int = Field(default=5, ge=1, le=10)
    tts_max_retries: int = Field(default=1, ge=0, le=1)
    publish_timeout_seconds: int = Field(default=30, ge=1, le=60)

    @classmethod
    def load(cls):
        values = dotenv_values(BACKEND / ".env", interpolate=False) | os.environ
        data = {}
        for name in cls.model_fields:
            prefix = "BIBOO_" if name in {"data_dir", "fake_models", "secure_cookie"} else ""
            key = prefix + name.upper()
            if values.get(key) is not None:
                data[name] = values[key]
        settings = cls.model_validate(data)
        settings.data_dir = (BACKEND / settings.data_dir).resolve()
        return settings

    @property
    def credentials_ready(self):
        return bool(self.deepseek_api_key) and self.tts_credentials_ready

    @property
    def tts_credentials_ready(self):
        if self.tts_provider == "aihubmix":
            return bool(self.aihubmix_api_key)
        return bool(self.tencentcloud_secret_id and self.tencentcloud_secret_key)

    @property
    def oral_credentials_ready(self):
        app_id = self.tencent_soe_app_id.strip()
        return (
            app_id.isascii()
            and app_id.isdecimal()
            and len(app_id) <= 20
            and bool(self.tencentcloud_secret_id.strip() and self.tencentcloud_secret_key.strip())
        )

    @property
    def tts_model_label(self):
        if self.tts_provider == "aihubmix":
            return f"AIHubMix {self.aihubmix_tts_model}"
        return f"Tencent TTS {self.tts_voice_type}"
