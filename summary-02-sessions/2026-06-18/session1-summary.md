# Session 1 — email-automation-demo：arch-deck + LINE + Google Calendar 雙輸出擴充

**日期**：2026-06-18
**機器**：NB00547
**分支**：main
**起點**：`/arch-deck` 演示 → 延伸成多輸出管道功能擴充

---

## 完成事項

### 1. arch-deck 三件套（commit `dadd450`）

- `docs/architecture.md`：六節架構文件，逐檔查證 8 個 `.py`（1412 行）
- 5 張 Mermaid 圖（心智圖/流程圖/系統架構圖/序列圖/狀態圖）.mmd + PNG
- PPTX 合輯（封面 + 5 頁），雙層 QA（結構 + COM 視覺）通過
- 圖表搬進專案 `mermaid/20260618-email-automation/`，更新 CLAUDE.md 目錄樹

### 2. 文件漂移修正（commit `ee29f1a`）

- CLAUDE.md 目錄樹「每日 09:00」→「07:30」對齊 `daily-briefing.yml` 實際 cron
- `.gitignore` 新增 `~$*`（Office 暫存鎖檔）

### 3. LINE 輸出管道（commit `61c4ddd`）

- 新增 `line_briefer.py`：LINE Messaging API push（非已停的 LINE Notify）
- `_build_push_payload` 純函式 + 5000 字截斷；`X-Line-Retry-Key` 冪等重試；分類重試（4xx 不重試、429/5xx 重試）
- `run_briefing.py` Step 6 加 LINE 選填發送（獨立 try/except、--dry-run 跳過）；順修 E402
- 三 agent 鐵律：QA 抓到「截斷邏輯只在 send_line、純函式假陽性」bug → 退回修好 → reviewer APPROVED

### 4. Google Calendar 事件（commit `2b98b3a`）

- 新增 `calendar_creator.py`：單一直接 API 路徑（events.insert），選填
- 全天事件 `end.date = 截止日 +1 天`（Google exclusive 規則，純函式測試鎖住）
- `_load_credentials` 比照 gmail_fetcher；只在「有截止日 + GCAL_TOKEN_JSON」時建
- `run_briefing.py` 於 Notion 後、mark_processed 前建事件，內層 try/except **不 raise**（保護冪等）
- reviewer APPROVED（0 必改）

### 5. 文件 + 圖表同步（commit `62dbd6d`）

- architecture.md 全面更新（概觀/組件表/資料流/ADR-8~10/部署）
- CLAUDE.md Pipeline 圖、技術棧、目錄樹、設計模式
- 5 Mermaid 圖重生（輸出管道改 Notion+Calendar+Telegram+LINE）+ PPTX 重出，視覺 QA 通過

### 6. setup 工具擴充（commit `8e177e5`）

- `scripts/setup_gmail_token.py` SCOPES 加 `calendar.events`（最小權限）
- 一把 token 兩用（GMAIL_TOKEN_JSON + GCAL_TOKEN_JSON）；加「舊 token 需重跑」警告

### 7. techblog-demo 複製指南（未 commit，不同 repo）

- `techblog-demo/docs/setup-replication-guide.md`：說明「setting」兩層（流程層免費繼承 / 功能層需重寫）
- 功能未實作（使用者說「no need now」）

---

## 關鍵技術筆記

- **多輸出管道設計原則**：一律「選填 + 失敗隔離」。缺 env 即略過；單管道失敗不影響其他與整體。
- **冪等三防護**（Calendar）：內層 try/except 不 raise → 不跳過 mark_processed → 重跑不重建。
- **LINE at-least-once 陷阱**：重試會重複推播，用 `X-Line-Retry-Key`（UUID，兩次同一把）讓 LINE 端去重。
- **Calendar 全天事件 end.date 是 exclusive**：截止日 6/20 → `start=6/20, end=6/21`。
- **OAuth scope 擴充**：舊 token 不會自動長新 scope，必須重跑授權。
- **harness `.env*` 保護**：`.env.example` 無法由 Claude 讀寫，需使用者手動補。

---

## 產出檔案

| 檔案 | 動作 | commit |
|------|------|--------|
| `docs/architecture.md` | 新增→更新 | dadd450 / 62dbd6d |
| `mermaid/20260618-email-automation/`（5 mmd + 5 png + pptx）| 新增→重生 | dadd450 / 62dbd6d |
| `line_briefer.py` | 新增 | 61c4ddd |
| `calendar_creator.py` | 新增 | 2b98b3a |
| `run_briefing.py` | 改（LINE + Calendar + E402）| 61c4ddd / 2b98b3a |
| `.github/workflows/ci.yml` `daily-briefing.yml` | 改 | 61c4ddd / 2b98b3a |
| `CLAUDE.md` | 改（含外部 GitNexus 區段）| 62dbd6d |
| `scripts/setup_gmail_token.py` | 改（calendar scope）| 8e177e5 |
| `techblog-demo/docs/setup-replication-guide.md` | 新增（不同 repo）| 未 commit |

---

## HANDOFF（下次 session 優先處理）

### 立即行動

- [ ] **手動補 `.env.example`**（harness 擋住 .env*）：加 `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_TO` / `GCAL_TOKEN_JSON` / `GCAL_CALENDAR_ID=primary` 四行
- [ ] **Calendar 上線前置**：GCP 啟用 Google Calendar API → 重跑 `python scripts/setup_gmail_token.py` 取得含 calendar scope 的新 token → 設 GitHub Secret `GMAIL_TOKEN_JSON` + `GCAL_TOKEN_JSON`（同值）
- [ ] decide：techblog-demo 複製指南是否 commit（已建在 techblog-demo/docs/）

### 進行中（需接續）

- techblog-demo「similar task」：複製指南已寫好，但多管道通知功能**未實作**。使用者暫時喊停（「no need now」）。若接續，需先確認：要哪幾個管道（Telegram/LINE/Notion/Calendar）+ 觸發方式（API route `app/api/publish` vs 排程腳本 `scripts/notify-new-post.ts`）+ 用 TypeScript 重寫（techblog 是 Next.js 16）。

### 注意事項

- 功能不設 LINE/GCAL env 也能跑（選填會乾淨略過，只發 Telegram + 建 Notion）。
- repo 內 `AGENTS.md` / `.claude/` 是使用者並行的 GitNexus 產物，本 session 全程未碰。
- CLAUDE.md 含外部加入的 GitNexus 索引區段（lines 145+），更新時只動頂部 1-3 節避免衝突。
