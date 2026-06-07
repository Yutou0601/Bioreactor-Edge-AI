"""
感測器資料模擬器
================
從 CSV 檔案逐行讀取真實感測器資料，以固定間隔 POST 到 FastAPI，
模擬感測器即時寫入的效果。

使用方式：
    # 正常速度（每秒 1 筆，等同每分鐘加速 60 倍）
    python sensor_simulator.py

    # 指定 CSV 檔案與間隔
    python sensor_simulator.py --csv data/BTP_Sensor_log-2026-02-10.csv --interval 2

前提：main.py 必須已在執行中（http://192.168.55.1:8000）
"""

import argparse
import csv
import io
import os
import sys
import time
import requests
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────
API_BASE    = "http://127.0.0.1:8000/api"
DEFAULT_CSV = "data/BTP_Sensor_log-2026-02-10.csv"
DEFAULT_INTERVAL = 1.0   # 秒


def find_csv(hint: str) -> Path:
    p = Path(hint)
    if p.exists():
        return p
    # 在 data/ 目錄下搜尋最新的 CSV
    data_dir = Path(__file__).parent / "data"
    csvs = sorted(data_dir.glob("BTP_Sensor_log-*.csv"))
    if csvs:
        return csvs[-1]
    raise FileNotFoundError(f"找不到 CSV 檔案：{hint}")


def parse_rows(csv_path: Path) -> list[dict]:
    """解析 CSV，回傳 list of raw dicts"""
    rows = []
    text = csv_path.read_text(encoding='utf-8-sig', errors='ignore')
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) < 14:
            continue
        try:
            ts = (
                f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                f" {int(parts[3]):02d}:{int(parts[4]):02d}:{int(parts[5]):02d}"
            )
            rows.append({
                'timestamp':      ts,
                'orp_raw':        float(parts[7]),
                'pressure':       float(parts[8]),   # 反應器壓力
                'ph':             float(parts[9]),
                'temp':           float(parts[10]),
                'mixer_pressure': float(parts[11]),  # 混合槽壓力
                'co2_pct':        float(parts[12]),
                'ch4_pct':        float(parts[13]),
            })
        except (ValueError, IndexError):
            continue
    return rows


def post_record(session: requests.Session, record: dict) -> bool:
    try:
        res = session.post(f"{API_BASE}/records", json=record, timeout=3)
        return res.status_code == 200
    except requests.ConnectionError:
        return False


def run(csv_path: Path, interval: float):
    # ── 載入 signal_processor（需在 edge_backend 目錄下執行）
    sys.path.insert(0, str(Path(__file__).parent))
    from core.signal_processor import ORPSignalProcessor

    processor = ORPSignalProcessor(ema_window=10, spike_threshold=-20.0, spike_max_minutes=15)
    rows = parse_rows(csv_path)

    if not rows:
        print("❌ CSV 無有效資料，請確認格式：年,月,日,時,分,秒,_,ORP,壓力,pH,溫度,DO…")
        return

    print(f"\n{'='*54}")
    print(f"  感測器模擬器  |  {csv_path.name}")
    print(f"  共 {len(rows)} 筆  |  間隔 {interval}s  |  Ctrl+C 停止")
    print(f"{'='*54}")
    print(f"  {'時間戳':>20}  {'Raw':>6}  {'EMA':>6}  {'CH4%':>6}  {'CO2%':>5}  {'狀態':>6}")
    print(f"  {'-'*46}")

    session = requests.Session()

    # 確認 API 可連
    try:
        session.get(f"{API_BASE}/records", timeout=2)
    except requests.ConnectionError:
        print(f"\n❌ 無法連線到 {API_BASE}，請先啟動 main.py")
        return

    sent = 0
    anomaly_count = 0
    row_by_ts = {r['timestamp']: r for r in rows}

    try:
        for raw_row in rows:
            points = processor.process(raw_row['timestamp'], raw_row['orp_raw'])

            for pt in points:
                src = row_by_ts.get(pt.timestamp, raw_row)
                record = {
                    'timestamp':      pt.timestamp,
                    'orp':            pt.ema,
                    'orp_raw':        pt.raw,
                    'orp_cleaned':    pt.cleaned,
                    'is_anomaly':     pt.is_anomaly,
                    'pressure':       src['pressure'],
                    'ph':             src['ph'],
                    'temp':           src['temp'],
                    'mixer_pressure': src['mixer_pressure'],
                    'co2_pct':        src['co2_pct'],
                    'ch4_pct':        src['ch4_pct'],
                    'note':           'SIM · 突波' if pt.is_anomaly else 'SIM',
                }
                ok = post_record(session, record)
                status = '⚠ 突波' if pt.is_anomaly else ('✓' if ok else '✗ 失敗')
                if pt.is_anomaly:
                    anomaly_count += 1
                if ok:
                    sent += 1

                print(
                    f"  {pt.timestamp:>20}  "
                    f"{pt.raw:>6.1f}  {pt.ema:>6.1f}  "
                    f"{src['ch4_pct']:>6.2f}  {src['co2_pct']:>5.2f}  {status}"
                )

            time.sleep(interval)

        # flush 末尾突波緩衝
        for pt in processor.flush():
            src = row_by_ts.get(pt.timestamp, rows[-1])
            post_record(session, {
                'timestamp':      pt.timestamp,
                'orp':            pt.ema,
                'orp_raw':        pt.raw,
                'orp_cleaned':    pt.cleaned,
                'is_anomaly':     pt.is_anomaly,
                'pressure':       src['pressure'],
                'ph':             src['ph'],
                'temp':           src['temp'],
                'mixer_pressure': src['mixer_pressure'],
                'co2_pct':        src['co2_pct'],
                'ch4_pct':        src['ch4_pct'],
                'note':           'SIM · 突波',
            })
            sent += 1; anomaly_count += 1


    except KeyboardInterrupt:
        print("\n\n  使用者中止。")

    print(f"\n{'='*54}")
    print(f"  完成：共發送 {sent} 筆，偵測突波 {anomaly_count} 次")
    print(f"{'='*54}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='BTP 感測器資料模擬器')
    parser.add_argument('--csv',      default=DEFAULT_CSV,      help='CSV 檔案路徑')
    parser.add_argument('--interval', default=DEFAULT_INTERVAL, type=float, help='每筆間隔秒數（預設 1）')
    args = parser.parse_args()

    # 切換到 edge_backend 目錄，確保 import 路徑正確
    os.chdir(Path(__file__).parent)

    try:
        csv_path = find_csv(args.csv)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    run(csv_path, args.interval)
