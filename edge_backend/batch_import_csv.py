"""
批次匯入資料夾內所有 BTP_Sensor_log-*.csv
================================
把整個資料夾（例如監測電腦上感測器軟體寫出每日備份的位置）逐檔 POST 到
/import_csv，沿用該端點既有的格式偵測、突波修復、去重邏輯（已存在的
timestamp 會自動略過，可重複執行不會重複匯入），不用在網頁上一個一個
手動選檔。

使用方式：
    python batch_import_csv.py --dir "C:\\Users\\BTP\\Desktop\\data"
    python batch_import_csv.py --dir "C:\\Users\\BTP\\Desktop\\data" --api http://localhost:8000/api

前提：main.py 必須已在執行中。
"""

import argparse
import sys
from pathlib import Path

import requests

# Windows 主控台/重導向輸出預設用系統 codepage（如 cp1252），無法編碼中文字元
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

API_BASE = "http://127.0.0.1:8000/api"


def find_csvs(folder: Path) -> list[Path]:
    csvs = sorted(folder.glob("BTP_Sensor_log-*.csv"))
    if not csvs:
        raise FileNotFoundError(f"{folder} 底下找不到任何 BTP_Sensor_log-*.csv")
    return csvs


def import_one(session: requests.Session, api_base: str, path: Path) -> dict:
    with open(path, 'rb') as f:
        res = session.post(
            f"{api_base}/import_csv",
            files={'file': (path.name, f, 'text/csv')},
            timeout=30,
        )
    res.raise_for_status()
    return res.json()


def main():
    parser = argparse.ArgumentParser(description="批次匯入資料夾內所有 BTP_Sensor_log CSV")
    parser.add_argument('--dir', required=True, help=r"CSV 所在資料夾，例如 C:\Users\BTP\Desktop\data")
    parser.add_argument('--api', default=API_BASE, help=f"後端 API base url（預設 {API_BASE}）")
    args = parser.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f"[錯誤] 資料夾不存在：{folder}")
        sys.exit(1)

    try:
        csvs = find_csvs(folder)
    except FileNotFoundError as e:
        print(f"[錯誤] {e}")
        sys.exit(1)

    print(f"找到 {len(csvs)} 個檔案，開始匯入 → {args.api}/import_csv\n")

    session = requests.Session()
    total_imported = 0
    total_skipped = 0
    total_failed = 0

    for path in csvs:
        try:
            result = import_one(session, args.api, path)
            status = result.get('status', 'ok')
            imported = result.get('imported', 0)
            anomalies = result.get('anomalies_detected', 0)
            message = result.get('message', '')
            total_imported += imported
            if status == 'skipped' or imported == 0:
                total_skipped += 1
                print(f"  -  {path.name}：{message or '無新資料'}")
            else:
                extra = f"，突波 {anomalies} 個" if anomalies else ""
                print(f"  v  {path.name}：匯入 {imported} 筆{extra}")
        except requests.exceptions.RequestException as e:
            total_failed += 1
            print(f"  x  {path.name}：連線失敗（{e}）")
        except Exception as e:
            total_failed += 1
            print(f"  x  {path.name}：{e}")

    print(f"\n完成：共匯入 {total_imported} 筆資料，{total_skipped} 個檔案無新資料，{total_failed} 個檔案失敗")


if __name__ == '__main__':
    main()
