# 群組（伺服器）功能設計

日期：2026-06-30

## 目標

讓一個帳號可建立/加入多個「群組（伺服器）」，類似 Discord 的多群組模型：

- 群組內每位成員**各自抽**每日專輯，但能**互看**彼此的進度與評分。
- 個人頁（不屬任何群組）與群組頁**並存**。
- 身分沿用既有的 cookie slug 機制，**不加密碼登入**。
- 邀請靠群組網址本身分享（沿用既有 `?u=` 的分享思路）。

## 非目標（YAGNI）

- 不做密碼 / OAuth 登入。
- 不做全群共用同一張專輯的社交模式（已確認是「每人各自抽」）。
- 不做角色 / 權限 / 管理員制度。
- 不做邀請碼過期、踢人、群組設定等進階管理。

## 資料模型

### User（既有，加欄位）

- 新增 `name: str | None`（暱稱，可空）。群組裡用來認得彼此；空值時 UI 顯示 slug 前幾碼。

### Server（新）

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | int PK | |
| slug | str unique index | 同時當網址情境值與邀請碼 |
| name | str | 群組顯示名稱 |
| created_at | datetime | |

### Membership（新）

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | int PK | |
| user_id | FK user.id | |
| server_id | FK server.id | |
| joined_at | datetime | |

唯一鍵：`unique(user_id, server_id)`。

### DailyPick（既有，加欄位）

- 新增 `server_id: int | None`（FK server.id，可空）。
- **`NULL = 個人頁`**；非空 = 屬於該群組。
- 既有資料無 server_id → 自動成為個人頁資料（平滑遷移）。
- 一人一天一群一張：靠既有 `get_or_create_today_pick`（先查再建）保證。
  - SQLite / Postgres 對 `NULL` 在唯一鍵中視為相異，故不靠 DB 唯一鍵，改 app 層保證。
  - `ponytail:` 上限為單請求情境下的競態忽略；若未來要嚴格，改用「個人 = 專屬 server 列」或部分唯一索引。
- 既有的 `UniqueConstraint("user_id", "date")` 移除（改由 app 層 + server 維度處理）。

### DrawHistory（既有，加欄位）

- 新增 `server_id: int | None`（同 DailyPick 的語意）。

### Comment（不動）

- 仍掛在 `DailyPick` 上。成員互看 = 查「同群同日所有成員的 DailyPick」。

## 路由情境機制（方案 A）

沿用既有 `?u=<slug>` 的做法，新增 `g=<slug>` 群組情境：

- middleware 解析 `?g=`（或 cookie `gid`），寫入 `request.state.server_slug`，並黏著到 cookie（同 `uid` 做法）。
- `g` 不存在 / 空 → 個人情境（`server_id = NULL`）。
- 新依賴 `get_current_server`：依 `request.state.server_slug` 查 `Server`；查無則視為個人情境。
- 切換群組 / 回個人：由 `/groups` 頁提供連結（帶或清空 `?g=`）。

各既有 view 改動：在原本 `filter(user_id == user.id)` 之外，多一個 `server_id` 過濾條件（個人情境用 `server_id.is_(None)`，群組情境用 `== server.id`）。**既有路由路徑不變**。

## 既有 view 的範圍調整

下列既有路由全部加上 `server_id` 維度過濾（個人 = NULL）：

- `/`（home / gate / 今日 pick）
- `/history`
- `/draw`、`/draw/history`
- `/albums`、`/albums/{id}`（status 過濾與 picks 顯示依情境）
- `/stats`

`/admin/*` 不受影響（全域）。專輯庫（Album）仍全域共用。

## 新增頁面 / 路由

- `GET /groups`：我的群組清單（含「個人」入口）＋ 建群表單＋設暱稱。
- `POST /groups`：建群（取名 → 產 slug → 建立者自動入會 → 導向該群情境）。
- `GET /s/<slug>`：群組首頁。若已是成員 → 該群今日專輯＋成員面板；若非成員 → 顯示「加入」鈕。
- `POST /s/<slug>/join`：寫入 membership（不自動加入）。
- 成員面板 / 成員頁：列出該群全員的今日專輯、狀態、評分（社交核心視圖）。
- `POST /me`（或併入 `/groups`）：設定暱稱。

> 註：`/s/<slug>` 僅作為群組進入點（驗證成員、設定 `g` 情境後導回既有路由）；其餘瀏覽仍走既有路由 + `?g=`，避免重複 9 條路由。

## 遷移

- `init_db` 加極簡遷移：建立 `server` / `membership` 表（`create_all` 即可），並對既有 `user` / `daily_pick` / `draw_history` 缺欄位時 `ALTER TABLE ADD COLUMN`（SQLite 與 Postgres 皆適用），不丟既有資料。
- 既有 `daily_pick` / `draw_history` 的 `server_id` 預設 NULL → 自動歸個人頁。

## 排程

- `scheduler.run_daily_job` 改為：對每位 user 的「個人情境」＋其每個 membership 各建當日 pick。
- 即對 `(user, server=None)` 與每個 `(user, server)` 呼叫 `get_or_create_today_pick`。
- `get_or_create_today_pick`、`pending_gate_pick`、`_pick_unseen_album` 等簽名加上 `server` 參數（None = 個人）。

## 測試

- `Membership` / `Server` 建立與唯一性。
- `get_or_create_today_pick`：個人與群組情境各自獨立一天一張，互不干擾。
- 同一 user 在兩個群 + 個人，同一天得到三筆獨立 pick。
- 成員互看：查同群同日所有成員 pick。
- 遷移：既有無 server_id 的 pick 落在個人情境。
- 既有 daily / lifecycle / routes 測試更新以涵蓋情境維度。

## 風險 / 上限（ponytail 標記）

- 一天一群一張靠 app 層保證，非 DB 約束 —— 單請求情境下競態可忽略，未來要嚴格再上部分唯一索引。
- `g` 情境黏著於 cookie，「目前群組」較隱性；網址 `?g=abc` 不如路徑漂亮（方案 B 的取捨已知並接受）。
