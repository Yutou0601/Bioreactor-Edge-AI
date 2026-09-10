
# -*- coding: utf-8 -*-
"""covariate 模組進入點。

    python run.py <db_path> <input.json>

⚠ 這支跑在**獨立的短命行程**裡。它 import 的 pandas 與 scipy 不會進入
  常駐核心——這正是模組化的全部意義。跑完就結束，作業系統把記憶體收回。

⚠ 不得 import 核心的任何東西（core.*）。需要的資料由核心以 input.json
  傳進來，格式是 experiment_store.all_cycles() 濾掉不完整循環之後的列表。

⚠ 只准寫自己的表 mod_covariate。
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                 # analysis.py 是同目錄的兄弟

VERSION = '1.0.0'
TABLE = 'mod_covariate'

SCHEMA = """
CREATE TABLE IF NOT EXISTS mod_covariate (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  computed_at    TEXT,
  module_version TEXT,
  n_cycles       INTEGER,
  n_batches      INTEGER,
  status         TEXT,
  payload        TEXT
);
"""


def main():
    if len(sys.argv) < 3:
        print('用法：python run.py <db_path> <input.json>', file=sys.stderr)
        return 2
    db_path, input_path = sys.argv[1], sys.argv[2]

    with open(input_path, encoding='utf-8') as fh:
        rows = json.load(fh)

    if not rows:
        # ⚠ 沒有完整循環是常態（批次剛開始、或時間窗沒涵蓋到補氣），不是錯誤。
        #   仍然寫一筆進去，否則介面分不出「還沒跑過」和「跑過但沒資料」。
        result = {'status': 'insufficient', 'n_cycles': 0, 'n_batches': 0,
                  'message': '沒有完整循環可分析（完整＝頭尾都在批次時間窗內、'
                             '且中間沒有記錄斷點）。'}
        n_batches = 0
    else:
        # ⚠ pandas 只在這裡 import。放在檔案頂端也一樣不會影響核心（這是
        #   另一個行程），但保持與分析程式相鄰比較看得出相依從哪來。
        import pandas as pd
        from analysis import compute

        df = pd.DataFrame(rows)
        result = compute(df)
        n_batches = int(df['run_id'].nunique()) if 'run_id' in df else 0

    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        con.execute(
            'INSERT INTO mod_covariate (computed_at, module_version,'
            ' n_cycles, n_batches, status, payload) VALUES (?,?,?,?,?,?)',
            (datetime.now().isoformat(sep=' '), VERSION,
             len(rows), n_batches, result.get('status', 'ok'),
             json.dumps(result, ensure_ascii=False, default=str)))
        con.commit()
    finally:
        con.close()

    print('mod_covariate 已寫入：%d 個循環、%d 個批次、status=%s'
          % (len(rows), n_batches, result.get('status', 'ok')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
