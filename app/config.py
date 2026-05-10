"""Environment-driven configuration. All env vars loaded from here only."""
from __future__ import annotations

import json
from functools import cached_property

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LINE
    line_channel_access_token: str = Field(..., alias="LINE_CHANNEL_ACCESS_TOKEN")
    line_channel_secret: str = Field(..., alias="LINE_CHANNEL_SECRET")

    # Anthropic
    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    claude_model: str = Field("claude-sonnet-4-6", alias="CLAUDE_MODEL")

    # Google
    google_service_account_json: str = Field(..., alias="GOOGLE_SERVICE_ACCOUNT_JSON")
    google_spreadsheet_id: str = Field(..., alias="GOOGLE_SPREADSHEET_ID")
    google_drive_folder_id: str = Field(..., alias="GOOGLE_DRIVE_FOLDER_ID")

    # Business rules
    amount_alert_threshold: float = Field(100_000.0, alias="AMOUNT_ALERT_THRESHOLD")
    admin_line_user_id: str = Field("", alias="ADMIN_LINE_USER_ID")
    bot_timezone: str = Field("Asia/Taipei", alias="BOT_TIMEZONE")

    @cached_property
    def google_service_account_info(self) -> dict:
        return json.loads(self.google_service_account_json)


settings = Settings()  # type: ignore[call-arg]
