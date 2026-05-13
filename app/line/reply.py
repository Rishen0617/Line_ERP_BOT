"""LINE messaging helpers — reply and push utilities."""
from __future__ import annotations

import logging
from functools import lru_cache

from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    Configuration,
    MessageAction,
    PushMessageRequest,
    QuickReply,
    QuickReplyItem,
    ReplyMessageRequest,
    TextMessage,
)

from app.config import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _config() -> Configuration:
    return Configuration(access_token=settings.line_channel_access_token)


def get_line_api() -> AsyncMessagingApi:
    return AsyncMessagingApi(AsyncApiClient(_config()))


def get_line_blob_api() -> AsyncMessagingApiBlob:
    return AsyncMessagingApiBlob(AsyncApiClient(_config()))


async def reply_text(reply_token: str, text: str) -> None:
    text = (text or "")[:4900]
    try:
        api = get_line_api()
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )
    except Exception as e:
        log.warning("reply_text failed: %s", e)


async def push_text(user_or_group_id: str, text: str) -> None:
    text = (text or "")[:4900]
    try:
        api = get_line_api()
        await api.push_message(
            PushMessageRequest(to=user_or_group_id, messages=[TextMessage(text=text)])
        )
    except Exception as e:
        log.warning("push_text to %s failed: %s", user_or_group_id, e)


async def push_quick_reply(
    chat_id: str,
    intro: str,
    items: list[tuple[str, str]],
) -> None:
    """Send a text message with Quick Reply buttons.

    items: list of (label, text_sent_on_tap) — max 13 items, label max 20 chars.
    """
    qr_items = [
        QuickReplyItem(action=MessageAction(label=label[:20], text=text[:300]))
        for label, text in items[:13]
    ]
    try:
        api = get_line_api()
        await api.push_message(
            PushMessageRequest(
                to=chat_id,
                messages=[
                    TextMessage(
                        text=intro,
                        quick_reply=QuickReply(items=qr_items),
                    )
                ],
            )
        )
    except Exception as e:
        log.warning("push_quick_reply to %s failed: %s", chat_id, e)


async def download_image(message_id: str) -> bytes:
    blob = get_line_blob_api()
    return await blob.get_message_content(message_id=message_id)
