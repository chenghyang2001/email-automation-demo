# Session 4 — addwii YouTube Shorts 按讚＋正面留言

**日期**：2026-06-18
**主題**：用 `/addwii-yt-comment` skill（互動模式）為一支空污健康主題的 YouTube Shorts 按讚並發布 9 字正面留言

---

## 完成事項

### addwii-yt-comment pipeline（互動模式，3 候選 → 使用者選 1）

- 輸入：`https://www.youtube.com/shorts/h5B-4ZMayMQ?feature=share`（video ID `h5B-4ZMayMQ`）
- **字幕提取如預期失敗**（Shorts 無字幕軌，`get_transcript.py` 回 "Cannot extract video ID"）→ 依 learnings.md 既有回饋直接走 fallback，不浪費時間重試
- **WebFetch `watch?v=<ID>`** 取得影片標題：「室內悶、過敏好不了？這5種植物是NASA推薦的天然空氣清淨機！#airpollution #health」
- 生成 3 則 8-12 字候選（感性／實用／簡短有力），使用者選 **3.「植物淨化空氣超實用」（9 字）**
- 按讚：`like_video.py` → `previous_rating: none` → `action: liked`（先 getRating 再 rate）
- 留言：`post_comment.py` → 成功，comment_id `Ugzxbt7jPerb0jeBhVR4AaABAg`
- 留言身份：ChengHsien Yang（@chenghsienyang8188）

---

## 關鍵技術筆記

- **Shorts URL 走 og:meta 路線已三度實證**（本 session + S240 + 2026-06-12）：遇 `/shorts/` 直接 WebFetch `watch?v=<ID>`，跳過必然失敗的 `get_transcript.py`
- WebFetch 對 YouTube watch 頁僅穩定回傳 `<title>`（含頻道後綴 `- YouTube`），og:description / 頻道名常因內容截斷取不到 — 標題已足夠生成相關留言
- 按讚成本 getRating(1 unit) + rate(50 unit)；留言成功判定 = API 回傳含 `comment_id`（Ugzxxx），不需截圖確認
- 本 skill 無程式碼改動，純執行既有腳本（`addwii-yt-comment/scripts/`），不觸發三 agent 鐵律

---

## 產出檔案

| 檔案 | 說明 |
|------|------|
| `summary-02-sessions/2026-06-18/session4-summary.md` | 本 summary |

（本 session 無程式碼／設定變更，YouTube 留言為外部副作用，無 repo 內檔案異動）

---

## HANDOFF（下次 session 優先處理）

### 立即行動

- [ ] 無待辦 — addwii 留言任務已完結

### 進行中（需接續）

- 無進行中工作

### 注意事項

- addwii skill 互動模式須等使用者選號才按讚＋留言；若要全自動改用 `addwii auto <URL>`
- 每支影片只留一則，勿重複；短時間大量留言會觸發 YouTube 防垃圾機制（間隔 ≥ 30 秒）
- 留言 OAuth token 在 `~/.config/youtube-comment/token.json`；若回 HTTP 400 invalid_grant = token 過期，需使用者重跑 `auth_youtube.py`（瀏覽器 OAuth 無法代跑）
