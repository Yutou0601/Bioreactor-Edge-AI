
# -*- coding: utf-8 -*-
"""covariate 模組進入點。

    python run.py <db_path> <input.json>

這支模組有兩種跑法，**運算的部分是同一個函式** `compute_row()`：

  本機（監控電腦，4 GB）
      核心開一個短命子行程跑這支。pandas 與 scipy 只活在這個行程裡，
      跑完作業系統整個收回，常駐核心不受影響。main() 負責寫 mod_covariate。

  遠端（Jetson Orin NX，16 GB）
      compute_node/server.py 直接 import 本檔並呼叫 compute_row()。
      套件常駐熱著，不必每次重付 import 的錢。結果以 JSON 回給監控電腦，
      由核心寫進它自己的 mod_covariate。

⚠ compute_row() 不得碰資料庫。它一旦寫了 DB，遠端模式就會把結果寫到
  Orin 上那份不會有人看的資料庫裡，而監控電腦上的表永遠是舊的——
  而且兩邊都不會報錯。

⚠ 不得 import 核心的任何東西（core.*）。需要的資料由核心傳進來，
  格式是 experiment_store.all_cycles() 濾掉不完整循環之後的列表。

⚠ 只准寫自己的表 mod_covariate。欄位同時宣告在 module.json 的
  result_columns（遠端模式由核心據此建表）；兩邊必須一致，
  system_test 會比對，不一致就紅。
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


def compute_row(rows):
    """純運算：吃輸入、回「要寫進 mod_covariate 的那一列」。不碰資料庫。

    本機模式由 main() 拿去寫 SQLite；遠端模式由 compute_node 直接呼叫，
    把回傳的 dict 交給監控電腦的核心寫。兩條路徑跑的是同一段程式。
    """
    if not rows:
        # ⚠ 沒有完整循環是常態（批次剛開始、或時間窗沒涵蓋到補氣），不是錯誤。
        #   仍然寫一筆進去，否則介面分不出「還沒跑過」和「跑過但沒資料」。
        result = {'status': 'insufficient', 'n_cycles': 0, 'n_batches': 0,
                  'message': '沒有完整循環可分析（完整＝頭尾都在批次時間窗內、'
                             '且中間沒有記錄斷點）。'}
        n_batches = 0
    else:
        # ⚠ pandas 只在這裡 import。本機模式下放檔案頂端也不影響核心（這是
        #   另一個行程），但遠端模式會 import 本檔——頂層 import pandas 就會
        #   在「列出模組」這種不需要運算的時候也把它拉進來。留在函式裡。
        import pandas as pd
        from analysis import compute

        df = pd.DataFrame(rows)
        result = compute(df)
        n_batches = int(df['run_id'].nunique()) if 'run_id' in df else 0

    return {
        'computed_at': datetime.now().isoformat(sep=' '),
        'module_version': VERSION,
        'n_cycles': len(rows),
        'n_batches': n_batches,
        'status': result.get('status', 'ok'),
        'payload': json.dumps(result, ensure_ascii=False, default=str),
    }


def main():
    if len(sys.argv) < 3:
        print('用法：python run.py <db_path> <input.json>', file=sys.stderr)
        return 2
    db_path, input_path = sys.argv[1], sys.argv[2]

    with open(input_path, encoding='utf-8') as fh:
        rows = json.load(fh)

    row = compute_row(rows)

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

    print('mod_covariate 已寫入：%d 個循環、%d 個批次、status=%s'
          % (row['n_cycles'], row['n_batches'], row['status']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
