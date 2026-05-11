"""LINE Webhook handler. Responds 200 immediately; heavy work runs in BackgroundTasks."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    GroupSource,
    ImageMessageContent,
    MessageEvent,
    TextMessageContent,
)

from app.config import settings
from app.line.reply import get_line_api, get_line_blob_api
from app.handlers.image_handler import process_image
from app.handlers.text_handler import process_text

log = logging.getLogger(__name__)
router = APIRouter()
parser = WebhookParser(settings.line_channel_secret)


async def _get_display_name(user_id: str) -> str:
    try:
        api = get_line_api()
        profile = await api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return user_id


async def _get_group_name(group_id: str, user_id: str) -> str:
    try:
        api = get_line_api()
        profile = await api.get_group_member_profile(group_id, user_id)
        return profile.display_name
    except Exception:
        return group_id


@router.post("/webhook")
async def line_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(..., alias="X-Line-Signature"),
) -> JSONResponse:
    body_bytes = await request.body()

    try:
        events = parser.parse(body_bytes.decode("utf-8"), x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue

        user_id: str = event.source.user_id or ""
        group_id: str = (
            event.source.group_id
            if isinstance(event.source, GroupSource)
            else user_id
        )

        is_group = isinstance(event.source, GroupSource)

        if isinstance(event.message, ImageMessageContent):
            # Always process images — sending a photo is an explicit action
            background_tasks.add_task(
                process_image,
                message_id=event.message.id,
                reply_token=event.reply_token,
                user_id=user_id,
                group_id=group_id,
            )

        elif isinstance(event.message, TextMessageContent):
            text = event.message.text
            trigger = settings.bot_trigger.strip()

            # In group chats, require the trigger keyword (if configured)
            if is_group and trigger:
                if not text.startswith(trigger):
                    continue  # ignore — not addressed to this bot
                # Strip trigger prefix and leading whitespace before processing
                text = text[len(trigger):].strip()
                if not text:
                    continue

            background_tasks.add_task(
                process_text,
                text=text,
                reply_token=event.reply_token,
                user_id=user_id,
                group_id=group_id,
            )

    return JSONResponse({"ok": True})
