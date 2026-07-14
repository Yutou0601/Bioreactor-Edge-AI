"""
CSV 監看轉發器
================
監控電腦上的感測器軟體持續把資料寫進 BTP_Sensor_log-YYYY-MM-DD.csv，欄位為
舊版序列埠格式（年,月,日,時,分,秒,_,ORP(mV),反應器壓力,pH,溫度,混合槽壓力,
CO2%,CH4%，多一行中文標題），與 usb_receiver.py 直讀序列埠時解析的格式相同。
這支腳本不走序列埠，而是輪詢該檔案，偵測到新增列就套用跟 usb_receiver.py
相同的 ORP 訊號前處理（一階差分去突波 + 線性內插 + EMA），確保轉發給 Jetson
的 ORP 值跟模型訓練時看到的資料型態一致，而不是直接轉發未處理的原始值。
處理完 publish 到 Jetson 的 MQTT reactor/01/sensors（Jetson 上的
core/mqtt_client.py 已在訂閱這個主題，收到後自動推論並發布
reactor/01/prediction，前端訂閱即可顯示即時結果）。

使用方式：
    python csv_watcher.py --dir "C:\\Users\\BTP\\Desktop\\data"
    python csv_watcher.py --dir "C:\\Users\\BTP\\Desktop\\data" --broker 192.168.55.1 --poll 5

換日時會自動切到新的一天的檔案，重新開始計算已轉發的列數並重置訊號處理器，
Ctrl+C 結束。
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

from core.signal_processor import ORPSignalProcessor

# Windows 主控台/重導向輸出預設用系統 codepage（如 cp1252），無法編碼中文字元
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MQTT_PORT = 1883
MQTT_TOPIC_PUBLISH = "reactor/01/sensors"

_processor = ORPSignalProcessor(
    ema_window=10,
    spike_threshold=-20.0,
    spike_max_minutes=15,
)


def today_csv_path(folder: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(folder, f"BTP_Sensor_log-{today}.csv")


def read_all_data_rows(path: str) -> list:
    """回傳所有資料列（跳過標題列），每列是逗號切開的字串陣列。"""
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    return rows[1:] if rows else []


def parse_legacy_row(parts: list) -> dict | None:
    """解析舊版序列埠格式：年,月,日,時,分,秒,_,ORP,反應器壓力,pH,溫度,混合槽壓力,CO2%,CH4%"""
    if len(parts) < 14:
        return None
    try:
        ts = (
            f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            f" {int(parts[3]):02d}:{int(parts[4]):02d}:{int(parts[5]):02d}"
        )
        return {
            "timestamp":      ts,
            "orp_raw":        float(parts[7]),
            "pressure":       float(parts[8]),
            "ph":             float(parts[9]),
            "temp":           float(parts[10]),
            "mixer_pressure": float(parts[11]),
            "co2_pct":        float(parts[12]),
            "ch4_pct":        float(parts[13]),
        }
    except (ValueError, IndexError):
        return None


def publish_point(client: mqtt.Client, parsed: dict, pt) -> None:
    try:
        payload = json.dumps({
            "timestamp":      pt.timestamp,
            "orp":            pt.ema,
            "pressure":       parsed["pressure"],
            "ph":             parsed["ph"],
            "temp":           parsed["temp"],
            "mixer_pressure": parsed["mixer_pressure"],
            "co2_pct":        parsed["co2_pct"],
            "ch4_pct":        parsed["ch4_pct"],
        })
        client.publish(MQTT_TOPIC_PUBLISH, payload, qos=1)
        print(f"[MQTT] 已轉發 {pt.timestamp}  ORP(EMA)={pt.ema:.1f}")
    except Exception as e:
        print(f"[MQTT] 發布失敗：{e}")


def main():
    parser = argparse.ArgumentParser(description="監看監控電腦的 BTP_Sensor_log CSV，逐行轉發至 Jetson MQTT")
    parser.add_argument('--dir', required=True, help=r"CSV 所在資料夾，例如 C:\Users\BTP\Desktop\data")
    parser.add_argument('--broker', default="192.168.55.1", help="Jetson MQTT Broker IP（預設 192.168.55.1）")
    parser.add_argument('--poll', type=float, default=5.0, help="輪詢間隔秒數（預設 5 秒，遠短於資料 1 分鐘一筆的頻率）")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print(f"[錯誤] 資料夾不存在：{args.dir}")
        sys.exit(1)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "csv_watcher")
    client.connect_async(args.broker, MQTT_PORT, keepalive=60)
    client.loop_start()
    print(f"[MQTT] 背景連線至 {args.broker}:{MQTT_PORT}，開始監看 {args.dir}\n")

    seen_count = 0
    current_path = None

    try:
        while True:
            path = today_csv_path(args.dir)
            if path != current_path:
                current_path = path
                seen_count = 0
                _processor.reset()
                print(f"[CSV] 監看目標：{current_path}")

            rows = read_all_data_rows(current_path)
            for parts in rows[seen_count:]:
                parsed = parse_legacy_row(parts)
                if parsed is None:
                    print(f"[CSV] 跳過格式不完整的列：{parts}")
                    continue
                for pt in _processor.process(parsed["timestamp"], parsed["orp_raw"]):
                    publish_point(client, parsed, pt)
            seen_count = len(rows)

            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\n[CSV] 使用者中斷，結束監看。")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    main()
