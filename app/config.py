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
    google_drive_folder_id: str = Field("", alias="GOOGLE_DRIVE_FOLDER_ID")

    # Local storage
    storage_path: str = Field("storage", alias="STORAGE_PATH")
    public_base_url: str = Field("http://localhost:8001", alias="PUBLIC_BASE_URL")

    # Business rules
    amount_alert_threshold: float = Field(100_000.0, alias="AMOUNT_ALERT_THRESHOLD")
    admin_line_user_id: str = Field("", alias="ADMIN_LINE_USER_ID")
    bot_timezone: str = Field("Asia/Taipei", alias="BOT_TIMEZONE")

    # Group trigger: only respond in group chats when message starts with this keyword.
    # Set to empty string "" to respond to all messages (default for private chats).
    # Example: "@ERP" → users type "@ERP 支出 3200" or "@ERP /月報"
    bot_trigger: str = Field("@ERP", alias="BOT_TRIGGER")

    # Comma-separated LINE user IDs with manager privileges (can use /新增班, /核假).
    # Get a user's ID from LINE Developers Console → Webhook logs, or ask them to
    # send any message and check the server log for their user_id.
    # Example: "Uabc123,Udef456"
    manager_line_user_ids: str = Field("", alias="MANAGER_LINE_USER_IDS")

    # Morning report
    # Secret token to protect POST /api/morning-report/send
    # Set MORNING_REPORT_SECRET in Railway env vars, then use it as Bearer token in cron job
    morning_report_secret: str = Field("", alias="MORNING_REPORT_SECRET")

    def is_manager(self, user_id: str) -> bool:
        if not self.manager_line_user_ids.strip():
            return False
        ids = {uid.strip() for uid in self.manager_line_user_ids.split(",")}
        return user_id in ids

    @cached_property
    def google_service_account_info(self) -> dict:
        return json.loads(self.google_service_account_json)


settings = Settings()  # type: ignore[call-arg]
