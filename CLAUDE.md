# email-automation-演練 — AI 專案入職手冊

> 第三章六大核心支柱格式。第十二章「打造每週省下 5 小時的自動化工作流」示範專案。

---

## 1. Project Overview（專案目標與受眾定義）

**專案名稱**：email-automation-演練

**目的**：示範《Claude Code Pro》第十二章的多段 Pipeline 自動化架構。
每天早上掃描 Gmail，把需要行動的信件自動轉成 Notion 任務卡片 +（有截止日時）Google Calendar 全天事件，
並透過 Telegram + LINE 雙管道發送晨間簡報。

**Pipeline**：

```
Gmail → email_filter → summarizer → ┬─ notion_creator（任務卡片）
（取信）  （雙層過濾）   （AI 摘要）    ├─ calendar_creator（全天事件，有截止日才建）
                                     └─ telegram_briefer + line_briefer（晨報雙管道）
```

> 輸出管道一律「選填 + 失敗隔離」：LINE / Calendar 缺對應環境變數即略過，單一管道失敗不影響其他與整體流程。

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
| LINE Messaging API | v2 | push message，直接 HTTP POST（非已停用的 LINE Notify）|
| Google Calendar API | v3 | `events.insert` 建全天事件（`calendar.events` scope）|

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
├── calendar_creator.py    # 建立 Google Calendar 全天事件（有截止日才建，選填）
├── telegram_briefer.py    # Telegram Bot API → 晨間簡報
├── line_briefer.py        # LINE Messaging API push → 晨間簡報（選填）
├── gmail_fetcher.py       # Gmail OAuth2 直接抓信（CI/CD 用）
├── cache.py               # 冪等快取（.cache/processed_ids.json）
├── CLAUDE.md              # 本文件
├── .env.example           # 環境變數範本（不含真實值）
├── .env                   # 真實環境變數（gitignore）
├── requirements.txt
├── scripts/
│   └── setup_gmail_token.py  # 一次性 OAuth2 Token 設定工具
├── docs/
│   └── architecture.md       # 系統架構文件（六節：概觀/組件/互動/資料流/ADR/部署）
├── mermaid/                  # 架構圖表（arch-deck 產出，跟著 repo 走）
│   └── 20260618-email-automation/
│       ├── mmd/              # 5 個 Mermaid 原始碼（.mmd，含 LINE + Calendar 輸出）
│       ├── png/              # 5 張渲染圖（心智圖/流程圖/系統架構圖/序列圖/狀態圖）
│       └── *.pptx           # 圖表合輯簡報（封面 + 5 頁）
├── .github/
│   └── workflows/
│       ├── ci.yml             # PR/push 觸發：syntax check + dry-run
│       └── daily-briefing.yml # 排程：每日 07:30 台灣時間（周一~五，UTC 23:30 隔日）
└── .cache/
    ├── processed_ids.json # 已處理的 Gmail message_id（防重複）
    └── today_emails.json  # gmail_fetcher.py 預取快取
```

**設計模式**：

- **主控輕量**：`run_briefing.py` 只負責依序呼叫模組、處理錯誤日誌，不含業務邏輯
- **Graceful Failure**：每封信獨立 try/except，單封失敗不影響整體流程
- **冪等快取**：`cache.py` 記錄已處理的 `message_id`，重複執行不重複建 Notion 任務/Calendar 事件
- **MCP 委派**：Gmail 與 Notion 操作一律透過 `claude -p` 呼叫 MCP，不直接使用 API Key
- **多輸出管道（選填 + 失敗隔離）**：Notion（必）+ Calendar / Telegram / LINE。Calendar 與 LINE 缺對應環境變數即略過；各管道獨立 try/except，單一失敗不影響其他與整體流程
- **Calendar 冪等保護**：建事件的 try/except 不可 raise，否則會跳過 `mark_processed` 導致重跑重建（全天事件 `end.date` 取截止日 +1 天，Google exclusive 規則）

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

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **email-automation-demo** (105 symbols, 175 relationships, 5 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## When Debugging

1. `gitnexus_query({query: "<error or symptom>"})` — find execution flows related to the issue
2. `gitnexus_context({name: "<suspect function>"})` — see all callers, callees, and process participation
3. `READ gitnexus://repo/email-automation-demo/process/{processName}` — trace the full execution flow step by step
4. For regressions: `gitnexus_detect_changes({scope: "compare", base_ref: "main"})` — see what your branch changed

## When Refactoring

- **Renaming**: MUST use `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` first. Review the preview — graph edits are safe, text_search edits need manual review. Then run with `dry_run: false`.
- **Extracting/Splitting**: MUST run `gitnexus_context({name: "target"})` to see all incoming/outgoing refs, then `gitnexus_impact({target: "target", direction: "upstream"})` to find all external callers before moving code.
- After any refactor: run `gitnexus_detect_changes({scope: "all"})` to verify only expected files changed.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Tools Quick Reference

| Tool | When to use | Command |
|------|-------------|---------|
| `query` | Find code by concept | `gitnexus_query({query: "auth validation"})` |
| `context` | 360-degree view of one symbol | `gitnexus_context({name: "validateUser"})` |
| `impact` | Blast radius before editing | `gitnexus_impact({target: "X", direction: "upstream"})` |
| `detect_changes` | Pre-commit scope check | `gitnexus_detect_changes({scope: "staged"})` |
| `rename` | Safe multi-file rename | `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` |
| `cypher` | Custom graph queries | `gitnexus_cypher({query: "MATCH ..."})` |

## Impact Risk Levels

| Depth | Meaning | Action |
|-------|---------|--------|
| d=1 | WILL BREAK — direct callers/importers | MUST update these |
| d=2 | LIKELY AFFECTED — indirect deps | Should test |
| d=3 | MAY NEED TESTING — transitive | Test if critical path |

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/email-automation-demo/context` | Codebase overview, check index freshness |
| `gitnexus://repo/email-automation-demo/clusters` | All functional areas |
| `gitnexus://repo/email-automation-demo/processes` | All execution flows |
| `gitnexus://repo/email-automation-demo/process/{name}` | Step-by-step execution trace |

## Self-Check Before Finishing

Before completing any code modification task, verify:

1. `gitnexus_impact` was run for all modified symbols
2. No HIGH/CRITICAL risk warnings were ignored
3. `gitnexus_detect_changes()` confirms changes match expected scope
4. All d=1 (WILL BREAK) dependents were updated

## Keeping the Index Fresh

After committing code changes, the GitNexus index becomes stale. Re-run analyze to update it:

```bash
npx gitnexus analyze
```

If the index previously included embeddings, preserve them by adding `--embeddings`:

```bash
npx gitnexus analyze --embeddings
```

To check whether embeddings exist, inspect `.gitnexus/meta.json` — the `stats.embeddings` field shows the count (0 means no embeddings). **Running analyze without `--embeddings` will delete any previously generated embeddings.**

> Claude Code users: A PostToolUse hook handles this automatically after `git commit` and `git merge`.

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
