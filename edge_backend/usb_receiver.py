"""
USB 感測器接收器
================
從序列埠持續接收生物反應器感測器資料，套用訊號前處理後推送至共用資料倉儲。

資料格式（逗號分隔，共 14+ 欄）：
  年,月,日,時,分,秒,_,ORP(mV),反應器壓力(kg/cm²),pH,溫度(°C),混合槽壓力(kg/cm²),CO2%,CH4%
範例：
  2026,2,10,15,3,34,_,568,2.34,7.08,30.0,1.07,3.5,51.02
"""

import serial
import threading
import os
import csv
import json
import paho.mqtt.client as mqtt
from datetime import datetime

from core.signal_processor import ORPSignalProcessor
from core.data_store import append_record

# ── 硬體設定 ────────────────────────────────────────────
USB_PORT = '/dev/ttyUSB0'
BAUD_RATE = 9600

# ── MQTT 轉發設定 ───────────────────────────────────────
# 這支程式跑在監控電腦上，感測器資料要轉發給 Jetson 上的 core/mqtt_client.py
# （訂閱同一個主題、做推論、發布 reactor/01/prediction）。IP 是 USB-C 直連 Jetson
# 時的固定位址；若 Jetson 改用 WiFi，這裡要跟著 apiClient.js／.env.production
# 一起換成新 IP。
MQTT_BROKER_IP = "192.168.55.1"
MQTT_PORT = 1883
MQTT_TOPIC_PUBLISH = "reactor/01/sensors"

_mqtt_client: mqtt.Client | None = None


def _init_mqtt() -> None:
    """背景非阻塞連線，Broker 尚未就緒時 paho 會自動重試，不影響 USB 收資料。"""
    global _mqtt_client
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "usb_receiver")
        client.connect_async(MQTT_BROKER_IP, MQTT_PORT, keepalive=60)
        client.loop_start()
        _mqtt_client = client
        print(f"[MQTT] 背景連線至 Jetson Broker（{MQTT_BROKER_IP}:{MQTT_PORT}）...")
    except Exception as e:
        print(f"[MQTT] 初始化失敗：{e}（感測器資料仍會正常寫入本機，不影響 API）")
        _mqtt_client = None


def _publish_to_mqtt(record: dict) -> None:
    if _mqtt_client is None:
        return
    try:
        payload = json.dumps({
            "timestamp":      record["timestamp"],
            "orp":            record["orp"],
            "pressure":       record["pressure"],
            "ph":             record["ph"],
            "temp":           record["temp"],
            "mixer_pressure": record["mixer_pressure"],
            "co2_pct":        record["co2_pct"],
            "ch4_pct":        record["ch4_pct"],
        })
        _mqtt_client.publish(MQTT_TOPIC_PUBLISH, payload, qos=1)
    except Exception as e:
        print(f"[MQTT] 發布失敗：{e}")

# ── 訊號處理參數（依 PDF 設定）──────────────────────────
_processor = ORPSignalProcessor(
    ema_window=10,
    spike_threshold=-20.0,
    spike_max_minutes=15,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


# ── 資料解析 ────────────────────────────────────────────

def _parse_line(raw_line: str) -> dict | None:
    """
    解析 CSV 行，回傳原始欄位 dict。
    格式：年,月,日,時,分,秒,_,ORP,反應器壓力,pH,溫度,混合槽壓力,CO2%,CH4%
    """
    parts = raw_line.strip().split(',')
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
            "pressure":       float(parts[8]),   # 反應器壓力
            "ph":             float(parts[9]),
            "temp":           float(parts[10]),
            "mixer_pressure": float(parts[11]),  # 混合槽壓力
            "co2_pct":        float(parts[12]),
            "ch4_pct":        float(parts[13]),
        }
    except (ValueError, IndexError):
        return None


# ── CSV 備份（逐日輪換）────────────────────────────────

def _get_csv_path() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(DATA_DIR, f"BTP_Sensor_log-{today}.csv")


def _write_csv_row(path: str, row: dict) -> None:
    is_new = not os.path.exists(path)
    with open(path, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if is_new:
            writer.writeheader()
        writer.writerow(row)


# ── 主接收迴圈 ──────────────────────────────────────────

def _listener_loop() -> None:
    try:
        ser = serial.Serial(USB_PORT, BAUD_RATE, timeout=1)
        print(f"[USB] 已連接 {USB_PORT}  鮑率={BAUD_RATE}")
        _processor.reset()

        while True:
            if ser.in_waiting > 0:
                raw_line = ser.readline().decode('utf-8', errors='ignore')
                parsed = _parse_line(raw_line)
                if parsed is None:
                    continue

                points = _processor.process(parsed["timestamp"], parsed["orp_raw"])

                for pt in points:
                    record = {
                        "timestamp":      pt.timestamp,
                        "orp":            pt.ema,
                        "orp_raw":        pt.raw,
                        "orp_cleaned":    pt.cleaned,
                        "is_anomaly":     pt.is_anomaly,
                        "pressure":       parsed["pressure"],
                        "ph":             parsed["ph"],
                        "temp":           parsed["temp"],
                        "mixer_pressure": parsed["mixer_pressure"],
                        "co2_pct":        parsed["co2_pct"],
                        "ch4_pct":        parsed["ch4_pct"],
                        "note":           "anomaly" if pt.is_anomaly else "",
                    }
                    append_record(record)
                    _write_csv_row(_get_csv_path(), record)
                    _publish_to_mqtt(record)

                    status = "⚠ 突波" if pt.is_anomaly else "✓"
                    print(
                        f"[USB] {pt.timestamp}  "
                        f"raw={pt.raw:6.1f}  EMA={pt.ema:6.1f}  "
                        f"CH4={parsed['ch4_pct']:.1f}%  CO2={parsed['co2_pct']:.1f}%  {status}"
                    )

    except serial.SerialException as e:
        print(f"[USB] 無法開啟 {USB_PORT}：{e}")
        print("[USB] 感測器離線，FastAPI 服務仍可正常運作。")
    except Exception as e:
        print(f"[USB] 執行期間發生錯誤：{e}")


def start_usb_listener() -> threading.Thread:
    _init_mqtt()
    t = threading.Thread(target=_listener_loop, daemon=True, name="usb-receiver")
    t.start()
    return t
