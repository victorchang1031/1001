# 每日一張專輯網站 — 設計文件

日期：2026-06-21

## 目標

製作一個個人用網站，以《死前必聽的 1001 張專輯》的清單為基礎，每天 08:00 公布一張專輯，提供 Spotify / Apple Music 聆聽連結，並讓使用者記錄「有聽 / 沒聽」、撰寫評論與星等評分，以及回顧歷史與瀏覽全部專輯。

## 範圍與前提

- 單一使用者，無登入機制。
- 個人 / 少數朋友使用，本機或簡單雲端託管。
- 專輯清單僅使用公開可查的事實性資訊（書名、演出者、年份、類型），**不複製書中樂評或介紹原文**。
- 開發初期先以少量範例資料（10–20 筆）跑通流程，完整 1001 筆之後分批補齊。

## 技術棧

- 後端：Python + FastAPI
- 資料庫：SQLite（透過 SQLAlchemy）
- 排程：APScheduler，啟動時註冊每日 08:00 的 job
- 前端：Jinja2 模板 + 簡單 CSS（不使用前端框架）
- 設定：`.env` 存放 Spotify Client ID / Secret

## 資料模型

### Album
- `id`
- `title`
- `artist`
- `year`
- `genre`（可為 null）
- `spotify_url`（可為 null，第一次查詢後快取）
- `apple_music_url`（music.apple.com 搜尋連結）

### QueueEntry
- `album_id`
- `position`（整數，越小越早被推薦）
- 初始化：用固定隨機種子（seed=42）打亂全部 album，依序給 position。

### DailyPick
- `id`
- `date`（揭曉日期）
- `album_id`
- `status`：`pending` / `listened` / `skipped`
- `revealed_at`

### Comment
- `id`
- `daily_pick_id`
- `content`
- `rating`（1–5，可選）
- `created_at`

## 每日推薦機制（動態隊列）

推薦順序不是純日期計算，而是動態隊列，因為「沒聽就重新排隊」會改變後續順序。

每日流程（公布時間 08:00）：

1. **08:00 前**：頁面顯示「今天的專輯 08:00 揭曉，敬請期待」。
2. **08:00 後第一次造訪**：
   - 若昨天（或更早）的 `DailyPick` 仍為 `pending` → **強制先回答「前一天有聽嗎？」**，未回答看不到新專輯：
     - **有聽** → `status = listened`，可撰寫評論 + 打星星。
     - **沒聽** → `status = skipped`，該專輯**隨機插回未來隊列**（在尚未推薦的 QueueEntry 中隨機位置重新插入），之後會再出現。
   - 過 gate 後 → 從隊列取出 `position` 最小的 album，寫入今天的 `DailyPick`（status=`pending`），顯示專輯 + Spotify / Apple Music 連結。
3. **08:00 後再次造訪**：直接顯示今天已揭曉的專輯（內容固定不變）。

### 排程角色

- APScheduler 每天 08:00 觸發 job：
  - 若昨天 pick 已回答（非 `pending`），預先生成今天的 pick。
  - 若昨天仍 `pending`，不生成，等使用者回答 gate 後於造訪時 lazy 生成。
- 排程與 lazy 生成互補：排程是主要路徑，lazy 生成是備援，確保 gate 邏輯不被跳過。

## Spotify / Apple Music 串接

### Spotify
- 使用 Client Credentials Flow（只需 App 的 Client ID / Secret，不需使用者授權登入）。
- 呼叫 Spotify Search API，以「專輯名 + 演出者」搜尋取得精確的專輯連結。
- 第一次取得後寫入 `Album.spotify_url` 快取，之後不重複呼叫。
- 憑證放 `.env`；註冊步驟由開發者引導使用者於 developer.spotify.com 免費取得。

### Apple Music
- 組 `https://music.apple.com/search?term=<專輯+演出者>` 搜尋連結，不接 MusicKit API（避免企業開發者帳號門檻）。

## 頁面

1. `/` 首頁
   - 08:00 前：倒數 / 「敬請期待」提示。
   - 08:00 後：gate 問答（如昨日未回答）→ 今日專輯卡片（封面資訊、Spotify / Apple Music 連結）→ 評論表單（評論 + 星等）。
2. `/history` 歷史頁
   - 列出所有揭曉過的專輯，顯示狀態（已聽 / 沒聽）、評論與星等，可展開查看。
3. `/albums` 所有專輯總覽
   - 列出全部 1001 張，可依以下維度篩選 / 分組：
     - 年代（decade，由 year 推導）
     - 類型（genre）
     - 推薦狀態（已聽 / 沒聽 / 尚未推薦）
     - 演出者首字母（A–Z）

## 錯誤處理

- Spotify API 失敗（額度、網路、查無結果）：`spotify_url` 留空，頁面退回顯示 Spotify 搜尋連結，不中斷流程。
- 缺少 `.env` 憑證：跳過 Spotify API，全部使用搜尋連結。
- 隊列耗盡（1001 張全部推薦完）：循環回到隊列開頭，或顯示「已聽完全部」提示（預設循環）。

## 測試

- 每日推薦演算法：固定種子下隊列初始化可重現；取頭 / 隨機插回行為正確。
- Gate 邏輯：昨日 pending 時強制問答；有聽 / 沒聽分別正確更新狀態與隊列。
- 評論與星等寫入正確。
- `/albums` 各篩選維度回傳正確子集。
- Spotify 串接以 mock 測試成功與失敗路徑。

## 待補

- 完整 1001 筆專輯清單（含 genre）需分批整理與校對。
- Spotify Client ID / Secret 需使用者於 developer.spotify.com 註冊取得。
