# Google Drive 資料夾結構

## 根資料夾

設定在 `.env` 的 `GOOGLE_DRIVE_FOLDER_ID`，建議命名為 `SME-Bot-Files`。

## 自動建立的子資料夾結構

```
SME-Bot-Files/              ← GOOGLE_DRIVE_FOLDER_ID 指向此層
├── 2026/
│   ├── 05/
│   │   ├── receipts/      ← 收據、發票、訂購單
│   │   └── delivery/      ← 出貨單、送貨單
│   ├── 06/
│   │   ├── receipts/
│   │   └── delivery/
│   └── ...
└── 2027/
    └── ...
```

資料夾由 `drive_service.py` 的 `_get_or_create_folder()` 自動建立，無需手動建立。

## 檔案命名規則

```
{YYYYMMDD}_{單號或時間戳}_{文件類型}.jpg
```

範例：
- `20260510_AB-12345678_發票.jpg`
- `20260510_143022_收據.jpg`（無單號時用時間戳）
- `20260511_DELIVERY-001_出貨單.jpg`

## 權限設定

- 上傳後自動設為「知道連結的人可以檢視」
- Service Account 需對根資料夾有「編輯者」權限

## Service Account 設定

1. Google Cloud Console → IAM → 建立 Service Account
2. 產生 JSON 金鑰 → 放入 `.env` 的 `GOOGLE_SERVICE_ACCOUNT_JSON`
3. 在 Google Drive 根資料夾 → 共用 → 加入 Service Account email → 編輯者
4. 在 Google Sheets → 共用 → 加入 Service Account email → 編輯者
