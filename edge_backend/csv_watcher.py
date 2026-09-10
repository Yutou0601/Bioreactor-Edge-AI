
# -*- coding: utf-8 -*-
"""監看記錄程式寫出的 CSV 資料夾，有新資料就請後端重新匯入。

2026-09-01 改寫。原本這支是把 CSV 逐行轉發到 Jetson 的 MQTT broker；
Jetson 退場、前後端同機之後，那條路徑整段消失，改成直接呼叫
POST /api/ingest_folder。

    python csv_watcher.py --dir "C:\\Users\\BTP\\Desktop\\data"

⚠ 以**整個資料夾**送出，不逐檔處理。BTP_Sensor_log 是一天一檔，而循環
  中位長 10.2 小時、大多跨過午夜；逐檔匯入會把跨日的一段攔腰砍斷，
  時長與振幅都會錯（實測：同一批資料 25 段/0.0116 變成 32 段/0.0085）。

⚠ 匯入是冪等的：cycle 表對 (source, ts_start) 有 UNIQUE 條件，重複匯入
  只會寫入真正新增的段，所以可以放心地整個資料夾重送。

⚠ 只用標準函式庫。這支跑在監控電腦上，與常駐核心共用同一份 60 MB 預算。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 站台設定集中在 core/config.py（讀 .env）。這三個值以前寫死在這裡，
# 監控電腦上改過就會被下一次 git pull 覆蓋回去。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import config                                       # noqa: E402

DEFAULT_DIR = config.data_dir()
DEFAULT_API = config.api_base()
DEFAULT_POLL = int(config.get('REACTOR_POLL_SECONDS') or 60)


def folder_fingerprint(folder):
    """資料夾裡所有 CSV 的 (檔名, 大小, mtime)。變了就代表有新資料。

    比「只看最新 mtime」可靠：記錄程式是往當天的檔案**追加**寫入，
    檔名不會變、只有大小與 mtime 會動。
    """
    sig = []
    try:
        for f in sorted(os.listdir(folder)):
            if not f.lower().endswith('.csv'):
                continue
            p = os.path.join(folder, f)
            st = os.stat(p)
            sig.append((f, st.st_size, int(st.st_mtime)))
    except OSError as e:
        print('[watch] 讀不到資料夾：%s' % e)
        return None
    return tuple(sig)


def trigger_ingest(api_base, folder, timeout=900):
    url = (api_base.rstrip('/') + '/api/ingest_folder?folder='
           + urllib.parse.quote(folder, safe=''))
    req = urllib.request.Request(url, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser(
        description='監看 CSV 資料夾，有新資料就請後端重新匯入')
    ap.add_argument('--dir', default=DEFAULT_DIR, help='記錄程式寫出的資料夾')
    ap.add_argument('--api', default=DEFAULT_API, help='後端位址')
    ap.add_argument('--poll', type=int, default=DEFAULT_POLL,
                    help='檢查間隔（秒）')
    ap.add_argument('--once', action='store_true', help='只跑一次就結束')
    a = ap.parse_args()

    if not os.path.isdir(a.dir):
        print('[watch] 資料夾不存在：%s' % a.dir)
        return 1

    print('[watch] 監看 %s，每 %d 秒檢查一次' % (a.dir, a.poll))
    last = None
    while True:
        sig = folder_fingerprint(a.dir)
        if sig is not None and sig != last:
            n_files = len(sig)
            print('[watch] 偵測到變動（%d 個 CSV），匯入中…' % n_files)
            try:
                r = trigger_ingest(a.api, a.dir)
                print('[watch] 切出 %s 段，通過預篩 %s 段，新寫入 %s 筆'
                      % (r.get('segments'), r.get('screened'),
                         r.get('inserted')))
                last = sig
            except urllib.error.URLError as e:
                # ⚠ 後端還沒起來是常見情況，不要因此結束——下一輪再試。
                print('[watch] 後端無回應（%s），稍後重試' % e)
            except Exception as e:                # noqa: BLE001
                print('[watch] 匯入失敗：%s' % e)
        if a.once:
            return 0
        time.sleep(a.poll)


if __name__ == '__main__':
    sys.exit(main() or 0)
