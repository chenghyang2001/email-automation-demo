"""已處理 Gmail 訊息 ID 的快取管理模組

透過本地 JSON 檔案記錄已處理的訊息 ID，確保不重複建立 Notion 任務。
快取位置：腳本所在目錄的 .cache/processed_ids.json
"""
import json
import sys
from pathlib import Path

# 快取檔案路徑：相對於本腳本位置，避免硬編碼
_CACHE_FILE = Path(__file__).parent / ".cache" / "processed_ids.json"


def load_cache() -> set:
    """從快取檔案讀取已處理的訊息 ID 集合。

    Returns:
        已處理訊息 ID 的 set；若檔案不存在或格式錯誤，回傳空 set。
    """
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            # 格式損壞時安全降級為空集合，而非讓程式崩潰
            return set()
        return set(data)
    except FileNotFoundError:
        return set()
    except (json.JSONDecodeError, ValueError):
        # JSON 解析失敗代表檔案損壞，回傳空 set 讓程式繼續運作
        return set()


def save_cache(ids: set) -> None:
    """將訊息 ID 集合寫入快取檔案（排序後儲存，方便版本比對）。

    Args:
        ids: 要儲存的訊息 ID 集合。
    """
    # 若 .cache/ 目錄不存在則自動建立，不依賴外部確保目錄存在
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def is_processed(message_id: str, cache: set) -> bool:
    """檢查訊息 ID 是否已在快取中。

    Args:
        message_id: Gmail 訊息 ID。
        cache: 目前的快取 set（由 load_cache() 取得）。

    Returns:
        True 表示已處理（應跳過），False 表示尚未處理。
    """
    return message_id in cache


def mark_processed(message_id: str, cache: set) -> set:
    """回傳加入新訊息 ID 後的快取（immutable style，不修改原 set）。

    Args:
        message_id: 要標記為已處理的 Gmail 訊息 ID。
        cache: 目前的快取 set。

    Returns:
        包含新 ID 的新 set（原 set 不受影響）。
    """
    return cache | {message_id}


if __name__ == "__main__":
    # 冒煙測試：驗證 save/load 往返一致性
    TEST_IDS = {"msg_abc123", "msg_def456", "msg_ghi789"}

    print("=== cache.py 冒煙測試 ===")

    # 測試 1：寫入後讀回結果應與原始集合相同
    print("\n[測試 1] 儲存並讀回快取...")
    save_cache(TEST_IDS)
    loaded = load_cache()
    assert loaded == TEST_IDS, f"往返失敗：期望 {TEST_IDS}，實際 {loaded}"
    print(f"  PASS：讀回 {len(loaded)} 筆，內容一致")

    # 測試 2：is_processed / mark_processed 邏輯正確性
    print("\n[測試 2] 檢查成員判斷與標記功能...")
    new_id = "msg_new_999"
    assert is_processed("msg_abc123", loaded) is True
    assert is_processed(new_id, loaded) is False
    updated = mark_processed(new_id, loaded)
    assert is_processed(new_id, updated) is True
    # 確認 immutable：原 set 不受影響
    assert new_id not in loaded
    print("  PASS：is_processed 與 mark_processed 行為正確（原 set 未被修改）")

    # 清理測試快取（避免汙染正式環境）
    _CACHE_FILE.unlink(missing_ok=True)
    print("\n所有測試通過，測試快取已清除。")
    sys.exit(0)
