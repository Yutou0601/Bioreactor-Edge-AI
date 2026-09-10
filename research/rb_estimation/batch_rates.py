# -*- coding: utf-8 -*-
"""補算批次 2、3 的下降壓力平均速率，並對三批做甲烷化學計量對帳。

批次 1 的表上已有 0.0185 ± 0.0017 kg/cm2/hr (n=6)；2、3 標「尚未取得資料」。
定義沿用批次 1：逐循環的（壓降 / 時長），再取平均與標準差。

⚠ 欄位陷阱同 analyze_three_batches：紀錄的兩個壓力標籤是對調的。
  這裡直接沿用該檔的 load_txt，不自行解析。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
from paths import testing_data          # Testing_data 的位置解析
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from analyze_three_batches import load_txt

DIR = os.path.join(testing_data(), '202607至08最新循環研究')
ATM = 1.033
RISE = 0.03

# (名稱, 起, 迄, 起點CH4, 終點CH4, 起點錶壓, 終點錶壓, 表上總時)
BATCH = [
    ('2 (5 分)',  '2026-07-27 09:25', '2026-07-30 09:07',
     0.0856, 0.3484, 1.191, 1.014, 71.696),
    ('3 (10 分)', '2026-07-30 09:13', '2026-08-03 09:11',
     0.0841, 0.4304, 1.165, 0.962, 95.966),
]


def main():
    df = pd.concat([load_txt(p) for p in sorted(glob.glob(DIR + '/*.txt'))],
                   ignore_index=True).sort_values('ts')
    df = df.drop_duplicates('ts').reset_index(drop=True)
    print('讀入 %d 列   %s ~ %s\n' % (len(df), df.ts.iloc[0], df.ts.iloc[-1]))

    print('批次        n   下降速率 (kg/cm2/hr)   總時 hr   CH4比值  生物份額  r_b')
    for nm, a, b, f1, f2, Pg1, Pg2, tt in BATCH:
        s = df[(df.ts >= a) & (df.ts <= b)].reset_index(drop=True)
        if len(s) < 100:
            print('%-10s 資料不足（%d 列）' % (nm, len(s))); continue
        p = s.p_reactor.values
        t = (s.ts - s.ts.iloc[0]).dt.total_seconds().values / 3600
        # 補氣點：壓力單步上升
        cut = np.flatnonzero(np.diff(p) > RISE) + 1
        edges = np.concatenate([[0], cut, [len(p)]])
        rates = []
        for u, v in zip(edges[:-1], edges[1:]):
            if v - u < 60:
                continue
            drop = p[u] - p[v - 1]
            dur = t[v - 1] - t[u]
            if drop > 0.05 and dur > 2:
                rates.append(drop / dur)
        if len(rates) < 2:
            print('%-10s 有效循環僅 %d 個' % (nm, len(rates))); continue
        r = np.array(rates)
        rate, sd = r.mean(), r.std(ddof=1)
        desc = rate * tt
        ch4 = f2 * (Pg2 + ATM) - f1 * (Pg1 + ATM)
        ratio = ch4 / desc
        share = ratio / 0.25
        print('%-10s %2d   %.4f ± %.4f      %6.2f    %.4f    %4.0f%%   %.4f'
              % (nm, len(r), rate, sd, tt, ratio, share * 100, share * rate))

    print('\n批次 1（表上）  6   0.0185 ± 0.0017      114.49    0.2172      87%   0.0161')
    print('\n化學計量上限 0.25；份額 >100% 即超出上限，代表某個輸入有誤')


if __name__ == '__main__':
    main()
