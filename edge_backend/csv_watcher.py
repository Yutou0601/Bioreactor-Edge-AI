"""
CSV 監看轉發器
================
監控電腦上的感測器軟體持續把資料寫進 BTP_Sensor_log-YYYY-MM-DD.csv（欄位格式
與 usb_receiver.py 輸出相同：timestamp, orp, orp_raw, orp_cleaned, is_anomaly,
pressure, ph, temp, mixer_pressure, co2_pct, ch4_pct, note）。這支腳本不走序列
埠，而是輪詢該檔案，偵測到新增列就 publish 到 Jetson 的 MQTT reactor/01/sensors
（Jetson 上的 core/mqtt_client.py 已在訂閱這個主題，收到後自動推論並發布
reactor/01/prediction，前端訂閱即可顯示即時結果）。

使用方式：
    python csv_watcher.py --dir "C:\\Users\\BTP\\Desktop\\data"
    python csv_watcher.py --dir "C:\\Users\\BTP\\Desktop\\data" --broker 192.168.55.1 --poll 5

換日時會自動切到新的一天的檔案，重新開始計算已轉發的列數，Ctrl+C 結束。
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

# Windows 主控台/重導向輸出預設用系統 codepage（如 cp1252），無法編碼中文字元
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MQTT_PORT = 1883
MQTT_TOPIC_PUBLISH = "reactor/01/sensors"


def today_csv_path(folder: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(folder, f"BTP_Sensor_log-{today}.csv")


def read_all_rows(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def publish_row(client: mqtt.Client, row: dict) -> None:
    try:
        payload = json.dumps({
            "timestamp":      row.get("timestamp"),
            "orp":            float(row["orp"]),
            "pressure":       float(row["pressure"]),
            "ph":             float(row["ph"]),
            "temp":           float(row["temp"]),
            "mixer_pressure": float(row["mixer_pressure"]),
            "co2_pct":        float(row["co2_pct"]),
            "ch4_pct":        float(row["ch4_pct"]),
        })
        client.publish(MQTT_TOPIC_PUBLISH, payload, qos=1)
        print(f"[MQTT] 已轉發 {row.get('timestamp')}")
    except (KeyError, ValueError) as e:
        print(f"[MQTT] 跳過格式不完整的列：{e}")


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
                print(f"[CSV] 監看目標：{current_path}")

            rows = read_all_rows(current_path)
            for row in rows[seen_count:]:
                publish_row(client, row)
            seen_count = len(rows)

            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\n[CSV] 使用者中斷，結束監看。")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    main()
