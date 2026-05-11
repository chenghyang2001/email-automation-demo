"""
兩層式電子郵件篩選模組（早晨摘要自動化系統）

第一層：規則比對（快速、免費）— 關鍵字 & 寄件者模式
第二層：Claude AI 判斷（針對模糊郵件）— 呼叫 claude CLI

設計原則：
- 保守策略：不確定時保留郵件（不跳過），避免遺漏重要信件
- Claude CLI 失敗時回傳 False（保留郵件），確保可靠性
"""

import os
import subprocess
import sys
from typing import Any

import anthropic

CLAUDE_CMD = "claude.cmd" if sys.platform == "win32" else "claude"


# ── 第一層：規則清單 ──────────────────────────────────────────

# 主旨關鍵字（全小寫比對）
SKIP_SUBJECTS: list[str] = [
    "newsletter",
    "digest",
    "unsubscribe",
    "no-reply",
    "noreply",
    "notification",
    "automated",
    "do not reply",
    "donotreply",
    "weekly update",
    "monthly report",
    "subscription",
]

# 寄件者前綴模式
SKIP_SENDERS: list[str] = [
    "noreply@",
    "no-reply@",
    "notifications@",
    "newsletter@",
    "digest@",
]


# ── 第一層函式 ────────────────────────────────────────────────

def should_skip_rule(email: dict[str, Any]) -> bool:
    """
    規則比對層：判斷郵件是否應被跳過。

    Returns:
        True  → 跳過（主旨含關鍵字 或 寄件者符合模式）
        False → 保留（通過規則層，進行後續 AI 判斷或保留）
    """
    subject: str = (email.get("subject") or "").lower()
    sender: str = (email.get("sender") or "").lower()

    # 主旨關鍵字比對
    for keyword in SKIP_SUBJECTS:
        if keyword in subject:
            return True

    # 寄件者模式比對
    for pattern in SKIP_SENDERS:
        if sender.startswith(pattern) or ("," + pattern) in sender or ("<" + pattern) in sender:
            return True

    return False


# ── 第二層函式 ────────────────────────────────────────────────

def _ai_judge_via_api(prompt: str) -> bool:
    """
    透過 Anthropic Python SDK 直接呼叫 API 判斷郵件。

    當 ANTHROPIC_API_KEY 環境變數存在時使用此通路，
    比 subprocess 更快且不依賴本機 claude CLI 安裝。

    Args:
        prompt: 已組好的提問字串

    Returns:
        True  → AI 明確回答 NO，跳過郵件
        False → YES / MAYBE / 呼叫失敗 → 保留郵件（保守策略）
    """
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        answer: str = message.content[0].text.strip().upper()

        # 僅在明確 NO（且不含 YES/MAYBE）時才跳過
        if "NO" in answer and "YES" not in answer and "MAYBE" not in answer:
            return True
        return False

    except anthropic.APIError as exc:
        # Anthropic API 錯誤（網路、認證、限流等）→ 保留郵件（保守策略）
        print(f"[AI filter] Anthropic API 錯誤，保留郵件（保守策略）：{exc}", file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001
        # 其他未預期例外 → 保留郵件（保守策略）
        print(f"[AI filter] API 通路發生未預期錯誤，保留郵件（保守策略）：{exc}", file=sys.stderr)
        return False


def _ai_judge_via_subprocess(prompt: str) -> bool:
    """
    透過本機 claude CLI（subprocess stdin 模式）判斷郵件。

    當 ANTHROPIC_API_KEY 未設定時使用此通路，
    依賴 Max 訂閱額度，不消耗 API Credits。

    Args:
        prompt: 已組好的提問字串

    Returns:
        True  → AI 明確回答 NO，跳過郵件
        False → YES / MAYBE / CLI 失敗 → 保留郵件（保守策略）
    """
    try:
        result = subprocess.run(
            [CLAUDE_CMD, "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        answer: str = result.stdout.strip().upper()

        # 僅在明確 NO（且不含 YES/MAYBE）時才跳過
        if "NO" in answer and "YES" not in answer and "MAYBE" not in answer:
            return True
        return False

    except subprocess.TimeoutExpired:
        # 逾時 → 保留郵件（保守策略）
        print("[AI filter] claude CLI 逾時，保留郵件（保守策略）", file=sys.stderr)
        return False
    except FileNotFoundError:
        # 找不到 claude CLI → 保留郵件
        print("[AI filter] 找不到 claude CLI，保留郵件（保守策略）", file=sys.stderr)
        return False


def should_skip_ai(email: dict[str, Any]) -> bool:
    """
    Claude AI 判斷層：僅針對規則層無法明確判斷的模糊郵件使用。

    雙模式派發：
      - ANTHROPIC_API_KEY 存在 → 直接呼叫 Anthropic SDK（_ai_judge_via_api）
      - 未設定 → 回退到 subprocess claude -p 模式（_ai_judge_via_subprocess）

    保守策略：
      - 僅當 AI 明確回答 NO（且不含 YES 或 MAYBE）時才跳過
      - 任何失敗均回傳 False（保留郵件），避免遺漏重要信件

    Returns:
        True  → AI 確定不需要回應，跳過
        False → 需要回應 / 不確定 / 呼叫失敗 → 保留
    """
    subject: str = email.get("subject") or "(無主旨)"
    snippet: str = (email.get("snippet") or "")[:300]

    prompt = (
        "You are an email triage assistant.\n"
        f"Email subject: {subject}\n"
        f"Email preview: {snippet}\n\n"
        "Does this email require a response or action from the recipient? "
        "Reply with ONLY one word: YES, NO, or MAYBE."
    )

    # 雙模式派發：有 API key 走 SDK（快、省 CLI 依賴），否則走 subprocess
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _ai_judge_via_api(prompt)
    return _ai_judge_via_subprocess(prompt)


# ── 主篩選函式 ────────────────────────────────────────────────

def filter_emails(emails: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    """
    對郵件清單套用兩層篩選。

    Args:
        emails: 每封郵件為 dict，包含 id / subject / sender / snippet / body

    Returns:
        tuple (kept_emails, layer1_skipped_count, layer2_skipped_count)
        - kept_emails: 保留的郵件清單
        - layer1_skipped_count: 被規則層跳過的數量
        - layer2_skipped_count: 被 AI 層跳過的數量
    """
    kept: list[dict[str, Any]] = []
    layer1_skipped = 0
    layer2_skipped = 0

    for email in emails:
        # 第一層：規則比對（快速免費）
        if should_skip_rule(email):
            layer1_skipped += 1
            continue

        # 第二層：AI 判斷（針對通過規則層的郵件）
        if should_skip_ai(email):
            layer2_skipped += 1
            continue

        kept.append(email)

    return kept, layer1_skipped, layer2_skipped


# ── 冒煙測試 ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== 冒煙測試：兩層式電子郵件篩選器 ===\n")

    # 測試 1：第一層 — 電子報主旨應被跳過
    newsletter_email: dict[str, Any] = {
        "id": "test-001",
        "subject": "Your Weekly Newsletter — Top Stories",
        "sender": "info@example.com",
        "snippet": "This week's top stories...",
        "body": "",
    }
    result_1 = should_skip_rule(newsletter_email)
    status_1 = "PASS" if result_1 is True else "FAIL"
    print(f"[測試 1] 電子報主旨應被第一層跳過 → {status_1}")
    print(f"  should_skip_rule() = {result_1}（預期 True）\n")

    # 測試 2：第一層 — 一般郵件主旨應通過
    normal_email: dict[str, Any] = {
        "id": "test-002",
        "subject": "Meeting at 3pm tomorrow",
        "sender": "alice@company.com",
        "snippet": "Hi, just confirming our meeting for tomorrow...",
        "body": "",
    }
    result_2 = should_skip_rule(normal_email)
    status_2 = "PASS" if result_2 is False else "FAIL"
    print(f"[測試 2] 一般會議邀請應通過第一層 → {status_2}")
    print(f"  should_skip_rule() = {result_2}（預期 False）\n")

    # 測試 3：寄件者模式 — noreply@ 應被第一層跳過
    noreply_email: dict[str, Any] = {
        "id": "test-003",
        "subject": "Order Confirmation #12345",
        "sender": "noreply@shop.com",
        "snippet": "Your order has been placed.",
        "body": "",
    }
    result_3 = should_skip_rule(noreply_email)
    status_3 = "PASS" if result_3 is True else "FAIL"
    print(f"[測試 3] noreply@ 寄件者應被第一層跳過 → {status_3}")
    print(f"  should_skip_rule() = {result_3}（預期 True）\n")

    # 彙總
    all_pass = all([result_1 is True, result_2 is False, result_3 is True])
    print(f"=== 冒煙測試結果：{'全部通過' if all_pass else '有測試失敗'} ===")
    sys.exit(0 if all_pass else 1)
