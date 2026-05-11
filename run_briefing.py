"""早安簡報主協調器（Morning Briefing Orchestrator）

串接 cache / email_filter / summarizer / notion_creator / telegram_briefer 五個模組，
執行完整的「抓信 → 過濾 → 摘要 → 建 Notion → 發 Telegram」流程。

Smoke test 即為 --dry-run 模式（不呼叫 claude subprocess、不建 Notion、不發 Telegram）：
    python run_briefing.py --dry-run
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CLAUDE_CMD = "claude.cmd" if sys.platform == "win32" else "claude"
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from cache import load_cache, save_cache, is_processed, mark_processed
from email_filter import filter_emails
from summarizer import summarize_email
from notion_creator import create_notion_task
from telegram_briefer import format_briefing, send_telegram


def _check_env() -> None:
    """確認必要環境變數都存在，缺少任一個就終止程序。

    不用 .get("KEY", "") 靜默掩蓋：缺少環境變數是設定錯誤，
    應該早死早超生，避免後續流程用空值產生難以追蹤的 bug。
    """
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "NOTION_DATABASE_ID"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"錯誤：缺少環境變數 {missing}", file=sys.stderr)
        sys.exit(1)


def _fetch_emails_today(dry_run: bool) -> list[dict]:
    """抓取今日（台灣時間）收到的 Gmail 郵件。

    dry_run=True 時回傳假資料，供不依賴 claude CLI 的快速驗證使用。
    dry_run=False 時透過 `claude -p` 呼叫 Gmail MCP 工具取得 JSON 陣列。
    """
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    date_str = today.strftime("%Y/%m/%d")

    if dry_run:
        # 假資料：一封需要處理的重要信、一封電子報（預期被過濾層擋掉）
        return [
            {
                "id": "dry_001",
                "subject": "Re: Project proposal",
                "sender": "alice@example.com",
                "snippet": "Hi, please review the proposal by Thursday EOD before the client call.",
                "body": "Hi, please review the proposal by Thursday EOD. We need your approval before the Friday client call.",
            },
            {
                "id": "dry_002",
                "subject": "Weekly Newsletter",
                "sender": "noreply@newsletter.com",
                "snippet": "This week's top stories...",
                "body": "Newsletter content.",
            },
        ]

    # 優先使用預取快取（Gmail MCP 在 subprocess 模式下無法自動授權時的降級方案）
    prefetch_path = Path(__file__).parent / ".cache" / "today_emails.json"
    if prefetch_path.exists():
        try:
            with open(prefetch_path, encoding="utf-8") as f:
                emails = json.load(f)
            print(f"[抓信] 使用預取快取：{prefetch_path.name}（{len(emails)} 封）")
            return emails
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[抓信] 預取快取讀取失敗：{exc}，改用即時抓取", file=sys.stderr)

    prompt = (
        f"Use Gmail MCP to search for emails received after {date_str} Taiwan time. "
        "Return ONLY a JSON array. Each item must have: 'id' (message id), 'subject', "
        "'sender', 'snippet' (first 200 chars), 'body' (full text). "
        "If no emails, return []. Return ONLY the JSON array."
    )

    try:
        result = subprocess.run(
            [CLAUDE_CMD, "-p", "--dangerouslySkipPermissions"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        print("警告：抓取郵件逾時（60s），本次跳過", file=sys.stderr)
        return []

    # 從 claude 輸出中提取 JSON 陣列（可能夾雜說明文字）
    match = re.search(r"\[.*\]", result.stdout, re.DOTALL)
    if not match:
        print(f"警告：無法從輸出解析 JSON 陣列。stdout={result.stdout[:200]!r}", file=sys.stderr)
        return []

    try:
        return json.loads(match.group())
    except json.JSONDecodeError as e:
        print(f"警告：JSON 解析失敗 — {e}", file=sys.stderr)
        return []


def main() -> None:
    """主流程：解析參數 → 環境檢查 → 抓信 → 過濾 → 摘要 → Notion → Telegram"""

    parser = argparse.ArgumentParser(description="早安 Email 簡報系統")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="使用假資料跑完整流程，不呼叫 claude CLI / Notion API / Telegram API",
    )
    args = parser.parse_args()

    # 優先讀同目錄的 .env，避免讀到其他專案的設定
    load_dotenv(Path(__file__).parent / ".env")

    _check_env()

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    db_id = os.environ["NOTION_DATABASE_ID"]

    print(f"[早安簡報] 啟動 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"[早安簡報] 日期：{datetime.now(ZoneInfo('Asia/Taipei')).date()}")

    # ── Step 1：抓取今日郵件 ──────────────────────────────────────
    all_emails = _fetch_emails_today(args.dry_run)
    print(f"[Step 1] 抓到 {len(all_emails)} 封郵件")

    # ── Step 2：排除已處理（cache）──────────────────────────────────
    cache = load_cache()
    new_emails = [e for e in all_emails if not is_processed(e.get("id", ""), cache)]
    cached_count = len(all_emails) - len(new_emails)
    print(f"[Step 2] 快取已處理：{cached_count} 封，新信：{len(new_emails)} 封")

    # ── Step 3：規則過濾（L1 關鍵字 + L2 語意）──────────────────────
    filtered, l1_skip, l2_skip = filter_emails(new_emails)
    print(f"[Step 3] L1 跳過：{l1_skip}，L2 跳過：{l2_skip}，進入摘要：{len(filtered)}")

    stats = {
        "scanned": len(all_emails),
        "skipped_layer1": l1_skip,
        "skipped_layer2": l2_skip,
        "processed": len(filtered),
    }

    # ── Step 4：逐封摘要 + 建 Notion + 更新 cache ────────────────────
    summaries: list = []
    notion_urls: list = []

    for email in filtered:
        try:
            summary = summarize_email(email)
            if summary is None:
                print(f"警告：summarize_email 回傳 None，跳過 id={email.get('id')}", file=sys.stderr)
                continue

            if args.dry_run:
                # dry_run 模式只印出摘要結果，不寫入 Notion
                print(
                    f"  [DRY RUN 摘要] id={email.get('id')} | "
                    f"priority={summary.get('priority')} | "
                    f"one_liner={summary.get('one_liner')} | "
                    f"action={summary.get('action')} | "
                    f"deadline={summary.get('deadline')}"
                )
                notion_urls.append(None)
            else:
                url = create_notion_task(summary, email, db_id)
                print(f"  [Notion] 建立任務：{url}")
                notion_urls.append(url)

            summaries.append(summary)
            # 每封處理完就更新 cache，避免中途失敗時重複處理
            cache = mark_processed(email.get("id", ""), cache)

        except Exception as exc:
            # 單封失敗不中斷整體流程（Graceful Failure）
            print(
                f"警告：處理郵件 id={email.get('id')} 時發生錯誤：{exc}，跳過",
                file=sys.stderr,
            )
            continue

    # ── Step 5：儲存 cache（dry_run 不寫入，避免污染真實 cache）──────
    if not args.dry_run:
        save_cache(cache)

    # ── Step 6：組裝並發送 Telegram 簡報 ─────────────────────────────
    message = format_briefing(summaries, stats, notion_urls)

    print("\n" + "=" * 60)
    print(message)
    print("=" * 60 + "\n")

    if not args.dry_run:
        result = send_telegram(message, token, chat_id)
        print(f"[Telegram] 發送結果：{result}")
    else:
        print("[DRY RUN] Telegram 不發送")

    # ── 最終統計 ──────────────────────────────────────────────────
    print(
        f"[完成] 掃描 {stats['scanned']} 封 | "
        f"L1 跳過 {stats['skipped_layer1']} | "
        f"L2 跳過 {stats['skipped_layer2']} | "
        f"處理 {stats['processed']} 封"
    )


# Smoke test 即為 --dry-run：
#   python run_briefing.py --dry-run
# 此模式使用假資料跑完整流程，不需要真實的 Telegram/Notion/Gmail 憑證。
if __name__ == "__main__":
    main()
