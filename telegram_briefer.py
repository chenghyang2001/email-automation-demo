"""Telegram 早安簡報格式化與發送模組"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


# 中文星期對應表（weekday() 回傳 0=週一 … 6=週日）
_WEEKDAY_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


def _priority_emoji(score: int) -> str:
    """依優先級分數回傳對應顏色圓點 emoji。

    高優先（4+）→ 紅、中（3）→ 黃、低（2 以下）→ 綠。
    """
    if score >= 4:
        return "🔴"
    if score == 3:
        return "🟡"
    return "🟢"


def format_briefing(
    summaries: list,
    stats: dict,
    notion_urls: list,
) -> str:
    """將郵件摘要清單格式化為 Telegram 早安簡報訊息字串。

    Args:
        summaries: 摘要字典清單，每項含 one_liner / priority_score / detected_deadline。
        stats: 掃描統計字典，含 scanned / skipped_layer1 / skipped_layer2 / processed。
        notion_urls: Notion 頁面 URL 清單，順序與 summaries 對應，可為 None。

    Returns:
        格式化完成的純文字訊息字串。
    """
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    date_str = now.strftime("%m月%d日") + _WEEKDAY_ZH[now.weekday()]
    time_str = now.strftime("%H:%M")

    scanned = stats.get("scanned", 0)
    skipped = stats.get("skipped_layer1", 0) + stats.get("skipped_layer2", 0)
    processed = stats.get("processed", 0)

    header = f"🌅 Morning Briefing | {date_str}"
    footer = f"🤖 Automated by Claude Code • {time_str}"

    # 收件匣已清空的簡短版本
    if not summaries:
        return (
            f"{header}\n"
            f"✅ 收件匣已清空 — 今天沒有需要行動的郵件\n"
            f"\n"
            f"📊 共掃描 {scanned} 封，跳過 {skipped} 封\n"
            f"\n"
            f"{footer}"
        )

    # 有郵件需要處理的完整版本
    lines = [
        header,
        f"📬 {processed} 封需要處理 | 共掃描 {scanned} 封，跳過 {skipped} 封",
        "",
    ]

    for i, summary in enumerate(summaries):
        one_liner = summary.get("one_liner", "")
        priority_score = summary.get("priority_score", 0)
        detected_deadline = summary.get("detected_deadline")

        emoji = _priority_emoji(priority_score)
        deadline_str = f" — 截止：{detected_deadline}" if detected_deadline else ""

        lines.append(f"{emoji} {one_liner}{deadline_str}")

        # 只有 URL 非 None 才附上 Notion 連結
        url = notion_urls[i] if i < len(notion_urls) else None
        if url is not None:
            lines.append(f"   📋 {url}")

        # 項目之間留空行（最後一項除外）
        if i < len(summaries) - 1:
            lines.append("")

    lines.append("")
    lines.append(footer)

    return "\n".join(lines)


def send_telegram(message: str, token: str, chat_id: str) -> bool:
    """透過 Telegram Bot API 發送訊息，失敗最多重試一次（共 2 次嘗試）。

    Args:
        message: 要發送的純文字訊息內容。
        token:   Telegram Bot Token。
        chat_id: 目標聊天室 ID。

    Returns:
        True 表示至少一次成功，False 表示兩次都失敗。
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    # 最多嘗試 2 次（初次 + 重試一次）
    for attempt in range(1, 3):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.ok:
                return True
            # HTTP 錯誤（4xx/5xx）也算失敗，記錄後繼續重試
            print(
                f"Telegram 回傳非 2xx（第 {attempt} 次）："
                f" {resp.status_code} {resp.text}",
                file=sys.stderr,
            )
        except requests.RequestException as exc:
            print(
                f"Telegram 請求例外（第 {attempt} 次）：{exc}",
                file=sys.stderr,
            )

    return False


if __name__ == "__main__":
    # ── 冒煙測試 ──────────────────────────────────────────────────────────────
    errors = []

    # 測試 1：_priority_emoji 高分 → 紅色
    result = _priority_emoji(5)
    if result == "🔴":
        print("✅ 測試 1 PASS：_priority_emoji(5) == '🔴'")
    else:
        errors.append(f"❌ 測試 1 FAIL：_priority_emoji(5) 回傳 {result!r}，預期 '🔴'")

    # 測試 2：空摘要 → 收件匣已清空訊息
    all_clear_msg = format_briefing(
        [],
        {"scanned": 10, "skipped_layer1": 5, "skipped_layer2": 3, "processed": 0},
        [],
    )
    if "收件匣已清空" in all_clear_msg:
        print("✅ 測試 2 PASS：空摘要產生「收件匣已清空」訊息")
    else:
        errors.append(f"❌ 測試 2 FAIL：訊息未含「收件匣已清空」\n{all_clear_msg}")

    # 測試 3：單筆高優先摘要 → 包含紅色 emoji
    normal_msg = format_briefing(
        [{"one_liner": "Test", "priority_score": 5, "detected_deadline": None}],
        {"scanned": 5, "skipped_layer1": 2, "skipped_layer2": 1, "processed": 1},
        [None],
    )
    if "🔴" in normal_msg:
        print("✅ 測試 3 PASS：高優先摘要訊息包含 '🔴'")
    else:
        errors.append(f"❌ 測試 3 FAIL：訊息未含 '🔴'\n{normal_msg}")

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        sys.exit(1)

    print("\n所有冒煙測試通過。")
