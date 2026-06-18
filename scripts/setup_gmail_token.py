"""
scripts/setup_gmail_token.py — 一次性 Gmail + Calendar OAuth2 授權設定工具

執行一次即可取得 token JSON，這把 token 同時含 gmail.readonly 與 calendar.events
兩個 scope，可同時填入 GitHub Secret GMAIL_TOKEN_JSON 與 GCAL_TOKEN_JSON（同一個值）。

前置作業：
  1. 前往 https://console.cloud.google.com/
  2. 建立專案 → 在「同一個 GCP 專案」啟用 Gmail API 與 Google Calendar API（兩個都要啟用）
  3. 建立 OAuth2 憑證（桌面應用程式類型）
  4. 下載 credentials.json 至本目錄

執行：
  pip install google-auth-oauthlib
  python scripts/setup_gmail_token.py

產出：
  token.json（base64 後同時存為 GitHub Secret GMAIL_TOKEN_JSON 與 GCAL_TOKEN_JSON）
"""

import base64
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# 一把 token 兩用：gmail.readonly 供取信、calendar.events 供建立行事曆事件。
# 用 calendar.events 而非更廣的 calendar scope，是因為 events.insert 只需要事件寫入權限，
# 遵循最小權限原則（避免拿到讀寫整個行事曆設定的過大權限）。
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",   # Gmail 取信（唯讀）
    "https://www.googleapis.com/auth/calendar.events",  # Calendar 建立／管理事件
]
CREDS_FILE = Path(__file__).parent.parent / "credentials.json"
TOKEN_FILE = Path(__file__).parent.parent / "token.json"


def main() -> None:
    if not CREDS_FILE.exists():
        print(f"錯誤：找不到 {CREDS_FILE}")
        print("請先從 Google Cloud Console 下載 OAuth2 憑證（桌面應用程式），命名為 credentials.json")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }

    TOKEN_FILE.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    print(f"token.json 已儲存至 {TOKEN_FILE}")

    encoded = base64.b64encode(json.dumps(token_data).encode()).decode()
    print("\n=== 複製以下 base64 內容（同時含 gmail.readonly + calendar.events 兩個 scope）===")
    print("=== 同一個值請同時存為 GitHub Secret GMAIL_TOKEN_JSON 與 GCAL_TOKEN_JSON ===")
    print(encoded)

    # 舊 token 只授權 gmail.readonly，CI 呼叫 Calendar 會因 scope 不足噴 403 / insufficient permission。
    print("\n⚠️ 重要提醒：既有的舊 token 不含 calendar.events scope。")
    print("   若你是為了新增 Calendar 功能而來，必須重跑本工具產生新 token 並更新兩個 secret，")
    print("   否則 Calendar 功能在 CI 會因 scope 不足而失敗（insufficient permission / 403）。")


if __name__ == "__main__":
    main()
