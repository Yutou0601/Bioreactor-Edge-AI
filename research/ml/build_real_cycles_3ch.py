# -*- coding: utf-8 -*-
"""重建 separation_sim 用的真實循環模板（壓力＋pH＋ORP＋逐分鐘泵狀態）。

2026-10-18。原本的模板檔 /tmp/pb/real_cycles_3ch.npy 是臨時產生、沒有程式留下，
Jetson 重開機後就不見了。這支把它固定下來：

  循環：pump_mode_split.analyse_batch 的規律循環（≥4 hr、降幅 ≥0.10、直線 R² ≥0.9、
        迄壓 ≥0.7＝排除人工排氣），與 pinn_batched.load_real_cycles 同一來源
  泵：  每個循環用它自己的開泵分鐘（與批次剖面差 ≤1 分才採用，否則用批次值），
        小時內第 (分 − 開泵分) mod 60 < 運轉分鐘 → 泵開
  pH／ORP：同一時間戳的 CSV 讀數（ORP 已還原負號，見 multivariate_increments）

輸出 -> research/ml/out_separation/real_cycles_3ch.npy（不放 /tmp）
用法：python build_real_cycles_3ch.py   之後 REAL_NPY=<該路徑> 給 separation_sim 用
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, RESEARCH)
sys.path.insert(0, os.path.join(RESEARCH, 'cycles'))
sys.path.insert(0, os.path.join(os.path.dirname(RESEARCH), 'edge_backend'))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pump_mode_split as PM                                      # noqa: E402
from pump_rhythm import BATCHES, FOLDER                           # noqa: E402
from multivariate_increments import load4                         # noqa: E402

OUT = os.path.join(HERE, 'out_separation', 'real_cycles_3ch.npy')


def main():
    ts, h, p = PM.load()
    rows = load4(os.path.join(RESEARCH, 'Testing_data', FOLDER))
    by_ts = {r[0]: (r[2], r[3]) for r in rows}                    # ts -> (ORP 真值, pH)
    out, miss = [], 0
    for nm, tau, d0, d1 in BATCHES:
        B = PM.analyse_batch(ts, h, p, nm, tau, d0, d1)
        on_b, gap = B['on'], B['gap']
        for k, c in enumerate(B['reg']):
            s, e = c['s'], c['e']
            on_c = B['rows_by_cyc'].get(k + 1, (on_b, None))[0]
            tt = B['t2'][s:e + 1]
            t = B['h2'][s:e + 1] - B['h2'][s]
            P = B['p2'][s:e + 1].astype(float)
            orp = np.array([by_ts.get(x, (np.nan, np.nan))[0] for x in tt], float)
            ph = np.array([by_ts.get(x, (np.nan, np.nan))[1] for x in tt], float)
            bad = ~np.isfinite(orp) | ~np.isfinite(ph) | (ph < 5) | (ph > 9)   # 14.00 為故障值
            miss += int(bad.sum())
            if bad.all():
                continue
            idx = np.arange(len(t))
            orp[bad] = np.interp(idx[bad], idx[~bad], orp[~bad])
            ph[bad] = np.interp(idx[bad], idx[~bad], ph[~bad])
            pump = np.array([((x.minute - on_c) % 60) < gap for x in tt], bool)
            out.append(dict(batch=nm, tau=tau, cycle=k + 1, t=t, P=P, pH=ph, ORP=orp, pump=pump))
            print('  %-6s 第%2d 個  %5.1f hr  %4d 點  降 %.2f  泵開比例 %.3f  pH %.2f→%.2f'
                  % (nm, k + 1, t[-1], len(t), P[0] - P[-1], pump.mean(), ph[0], ph[-1]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.save(OUT, np.array(out, dtype=object), allow_pickle=True)
    print('共 %d 個循環；pH/ORP 缺值或故障以內插補 %d 點 -> %s' % (len(out), miss, OUT))


if __name__ == '__main__':
    main()
