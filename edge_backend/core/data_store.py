"""
共用記憶體資料倉儲
==================
集中管理感測器記錄，讓 usb_receiver 和 api/routes 共用同一份資料。
"""

from datetime import datetime
from typing import List

sensor_records: List[dict] = []
_id_counter: int = 0


def clear_all() -> int:
    global _id_counter
    count = len(sensor_records)
    sensor_records.clear()
    _id_counter = 0
    return count


def append_record(record: dict) -> dict:
    global _id_counter
    _id_counter += 1
    record = dict(record)  # 防止外部 dict 被共用修改
    record["id"] = _id_counter
    if not record.get("timestamp"):
        record["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sensor_records.append(record)
    return record
