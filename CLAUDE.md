# email-automation-演練 — AI 專案入職手冊

> 第三章六大核心支柱格式。第十二章「打造每週省下 5 小時的自動化工作流」示範專案。

---

## 1. Project Overview（專案目標與受眾定義）

**專案名稱**：email-automation-演練

**目的**：示範《Claude Code Pro》第十二章的四段 Pipeline 自動化架構。
每天早上掃描 Gmail，把需要行動的信件自動轉成 Notion 任務卡片，並透過 Telegram 發送晨間簡報。

**四段 Pipeline**：
```
Gmail MCP → email_filter.py → summarizer.py → notion_creator.py → telegram_briefer.py
（取信）       （雙層過濾）       （AI 摘要）       （建任務）           （晨報）
```

**執行方式**：
```bash
# 正式執行
python run_briefing.py

# 乾跑（只印輸出，不建 Notion、不發 Telegram）
python run_briefing.py --dry-run
```

**目標受眾**：閱讀《Claude Code Pro》第十二章的開發者，想看 MCP 跨服務自動化的實際產出。

---

## 2. Tech Stack（核心技術棧與精確版本號）

| 技術 | 版本 | 備註 |
|------|------|------|
| Python | 3.9+ | 使用內建 `zoneinfo`（不需 pytz）|
| requests | 2.x | Telegram Bot API HTTP 呼叫 |
| python-dotenv | 1.x | 載入 `.env` 環境變數 |
| anthropic | 0.40+ | 直接呼叫 Claude API（CI/GitHub Actions 路徑）|
| notion-client | 2.2+ | 直接呼叫 Notion API（CI/GitHub Actions 路徑）|
| google-auth / google-api-python-client | 2.x | Gmail OAuth2（CI/GitHub Actions 路徑）|
| Claude Code CLI | 最新 | `subprocess` 呼叫 `claude -p`（本機 Max 訂閱路徑）|
| Gmail MCP | claude.ai 內建 | 本機執行時由 `claude -p` 呼叫 |
| Notion MCP | claude.ai 內建 | 本機執行時由 `claude -p` 呼叫 |
| Telegram Bot API | v7 | 直接 HTTP POST，不需 SDK |

**安裝**：
```bash
cd email-automation-演練
pip install -r requirements.txt
cp .env.example .env
# 填入 .env 的環境變數後執行
```

---

## 3. Architecture（資料夾結構與設計模式）

```
email-automation-演練/
├── run_briefing.py        # 主控協調器（Orchestrator）
├── email_filter.py        # Layer1 規則過濾 + Layer2 Claude AI 判斷
├── summarizer.py          # Claude AI → JSON-only 結構化摘要
├── notion_creator.py      # 建立 Notion 任務卡片（雙模式）
├── telegram_briefer.py    # Telegram Bot API → 晨間簡報
├── gmail_fetcher.py       # Gmail OAuth2 直接抓信（CI/CD 用）
├── cache.py               # 冪等快取（.cache/processed_ids.json）
├── CLAUDE.md              # 本文件
├── .env.example           # 環境變數範本（不含真實值）
├── .env                   # 真實環境變數（gitignore）
├── requirements.txt
├── scripts/
│   └── setup_gmail_token.py  # 一次性 OAuth2 Token 設定工具
├── .github/
│   └── workflows/
│       ├── ci.yml             # PR/push 觸發：syntax check + dry-run
│       └── daily-briefing.yml # 排程：每日 09:00 台灣時間（周一~五）
└── .cache/
    ├── processed_ids.json # 已處理的 Gmail message_id（防重複）
    └── today_emails.json  # gmail_fetcher.py 預取快取
```

**設計模式**：
- **主控輕量**：`run_briefing.py` 只負責依序呼叫模組、處理錯誤日誌，不含業務邏輯
- **Graceful Failure**：每封信獨立 try/except，單封失敗不影響整體流程
- **冪等快取**：`cache.py` 記錄已處理的 `message_id`，重複執行不重複建 Notion 任務
- **MCP 委派**：Gmail 與 Notion 操作一律透過 `claude -p` 呼叫 MCP，不直接使用 API Key

---

## 4. Code Conventions（程式碼撰寫慣例）

- **Claude 呼叫**：一律用 `subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=60)`
- **JSON 解析**：`claude -p` 輸出可能含前後雜訊，用 `re.search(r'\{.*\}', output, re.DOTALL)` 提取 JSON
- **時間處理**：`zoneinfo.ZoneInfo("Asia/Taipei")` 計算今天 0 點，轉 UTC 後傳給 Gmail MCP
- **環境變數**：一律 `os.environ["KEY"]`（不用 `.get()` 預設值，缺少時應立即失敗）
- **日誌**：`print(f"[{module}] {message}")` 格式，方便 --dry-run 時追蹤
- **priority_score → Notion Priority 映射**：5-4 → P1, 3 → P2, 2-1 → P3
- **日期解析**：ASAP/today → 今天，EOD → 今天，Thursday/Friday → 下一個該星期幾的日期

---

## 5. Testing Approach（測試框架與執行規範）

| 驗證層 | 方法 |
|--------|------|
| 語法 | `python -m py_compile *.py` — 0 錯誤 |
| 乾跑 | `python run_briefing.py --dry-run` — 終端機印出摘要，不呼叫 Notion/Telegram |
| Layer1 過濾 | 手動確認 newsletter/digest/no-reply 類信件被跳過 |
| Layer2 判斷 | 確認 YES/MAYBE 的信有進摘要，NO 的被跳過 |
| 摘要 JSON | 確認 5 個欄位（one_liner/full_summary/action_required/detected_deadline/priority_score）都有值 |
| 冪等性 | 連跑兩次，第二次 Notion 不建重複任務 |

---

## 6. Standing Constraints（絕對禁忌與強制規則）

### 🔴 絕對禁止

- **禁止在 Python 程式碼中硬編碼任何 API Key / Token**：全部從 `os.environ` 讀取
- **禁止直接呼叫 Gmail API 或 Notion API**（本機開發路徑）：一律透過 `claude -p` + MCP；例外：`gmail_fetcher.py` 與 `notion_creator.py` 在偵測到 `GMAIL_TOKEN_JSON` / `NOTION_API_KEY` 環境變數時使用直接 API，此為 GitHub Actions CI/CD 設計，本機開發不需設定這兩個變數
- **禁止用 `os.environ.get("KEY", "")` 靜默掩蓋缺少的環境變數**：缺少時應讓程式立即 sys.exit(1)
- **禁止在 `cache.py` 之外直接讀寫 `.cache/processed_ids.json`**：所有快取操作集中在 `cache.py`
- **禁止在正式執行時跳過 Layer1 過濾**：Layer1 是成本保護機制，移除會導致 API 費用爆增

### 🟡 強制規範

- `claude -p` 呼叫必須設 `timeout=60`（秒），超時要 catch `subprocess.TimeoutExpired`
- Telegram 發送失敗不可讓整個程式崩潰（try/except，最多 retry 一次）
- `--dry-run` 模式下，所有 `claude -p` 呼叫（摘要除外）必須跳過，改印 `[DRY RUN]` 訊息
- 每次執行完必須印出統計：掃描幾封 / 跳過幾封 / 處理幾封 / 建立幾個 Notion 任務
