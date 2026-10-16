# -*- coding: utf-8 -*-
"""pH 計解析度情境的評估：0.01（現況）/ 0.001 / 0.0001（separation_sim --ph_res）。

2026-10-17。結果：幾乎沒有差別（穩健 R² 0.44 → 0.47 → 0.48；ABC 誤差到小數第四位相同）。
原因：特徵本身就是多點平均（ΔpH＝末 30 分－首 30 分），量化雜訊已降到約 0.0007；
真正的雜訊底線是 15 分鐘以上的不規則慢速漂移（SD 約 0.006–0.007）——不是溫度（全程 30.0 °C），
泵鎖定的圖樣也只佔 6–8%——換 pH 計消不掉。

「像真實」的區域：降速與起始降速落在真實 29 個循環範圍內、且溶解真值 |diss| ≤ 0.004
（ph_abc 推得真實循環的溶解 ≈ 0）。在那裡壓力與壓力＋pH 的穩健 R² 都是負的：溶解近零時，
pH 能分的「生物 vs 溶解」已無事可做，剩下的「生物 vs 洩漏」pH 看不到。

用法：python ph_resolution_eval.py（需先有 out_separation/sim_N2.npz 與 sim_N2_ph*.npz）
輸出 -> out_separation/ph_resolution_summary.csv
"""
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'out_separation')
sys.path.insert(0, HERE)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import separation_ga as G                                   # noqa: E402
import ph_abc as A                                          # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402

SCEN = (('N2_ph0.01', '現況 0.01'), ('N2_ph0.001', '升級 0.001'), ('N2_ph0.0001', '理想 0.0001'))


def mk():
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=0)


def main():
    d0 = np.load(os.path.join(DATA, 'sim_N2.npz'), allow_pickle=True)
    F = list(d0['features'])
    R0 = d0['real_X']

    def real_like(d, key):
        X = d[key + '_X']
        m = np.ones(len(X), bool)
        for f in ('drop_rate', 's0'):
            v = R0[:, F.index(f)]
            lo, hi = v.min(), v.max()
            w = 0.1 * (hi - lo)
            m &= (X[:, F.index(f)] >= lo - w) & (X[:, F.index(f)] <= hi + w)
        T = list(d['targets'])
        m &= np.abs(d[key + '_Y'][:, T.index('diss')]) <= 0.004
        return m

    rows = []
    for tag, label in SCEN:
        Z, feats, d, mu, sd, fold = G.load(tag)
        orp = [i for i, f in enumerate(feats) if 'orp' in f]
        ph = [i for i, f in enumerate(feats) if 'ph' in f and 'orp' not in f]
        P = [i for i in range(len(feats)) if i not in orp + ph]
        out = {'label': label}
        for name, idx in (('P', P), ('PpH', P + ph)):
            pr = G.cv_predict(Z, fold, idx, mk)
            out[name + '_all'] = min(G.r2(Z[k][1], pr[k]) for k in ('testB1', 'testB2'))
            out[name + '_real'] = min(G.r2(Z[k][1][real_like(d, k)], pr[k][real_like(d, k)])
                                      for k in ('testB1', 'testB2'))
        T = list(d['targets'])
        si = [F.index(s) for s in A.STATS]
        pi = [T.index(p) for p in A.PARAMS]
        S = np.vstack([d['trainA_X'], d['testA_X']])[:, si]
        TH = np.vstack([d['trainA_Y'], d['testA_Y']])[:, pi]
        tpl = np.concatenate([d['trainA_tpl'], d['testA_tpl']])
        mad = np.median(np.abs(S - np.median(S, 0)), 0) * 1.4826
        mad[mad == 0] = 1
        rng = np.random.default_rng(0)
        for key in ('testB1', 'testB2'):
            Xs, Ys, ts = d[key + '_X'][:, si], d[key + '_Y'][:, pi], d[key + '_tpl']
            pick = rng.choice(len(Xs), 200, replace=False)
            hit, wid, err = np.zeros(3), np.zeros(3), np.zeros(3)
            for i in pick:
                m = tpl != ts[i]
                for j, (q50, q10, q90) in enumerate(A.abc_one(Xs[i], S[m], TH[m], mad)):
                    hit[j] += q10 <= Ys[i, j] <= q90
                    wid[j] += q90 - q10
                    err[j] += abs(q50 - Ys[i, j])
            for j, p in enumerate(A.PARAMS):
                out['%s_%s_cov' % (key[-2:], p)] = hit[j] / 200
                out['%s_%s_mae' % (key[-2:], p)] = err[j] / 200
                out['%s_%s_w' % (key[-2:], p)] = wid[j] / 200
        rows.append(out)
        print('%-11s 穩健 R²（非線性）壓力 %+.3f→像真實 %+.3f ｜ 壓力＋pH %+.3f→像真實 %+.3f ｜ '
              'ABC 中位絕對誤差(B1/B2) 生物 %.4f/%.4f 溶解 %.4f/%.4f 洩漏 %.4f/%.4f'
              % (label, out['P_all'], out['P_real'], out['PpH_all'], out['PpH_real'],
                 out['B1_bio_mae'], out['B2_bio_mae'], out['B1_diss_mae'], out['B2_diss_mae'],
                 out['B1_leak_mae'], out['B2_leak_mae']))
    path = os.path.join(DATA, 'ph_resolution_summary.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print('-> %s' % path)


if __name__ == '__main__':
    main()
