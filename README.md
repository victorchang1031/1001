# 每日一張專輯

依《死前必聽的 1001 張專輯》清單，每天 08:00 公布一張。

## 安裝

```bash
pip install -r requirements.txt
cp .env.example .env  # 填入 Spotify 憑證（可留空，會退回搜尋連結）
```

## Spotify 憑證取得

1. 前往 https://developer.spotify.com/dashboard 登入
2. Create app，Redirect URI 隨意填 http://localhost
3. 複製 Client ID 與 Client Secret 到 `.env`

## 啟動

```bash
uvicorn app.main:app --reload --reload-dir app
```

開 http://127.0.0.1:8000

## 機制

- 08:00 公布當日專輯，當天反覆造訪顯示同一張
- 隔天 08:00 須先回答「前一天有聽嗎？」
  - 有聽 → 可評論、打星等
  - 沒聽 → 該專輯隨機插回未來隊列，之後會再出現
- `/history` 回顧、`/albums` 瀏覽全部（可依年代/類型/狀態/首字母篩選）

## 補齊完整清單

`app/seed_data.py` 的 `SAMPLE_ALBUMS` 目前為範例。補齊 1001 筆後刪除 `app.db` 重新啟動即可重建。
