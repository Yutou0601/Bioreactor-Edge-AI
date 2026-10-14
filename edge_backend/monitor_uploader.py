# -*- coding: utf-8 -*-
"""監控電腦上的上傳程式：把記錄程式寫出的 CSV 新增行送到 Jetson。

    設備 ─COM4─▶ 廠商記錄程式 ─▶ REACTOR_DATA_DIR\\BTP_Sensor_log-日期.csv
                                        │  這支：只讀檔、只送新增的完整行
                                        ▼  USB
                         REACTOR_UPLOAD_URL/api/ingest（Jetson）

用法（在監控電腦的 edge_backend\\ 下）：
    python monitor_uploader.py              持續執行（開機自動啟動用這個）
    python monitor_uploader.py --once       掃一輪就結束
    python monitor_uploader.py --check      對帳：本機每日行數 vs Jetson 收到的筆數

⚠ 絕不打開 COM 埠。Windows 的序列埠同時只能一個程式開，我們開了，記錄程式
  就讀不到設備，整條資料流斷掉。這支只讀記錄程式**寫出來的檔案**。

⚠ 只准標準函式庫。這台是 4 GB 的監控電腦（見 core/sample_store.py 開頭）；
  numpy 都不需要。

⚠ 進度（每個檔送到第幾個位元組）存在 .uploader_state.json，**收到 Jetson 回
  OK 才往前推**。Jetson 那邊是原始行落地之後才回 OK（core/ingest.py），兩邊
  合起來保證：回過 OK 的行不會掉；沒回 OK 的行下一輪重送，Jetson 以時間戳
  去重，重送不會重複。
"""
import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import config            # noqa: E402  只用標準庫

STATE_PATH = os.path.join(HERE, '.uploader_state.json')
PATTERN = 'BTP_Sensor_log-*.csv'
CHUNK_BYTES = 1 << 20              # 一次最多讀 1 MB（約 13 天份）
BATCH_LINES = 2000                 # 一個請求最多幾行


def log(msg):
    print('[%s] %s' % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg), flush=True)


def load_state():
    try:
        with open(STATE_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state):
    """原子寫入：先寫暫存檔再替換，斷電也不會留下半個 JSON。"""
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def read_complete_lines(path, offset):
    """從 offset 讀到最後一個換行為止。回傳 (行列表, 新 offset)。

    ⚠ 最後一段沒有換行＝記錄程式還在寫那一行，不送、也不把 offset 推過去，
      下一輪它寫完了再一起送。送出半行的話，Jetson 會把它當格式錯誤丟掉，
      而 offset 已經推過去，那一分鐘就永遠不見了。
    """
    with open(path, 'rb') as fh:
        fh.seek(offset)
        data = fh.read(CHUNK_BYTES)
    cut = data.rfind(b'\n')
    if cut < 0:
        return [], offset
    body = data[:cut + 1]
    text = body.decode('utf-8', errors='replace')
    if offset == 0 and text.startswith('﻿'):
        text = text[1:]                          # BOM
    lines = [ln.rstrip('\r') for ln in text.split('\n') if ln.strip()]
    return lines, offset + len(body)


def post(url, token, payload, timeout=60):
    req = urllib.request.Request(
        url.rstrip('/') + '/api/ingest',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'X-Reactor-Token': token},
        method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def scan_once(data_dir, url, token, station, state, since=''):
    """掃一輪。回傳 (送出的行數, 錯誤訊息或 None)。"""
    files = sorted(glob.glob(os.path.join(data_dir, PATTERN)))
    sent = 0
    for path in files:
        name = os.path.basename(path)
        day = name[len('BTP_Sensor_log-'):-len('.csv')]
        if since and day < since:
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        off = int(state.get(name, 0))
        if size < off:
            # 檔案變小＝被換掉或截斷了。從頭重送；Jetson 會依時間戳去重。
            log('⚠ %s 變小了（%d < %d），從頭重送' % (name, size, off))
            off = 0
        while off < size:
            lines, new_off = read_complete_lines(path, off)
            if new_off == off:
                break                               # 只剩寫到一半的末行
            for i in range(0, len(lines), BATCH_LINES):
                part = lines[i:i + BATCH_LINES]
                last_batch = i + BATCH_LINES >= len(lines)
                try:
                    res = post(url, token, {
                        'station': station, 'file': name, 'lines': part,
                        'offset': new_off if last_batch else None})
                except urllib.error.HTTPError as e:
                    return sent, '%s 回 HTTP %s：%s' % (url, e.code,
                                                       e.read().decode('utf-8', 'replace')[:200])
                except Exception as e:                       # 連不到 Jetson、逾時…
                    return sent, '連不到 %s（%s: %s）' % (url, type(e).__name__, e)
                if not res.get('ok'):
                    return sent, 'Jetson 回報失敗：%s' % res
                sent += len(part)
                if res.get('unparsed'):
                    log('⚠ %s 有 %d 行無法解析（表頭或格式不符），已略過'
                        % (name, res['unparsed']))
            off = new_off
            state[name] = off
            save_state(state)                        # ← 收到 OK 才推進度
    return sent, None


def check(data_dir, url, station):
    """對帳：本機每天的有效行數 vs Jetson sample 表的筆數。"""
    with urllib.request.urlopen(url.rstrip('/') + '/api/days', timeout=30) as r:
        remote = {d['day']: d['n'] for d in json.loads(r.read().decode('utf-8'))}
    bad = 0
    for path in sorted(glob.glob(os.path.join(data_dir, PATTERN))):
        day = os.path.basename(path)[len('BTP_Sensor_log-'):-len('.csv')]
        with open(path, encoding='utf-8-sig', errors='replace') as fh:
            n = sum(1 for ln in fh if ln.count(',') >= 13 and ln[:4].isdigit())
        got = remote.get(day, 0)
        mark = '✓' if got == n else '✘'
        bad += got != n
        print('%s %s  本機 %5d 行  Jetson %5d 筆' % (mark, day, n, got))
    print('對帳完成：%s' % ('全部相符' if not bad else '%d 天不符' % bad))
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--once', action='store_true', help='掃一輪就結束')
    ap.add_argument('--check', action='store_true', help='對帳後結束')
    ap.add_argument('--interval', type=float, default=20.0, help='掃描間隔秒數')
    ap.add_argument('--since', default='', help='只送這天（YYYY-MM-DD）以後的檔')
    a = ap.parse_args()

    data_dir = config.data_dir()
    url = config.get('REACTOR_UPLOAD_URL')
    token = (config.get('REACTOR_INGEST_TOKEN') or '').strip()
    station = config.get('REACTOR_STATION') or 'BTP-1'

    log('資料夾 %s → %s（站台 %s）' % (data_dir, url, station))
    if not os.path.isdir(data_dir):
        log('✘ 資料夾不存在：%s（檢查 .env 的 REACTOR_DATA_DIR）' % data_dir)
        return 2
    if a.check:
        return 1 if check(data_dir, url, station) else 0
    if not token:
        log('✘ 沒有設定 REACTOR_INGEST_TOKEN（要與 Jetson 的 .env 相同）')
        return 2

    state = load_state()
    wait = a.interval
    while True:
        sent, err = scan_once(data_dir, url, token, station, state, since=a.since)
        if sent:
            log('送出 %d 行' % sent)
        if err:
            # 退避：連不到時不要每 20 秒狂打，最長 5 分鐘一次。資料都在本機檔案裡，晚送不會掉。
            wait = min(wait * 2, 300.0)
            log('✘ %s；%d 秒後重試' % (err, wait))
        else:
            wait = a.interval
        if a.once:
            return 1 if err else 0
        time.sleep(wait)


if __name__ == '__main__':
    sys.exit(main())
