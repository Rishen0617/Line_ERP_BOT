# LINE SME Bot — Claude Code Context

## 專案說明
台灣中小企業 LINE 群組智慧助理。
主要功能：OCR 收據辨識、記帳、叫貨、物流追蹤，資料同步 Google Sheets。

## 常用指令
- 啟動本地開發：`uvicorn app.main:app --reload --port 8000`
- 建立 ngrok 測試通道：`ngrok http 8000`
- 執行測試：`pytest tests/ -v`
- 安裝套件：`pip install -r requirements.txt`
- 部署到 Railway：`railway up`

## 架構重點
- 所有 LINE 事件進入 `app/line/webhook.py`
- 圖片事件 → `app/handlers/image_handler.py` → `app/services/claude_service.py`（Vision OCR）
- 文字事件 → `app/handlers/text_handler.py` → 意圖辨識 → 對應服務
- Google Sheets 所有讀寫統一透過 `app/services/sheets_service.py`，不在其他地方直接呼叫

## 程式碼規範
- 使用 Python type hints（所有函數必須標注參數與回傳型別）
- Pydantic models 放在 `app/models/`，不在 handler 裡定義
- 錯誤處理：所有外部 API 呼叫（Claude、Sheets、LINE）必須有 try/except，並記錄 log
- 環境變數只從 `app/config.py` 的 Settings class 讀取，不直接 os.environ
- Prompt 文字統一放在 `prompts/` 目錄，不 hardcode 在程式碼裡

## 重要限制
- LINE Webhook 必須在 3 秒內回應 200，耗時工作（OCR）用 BackgroundTasks 處理
- Google Sheets 寫入前必須先呼叫 `duplicate_check.py` 確認單號未重複
- 金額超過 NT$100,000 時必須發送警示訊息給群組管理員
- 圖片下載後存在記憶體，不寫入本地磁碟（Railway ephemeral storage）
- 圖片 > 5MB 必須用 Pillow 壓縮後再送 Claude API

## 關鍵文件
- Google Sheets 欄位定義：見 `docs/sheets_schema.md`
- Drive 資料夾結構：見 `docs/drive_structure.md`
- OCR prompt 調優：見 `.claude/skills/ocr-prompt.md`

## Sheets 欄位對照（Sheet 1 收據記錄）
A=日期, B=上傳時間, C=上傳者, D=文件類型, E=廠商/客戶, F=品項摘要,
G=金額, H=稅額, I=單號, J=圖片連結, K=AI信心度, L=群組, M=備註
