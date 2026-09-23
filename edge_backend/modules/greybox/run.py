
# -*- coding: utf-8 -*-
"""greybox 模組進入點。

    python run.py <db_path> <input.json>

⚠ 跑在獨立的短命行程裡。scipy（磁碟 109 MB）只存在於這個行程，
  跑完就隨行程一起消失，常駐核心不受影響。

⚠ 不得 import 核心。輸入由核心以 input.json 傳入，格式是
  experiment_store.complete_cycle_trajectories() 的回傳值。

⚠ 只准寫自己的表 mod_greybox。

這支比 covariate 慢（profile likelihood），所以排程間隔設 180 分鐘、
逾時 300 秒。逾時會被核心強制終止並記進 module_run，不會拖著不放。
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
CREATE TABLE IF NOT EXISTS mod_greybox (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  computed_at    TEXT,
  module_version TEXT,
  n_cycles       INTEGER,
  status         TEXT,
  payload        TEXT
);
"""


TABLE = 'mod_greybox'


def compute_row(cycles):
    """純運算：吃軌跡、回「要寫進 mod_greybox 的那一列」。不碰資料庫。

    本機模式由 main() 寫 SQLite；遠端模式由 compute_node 直接呼叫，
    結果 JSON 回給監控電腦的核心寫。兩條路徑跑同一段程式。
    """
    if not cycles:
        result = {'status': 'insufficient', 'n_cycles': 0,
                  'message': '沒有完整循環軌跡可擬合。'}
    else:
        # ⚠ scipy 留在函式裡 import。遠端模式會在啟動時 import 本檔，
        #   頂層 import 會讓「列出模組」也把 scipy 拉進來。
        from analysis import analyze_real
        result = analyze_real(cycles)

    return {
        'computed_at': datetime.now().isoformat(sep=' '),
        'module_version': VERSION,
        'n_cycles': len(cycles),
        'status': result.get('status', 'ok'),
        'payload': json.dumps(result, ensure_ascii=False, default=str),
    }


def main():
    if len(sys.argv) < 3:
        print('用法：python run.py <db_path> <input.json>', file=sys.stderr)
        return 2
    db_path, input_path = sys.argv[1], sys.argv[2]

    with open(input_path, encoding='utf-8') as fh:
        cycles = json.load(fh)

    row = compute_row(cycles)

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

    print('mod_greybox 已寫入：%d 條軌跡、status=%s'
          % (row['n_cycles'], row['status']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
