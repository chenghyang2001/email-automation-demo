"""
gmail_fetcher.py — Gmail API OAuth2 郵件抓取器（GitHub Actions 專用）

用途：在 GitHub Actions 中抓取今日 Gmail 郵件，寫入 .cache/today_emails.json，
      供 run_briefing.py 讀取（run_briefing.py 優先使用預取快取）。

環境變數（必填）：
  GMAIL_TOKEN_JSON  OAuth2 token JSON 字串（可為 base64 編碼或原始 JSON）
                    取得方式見 scripts/setup_gmail_token.py

執行方式：
  python gmail_fetcher.py
"""

import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def _extract_body(payload: dict) -> str:
    """遞迴從 MIME 結構中取出純文字 body。

    Gmail API 回傳的郵件 payload 是巢狀 MIME 結構，
    plain text 可能在多層 parts 深處。
    """
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            # Gmail API 用 URL-safe base64 編碼 body，需補 padding
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        body = _extract_body(part)
        if body:
            return body

    return ""


def _load_credentials(token_json_env: str) -> Credentials:
    """從環境變數載入並刷新 OAuth2 憑證。

    支援兩種格式：
    - 原始 JSON 字串（本機測試用）
    - Base64 編碼 JSON（GitHub Secrets 推薦格式，避免換行符號問題）
    """
    try:
        creds_data = json.loads(base64.b64decode(token_json_env).decode("utf-8"))
    except Exception:
        creds_data = json.loads(token_json_env)

    creds = Credentials.from_authorized_user_info(creds_data)

    # 若 access_token 過期但有 refresh_token，自動刷新
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return creds


def fetch_emails_today() -> list[dict]:
    """抓取今日（台灣時間）的 Gmail 收件匣郵件。

    Returns:
        每封郵件含 id / subject / sender / snippet / body 的字典清單。
    """
    token_json = os.environ.get("GMAIL_TOKEN_JSON")
    if not token_json:
        print("錯誤：缺少環境變數 GMAIL_TOKEN_JSON", file=sys.stderr)
        sys.exit(1)

    creds = _load_credentials(token_json)
    service = build("gmail", "v1", credentials=creds)

    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    query = f"after:{today.strftime('%Y/%m/%d')} in:inbox"

    result = service.users().messages().list(
        userId="me", q=query, maxResults=20
    ).execute()

    message_refs = result.get("messages", [])
    if not message_refs:
        return []

    emails = []
    for ref in message_refs:
        try:
            msg = service.users().messages().get(
                userId="me", id=ref["id"], format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            subject = headers.get("Subject", "")
            sender = headers.get("From", "")
            snippet = msg.get("snippet", "")[:200]
            body = _extract_body(msg["payload"])

            emails.append({
                "id": ref["id"],
                "subject": subject,
                "sender": sender,
                "snippet": snippet,
                "body": body[:2000],
            })
        except Exception as exc:
            print(f"[gmail_fetcher] 警告：跳過郵件 id={ref['id']}，原因：{exc}", file=sys.stderr)
            continue

    return emails


def main() -> None:
    """主流程：抓取郵件並寫入快取檔。"""
    emails = fetch_emails_today()

    cache_path = Path(__file__).parent / ".cache" / "today_emails.json"
    cache_path.parent.mkdir(exist_ok=True)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(emails, f, ensure_ascii=False, indent=2)

    print(f"[gmail_fetcher] 寫入 {len(emails)} 封郵件至 {cache_path}")


if __name__ == "__main__":
    main()
