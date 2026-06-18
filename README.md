# email-automation-demo

每天早上自動掃描 Gmail，把**需要行動**的信件轉成 Notion 任務卡片，並推播一則晨間簡報到 Telegram（與選填的 LINE）。

> 《Claude Code Pro》第十二章「打造每週省下 5 小時的自動化工作流」示範專案。

---

## 這是什麼

一條四段式的 Email 自動化 Pipeline。核心價值在於**雙層過濾**——先用規則擋掉電子報／通知信（省 API 成本），再用 Claude 判斷剩下的信「是否真的需要你處理」，只有真正重要的信才會變成任務並出現在你的晨報裡。

```
Gmail ──► email_filter ──► summarizer ──► notion_creator ──► telegram_briefer
（取信）   （L1 規則 +        （Claude AI      （建任務卡片）      （晨報推播）
            L2 語意過濾）      結構化摘要）                       └─► line_briefer（選填）
```

特色：

- **雙層過濾省成本**：L1 關鍵字規則先擋掉 newsletter / no-reply，L2 才用 Claude 做語意判斷
- **冪等快取**：`cache.py` 記住處理過的信，重複執行不會重建 Notion 任務
- **Graceful Failure**：每封信獨立 try/except，單封失敗不影響整體
- **乾跑模式**：`--dry-run` 用假資料跑完整流程，不需任何真實憑證

---

## 安裝

需求：Python 3.9+（使用內建 `zoneinfo`，不需 pytz）

```bash
git clone <this-repo>
cd email-automation-demo

python -m venv .venv
# Windows: .venv\Scripts\activate ／ macOS/Linux: source .venv/bin/activate

python -m pip install -r requirements.txt

cp .env.example .env   # 接著填入下方環境變數
```

---

## 快速開始

最快驗證能不能跑——**乾跑模式**（不需任何金鑰）：

```bash
python run_briefing.py --dry-run
```

會用兩封假資料（一封重要信、一封電子報）跑完整 Pipeline，終端機印出過濾統計與摘要，但**不會**呼叫 Claude、Notion、Telegram、LINE。

正式執行：

```bash
python run_briefing.py
```

---

## 環境變數

填入專案根目錄的 `.env`（已被 `.gitignore` 排除，不會進版控）。

| 變數 | 必填 | 用途 |
|------|:---:|------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Telegram Bot API token |
| `TELEGRAM_CHAT_ID` | ✅ | 接收晨報的 Telegram chat id |
| `NOTION_DATABASE_ID` | ✅ | 建立任務卡片的 Notion 資料庫 id |
| `LINE_CHANNEL_ACCESS_TOKEN` | ⬜ 選填 | LINE Messaging API token（要 LINE 推播才需要） |
| `LINE_TO` | ⬜ 選填 | LINE 推播目標 ID（user/group/room） |

> 缺少**必填**變數時程式會立即 `sys.exit(1)`（不靜默掩蓋設定錯誤）。
> LINE 為選填管道：沒設就略過，不中斷流程。

**CI / GitHub Actions 路徑**會另外用直連 API（而非本機的 `claude -p` + MCP），需要 `GMAIL_TOKEN_JSON`、`NOTION_API_KEY`、`ANTHROPIC_API_KEY`（透過 GitHub Secrets 提供）。本機開發**不需要**設這幾個。

---

## 專案結構

```
email-automation-demo/
├── run_briefing.py        # 主協調器：抓信→過濾→摘要→Notion→Telegram/LINE
├── email_filter.py        # L1 規則過濾 + L2 Claude 語意判斷
├── summarizer.py          # Claude AI → JSON 結構化摘要
├── notion_creator.py      # 建立 Notion 任務卡片（本機 MCP / CI 直連雙模式）
├── telegram_briefer.py    # Telegram Bot API 晨報推播
├── line_briefer.py        # LINE Messaging API 推播（選填，與 Telegram 共用訊息）
├── gmail_fetcher.py       # Gmail OAuth2 直接抓信（CI/CD 用）
├── cache.py               # 冪等快取（.cache/processed_ids.json）
├── scripts/
│   └── setup_gmail_token.py   # 一次性 OAuth2 Token 設定工具
├── docs/architecture.md       # 系統架構文件
├── mermaid/                   # 架構圖表（.mmd + .png + .pptx）
├── .github/workflows/
│   ├── ci.yml                 # PR/push：語法檢查 + 乾跑
│   └── daily-briefing.yml     # 排程：每日 07:30 台灣時間（週一~五）
└── CLAUDE.md                  # 給 Claude Code 的專案指引
```

### 設計重點

- **主控輕量**：`run_briefing.py` 只負責依序呼叫模組與錯誤日誌，不含業務邏輯
- **MCP 委派（本機）**：Gmail / Notion 操作透過 `claude -p` 呼叫 MCP，不直接用 API Key
- **直連 API（CI）**：`gmail_fetcher.py` / `notion_creator.py` 偵測到 CI 環境變數時改走直接 API

---

## 執行流程

`run_briefing.py` 的六個步驟：

1. **抓信** — 取今日（台灣時間）Gmail；乾跑用假資料，正式用 Gmail MCP 或預取快取
2. **去重** — 用 `cache.py` 排除已處理過的 message id
3. **過濾** — L1 關鍵字 + L2 語意，擋掉不需處理的信
4. **摘要 + 建任務** — 逐封 Claude 摘要 → 建 Notion 卡片 → 即時更新快取
5. **存快取** — 正式模式才寫入（乾跑不污染真實快取）
6. **推播** — 組裝晨報 → 發 Telegram →（選填）發 LINE

每次跑完印出統計：掃描幾封 / L1 跳過 / L2 跳過 / 處理幾封。

---

## 測試

| 驗證層 | 指令 |
|--------|------|
| 語法 | `python -m py_compile *.py` |
| 完整流程（乾跑） | `python run_briefing.py --dry-run` |
| 單模組冒煙測試 | 例：`python line_briefer.py`（內含 3 個內嵌測試案例） |

> Windows 執行 Python 前記得加 `PYTHONUTF8=1` 避免 cp950 編碼問題。

---

## 自動化排程

`.github/workflows/daily-briefing.yml` 每個工作日 **07:30（台灣時間，UTC 23:30 前一日）** 自動執行。敏感值全部走 GitHub Secrets，不寫在 workflow 檔裡。
