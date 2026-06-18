# email-automation-demo — 系統架構文件

**版本基準**：2026-06-18（commit 2b98b3a，含 LINE + Google Calendar 輸出）
**取樣範圍**：全專案 10 個 `.py`（約 1835 行）逐檔查證，含 `.github/workflows/` 兩個 CI/CD 設定。

---

## 1. 系統概觀

```
                    ┌──────────────────────────────────────────────┐
                    │           run_briefing.py（協調器）           │
                    │   抓信 → 過濾 → 摘要 → 建任務/事件 → 發簡報    │
                    └──────────────────────────────────────────────┘
                          │        │         │          │
            ┌─────────────┘        │         │          └──────────────┐
            ▼                      ▼         ▼                         ▼
      ┌──────────┐         ┌────────────┐ ┌──────────────┐    ┌────────────────────────┐
      │ cache.py │         │email_filter│ │ summarizer.py│    │ 輸出管道（多目標）     │
      │ 冪等去重 │         │ L1規則+L2AI│ │ AI→JSON摘要  │    │ telegram_briefer 晨報  │
      └──────────┘         └────────────┘ └──────────────┘    │ line_briefer    LINE   │
                                  │              │             └────────────────────────┘
                                  │              ▼                     ▲
                                  │       ┌──────────────────────┐    │
                                  │       │ 每封信建立（有截止日）│    │
                                  │       │ notion_creator 任務卡 │────┘
                                  │       │ calendar_creator 事件 │ (Notion URL / Cal htmlLink)
                                  │       └──────────────────────┘
                                  ▼
                          ┌──────────────┐
                          │ gmail_fetcher│ (CI 專用：OAuth2 預取)
                          └──────────────┘
```

**定位**：這是《Claude Code Pro》第十二章「每週省下 5 小時的自動化工作流」的示範專案。
每天早上掃描 Gmail，把「需要行動」的信件經 AI 兩層過濾與摘要，轉成 **Notion 任務卡片 +（有截止日時）Google Calendar 全天事件**，
並透過 **Telegram + LINE 雙管道**發出晨間簡報。核心價值不在演算法，而在**一份程式碼如何同時適配「本機 Max 訂閱」
與「CI 無人值守」兩種執行環境**（透過環境變數有無做通路派發，見第 5 節 ADR-1），
以及**多輸出管道一律可選且失敗隔離**（任一管道掛掉不影響其他與整體流程，見 ADR-8/9）。

---

## 2. 組件與角色

| 層級 | 檔案 | 行數 | 角色 |
|------|------|:---:|------|
| **進入點** | `run_briefing.py` | 270 | 主協調器（Orchestrator）。解析 `--dry-run`、環境檢查、依序串接各模組、Graceful Failure 包裹每封信、最終統計輸出 |
| **進入點（CI）** | `gmail_fetcher.py` | 135 | GitHub Actions 專用取信器。Gmail OAuth2 直連 API，抓今日信寫入 `.cache/today_emails.json` 供協調器預取 |
| **核心模組** | `email_filter.py` | 271 | 兩層過濾：L1 關鍵字/寄件者規則（免費）+ L2 Claude AI 語意判斷（雙通路：SDK / subprocess）|
| **核心模組** | `summarizer.py` | 292 | Claude → JSON-only 結構化摘要（5 欄位）+ 自然語言截止日標準化為 `YYYY-MM-DD`（雙通路）|
| **輸出：任務** | `notion_creator.py` | 220 | 建立 Notion 任務卡片。`priority_score`→P1/P2/P3 映射（雙通路：notion-client SDK / claude -p + MCP）|
| **輸出：事件** | `calendar_creator.py` | 230 | 建立 Google Calendar 全天事件（**有截止日才建**）。`end.date = 截止日 +1 天`（exclusive）。單一直接 API 路徑，**選填**（缺 `GCAL_TOKEN_JSON` 略過）|
| **輸出：晨報** | `telegram_briefer.py` | 167 | 純函式格式化晨報字串 + Telegram Bot API 發送（失敗重試一次）|
| **輸出：晨報** | `line_briefer.py` | 151 | LINE Messaging API push 發送同一串晨報。`X-Line-Retry-Key` 冪等重試 + 分類重試（4xx 不重試）。**選填**（缺 `LINE_*` 略過）|
| **純函式層** | `cache.py` | 99 | 冪等快取：以 `.cache/processed_ids.json` 記錄已處理 `message_id`，immutable 風格不就地改 set |
| **周邊工具** | `scripts/setup_gmail_token.py` | 59 | 一次性 OAuth2 授權，產出 base64 token 供 GitHub Secret `GMAIL_TOKEN_JSON` |

**外部服務**：Gmail（MCP 或 OAuth2 API）、Anthropic Claude（CLI subprocess 或 Python SDK，Haiku 模型）、
Notion（MCP 或 notion-client SDK）、Google Calendar（Calendar API，`calendar.events` scope）、
Telegram Bot API + LINE Messaging API（皆直接 HTTP POST）。

**依賴套件**：`requests` / `python-dotenv` / `anthropic≥0.40` / `notion-client≥2.2` /
`google-auth` / `google-auth-oauthlib` / `google-api-python-client`。

---

## 3. 組件互動模式

### 執行模型：單執行緒順序管線

協調器以單一 for-loop 逐封處理信件，無並行、無共享可變狀態。每封信獨立 `try/except`，
單封失敗只印警告並 `continue`，不中斷整體流程（Graceful Failure）。

```
all_emails ──► [cache 去重] ──► new_emails ──► [filter_emails] ──► filtered
                                                                      │
            ┌─────────────────────────────────────────────────────┘
            ▼ for each email（獨立 try/except）
   summarize_email ──► create_notion_task ──► create_calendar_event（選填，有截止日才建）──► mark_processed（每封即時更新 cache）
            │
            ▼ 全部處理完
   format_briefing ──► send_telegram ──► send_line（選填）──► 最終統計
```

> Calendar 的內層 try/except **不可 raise**：若 Calendar 失敗冒泡到外層 per-email except，
> 會走 `continue` 跳過 `mark_processed`，導致下次重跑重建 Notion 任務（破壞冪等）。LINE 同理放在簡報階段、失敗隔離。

### 狀態管理：冪等快取集中於 cache.py

- 所有 `.cache/processed_ids.json` 讀寫只能經 `cache.py`（CLAUDE.md 硬性約束）。
- `mark_processed` 採 immutable 風格回傳新 set，每處理完一封立即合併，
  確保中途崩潰時已處理的信不會在重跑時重複建 Notion 任務。
- `dry_run` 模式**不**寫入 cache，避免假資料污染正式快取。

### 關鍵約束

- **雙通路派發**：`should_skip_ai` / `summarize_email` / `create_notion_task` 三者皆以
  `os.environ.get(...)` 判斷 API key 是否存在來選路徑。
- **保守過濾策略**：AI 判斷僅在明確回答 `NO`（且不含 `YES`/`MAYBE`）時才跳過；
  任何逾時、找不到 CLI、API 錯誤都回傳 `False`（保留信件），寧可誤留不可誤刪。
- **環境變數 fail-fast**：缺 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/`NOTION_DATABASE_ID`
  立即 `sys.exit(1)`，不用 `.get("KEY","")` 靜默掩蓋。

---

## 4. 使用者操作觸發的資料流

### 流程 A：本機手動執行（`python run_briefing.py`，Max 訂閱通路）

```
1. load_dotenv(.env) → _check_env() 驗證 3 個必填環境變數
2. _fetch_emails_today(dry_run=False)
   ├─ 若 .cache/today_emails.json 存在 → 直接讀預取快取
   └─ 否則 → claude -p 呼叫 Gmail MCP，re.search 提取 JSON 陣列
3. cache 去重：排除 processed_ids.json 中已處理的 message_id
4. filter_emails：
   ├─ L1 should_skip_rule（關鍵字 newsletter/digest…、寄件者 noreply@…）
   └─ L2 should_skip_ai → 無 ANTHROPIC_API_KEY → _ai_judge_via_subprocess（claude -p）
5. 逐封 summarize_email → _summarize_via_subprocess（claude -p → JSON）
6. 逐封 create_notion_task → _create_via_subprocess（claude -p + Notion MCP → URL）
7. 逐封 create_calendar_event：有截止日 + 有 GCAL_TOKEN_JSON → Calendar API 建全天事件；否則略過
8. format_briefing 組裝 → send_telegram（HTTP POST，重試 1 次）
9. send_line：有 LINE_CHANNEL_ACCESS_TOKEN + LINE_TO → LINE push（X-Line-Retry-Key 冪等）；否則略過
```

### 流程 B：GitHub Actions 排程（`daily-briefing.yml`，直接 API 通路）

```
1. cron '30 23 * * 0-4'（UTC）= 台灣 07:30 週一~週五，或 workflow_dispatch 手動觸發
2. Step「Fetch Gmail emails」：gmail_fetcher.py
   └─ GMAIL_TOKEN_JSON（OAuth2）→ Gmail API list+get → .cache/today_emails.json
3. Step「Run morning briefing」：run_briefing.py
   ├─ 讀預取快取（流程 A 第 2 步走預取分支）
   ├─ filter_emails → 有 ANTHROPIC_API_KEY → _ai_judge_via_api（Haiku SDK）
   ├─ summarize_email → _summarize_via_api（Haiku SDK）
   ├─ create_notion_task → 有 NOTION_API_KEY → _create_via_api（notion-client SDK）
   ├─ create_calendar_event → 有 GCAL_TOKEN_JSON + 截止日 → Calendar API events.insert
   ├─ send_telegram（Bot API）
   └─ send_line → 有 LINE secrets → LINE Messaging API push
```

### 流程 C：乾跑驗證（`python run_briefing.py --dry-run`，即 Smoke Test）

```
1. _fetch_emails_today(dry_run=True) → 回傳 2 封假資料（1 重要信 + 1 電子報）
2. 完整跑過濾，但 summarize 之外的 claude 呼叫全跳過
3. 摘要結果只印 [DRY RUN 摘要]，不建 Notion、不寫 cache、不發 Telegram
4. 最終印統計（掃描/L1跳過/L2跳過/處理）
```

---

## 5. 關鍵架構決策（ADR 摘要）

| # | 決策 | 理由 | 代價 |
|---|------|------|------|
| ADR-1 | 三模組雙通路派發（API key 有無決定 SDK / subprocess）| 同碼適配本機 Max 訂閱（零成本）與 CI 無人值守（直接 API）兩環境 | 每模組多一組 `_xxx_via_api` / `_xxx_via_subprocess` 函式，維護面變兩倍 |
| ADR-2 | 兩層過濾（L1 規則 + L2 AI）| L1 免費擋掉電子報/通知類，是成本保護機制（CLAUDE.md 禁止正式執行跳過 L1）| 規則清單需人工維護；L1 誤判會讓信進不到 L2 |
| ADR-3 | 保守過濾：不確定一律保留 | 漏掉重要信件的代價遠高於多處理幾封 | 偶有電子報漏網，需 L1 規則補強 |
| ADR-4 | 冪等快取集中 cache.py + 每封即時更新 | 中途崩潰可安全重跑不重複建任務 | 每封多一次檔案寫入 I/O |
| ADR-5 | 摘要強制 JSON-only + `re.search` 提取 | `claude -p` 輸出常夾雜說明文字，需容錯解析 | 正則綁定欄位名（如 `one_liner`），prompt 改欄位要同步改正則 |
| ADR-6 | Haiku 模型做摘要/判斷 | 摘要與 YES/NO 判斷不需高階推理，符合成本規則 | 複雜信件摘要品質略低於 Sonnet |
| ADR-7 | 截止日在 summarizer 標準化為 ISO | 下游 Notion/Telegram/Calendar 需可排序日期，不能用「Thursday EOD」 | 自然語言解析涵蓋有限（僅星期/today/tomorrow/EOD/ISO）|
| ADR-8 | 多輸出管道一律「選填 + 失敗隔離」（LINE / Calendar 缺 env 即略過、各自 try/except）| 加管道不該強制每個環境都設定；單一管道掛掉不可拖垮晨報 | 略過是靜默的，需看 log 才知哪些管道沒發；選填與必填（Telegram/Notion）混用要清楚標示 |
| ADR-9 | Calendar 採單一直接 API 路徑（非 notion 的雙通路）+ 只在有截止日建全天事件，`end.date` 取截止日 +1 天 | 「缺 token 就略過」語意比雙通路清楚；沒截止日的信沒有合理日期；Google 全天事件 end 是 exclusive | 本機無 `GCAL_TOKEN_JSON` 時不像 Notion 能走 MCP 降級；CI 需另備 `calendar.events` scope 的 OAuth token |
| ADR-10 | LINE 重試帶 `X-Line-Retry-Key`（冪等）+ 4xx 不重試 | 網路抖動下「送了但回應遺失」重試會重複推播；對確定性 4xx 重試純浪費 | 每次發送多產一把 UUID；429/5xx 才重試並 sleep 1 秒 |

---

## 6. 部署與測試拓撲

```
開發（本機 Windows）
  └─ python run_briefing.py --dry-run   ← Smoke test，零憑證
         │
打包（git push main）
  └─ ci.yml 觸發
         ├─ py_compile 9 檔語法檢查（含 line_briefer / calendar_creator）
         ├─ Smoke tests：email_filter / summarizer / notion_creator / calendar_creator / line_briefer 各自 __main__
         └─ Dry run：run_briefing.py --dry-run（dummy env）
         │
發佈（GitHub Actions 排程）
  └─ daily-briefing.yml
         ├─ cron 30 23 * * 0-4（UTC）= 台灣 07:30 週一~五
         ├─ Secrets（必填）：GMAIL_TOKEN_JSON / ANTHROPIC_API_KEY / NOTION_API_KEY
         │                  / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / NOTION_DATABASE_ID
         ├─ Secrets（選填）：LINE_CHANNEL_ACCESS_TOKEN / LINE_TO / GCAL_TOKEN_JSON / GCAL_CALENDAR_ID
         └─ gmail_fetcher.py（取信）→ run_briefing.py（全流程，直接 API 通路）
         │
驗證
  ├─ Telegram + LINE 收到晨報訊息
  ├─ Notion 看板出現新任務卡片（P1/P2/P3）
  ├─ Google Calendar 在截止日當天出現全天事件
  └─ 連跑兩次確認冪等（第二次不建重複任務/事件）
```

**測試分層**：語法（`py_compile` 0 錯誤）→ 模組冒煙（各檔 `__main__` 內建 assert）→
端到端乾跑（`--dry-run`）→ 真實整合（手動確認 Telegram/LINE/Notion/Calendar 產出）。
