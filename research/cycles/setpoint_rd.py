# -*- coding: utf-8 -*-
"""把 2026-07-11 的觸發設定點變更當成外生衝擊，檢定 r_b 是否跨越它連續。

文獻定位：regression discontinuity in time（Hausman & Rapson 2018）、
interrupted time series（Bernal 2017）、系統辨識那側的 persistent
excitation（Ljung）。一律寫成引用並應用。

邏輯（這是否證檢定，不是點估計）：
  設定點變更改變壓力操作帶 → 改變物理項的驅動力與 k 的操作範圍
  但它不改變菌
  所以 r_b 應該跨越變更點連續，而物理參數應該跳
  若 r_b 也跳，代表它在吸收物理，那是壞消息但很重要
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import csv
import sys

import numpy as np

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dataset_c import EXCLUDE, collect_c

CUT = '2026-07-11'


def load_rows():
    p = '../docs/analysis_charts_3batch/rb_per_cycle.csv'
    return [r for r in csv.DictReader(open(p, encoding='utf-8-sig'))
            if r['folder'] not in EXCLUDE]


def main():
    cyc, rows = collect_c(), load_rows()
    print('段數  collect_c=%d  csv=%d' % (len(cyc), len(rows)))
    if len(cyc) != len(rows):
        print('對不起來，中止'); return
    # 用時長交叉驗證兩邊順序一致
    d1 = np.array([c[1][-1] - c[1][0] for c in cyc])
    d2 = np.array([float(r['dur_hr']) for r in rows])
    err = np.abs(d1 - d2)
    print('時長對齊誤差 中位 %.4f  最大 %.4f hr' % (np.median(err), err.max()))
    if np.median(err) > 0.2:
        print('順序疑似不一致，中止'); return

    pre, post = [], []
    for (tag, x, y), r in zip(cyc, rows):
        rec = dict(t=r['time'], rb=float(r['rb']), k=float(r['k']),
                   top=float(np.max(y)), bot=float(np.min(y)),
                   amp=float(np.max(y) - np.min(y)))
        (pre if r['time'][:10] < CUT else post).append(rec)

    print('\n變更點 %s：之前 %d 段、之後 %d 段' % (CUT, len(pre), len(post)))
    if min(len(pre), len(post)) < 15:
        print('某一側樣本太少，這個檢定做不了'); return

    def med(g, key):
        return float(np.median([q[key] for q in g]))

    print('\n量                  之前      之後      變化')
    for key, name in (('top', '循環頂點壓力'), ('bot', '循環谷底壓力'),
                      ('amp', '振幅'), ('k', '鬆弛常數 k'),
                      ('rb', '生物速率 r_b')):
        a, b = med(pre, key), med(post, key)
        ch = (b - a) / abs(a) * 100 if a else float('nan')
        print('%-16s  %8.4f  %8.4f   %+7.1f%%' % (name, a, b, ch))

    ra = np.array([q['rb'] for q in pre])
    rb_ = np.array([q['rb'] for q in post])
    g = np.random.default_rng(3)
    obs = abs(np.median(rb_) - np.median(ra))
    pool = np.concatenate([ra, rb_])
    cnt = 0
    for _ in range(4000):
        g.shuffle(pool)
        if abs(np.median(pool[len(ra):]) - np.median(pool[:len(ra)])) >= obs:
            cnt += 1
    print('\nr_b 中位差 %.5f   置換檢定 p = %.3f' % (obs, cnt / 4000))
    print('  p 大 → r_b 跨越變更點連續（生物解讀站得住）')
    print('  p 小 → r_b 也跟著跳（它在吸收物理，壞消息）')


if __name__ == '__main__':
    main()
