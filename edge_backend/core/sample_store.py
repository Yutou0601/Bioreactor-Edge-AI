
# -*- coding: utf-8 -*-
"""sample 表：感測資料的durable 儲存。

⚠ 常駐核心的一部分：只用 sqlite3 與標準函式庫，**不得 import numpy／pandas**。
  這支的工作只有「把 dict 寫進去、讀出來」，不需要任何數值套件。

為什麼需要這張表（兩個都是實測出來的，不是設計潔癖）：

  1. **重啟就沒了。** 在此之前感測資料只存在 core/data_store.py 的記憶體
     列表裡。後端一重開，`sensor_records` 是空的——監控頁、批次循環分析、
     CH4 預測全部歸零，而且畫面上看不出是「沒資料」還是「重開過」。

  2. **記憶體會隨時間線性長大。** 實測每筆記錄在記憶體佔 517 bytes：

         7 天（10,080 筆）    5.0 MB   ✓
        30 天（43,200 筆）   21.3 MB   ✗
         1 年（525,600 筆）  259.1 MB  ✗✗

     監控電腦的常駐預算是 60 MB，而核心本身已經用掉 65.5 MB。也就是說
     「全部放記憶體」這個做法撐不過幾個月，而且是慢慢惡化、不會當場報錯。

**分工**：這張表是完整歷史（SQLite 存幾百萬筆沒問題），記憶體只留一個
**有界的最近視窗**。要看更早的資料就從表裡查，不要把整段歷史載回記憶體。

⚠ 與架構文件 §6 的差異：文件的 schema 只有 (ts, pressure, orp, ph, temp)
  五欄。實際的記錄還有 orp_raw / orp_cleaned / is_anomaly / mixer_pressure /
  co2_pct / ch4_pct / note，而且都有使用端（監控頁畫原始與清洗後的 ORP、
  CH4 預測讀 ch4_pct）。只存五欄的話，重啟還原之後那些欄位會靜默變成預設
  值，圖看起來正常但內容是假的。所以這裡存完整記錄。
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # edge_backend/

SCHEMA = """
CREATE TABLE IF NOT EXISTS sample (
  ts             TEXT PRIMARY KEY,   -- ISO8601，現場是一分鐘一筆
  orp            REAL,               -- EMA 平滑後（監控頁主要畫這條）
  orp_raw        REAL,
  orp_cleaned    REAL,
  is_anomaly     INTEGER,
  pressure       REAL,
  ph             REAL,
  temp           REAL,
  mixer_pressure REAL,
  co2_pct        REAL,
  ch4_pct        REAL,
  note           TEXT
);
"""

COLUMNS = ('ts', 'orp', 'orp_raw', 'orp_cleaned', 'is_anomaly', 'pressure',
           'ph', 'temp', 'mixer_pressure', 'co2_pct', 'ch4_pct', 'note')

# 啟動時載回記憶體的筆數上限。
# ⚠ 用「最近 N 筆」而不是「最近 N 天」：現場的用法是匯入**歷史**批次的 CSV
#   再分析（例如 2026-07 的三批）。若用牆上時鐘算天數，重啟之後那些歷史資料
#   會全部落在視窗外、等於憑空消失，而畫面上只會顯示「尚無資料」。
#   20000 筆約 10 MB、約當 14 天的一分鐘取樣。
DEFAULT_MEMORY_LIMIT = 20000


def _db_path():
    return os.environ.get('REACTOR_DB') or os.path.join(HERE, 'reactor.db')


def connect(path=None):
    con = sqlite3.connect(path or _db_path())
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _to_row(rec):
    """把記憶體裡的記錄 dict 轉成資料列。缺欄位用 None，不要自己編預設值。"""
    return (
        rec.get('timestamp'),
        rec.get('orp'), rec.get('orp_raw'), rec.get('orp_cleaned'),
        1 if rec.get('is_anomaly') else 0,
        rec.get('pressure'), rec.get('ph'), rec.get('temp'),
        rec.get('mixer_pressure'), rec.get('co2_pct'), rec.get('ch4_pct'),
        rec.get('note'),
    )


def _to_record(row):
    """反向轉換。id 由 data_store 在載入時自行編號，不存進表。"""
    return {
        'timestamp': row['ts'],
        'orp': row['orp'], 'orp_raw': row['orp_raw'],
        'orp_cleaned': row['orp_cleaned'],
        'is_anomaly': bool(row['is_anomaly']),
        'pressure': row['pressure'], 'ph': row['ph'], 'temp': row['temp'],
        'mixer_pressure': row['mixer_pressure'],
        'co2_pct': row['co2_pct'], 'ch4_pct': row['ch4_pct'],
        'note': row['note'],
    }


def append_many(records, con=None):
    """批次寫入。回傳實際新增的筆數（重複的時間戳不算）。

    ⚠ 用 INSERT OR IGNORE：ts 是主鍵，同一份 CSV 重匯不會產生重複列，
      而且**先寫的那筆保留**。這與 cycle 表的 `INSERT OR IGNORE` 一致，
      也符合架構文件 §6 說的「只追加，不更新」。
      要修正既有資料請明確地 delete 再寫，不要靠重匯蓋掉——靜默覆蓋會讓
      「這個數字是什麼時候變的」變成無解。

    ⚠ 一定要用 executemany 而不是逐筆 execute：CSV 匯入一次上萬筆，
      逐筆 commit 會慢到讓前端誤判逾時。
    """
    rows = [_to_row(r) for r in records if r.get('timestamp')]
    if not rows:
        return 0
    own = con is None
    con = con or connect()
    try:
        before = con.execute('SELECT COUNT(*) FROM sample').fetchone()[0]
        con.executemany(
            'INSERT OR IGNORE INTO sample (%s) VALUES (%s)'
            % (', '.join(COLUMNS), ', '.join('?' * len(COLUMNS))), rows)
        con.commit()
        after = con.execute('SELECT COUNT(*) FROM sample').fetchone()[0]
        return after - before
    finally:
        if own:
            con.close()


def append(record, con=None):
    """單筆寫入（/upload_sensor 走這條）。"""
    return append_many([record], con=con)


def load_recent(limit=None, con=None):
    """讀最近的 N 筆，**依時間由舊到新**回傳。

    ⚠ 順序很重要：ORP 的 EMA、相位判定、循環切段全都假設輸入是時間遞增的。
      SQL 取「最近 N 筆」必須先 DESC 再反轉，不能直接 ASC LIMIT——那會拿到
      最舊的 N 筆。
    """
    limit = int(limit or DEFAULT_MEMORY_LIMIT)
    own = con is None
    con = con or connect()
    try:
        rows = con.execute(
            'SELECT * FROM sample ORDER BY ts DESC LIMIT ?', (limit,)).fetchall()
        return [_to_record(r) for r in reversed(rows)]
    finally:
        if own:
            con.close()


def load_window(start, end=None, con=None):
    """讀一段時間窗（含頭含尾），由舊到新。給批次分析與模組用。

    這是「看更早的資料」的正確做法——不要為了看七月的資料而把整年載回記憶體。
    """
    own = con is None
    con = con or connect()
    try:
        if end:
            rows = con.execute(
                'SELECT * FROM sample WHERE ts >= ? AND ts <= ? ORDER BY ts',
                (start, end)).fetchall()
        else:
            rows = con.execute(
                'SELECT * FROM sample WHERE ts >= ? ORDER BY ts',
                (start,)).fetchall()
        return [_to_record(r) for r in rows]
    finally:
        if own:
            con.close()


def clear(con=None):
    """清空整張表。對應 DELETE /api/records。

    ⚠ 這是真的刪現場資料。呼叫端要確定使用者是有意的——記憶體清掉還能重匯，
      表清掉就沒了。
    """
    own = con is None
    con = con or connect()
    try:
        n = con.execute('SELECT COUNT(*) FROM sample').fetchone()[0]
        con.execute('DELETE FROM sample')
        con.commit()
        return n
    finally:
        if own:
            con.close()


def stats(con=None):
    """筆數與時間範圍。介面用它回答「表裡有多少、記憶體裡有多少」。"""
    own = con is None
    con = con or connect()
    try:
        r = con.execute(
            'SELECT COUNT(*) n, MIN(ts) lo, MAX(ts) hi FROM sample').fetchone()
        return {'n_samples': r['n'], 'first_ts': r['lo'], 'last_ts': r['hi']}
    finally:
        if own:
            con.close()
