"""
notion_creator.py — 建立 Notion 任務卡片，支援雙模式執行

模式一（直接 API）：環境變數 NOTION_API_KEY 存在時，使用 notion-client Python SDK
  直接呼叫 Notion API，速度較快且不依賴 claude CLI。

模式二（subprocess 委派）：NOTION_API_KEY 未設定時，退回原有的 claude -p + Notion MCP 流程，
  複用 claude.ai 已設定的 MCP 認證，不需要額外的 API Key 管理。

設計理由：讓使用者可以在「有 Notion Integration Token」和「只有 Claude Code Max 訂閱」
兩種環境下都能正常執行，無需修改程式碼。
"""
import os
import re
import subprocess
import sys

CLAUDE_CMD = "claude.cmd" if sys.platform == "win32" else "claude"


def priority_label(score: int) -> str:
    """
    將數字優先度分數轉換為 P1/P2/P3 標籤。

    之所以分三段而非五段，是為了與 Notion 看板欄位 "P1/P2/P3" 對應，
    避免顆粒度過細導致標籤選擇困難（5 個分數 → 3 個標籤的折疊對應）。
    """
    if score >= 4:
        return "P1"
    if score == 3:
        return "P2"
    return "P3"


def _create_via_api(
    summary: dict,
    email: dict,
    db_id: str,
    name: str,
    priority: str,
    source: str,
) -> "str | None":
    """
    使用 notion-client SDK 直接呼叫 Notion API 建立任務頁面。

    比 subprocess 路徑快，且不依賴 claude CLI 是否安裝。
    NOTION_API_KEY 必須已在環境變數中（呼叫前由 create_notion_task 確認）。
    """
    try:
        from notion_client import Client  # noqa: PLC0415（延遲 import 避免未安裝時全模組崩潰）
    except ImportError:
        print(
            "[notion_creator] 錯誤：notion-client 套件未安裝。"
            "請執行 pip install notion-client 後重試。",
            file=sys.stderr,
        )
        return None

    try:
        notion = Client(auth=os.environ["NOTION_API_KEY"])

        # 組合 Notion properties，截止日期為 None 時整個 Due Date 屬性不傳遞
        properties: dict = {
            "Name": {"title": [{"text": {"content": name}}]},
            "Priority": {"select": {"name": priority}},
            "Status": {"select": {"name": "Todo"}},
            "Notes": {"rich_text": [{"text": {"content": summary["full_summary"][:2000]}}]},
            "Action": {"rich_text": [{"text": {"content": summary["action_required"][:2000]}}]},
            "Source": {"rich_text": [{"text": {"content": source[:2000]}}]},
            "Email ID": {"rich_text": [{"text": {"content": email["id"]}}]},
        }

        if summary["detected_deadline"] is not None:
            properties["Due Date"] = {"date": {"start": summary["detected_deadline"]}}

        response = notion.pages.create(
            parent={"database_id": db_id},
            properties=properties,
        )
        return response.get("url")

    except Exception as exc:  # notion-client 可能拋出多種例外（APIResponseError 等）
        print(
            f"[notion_creator] 錯誤：Notion API 呼叫失敗。{exc}",
            file=sys.stderr,
        )
        return None


def _create_via_subprocess(
    summary: dict,
    email: dict,
    db_id: str,
    name: str,
    priority: str,
    source: str,
) -> "str | None":
    """
    透過 claude -p + Notion MCP 在 Notion 資料庫建立任務頁面。

    委託給 Claude 代理執行，複用 claude.ai 已設定的 MCP 認證，
    不需要在本機額外管理 Notion Integration Token。
    """
    # 截止日期為 None 時整個 Due Date 屬性不傳遞，避免 Notion API 拋錯
    due_date_line = (
        f'- Due Date: {summary["detected_deadline"]} (YYYY-MM-DD format)\n'
        if summary["detected_deadline"] is not None
        else ""
    )

    prompt = (
        f"Use the Notion MCP tool to create a new page in Notion database ID: {db_id}\n\n"
        f"Set these properties exactly:\n"
        f'- Name: {name}\n'
        f'- Priority: {priority}\n'
        f'- Status: Todo\n'
        f'- Notes: {summary["full_summary"]}\n'
        f'- Action: {summary["action_required"]}\n'
        f'- Source: {source}\n'
        f'- Email ID: {email["id"]}\n'
        f"{due_date_line}"
        f"\nReturn only the created page URL."
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
        output = result.stdout or ""
        match = re.search(r"https://www\.notion\.so/\S+", output)
        if match:
            return match.group(0)
        # claude 執行成功但找不到 URL（可能 Notion MCP 未設定或回傳格式不同）
        print(
            f"[notion_creator] 未在輸出中找到 Notion URL。\n"
            f"stdout: {output[:200]}\nstderr: {result.stderr[:200]}",
            file=sys.stderr,
        )
        return None

    except subprocess.TimeoutExpired:
        print(
            "[notion_creator] 警告：呼叫 claude -p 逾時（60 秒），跳過此任務建立。",
            file=sys.stderr,
        )
        return None

    except FileNotFoundError:
        # claude CLI 未安裝或不在 PATH 時的明確錯誤（避免靜默失敗）
        print(
            "[notion_creator] 錯誤：找不到 claude 指令，請確認 Claude Code CLI 已安裝並設定 PATH。",
            file=sys.stderr,
        )
        return None


def create_notion_task(
    summary: dict,
    email: dict,
    db_id: str,
    dry_run: bool = False,
) -> "str | None":
    """
    根據郵件摘要在 Notion 資料庫建立一張任務卡片。

    summary 必要鍵：
      one_liner, full_summary, action_required, detected_deadline, priority_score

    email 必要鍵：
      id, subject, sender

    db_id：目標 Notion 資料庫 ID。

    若 dry_run=True：僅印出預計建立的任務資訊，不實際呼叫 claude CLI 或 Notion API。
    成功時回傳建立後的 Notion 頁面 URL；失敗或 dry_run 時回傳 None。

    執行模式由環境變數決定：
      - NOTION_API_KEY 已設定 → 直接呼叫 Notion API（_create_via_api）
      - NOTION_API_KEY 未設定 → 委派 claude -p + MCP（_create_via_subprocess）
    """
    # 組合頁面欄位值（兩條路徑共用）
    name = summary["one_liner"][:100]
    priority = priority_label(summary["priority_score"])
    source = f"{email['sender']} | {email['subject']}"

    if dry_run:
        print(f"[notion_creator] [DRY RUN] 建立任務: {name} ({priority})")
        return None

    # 根據環境變數決定使用哪條路徑
    if os.environ.get("NOTION_API_KEY"):
        return _create_via_api(summary, email, db_id, name, priority, source)
    return _create_via_subprocess(summary, email, db_id, name, priority, source)


if __name__ == "__main__":
    # 冒煙測試：驗證 priority_label 對應規則
    test_cases = [
        (5, "P1"),
        (4, "P1"),
        (3, "P2"),
        (2, "P3"),
        (1, "P3"),
    ]
    all_pass = True
    for score, expected in test_cases:
        result = priority_label(score)
        status = "PASS" if result == expected else "FAIL"
        if result != expected:
            all_pass = False
        print(f"  priority_label({score}) = {result!r}  (預期 {expected!r}) [{status}]")

    print()
    print("冒煙測試結果:", "全部通過" if all_pass else "有失敗項目")
    sys.exit(0 if all_pass else 1)
