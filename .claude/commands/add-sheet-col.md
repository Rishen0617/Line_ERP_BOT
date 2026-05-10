# /add-sheet-col — 新增 Google Sheets 欄位

## 用途
當需要在 Sheets 新增欄位時，提醒需要同步修改的所有位置。

## 修改清單

新增欄位時，必須同步更新以下位置（以新增「付款方式」欄為例）：

### 1. `docs/sheets_schema.md`
更新欄位表格，加入新欄（如欄 N）。

### 2. `app/services/sheets_service.py`
在 `append_receipt()` 函數的 `row` 陣列末尾加入新欄值：
```python
row = [
    ...,
    receipt.payment_method or "",  # N 付款方式（新增）
]
```

### 3. `app/models/receipt.py`
在 `Receipt` 模型加入對應欄位：
```python
payment_method: Optional[str] = None
```

### 4. `prompts/ocr_receipt.txt`
在 OCR prompt 的 JSON schema 加入新欄：
```json
"payment_method": "現金|轉帳|信用卡|支票|其他"
```

### 5. `app/services/claude_service.py`
在 `vision_ocr()` 的解析區段加入：
```python
receipt.payment_method = data.get("payment_method") or None
```

### 6. `tests/test_sheets.py`
更新相關測試案例。

## 注意
- Google Sheets 本身不需要預先「建立」欄位，append 時帶入值即可
- 若 Sheet 有標題列，請手動在 Google Sheets 加入欄位標題
