
# -*- coding: utf-8 -*-
"""ch4_attribution 模組進入點。

    python run.py <db_path> <input.json>

⚠ 跑在獨立的短命行程裡。`import xgboost` 實測單獨 +119.5 MB——那筆錢在這裡
  付，跑完隨行程一起消失，常駐核心不受影響。搬過來之前它是在核心的**背景
  執行緒**裡跑的，只要有人開過一次 CH4 面板就永久留著。

⚠ 只准寫自己的表 mod_ch4_attribution。

⚠ `fingerprint` 一定要寫進去。歸因是排程算的，可能落後於目前的訓練集
  （又排氣了幾次）；核心拿它比對就知道眼前用的選擇是不是舊的。少了它，
  舊的特徵選擇會被靜默拿去擬合，預測值不對也沒有人看得出來。
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                 # analysis.py 是同目錄的兄弟

VERSION = '1.0.0'

SCHEMA = """
CREATE TABLE IF NOT EXISTS mod_ch4_attribution (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  computed_at    TEXT,
  module_version TEXT,
  fingerprint    TEXT,
  n_train        INTEGER,
  method         TEXT,
  status         TEXT,
  payload        TEXT
);
"""

# 樣本太少時 GA／XGBoost 的選擇沒有意義（留一交叉驗證會退化）。
# 與 core/ch4_realtime.MIN_TRAIN_CYCLES 對齊。
MIN_TRAIN = 3


TABLE = 'mod_ch4_attribution'


def compute_row(data):
    """純運算：吃訓練集、回「要寫進 mod_ch4_attribution 的那一列」。不碰資料庫。

    本機模式由 main() 寫 SQLite；遠端模式由 compute_node 直接呼叫。
    xgboost 在 Orin 上是常駐熱著的，不必每次重付 +119.5 MB 的 import。
    """
    X_raw = data.get('X') or []
    y_raw = data.get('y') or []
    fingerprint = data.get('fingerprint') or ''
    n = len(y_raw)

    if n < MIN_TRAIN:
        # ⚠ 樣本不足是常態（批次剛開始、還沒排幾次氣），不是錯誤。仍要寫一筆，
        #   否則介面分不出「還沒跑過」與「跑過但資料不夠」。
        result = {'status': 'insufficient', 'n_train': n,
                  'message': '完成週期僅 %d 個，少於 %d 個，不做特徵歸因。'
                             % (n, MIN_TRAIN)}
        method = None
    else:
        import numpy as np
        from analysis import attribute

        X = np.asarray(X_raw, dtype=float)
        y = np.asarray(y_raw, dtype=float)
        result = attribute(X, y)
        result['status'] = 'ok'
        result['n_train'] = n
        method = result.get('method')

    result['fingerprint'] = fingerprint

    return {
        'computed_at': datetime.now().isoformat(sep=' '),
        'module_version': VERSION,
        'fingerprint': fingerprint,
        'n_train': n,
        'method': method,
        'status': result.get('status'),
        'payload': json.dumps(result, ensure_ascii=False, default=str),
    }


def main():
    if len(sys.argv) < 3:
        print('用法：python run.py <db_path> <input.json>', file=sys.stderr)
        return 2
    db_path, input_path = sys.argv[1], sys.argv[2]

    with open(input_path, encoding='utf-8') as fh:
        data = json.load(fh)

    row = compute_row(data)

    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        cols = [c for c in row]
        con.execute(
            'INSERT INTO %s (%s) VALUES (%s)'
            % (TABLE, ','.join(cols), ','.join('?' * len(cols))),
            tuple(row[c] for c in cols))
        con.commit()
    finally:
        con.close()

    print('mod_ch4_attribution 已寫入：n_train=%d method=%s status=%s'
          % (row['n_train'], row['method'], row['status']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
