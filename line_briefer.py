"""LINE 早安簡報發送模組

透過 LINE Messaging API 的 push endpoint 主動推播早安簡報。
與 telegram_briefer.py 平行，共用 format_briefing() 產出的純文字訊息。

注意：LINE Notify 已於 2025-03-31 停止服務，本模組改用 Messaging API push。
"""
import sys
import time
import uuid

import requests


# LINE Messaging API push 端點（主動推播，不需使用者先發訊息）
_LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

# LINE text message 單則上限 5000 字，超過會回 400。
# 截斷邏輯集中在 _build_push_payload，確保任何呼叫端（含直接呼叫純函式者）
# 都不可能組出超限的 payload。
_LINE_TEXT_LIMIT = 5000


def _build_push_payload(message: str, to: str) -> dict:
    """組 LINE push API 的 request body，並在此處保證訊息不超過 LINE 上限。

    把截斷邏輯放進這個純函式，是因為它是「組 payload」的唯一入口；
    在這裡截斷可讓函式自帶保護、能獨立測試，避免呼叫端各自重複截斷
    （重複邏輯易產生只改一處的漏網之魚）。

    Args:
        message: 要推播的純文字訊息內容。
        to:      推播目標 ID（user ID / group ID / room ID）。

    Returns:
        符合 LINE push API 規格的 request body 字典；text 長度必 <= _LINE_TEXT_LIMIT。
    """
    # 超過上限即截斷並警告。保留至 _LINE_TEXT_LIMIT - 1（4999）字，
    # 留 1 字餘裕避免邊界誤判（LINE 對長度的計算偶有差一）。
    if len(message) > _LINE_TEXT_LIMIT:
        print(
            f"LINE 訊息長度 {len(message)} 超過上限 {_LINE_TEXT_LIMIT}，"
            f"截斷至 {_LINE_TEXT_LIMIT - 1} 字",
            file=sys.stderr,
        )
        message = message[: _LINE_TEXT_LIMIT - 1]

    return {"to": to, "messages": [{"type": "text", "text": message}]}


def send_line(message: str, token: str, to: str) -> bool:
    """透過 LINE Messaging API push 發送訊息，依失敗類型決定是否重試（最多 2 次嘗試）。

    重試策略：
      - 2xx：成功，回 True。
      - 429 / 5xx：暫時性錯誤（限流或伺服器端），可重試。
      - 其他 4xx（如 400 to 無效）：確定性失敗，重試只會再拿同樣錯誤，直接回 False。
      - 連線例外（timeout / 中斷）：暫時性錯誤，可重試。

    Args:
        message: 要發送的純文字訊息內容。
        token:   LINE Channel Access Token。
        to:      推播目標 ID（user ID / group ID / room ID）。

    Returns:
        True 表示至少一次成功，False 表示失敗（含不可重試的 4xx 與兩次嘗試皆敗）。
    """
    # 兩次嘗試共用同一把 retry key：防止網路抖動下重複推播。
    # 若第一次其實已送達、只是回應在網路上遺失，重試時 LINE 端會用同一把 key
    # 做去重（idempotency），不會送出第二則晨報。每次呼叫才新生成，確保跨次推播不互相去重。
    retry_key = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Line-Retry-Key": retry_key,
    }
    # 截斷由 _build_push_payload 統一處理，這裡不再重複，避免雙重邏輯。
    payload = _build_push_payload(message, to)

    # 最多嘗試 2 次（初次 + 重試一次）
    for attempt in range(1, 3):
        try:
            resp = requests.post(
                _LINE_PUSH_URL, headers=headers, json=payload, timeout=10
            )
            if resp.ok:
                return True

            # 非 2xx：錯誤訊息只印 status_code + text，絕不印 token / Authorization。
            print(
                f"LINE 回傳非 2xx（第 {attempt} 次）："
                f" {resp.status_code} {resp.text}",
                file=sys.stderr,
            )
            # 4xx（429 除外）屬於請求本身的錯誤，重試也是同樣結果，直接放棄。
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                return False
            # 429 / 5xx：可重試。若還有下一次嘗試，先停 1 秒避開限流尖峰。
            if attempt < 2:
                time.sleep(1)
        except requests.RequestException as exc:
            # 連線層例外（timeout / 連線中斷）屬暫時性，可重試。
            print(
                f"LINE 請求例外（第 {attempt} 次）：{exc}",
                file=sys.stderr,
            )
            if attempt < 2:
                time.sleep(1)

    return False


if __name__ == "__main__":
    # ── 冒煙測試 ──────────────────────────────────────────────────────────────
    errors = []

    # 測試 1（happy path）：_build_push_payload 結構正確
    payload = _build_push_payload("Hello", "U123")
    expected = {"to": "U123", "messages": [{"type": "text", "text": "Hello"}]}
    if payload == expected:
        print("✅ 測試 1 PASS：_build_push_payload 結構正確")
    else:
        errors.append(f"❌ 測試 1 FAIL：payload 為 {payload!r}，預期 {expected!r}")

    # 測試 2（edge case）：超長訊息實際呼叫 _build_push_payload 後 text 必須 <= 上限。
    # 直接驗證純函式回傳值，不再手動模擬截斷，避免假陽性。
    long_payload = _build_push_payload("A" * 6000, "U456")
    long_text = long_payload["messages"][0]["text"]
    if len(long_text) <= _LINE_TEXT_LIMIT:
        print(f"✅ 測試 2 PASS：超長訊息經 payload 截斷至 {len(long_text)} 字（<= {_LINE_TEXT_LIMIT}）")
    else:
        errors.append(
            f"❌ 測試 2 FAIL：截斷後長度為 {len(long_text)}，超過上限 {_LINE_TEXT_LIMIT}"
        )

    # 測試 3（邊界 case）：剛好 5000 字不應被截斷，text 應原樣保留。
    boundary_payload = _build_push_payload("y" * _LINE_TEXT_LIMIT, "U789")
    boundary_text = boundary_payload["messages"][0]["text"]
    if len(boundary_text) == _LINE_TEXT_LIMIT:
        print(f"✅ 測試 3 PASS：邊界長度（{_LINE_TEXT_LIMIT} 字）未被截斷")
    else:
        errors.append(
            f"❌ 測試 3 FAIL：邊界訊息長度變為 {len(boundary_text)}，預期 {_LINE_TEXT_LIMIT}"
        )

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        sys.exit(1)

    print("\n所有冒煙測試通過。")
