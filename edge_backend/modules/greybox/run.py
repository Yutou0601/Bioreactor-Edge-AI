
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


def main():
    if len(sys.argv) < 3:
        print('用法：python run.py <db_path> <input.json>', file=sys.stderr)
        return 2
    db_path, input_path = sys.argv[1], sys.argv[2]

    with open(input_path, encoding='utf-8') as fh:
        cycles = json.load(fh)

    if not cycles:
        result = {'status': 'insufficient', 'n_cycles': 0,
                  'message': '沒有完整循環軌跡可擬合。'}
    else:
        from analysis import analyze_real
        result = analyze_real(cycles)

    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        con.execute(
            'INSERT INTO mod_greybox (computed_at, module_version,'
            ' n_cycles, status, payload) VALUES (?,?,?,?,?)',
            (datetime.now().isoformat(sep=' '), VERSION, len(cycles),
             result.get('status', 'ok'),
             json.dumps(result, ensure_ascii=False, default=str)))
        con.commit()
    finally:
        con.close()

    print('mod_greybox 已寫入：%d 條軌跡、status=%s'
          % (len(cycles), result.get('status', 'ok')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
