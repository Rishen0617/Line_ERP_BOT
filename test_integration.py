"""一鍵驗證 Google Sheets + Drive 是否正常連線。

執行方式：
    python test_integration.py
"""
import asyncio
import sys
from datetime import date
from pathlib import Path


async def main():
    print("=" * 50)
    print("SME Bot — Google 整合測試")
    print("=" * 50)

    # ── 1. Sheets 寫入測試 ─────────────────────────────
    print("\n[1/2] Google Sheets 寫入測試...")
    try:
        from app.models.receipt import Receipt, ReceiptItem
        from app.services.sheets_service import append_receipt

        fake_receipt = Receipt(
            doc_type="發票",
            doc_number=f"TEST-{date.today().strftime('%Y%m%d')}",
            doc_date=date.today(),
            vendor_name="測試廠商（請手動刪除）",
            items=[
                ReceiptItem(name="測試品項A", qty=2, unit="個", unit_price=100, subtotal=200),
                ReceiptItem(name="測試品項B", qty=1, unit="箱", unit_price=500, subtotal=500),
            ],
            total_amount=700.0,
            tax_amount=35.0,
            confidence="高",
            uploaded_by="test-script",
            group_id="test-group",
            notes="整合測試，請手動刪除此列",
        )

        row = await append_receipt(fake_receipt, "測試腳本", "test-group")
        print(f"  ✅ 寫入成功！第 {row} 列")
        print(f"  → 請開啟 Sheets 確認「收據記錄」工作表最後一列")
        sheets_ok = True
    except Exception as e:
        print(f"  ❌ 失敗：{e}")
        sheets_ok = False

    # ── 2. Drive 上傳測試 ──────────────────────────────
    print("\n[2/2] Google Drive 上傳測試...")
    try:
        from app.services.drive_service import upload_image

        # 產生一個最小 1x1 白色 JPEG（不需要真實圖片）
        import io
        from PIL import Image
        img = Image.new("RGB", (100, 100), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        dummy_bytes = buf.getvalue()

        url = await upload_image(
            dummy_bytes,
            doc_type="發票",
            doc_number=f"TEST-{date.today().strftime('%Y%m%d')}",
            doc_date=date.today(),
        )
        print(f"  ✅ 上傳成功！")
        print(f"  → 圖片連結：{url}")
        drive_ok = True
    except Exception as e:
        print(f"  ❌ 失敗：{e}")
        drive_ok = False

    # ── 結果 ──────────────────────────────────────────
    print("\n" + "=" * 50)
    if sheets_ok and drive_ok:
        print("🎉 全部通過！Sheets 和 Drive 都正常。")
        print("可以開始透過 LINE 上傳真實收據了。")
    else:
        print("⚠️  有項目失敗，請檢查：")
        if not sheets_ok:
            print("  • Sheets：確認 Service Account 已加入試算表共用（編輯者）")
            print("  • 確認 GOOGLE_SPREADSHEET_ID 正確")
            print("  • 確認試算表有 4 個工作表：收據記錄、記帳流水帳、訂單追蹤、月報")
        if not drive_ok:
            print("  • Drive：確認 Service Account 已加入資料夾共用（編輯者）")
            print("  • 確認 GOOGLE_DRIVE_FOLDER_ID 正確")
    print("=" * 50)


if __name__ == "__main__":
    # 讓 app/config.py 讀到 .env
    import os
    os.chdir(Path(__file__).parent)
    asyncio.run(main())
