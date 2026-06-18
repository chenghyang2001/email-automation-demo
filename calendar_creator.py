"""
calendar_creator.py — 為有截止日的郵件建立 Google Calendar 全天事件

用途：run_briefing.py 處理每封信時，若該信摘要含 detected_deadline（YYYY-MM-DD），
      除了建立 Notion 任務外，再於 Google Calendar 建立一個「全天事件」當作提醒。

設計取捨：本模組採「單一直接 API 路徑」（google-api-python-client，已是現有依賴），
          不做 notion_creator.py 那種 subprocess 雙通路。理由是 Calendar 屬選填增強功能，
          只在 GCAL_TOKEN_JSON 存在時啟用，無需 Max 訂閱降級路徑，保持簡單。

環境變數：
  GCAL_TOKEN_JSON   OAuth2 token JSON 字串（可為 base64 編碼或原始 JSON），
                    Scope 需含 https://www.googleapis.com/auth/calendar.events。
                    （由呼叫端 gate 確認存在後才呼叫 create_calendar_event）

執行方式（冒煙測試）：
  python calendar_creator.py
"""

import base64
import json
import os
import sys
from datetime import date, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Calendar 寫入事件所需的最小 scope（只建立事件，不讀其他日曆資料）
_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def _build_event_body(summary: dict, email: dict) -> dict:
    """組出 Google Calendar event body（純函式，不打 API，方便單元測試）。

    為何拆成純函式：建立 event body 是純資料轉換邏輯，抽出來才能在不連線、
    不需憑證的情況下驗證 +1 天等邊界規則（測試友善）。

    全天事件的日期規則（Google Calendar API 特性）：
      start.date = detected_deadline（截止當天）
      end.date   = detected_deadline + 1 天

    為何 end 要 +1 天：Google Calendar 全天事件的 end.date 是「排除式（exclusive）」，
    意思是事件涵蓋到 end.date 的「前一天」為止。若 start 與 end 都填同一天，
    Google 會視為零長度而拒絕或顯示異常；填 start 當天、end 隔天，才能正確
    呈現「涵蓋截止當天一整天」的全天事件。

    Args:
        summary: 含 one_liner / full_summary / action_required / detected_deadline 的字典。
        email:   含 sender / subject 的字典。

    Returns:
        可直接傳給 events().insert(body=...) 的事件字典。
    """
    deadline = summary["detected_deadline"]
    # 用 date.fromisoformat 解析 YYYY-MM-DD，再加一天得到 exclusive 的 end.date
    start_date = date.fromisoformat(deadline)
    end_date = start_date + timedelta(days=1)

    # description 串接完整摘要 + 行動項 + 來源信件，方便在行事曆上一眼看懂背景
    description = (
        f"{summary['full_summary']}"
        f"\n\nAction: {summary['action_required']}"
        f"\n\nSource: {email['sender']} | {email['subject']}"
    )

    return {
        "summary": summary["one_liner"],
        "description": description,
        "start": {"date": start_date.isoformat()},
        "end": {"date": end_date.isoformat()},
    }


def _load_credentials(token_json: str) -> Credentials:
    """從 token JSON 字串載入並（必要時）刷新 OAuth2 憑證。

    比照 gmail_fetcher._load_credentials 的寫法，支援兩種格式：
    - Base64 編碼 JSON（GitHub Secrets 推薦格式，避免換行符號問題）
    - 原始 JSON 字串（本機測試用）

    Args:
        token_json: OAuth2 token 的 JSON 字串（base64 或原始）。

    Returns:
        可用於 build("calendar", ...) 的 Credentials 物件。
    """
    try:
        creds_data = json.loads(base64.b64decode(token_json).decode("utf-8"))
    except Exception:
        # base64 解碼失敗代表傳入的就是原始 JSON 字串，直接解析
        creds_data = json.loads(token_json)

    # 指定 scope，確保刷新後的憑證帶有 calendar.events 權限
    creds = Credentials.from_authorized_user_info(creds_data, scopes=[_CALENDAR_SCOPE])

    # access_token 過期但有 refresh_token 時自動刷新，避免每次都要重新授權
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return creds


def create_calendar_event(
    summary: dict,
    email: dict,
    calendar_id: str = "primary",
    dry_run: bool = False,
) -> "str | None":
    """為一封有截止日的郵件建立 Google Calendar 全天事件。

    self-protecting：若 summary 沒有 detected_deadline（None），直接回 None 不建事件，
    也不嘗試連線——沒有日期的全天事件沒有意義。

    Args:
        summary:     郵件摘要字典（需含 one_liner / full_summary / action_required /
                     detected_deadline）。
        email:       郵件字典（需含 sender / subject）。
        calendar_id: 目標日曆 ID，預設 "primary"（使用者主日曆）。
        dry_run:     True 時只印出預計建立的事件，不實際呼叫 API。

    Returns:
        成功時回傳事件的 htmlLink（可點開的網址）；
        dry_run / 無截止日 / 失敗時回傳 None。
    """
    deadline = summary.get("detected_deadline")

    if dry_run:
        print(
            f"[calendar_creator] [DRY RUN] 建立事件: "
            f"{summary.get('one_liner')} @ {deadline}"
        )
        return None

    # 沒有截止日就不建事件（self-protecting，且避免無謂的 API 連線）
    if deadline is None:
        return None

    token_json = os.environ["GCAL_TOKEN_JSON"]

    try:
        creds = _load_credentials(token_json)
        service = build("calendar", "v3", credentials=creds)
        event_body = _build_event_body(summary, email)
        response = (
            service.events()
            .insert(calendarId=calendar_id, body=event_body)
            .execute()
        )
        return response.get("htmlLink")

    except Exception as exc:
        # google-api 可能拋出多種例外（HttpError / RefreshError 等），用寬鬆 except
        # 統一捕捉；訊息只印例外本身，絕不印出 token_json / creds 內容以免洩漏憑證。
        print(
            f"[calendar_creator] 錯誤：Google Calendar API 呼叫失敗。{exc}",
            file=sys.stderr,
        )
        return None


if __name__ == "__main__":
    # ── 冒煙測試（3 案例）─────────────────────────────────────────
    all_pass = True

    # 共用的假資料
    sample_email = {
        "sender": "alice@example.com",
        "subject": "Re: Project proposal",
    }

    # TC1（Happy）：_build_event_body 對 deadline 2026-06-20 →
    #   start.date == "2026-06-20"，end.date == "2026-06-21"（+1 天 exclusive），
    #   summary == one_liner。
    print("=== TC1（Happy）：_build_event_body +1 天規則 ===")
    summary_tc1 = {
        "one_liner": "Review proposal before client call",
        "full_summary": "Alice needs the proposal reviewed and approved.",
        "action_required": "Reply with approval",
        "detected_deadline": "2026-06-20",
    }
    body = _build_event_body(summary_tc1, sample_email)
    tc1_ok = (
        body["start"]["date"] == "2026-06-20"
        and body["end"]["date"] == "2026-06-21"
        and body["summary"] == "Review proposal before client call"
    )
    print(f"  start.date = {body['start']['date']!r}（預期 '2026-06-20'）")
    print(f"  end.date   = {body['end']['date']!r}（預期 '2026-06-21'，+1 天 exclusive）")
    print(f"  summary    = {body['summary']!r}")
    print(f"  [{'PASS' if tc1_ok else 'FAIL'}]\n")
    all_pass = all_pass and tc1_ok

    # TC2（Edge）：detected_deadline 為 None 時，create_calendar_event 回 None
    #   且不嘗試連線（不需設定 GCAL_TOKEN_JSON 也能跑過）。
    print("=== TC2（Edge）：無截止日 → 回 None 且不連線 ===")
    summary_tc2 = {
        "one_liner": "FYI only",
        "full_summary": "No action needed.",
        "action_required": "None",
        "detected_deadline": None,
    }
    result_tc2 = create_calendar_event(summary_tc2, sample_email, dry_run=False)
    tc2_ok = result_tc2 is None
    print(f"  回傳 = {result_tc2!r}（預期 None）")
    print(f"  [{'PASS' if tc2_ok else 'FAIL'}]\n")
    all_pass = all_pass and tc2_ok

    # TC3（Edge）：description 正確串接 action_required 與 source（含 sender|subject）。
    print("=== TC3（Edge）：description 串接 action 與 source ===")
    body_tc3 = _build_event_body(summary_tc1, sample_email)
    desc = body_tc3["description"]
    tc3_ok = (
        "Action: Reply with approval" in desc
        and "Source: alice@example.com | Re: Project proposal" in desc
        and summary_tc1["full_summary"] in desc
    )
    print(f"  description =\n    {desc!r}")
    print(f"  含 full_summary：{summary_tc1['full_summary'] in desc}")
    print(f"  含 'Action: Reply with approval'：{'Action: Reply with approval' in desc}")
    print(
        "  含 'Source: alice@example.com | Re: Project proposal'："
        f"{'Source: alice@example.com | Re: Project proposal' in desc}"
    )
    print(f"  [{'PASS' if tc3_ok else 'FAIL'}]\n")
    all_pass = all_pass and tc3_ok

    print("=== 冒煙測試結果:", "全部通過 ===" if all_pass else "有失敗項目 ===")
    sys.exit(0 if all_pass else 1)
