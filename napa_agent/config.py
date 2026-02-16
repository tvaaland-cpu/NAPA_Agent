from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    database_url: str = Field(default="sqlite:///napa_agent.db", alias="DATABASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    smtp_host: str = Field(alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(alias="SMTP_USERNAME")
    smtp_password: str = Field(alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_from: str = Field(alias="SMTP_FROM")
    smtp_to: str = Field(alias="SMTP_TO")

    napatech_shareinfo_url: str = Field(
        default="https://napatech.com/investor-relations/share-information/",
        alias="NAPATECH_SHAREINFO_URL",
    )
    euronext_news_url: str = Field(
        default="https://live.euronext.com/en/product/equities/DK0060520450-XCSE/company-information",
        alias="EURONEXT_NEWS_URL",
    )
    napatech_ir_base_url: str = Field(
        default="https://napatech.com/investor-relations/",
        alias="NAPATECH_IR_BASE_URL",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    try:
        return Settings.model_validate(dict(os.environ))
    except ValidationError as exc:
        missing = [".".join(map(str, e["loc"])) for e in exc.errors()]
        raise RuntimeError(f"Invalid configuration. Missing or invalid env vars: {missing}") from exc
