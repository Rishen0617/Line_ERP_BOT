"""Alert admin when a transaction amount exceeds the threshold."""
from __future__ import annotations

import logging
from typing import Optional

from app.config import settings

log = logging.getLogger(__name__)


async def check_and_alert(
    amount: Optional[float],
    doc_type: str,
    doc_number: Optional[str],
    group_id: str,
) -> None:
    if not amount or amount <= settings.amount_alert_threshold:
        return
    if not settings.admin_line_user_id:
        log.warning("admin_line_user_id not set; cannot send alert for %.0f", amount)
        return

    from app.line.reply import push_text

    msg = (
        f"⚠️ 大額單據警示\n"
        f"金額：NT${amount:,.0f}（超過 NT${settings.amount_alert_threshold:,.0f}）\n"
        f"類型：{doc_type}\n"
        f"單號：{doc_number or '無'}\n"
        f"群組：{group_id}\n"
        f"請人工核對。"
    )
    await push_text(settings.admin_line_user_id, msg)
    log.info("large amount alert sent for %.0f", amount)
