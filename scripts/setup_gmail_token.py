"""
scripts/setup_gmail_token.py — 一次性 Gmail OAuth2 授權設定工具

執行一次即可取得 token JSON，存為 GitHub Secret GMAIL_TOKEN_JSON。

前置作業：
  1. 前往 https://console.cloud.google.com/
  2. 建立專案 → 啟用 Gmail API
  3. 建立 OAuth2 憑證（桌面應用程式類型）
  4. 下載 credentials.json 至本目錄

執行：
  pip install google-auth-oauthlib
  python scripts/setup_gmail_token.py

產出：
  token.json（存為 GitHub Secret GMAIL_TOKEN_JSON 的內容）
"""

import base64
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
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
    print("\n=== 複製以下內容，存為 GitHub Secret GMAIL_TOKEN_JSON ===")
    print(encoded)


if __name__ == "__main__":
    main()
