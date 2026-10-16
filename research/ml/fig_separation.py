# -*- coding: utf-8 -*-
"""fig59：哪些現有特徵能把生物從溶解／洩漏裡分出來（separation_sim ＋ separation_ga）。

  a　各設計 × 特徵類別的穩健 R²（線性，依模板分組交叉驗證；最不利先驗）＋ GA 最佳 ＋ 置換虛無
  b　同上，非線性（梯度提升樹）
  c　為什麼 ORP 不行：真實循環內 ΔORP vs 機理模型能產生的 ΔORP

數字全部由 out_separation/ 的檔案重算，不手抄。
用法：python fig_separation.py
"""
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import matplotlib                                           # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt                             # noqa: E402

from fig_pinn_batched import (BLUE, RED, AQUA, YELLOW, INK, INK2, MUTED, BASELINE,  # noqa: E402
                              OUT as FIGDIR, style)
import separation_ga as G                                   # noqa: E402

DATA = G.DATA
DESIGNS = [('N2', '單一循環'), ('grp_same_K4_N2', '同條件\n4 循環'), ('grp_same_K8_N2', '同條件\n8 循環'),
           ('grp_cross_K4_N2', '跨條件\n4 循環'), ('grp_cross_K8_N2', '跨條件\n8 循環')]
FAM_COL = [('只用壓力', BLUE), ('壓力＋pH', AQUA), ('壓力＋ORP', YELLOW)]


def family_idx(feats):
    orp = [i for i, f in enumerate(feats) if 'orp' in f]
    ph = [i for i, f in enumerate(feats) if 'ph' in f and 'orp' not in f]
    p = [i for i in range(len(feats)) if i not in orp and i not in ph]
    return {'只用壓力': p, '壓力＋pH': p + ph, '壓力＋ORP': p + orp}


def compute():
    from sklearn.ensemble import HistGradientBoostingRegressor
    res = []
    for key, label in DESIGNS:
        Z, feats, d, mu, sd, fold = G.load(key)
        sc = G.Scorer(Z, fold)
        fam = family_idx(feats)
        lin = {n: sc.score(ix)['robust'] for n, ix in fam.items()}
        hgb = {}
        for n, ix in fam.items():
            pr = G.cv_predict(Z, fold, ix, lambda: HistGradientBoostingRegressor(
                max_iter=300, learning_rate=0.05, random_state=0))
            hgb[n] = min(G.r2(Z['testB1'][1], pr['testB1']), G.r2(Z['testB2'][1], pr['testB2']))
        tag = key if key.startswith('grp_') else key
        with open(os.path.join(DATA, 'ga_%s_front.csv' % tag), encoding='utf-8-sig') as f:
            ga = max(float(r['robust_r2']) for r in csv.DictReader(f))
        null = np.load(os.path.join(DATA, 'ga_%s_null.npy' % tag))
        res.append(dict(key=key, label=label, lin=lin, hgb=hgb, ga=ga, null_max=float(null.max())))
        print('%-18s 線性 %s  非線性 %s  GA %.3f  虛無最大 %.3f'
              % (key, {k: round(v, 3) for k, v in lin.items()},
                 {k: round(v, 3) for k, v in hgb.items()}, ga, null.max()))
    return res


def main():
    res = compute()
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 5.0), gridspec_kw={'wspace': 0.3,
                                                                       'width_ratios': [1.15, 1.15, 0.9]})
    x = np.arange(len(res))
    for ax, which, title in ((axes[0], 'lin', 'a　線性模型（GA 用的）'),
                             (axes[1], 'hgb', 'b　非線性模型（梯度提升樹）')):
        for j, (fam, col) in enumerate(FAM_COL):
            v = [r[which][fam] for r in res]
            ax.plot(x, v, color=col, lw=2, marker='o', ms=7, label=fam, zorder=3)
            ax.text(x[-1] + 0.12, v[-1], fam, color=INK2, fontsize=9, va='center')
        if which == 'lin':
            ax.plot(x, [r['ga'] for r in res], color=INK, lw=1.4, ls='--', marker='D', ms=5,
                    label='GA 最佳組合', zorder=4)
            ax.text(x[-1] + 0.12, res[-1]['ga'] + 0.03, 'GA 最佳', color=INK2, fontsize=9, va='center')
            ax.fill_between(x, -1, [r['null_max'] for r in res], color=BASELINE, alpha=0.5, lw=0,
                            zorder=1)
            ax.text(0.05, 0.02, '灰帶＝標籤打亂後 GA 能找到的最大值（置換虛無）', fontsize=8.5,
                    color=INK2, transform=ax.get_xaxis_transform(), va='bottom')
        ax.axhline(0, color=BASELINE, lw=1)
        ax.set_xticks(x)
        ax.set_xticklabels([r['label'] for r in res], fontsize=9)
        ax.set_xlim(-0.3, len(res) - 0.3 + 0.9)
        ax.set_ylim(-0.2, 0.85)
        ax.legend(loc='upper left', fontsize=8.5, frameon=False)
        style(ax, title, None, '穩健 R²（最不利先驗；沒見過的真實雜訊）')

    # c　ORP：真實 vs 機理
    ax = axes[2]
    d1 = np.load(os.path.join(DATA, 'sim_N1.npz'), allow_pickle=True)
    feats = list(d1['features'])
    i = feats.index('dorp')
    real = d1['real_X'][:, i]
    mech = d1['trainA_X'][:, i]                      # N1：真實趨勢已扣除 → 近似機理訊號＋殘差
    for v, col, lab in ((mech, YELLOW, '模型（Nernst＋氣體組成＋雜訊）'),
                        (real, RED, '29 個真實循環')):
        s = np.sort(v)
        ax.step(s, np.arange(1, len(s) + 1) / len(s), where='post', color=col, lw=2.2, label=lab)
        med = float(np.median(v))
        ax.plot([med], [0.5], 'o', color=col, ms=8, mec='white', mew=1.5, zorder=4)
        ax.text(med, 0.53, '中位 %.0f' % med, color=INK2, fontsize=9, ha='center', va='bottom')
    ax.axhline(0.5, color=BASELINE, lw=0.8, ls=':')
    ax.set_xlim(-130, 70)
    ax.set_ylim(0, 1.02)
    ax.legend(loc='upper left', fontsize=8.5, frameon=False)
    style(ax, 'c　ORP 為什麼不行', '循環內 ΔORP（mV）', '累積比例')
    ax.text(0.02, 0.82, '真實 ORP 循環內\n系統性下降約 40 mV；\n機理部分只有 ±5 mV\n（不加雜訊時）。\n差距＝泵／補氣等\n操作訊號。',
            transform=ax.transAxes, fontsize=8.5, color=INK2, ha='left', va='top')

    fig.suptitle('GA 篩選「哪些現有特徵能分出生物」：只有 pH 是真槓桿，且要累積多個循環、跨不同 τ\n'
                 '（機理模擬＋真實殘差；在先驗 A 訓練、在相關結構相反的 B1／B2 測試；依模板分組交叉驗證；保守雜訊 N2）',
                 fontweight='bold', x=0.06, ha='left', y=1.05, fontsize=11)
    path = os.path.join(FIGDIR, 'fig59_separation_ga.png')
    fig.savefig(path)
    plt.close(fig)
    print('-> %s' % path)
    with open(os.path.join(DATA, 'summary_designs.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['design', 'lin_pressure', 'lin_pressure_ph', 'lin_pressure_orp', 'hgb_pressure',
                    'hgb_pressure_ph', 'hgb_pressure_orp', 'ga_best_lin', 'null_max'])
        for r in res:
            w.writerow([r['key']] + [round(r['lin'][k], 3) for k, _ in FAM_COL]
                       + [round(r['hgb'][k], 3) for k, _ in FAM_COL] + [r['ga'], round(r['null_max'], 3)])


if __name__ == '__main__':
    main()
