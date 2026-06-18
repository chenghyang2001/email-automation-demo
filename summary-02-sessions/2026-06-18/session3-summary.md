# Session 3 — NotebookLM Audio Overview 生成（中途取消）

**日期**：2026-06-18
**主題**：用 NotebookLM CLI 為 email-automation-demo 專案生成「雙主持人 podcast」語音摘要，使用者中途決定不下載並取消

---

## 完成事項

### NotebookLM 操作（主 Claude 直接做，依 notebooklm-delegation 規則 1）

- 回答使用者問題：**NotebookLM 不支援直接上傳 `.zip`**，支援格式為 PDF / `.txt` / `.md` / Google Docs/Slides / 網站 URL / YouTube URL / 音訊 / 純文字；繞道是「先解壓逐檔加」或「打包成單一 Markdown」
- 把整個專案打包成單一 Markdown 來源（`README.md` + `CLAUDE.md` + `docs/architecture.md` + 全部 10 支 `.py`），共 **2561 行 / 107735 bytes**
- 建立 notebook `email-automation-demo`（id `2d72fc48-5367-4433-b6b4-360f27e53b1d`）
- 加入打包來源（source id `07f114dd-96cf-4443-b6fe-65f7ad1806c1`）
- 觸發繁中（`zh_Hant`）audio overview，格式 `deep-dive` / 長度 `default`（artifact id `5fc700de-2b38-459f-960a-d4a8c348e031`）
- 開背景輪詢任務 `bm10cactn`（`artifact wait` → `download audio`）

### 使用者中途指令

- 「stop it」→ 用 `TaskStop` 停掉背景輪詢 `bm10cactn`（雲端生成不受影響，會自己跑完）
- 「no need to 下載」→ 確認不下載 `.m4a`
- 「順手清掉」→ `rm -rf .nlm-pipeline`（打包來源 + 4 個 JSON 紀錄），git status 回乾淨

---

## 關鍵技術筆記

### NotebookLM CLI 已升級到新版（指令結構變更，覆寫舊記憶）

- 舊記憶的 `notebooklm notebook list` **已失效** → 新版是 `notebooklm list`
- 新版指令樹：
  - Notebooks：`list` / `create` / `delete` / `rename` / `summary`
  - `source` group：`add` / `add-drive` / `list` / `delete` / `wait` …
  - `artifact` group：`list` / `poll` / **`wait`**（阻塞到完成/失敗/timeout）/ `delete` / `export` …
  - `generate <type>`：`audio` / `slide-deck` / `infographic` / `mind-map` / `quiz` / `video` …
  - `download <type>`：`audio` / `slide-deck` …
- `generate audio` 參數：`--format [deep-dive|brief|critique|debate]` / `--length [short|default|long]` / `--language` / `-s source` / `--wait/--no-wait` / `--retry`
- `artifact wait <ART> -n <NB> --timeout 900 --interval 20 --json`：給 LLM agent 用的阻塞等待
- `download audio -n <NB> -a <ART> <OUTPUT_PATH>`：positional output path（也可 `--latest` / `--name` 模糊比對）

### Auth 雙層過期（CLI + MCP 各自獨立 auth 檔，都過期）

- 開場 hook 已警告「NotebookLM auth 50 hours old」
- CLI `notebooklm list` → `Authentication expired or invalid. Redirected to accounts.google.com`
- MCP `notebook_list` → `Authentication expired. Run notebooklm-mcp-server auth`
- **兩條通路都過期** → 唯一解是使用者本人跑 `! notebooklm login` 做瀏覽器 OAuth（主 Claude 無法代勞）
- 使用者登入後 `notebooklm list` 正常列出 notebook，繼續流程

### 背景任務取消語義

- `TaskStop` 只停**本機**的 wait/download 腳本，**不取消 NotebookLM 雲端的生成工作** → audio 仍會在雲端跑完，之後可上 notebooklm.google.com 聽或用 `download audio --latest` 抓

---

## 產出檔案

| 檔案 | 動作 | 狀態 |
|------|------|------|
| `.nlm-pipeline/`（暫存） | 建立後刪除 | 已 `rm -rf`，未進版控 |
| NotebookLM `email-automation-demo` notebook | 雲端建立 | 留在雲端（本機無檔） |
| `summary-02-sessions/2026-06-18/session3-summary.md` | 新增 | 本檔 |

> 本 session **無 repo 程式碼改動** — 純 NotebookLM 雲端操作 + 暫存檔清理。

---

## HANDOFF（下次 session 優先處理）

### 立即行動

- [ ] 若還想要這份語音摘要：`notebooklm download audio -n 2d72fc48-5367-4433-b6b4-360f27e53b1d --latest`（雲端應已生成完成）
- [ ] 若不要了：可刪雲端 notebook `notebooklm delete 2d72fc48`（使用者已表示不下載，但未要求刪 notebook）

### 進行中（需接續）

- 無進行中的程式任務。本 session 為一次性 NotebookLM 操作，已收尾。

### 注意事項

- **NotebookLM CLI 已換新版指令**：`notebooklm list`（非 `notebook list`）、`artifact wait`、`generate audio --format/--length`——舊 session 記憶的指令需以本 session 為準
- **NLM auth 約 50 小時過期**，CLI 與 MCP 各自獨立 auth 檔、都會過期 → 過期時只能使用者本人 `! notebooklm login`
- `TaskStop` 不取消雲端生成，只停本機腳本
- repo 未追蹤項目 `.claude/` 與 `AGENTS.md` 為 GitNexus 並行產物，與本 session 無關
