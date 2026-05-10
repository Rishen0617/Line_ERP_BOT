# /test-webhook — 快速測試 LINE Webhook

## 用途
在本機用 curl 模擬 LINE 送來的文字訊息，確認 Webhook 路由正常。

## 指令

```bash
# 1. 啟動服務
uvicorn app.main:app --reload --port 8000

# 2. 另開終端，發送模擬 webhook（使用 ngrok URL 或 localhost）
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: test" \
  -d '{
    "destination": "xxxxxxxxxx",
    "events": [{
      "type": "message",
      "replyToken": "test-token",
      "source": { "type": "group", "groupId": "G001", "userId": "U001" },
      "message": { "type": "text", "id": "12345", "text": "支出 3200 阿成食品 進貨" }
    }]
  }'
```

> **注意：** 本機測試時簽章驗證會失敗（400 invalid signature）。
> 若要完整測試，請使用 ngrok 並在 LINE Developers 設定 Webhook URL，由 LINE 平台送出真實的簽章。

## 測試 OCR 端點（不需 LINE）

```bash
# 將圖片轉 base64 再呼叫 /admin/test-ocr
python -c "
import base64, json
img = open('tests/fixtures/sample_receipt.jpg','rb').read()
print(json.dumps({'image_b64': base64.b64encode(img).decode()}))
" | curl -X POST http://localhost:8000/admin/test-ocr \
     -H "Content-Type: application/json" -d @-
```
