# -*- coding: utf-8 -*-
"""串流接收：監控電腦的上傳程式把記錄程式 CSV 的新增行送進來。

    設備 ─COM4─▶ 廠商記錄程式 ─▶ BTP_Sensor_log-日期.csv（監控電腦，唯一正本）
                                      │ deploy/monitor_uploader.py：只送新增的完整行
                                      ▼
                       POST /api/ingest ─▶ 這支 ─▶ raw_sample ─▶ ORP 前處理 ─▶ sample

⚠ 兩段式寫入是刻意的。ORP 前處理遇到突波會**先緩衝、不輸出**（最多 15 分鐘），
  等突波結束才內插補值。如果收到就直接處理、處理完才寫，那上傳程式拿到 OK、
  把進度推過去之後後端剛好重開，緩衝裡那幾分鐘就永遠消失——上傳程式不會重送
  （它以為送過了），而且畫面上只是少了幾個點，沒有人會發現。
  所以：原始行先落進 raw_sample 才回 OK；處理器的輸出再進 sample。重開之後把
  「raw 有、sample 沒有」的那段重新餵給處理器（見 _recover）。

⚠ 只准標準函式庫——上傳端是 4 GB 的監控電腦，但這支在後端裡；後端雖然搬到
  Jetson，常駐核心的規矩不變（見 core/sample_store.py 開頭）。

⚠ sample 表的主鍵只有 ts，沒有站台。目前一台反應器一個站台；真的要接第二台
  反應器時，sample 表要先加 station 欄，否則兩台同一分鐘的資料會互相吃掉。
  raw_sample 已經帶 station，這一層不用改。
"""
import hmac
import os
import sqlite3
import threading
from datetime import datetime

from core import btp_format, config, sample_store
from core.data_store import append_record
from core.signal_processor import ORPSignalProcessor

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_sample (
  station        TEXT NOT NULL,
  ts             TEXT NOT NULL,
  orp_raw        REAL,
  pressure       REAL,
  ph             REAL,
  temp           REAL,
  mixer_pressure REAL,
  co2_pct        REAL,
  ch4_pct        REAL,
  file           TEXT,
  received_at    TEXT,
  PRIMARY KEY (station, ts)
);
CREATE TABLE IF NOT EXISTS ingest_state (
  station     TEXT PRIMARY KEY,
  file        TEXT,          -- 上傳程式目前在送的檔
  offset      INTEGER,       -- 它回報送到第幾個位元組（僅供顯示與對帳）
  last_ts     TEXT,          -- 最後收到的資料時間戳
  n_batches   INTEGER,
  n_rows      INTEGER,       -- 累計收到的列（含重送）
  n_new       INTEGER,       -- 累計新寫入的列
  updated_at  TEXT,          -- 最後一次收到請求的牆上時間
  ema_full    REAL,          -- 處理器內部未四捨五入的 EMA（重開接續用）
  ema_ts      TEXT           -- ema_full 對應的那一筆（最後輸出的點）
);
"""
# ⚠ sample 表存的 EMA 四捨五入到小數兩位。重開後若從那個值接續，之後每一點
#   都差 0.01 mV 左右再慢慢衰減（實測一天兩次重開，2 筆差 0.01）。差得很小，
#   但這條管線的承諾是「串流與一次匯入逐位元相同」，所以存完整精度。
_MIGRATE = (('ema_full', 'REAL'), ('ema_ts', 'TEXT'))

# 與 /api/import_csv 相同的前處理參數。兩條路進來的資料必須一樣處理。
_PROC_KW = dict(ema_window=10, spike_threshold=-20.0, spike_max_minutes=15)

_lock = threading.Lock()
_proc = {}            # station -> ORPSignalProcessor
_last_ts = {}         # station -> 處理器吃過的最後一個時間戳
# station -> {ts: 原始列}：已餵進處理器、還沒被輸出的列。
# ⚠ 突波期間處理器會把前幾批的點緩衝住，在**後面某一批**才一起輸出。輸出時
#   若只拿「這一批」的原始列去配對，前幾批的點找不到來源就被丟掉——實測
#   一天 1404 筆串流進來少了 33 筆，raw_sample 裡都在、sample 裡沒有。
_pending = {}
_emitted = {}         # station -> (最後輸出的 ts, 當時未四捨五入的 EMA)


def _db_path():
    return os.environ.get('REACTOR_DB') or sample_store._db_path()


def connect():
    con = sqlite3.connect(_db_path(), timeout=30)
    con.row_factory = sqlite3.Row
    # ⚠ sample 表也要建：Jetson 第一次啟動時資料庫是空的，_processor() 一開始
    #   就要查 sample 的最後一筆（實測：全新資料庫上第一批就 no such table）。
    con.executescript(sample_store.SCHEMA)
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute('PRAGMA table_info(ingest_state)')}
    for col, typ in _MIGRATE:
        if col not in have:
            con.execute('ALTER TABLE ingest_state ADD COLUMN %s %s' % (col, typ))
    return con


def check_token(given):
    """通行碼比對。沒設 REACTOR_INGEST_TOKEN 時拒收——不設就等於誰都能灌資料。

    ⚠ 用 hmac.compare_digest，避免逐字比對洩漏時間差。
    """
    want = (config.get('REACTOR_INGEST_TOKEN') or '').strip()
    if not want:
        return False, '後端沒有設定 REACTOR_INGEST_TOKEN，拒收（不設等於誰都能寫）'
    if not given or not hmac.compare_digest(str(given).strip(), want):
        return False, '通行碼不符'
    return True, ''


def _existing_sample_ts(ts_list):
    """這批時間戳裡，哪些 sample 表已經有了。"""
    out = set()
    con = sample_store.connect()
    try:
        for i in range(0, len(ts_list), 500):          # SQLite 參數上限 999
            chunk = ts_list[i:i + 500]
            out.update(r[0] for r in con.execute(
                'SELECT ts FROM sample WHERE ts IN (%s)' % ','.join('?' * len(chunk)),
                chunk))
    finally:
        con.close()
    return out


def _emit(points, src_by_ts, note):
    """處理器輸出 → 記憶體與 sample 表。回傳寫入筆數。

    ⚠ 先剔除 sample 表已有的時間戳再進記憶體。表本身有主鍵擋重複，記憶體的
      列表沒有——不剔除的話，同一分鐘（例如先手動匯入過、後來上傳程式又送）
      會在監控圖上畫兩次，而表裡看起來完全正常。
    """
    have = _existing_sample_ts([pt.timestamp for pt in points])
    recs = []
    for pt in points:
        src = src_by_ts.get(pt.timestamp)
        if src is None or pt.timestamp in have:
            continue
        recs.append(append_record({
            'timestamp': pt.timestamp,
            'orp': pt.ema, 'orp_raw': pt.raw, 'orp_cleaned': pt.cleaned,
            'is_anomaly': pt.is_anomaly,
            'pressure': src['pressure'], 'ph': src['ph'], 'temp': src['temp'],
            'mixer_pressure': src['mixer_pressure'],
            'co2_pct': src['co2_pct'], 'ch4_pct': src['ch4_pct'],
            'note': note,
        }))
    return sample_store.append_many(recs) if recs else 0


def _processor(station, con):
    """取得站台的常駐處理器；第一次用時從 sample 表最後一筆接續，並補做重開前
    沒處理完的那段（_recover）。"""
    p = _proc.get(station)
    if p is not None:
        return p
    p = ORPSignalProcessor(**_PROC_KW)
    _pending[station] = {}
    last = con.execute(
        'SELECT ts, orp, orp_raw FROM sample ORDER BY ts DESC LIMIT 1').fetchone()
    if last is not None and last['orp'] is not None and last['orp_raw'] is not None:
        ema = float(last['orp'])
        st = con.execute('SELECT ema_full, ema_ts FROM ingest_state WHERE station = ?',
                         (station,)).fetchone()
        if st is not None and st['ema_ts'] == last['ts'] and st['ema_full'] is not None:
            ema = float(st['ema_full'])
        p.resume(last['ts'], float(last['orp_raw']), ema)
        _last_ts[station] = last['ts']
    _proc[station] = p
    _recover(station, con)
    return p


def _rows_after(station, ts, con):
    q = ('SELECT * FROM raw_sample WHERE station = ? AND ts > ? ORDER BY ts'
         if ts else 'SELECT * FROM raw_sample WHERE station = ? ORDER BY ts')
    args = (station, ts) if ts else (station,)
    return [dict(r) for r in con.execute(q, args)]


def _recover(station, con):
    """重開前已收進 raw_sample、但還沒變成 sample 的列，重新處理一次。"""
    rows = _rows_after(station, _last_ts.get(station), con)
    if rows:
        _feed(station, rows, 'stream · 重開後補處理')


def _feed(station, rows, note):
    """依時間順序把原始列餵進常駐處理器。rows 必須已排序且都晚於 _last_ts。"""
    p = _proc[station]
    src = _pending.setdefault(station, {})
    pts = []
    for r in rows:
        src[r['ts']] = r
        pts.extend(p.process(r['ts'], float(r['orp_raw'])))
        _last_ts[station] = r['ts']
    n = _emit(pts, src, note)
    for pt in pts:
        src.pop(pt.timestamp, None)
    if pts:
        # 突波緩衝期間 EMA 不動，所以處理器的 _ema 永遠等於「最後輸出那一點」的 EMA。
        _emitted[station] = (pts[-1].timestamp, p._ema)
    return n


def _backfill(rows, note):
    """比處理器目前位置還舊的列（補送舊檔、或順序錯亂）：用一個獨立的處理器
    整段跑完並 flush，不去動常駐那個的狀態。等同 /api/import_csv 的作法。"""
    p = ORPSignalProcessor(**_PROC_KW)
    src = {r['ts']: r for r in rows}
    pts = []
    for r in rows:
        pts.extend(p.process(r['ts'], float(r['orp_raw'])))
    pts.extend(p.flush())
    return _emit(pts, src, note)


def ingest_lines(station, file, lines, offset=None):
    """收一批 CSV 行。回傳摘要。

    冪等：同一批重送不會多寫（raw_sample 與 sample 都以時間戳為主鍵）。
    """
    station = (station or '').strip() or 'default'
    now = datetime.now().isoformat(sep=' ', timespec='seconds')
    parsed, bad = [], 0
    for ln in lines or []:
        r = btp_format.parse_csv_line(ln)
        if r is None:
            if ln.strip():
                bad += 1
            continue
        parsed.append(r)

    with _lock:
        con = connect()
        try:
            # ⚠ 先取處理器（第一次會跑 _recover），**之後**才寫這一批。順序反過來
            #   的話，_recover 會把這批新列當成「重開前沒處理完的」先處理一次，
            #   下面又當成「比處理器舊的」再處理一次。
            _processor(station, con)
            new_rows = []
            for r in parsed:
                cur = con.execute(
                    'INSERT OR IGNORE INTO raw_sample (station, ts, orp_raw,'
                    ' pressure, ph, temp, mixer_pressure, co2_pct, ch4_pct,'
                    ' file, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (station, r['timestamp'], r['orp_raw'], r['pressure'],
                     r['ph'], r['temp'], r['mixer_pressure'], r['co2_pct'],
                     r['ch4_pct'], file, now))
                if cur.rowcount:
                    new_rows.append(dict(r, ts=r['timestamp']))
            con.commit()          # ← 原始行落地之後才算收到

            new_rows.sort(key=lambda r: r['ts'])
            mark = _last_ts.get(station)
            fwd = [r for r in new_rows if mark is None or r['ts'] > mark]
            old = [r for r in new_rows if mark is not None and r['ts'] <= mark]
            n_saved = 0
            if fwd:
                n_saved += _feed(station, fwd, 'stream · %s' % (file or station))
            if old:
                n_saved += _backfill(old, 'stream 補送 · %s' % (file or station))

            last_ts = parsed[-1]['timestamp'] if parsed else None
            con.execute(
                'INSERT INTO ingest_state (station, file, offset, last_ts,'
                ' n_batches, n_rows, n_new, updated_at)'
                ' VALUES (?,?,?,?,1,?,?,?)'
                ' ON CONFLICT(station) DO UPDATE SET'
                '  file = excluded.file,'
                '  offset = COALESCE(excluded.offset, ingest_state.offset),'
                '  last_ts = MAX(COALESCE(ingest_state.last_ts, ""),'
                '                COALESCE(excluded.last_ts, "")),'
                '  n_batches = ingest_state.n_batches + 1,'
                '  n_rows = ingest_state.n_rows + excluded.n_rows,'
                '  n_new = ingest_state.n_new + excluded.n_new,'
                '  updated_at = excluded.updated_at',
                (station, file, offset, last_ts, len(parsed), len(new_rows), now))
            if station in _emitted:
                ets, ema = _emitted[station]
                con.execute('UPDATE ingest_state SET ema_full = ?, ema_ts = ?'
                            ' WHERE station = ?', (ema, ets, station))
            con.commit()
        finally:
            con.close()

    return {'ok': True, 'station': station, 'received': len(parsed),
            'new': len(new_rows), 'duplicate': len(parsed) - len(new_rows),
            'saved': n_saved, 'unparsed': bad, 'last_ts': last_ts,
            'pending_in_spike': bool(_proc[station]._in_spike)}


def status():
    """各站台的接收狀態。介面用它回答「資料還有沒有在進來」。

    ⚠ lag_sec 用牆上時間算的是「多久沒收到請求」，data_lag_sec 是「最新資料
      距今多久」。兩個都要看：上傳程式活著但記錄程式停了，前者正常、後者會
      一直長大——2026-07-22 記錄靜默中斷 17.5 小時就是這種。
    """
    con = connect()
    try:
        out = []
        now = datetime.now()
        for r in con.execute('SELECT * FROM ingest_state ORDER BY station'):
            d = dict(r)
            for key, col in (('lag_sec', 'updated_at'), ('data_lag_sec', 'last_ts')):
                try:
                    d[key] = int((now - datetime.fromisoformat(d[col])).total_seconds())
                except (TypeError, ValueError):
                    d[key] = None
            d['pending_in_spike'] = bool(
                _proc.get(d['station']) and _proc[d['station']]._in_spike)
            out.append(d)
        return out
    finally:
        con.close()


def days(con=None):
    """sample 表裡有資料的日期與筆數（新到舊）。介面的日期選單用這個。

    expected=1440 是一分鐘一筆的整天；覆蓋率讓人一眼看出哪天缺資料。
    """
    own = con is None
    con = con or sample_store.connect()
    try:
        rows = con.execute(
            'SELECT substr(ts, 1, 10) AS day, COUNT(*) AS n,'
            ' MIN(ts) AS first_ts, MAX(ts) AS last_ts'
            ' FROM sample GROUP BY day ORDER BY day DESC').fetchall()
        return [dict(r, coverage=round(r['n'] / 1440.0, 3)) for r in rows]
    finally:
        if own:
            con.close()
