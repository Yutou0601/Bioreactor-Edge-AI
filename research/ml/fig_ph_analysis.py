# -*- coding: utf-8 -*-
"""fig60：pH 能分出什麼、分不出什麼（separation_sim、ph_abc、ph_resolution_eval）。

  a　pH 特徵與三條途徑的相關（先驗 A 的模擬）：看得到「生物 vs 溶解」，看不到洩漏
  b　真實 29 個循環的 ABC：溶解 ≈ 0（校準通過），對照量到的總降速
  c　換 pH 計：解析度幾乎沒差；在「像真實」的區域（溶解≈0）連壓力＋pH 都分不出生物

用法：python fig_ph_analysis.py（需 out_separation/ 的 sim_N2.npz、abc_N2_real.csv、ph_resolution_summary.csv）
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

import matplotlib                                           # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt                             # noqa: E402

from fig_pinn_batched import (BLUE, RED, AQUA, YELLOW, INK, INK2, MUTED, BASELINE,  # noqa: E402
                              OUT as FIGDIR, style)

PATH_COL = [('bio', '生物', BLUE), ('diss', '溶解', AQUA), ('leak', '洩漏', YELLOW)]
FEATS = [('s0', '起始降速'), ('ph_slope', 'pH 斜率'), ('dph', 'ΔpH'), ('corr_ph_p', 'pH 與壓力的相關')]


def main():
    d = np.load(os.path.join(DATA, 'sim_N2.npz'), allow_pickle=True)
    F, T = list(d['features']), list(d['targets'])
    X = np.vstack([d['trainA_X'], d['testA_X']])
    Y = np.vstack([d['trainA_Y'], d['testA_Y']])
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.2), gridspec_kw={'wspace': 0.32,
                                                                     'width_ratios': [1, 1.35, 1]})

    # a
    ax = axes[0]
    yb = np.arange(len(FEATS))
    h = 0.26
    for j, (key, lab, col) in enumerate(PATH_COL):
        v = [np.corrcoef(X[:, F.index(f)], Y[:, T.index(key)])[0, 1] for f, _ in FEATS]
        ax.barh(yb + (j - 1) * h, v, height=h * 0.9, color=col, label=lab, zorder=3)
        for y, val in zip(yb + (j - 1) * h, v):
            if abs(val) >= 0.3:
                ax.text(val + (0.03 if val > 0 else -0.03), y, '%+.2f' % val, va='center',
                        ha='left' if val > 0 else 'right', fontsize=8, color=INK2)
    ax.axvline(0, color=INK, lw=0.8)
    ax.set_yticks(yb)
    ax.set_yticklabels([l for _, l in FEATS])
    ax.invert_yaxis()
    ax.set_xlim(-1.0, 1.15)
    ax.legend(loc='upper left', fontsize=8.5, frameon=False)
    style(ax, 'a　 pH 看到「生物 vs 溶解」，看不到洩漏', '與各途徑的相關（模擬，先驗 A）', None)

    # b
    ax = axes[1]
    with open(os.path.join(DATA, 'abc_N2_real.csv'), encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    order = {'tau1': 0, 'tau5': 1, 'tau10': 2}
    rows.sort(key=lambda r: (order[r['cycle'].split('#')[0]], int(r['cycle'].split('#')[1])))
    x = np.arange(len(rows))
    tot = np.array([float(r['drop_rate']) for r in rows])
    med = np.array([float(r['diss_med']) for r in rows])
    lo = np.array([float(r['diss_q10']) for r in rows])
    hi = np.array([float(r['diss_q90']) for r in rows])
    ax.bar(x, tot, color=BASELINE, width=0.7, zorder=1, label='量到的總降速')
    ax.vlines(x, lo, hi, color=AQUA, lw=4, zorder=3, label='溶解（80% 可信區間）')
    ax.scatter(x, med, color=AQUA, edgecolor='white', s=30, zorder=4)
    ax.axhline(0, color=INK, lw=0.8)
    prev = None
    for i, r in enumerate(rows):
        b = r['cycle'].split('#')[0]
        if prev and b != prev:
            ax.axvline(i - 0.5, color=MUTED, lw=0.8, ls=':')
        prev = b
    for b, nm in (('tau1', 'τ=1'), ('tau5', 'τ=5'), ('tau10', 'τ=10')):
        idx = [i for i, r in enumerate(rows) if r['cycle'].startswith(b + '#')]
        ax.text(np.mean(idx), tot.max() * 1.04, nm, ha='center', fontsize=9.5, color=INK2)
    share = np.median(np.maximum(np.abs(lo), np.abs(hi)) / tot)
    ax.text(0.01, 0.985, '溶解的 80%% 區間都貼著 0：逐循環最壞情況約佔總降速的 %.0f%%（中位）\n'
            '⇒ 壓降幾乎全是「生物＋洩漏」；這兩者各佔多少，pH 分不出來' % (share * 100),
            transform=ax.transAxes, fontsize=8.5, color=INK2, va='top')
    ax.set_xticks(x)
    ax.set_xticklabels([r['cycle'].split('#')[1] for r in rows], fontsize=7.5)
    ax.set_ylim(-0.01, tot.max() * 1.5)
    ax.legend(loc='upper right', fontsize=8.5, frameon=False, bbox_to_anchor=(1.0, 0.875), ncol=2)
    style(ax, 'b　真實 29 個循環：溶解 ≈ 0（ABC，校準通過）', '循環（各批內依時間順序）',
          'kg/cm²/hr')

    # c
    ax = axes[2]
    with open(os.path.join(DATA, 'ph_resolution_summary.csv'), encoding='utf-8-sig') as f:
        res = list(csv.DictReader(f))
    xs = np.arange(len(res))
    for key, lab, col, ls in (('PpH_all', '壓力＋pH，全部模擬', AQUA, '-'),
                              ('P_all', '只用壓力，全部模擬', BLUE, '-'),
                              ('PpH_real', '壓力＋pH，像真實的區域', AQUA, '--'),
                              ('P_real', '只用壓力，像真實的區域', BLUE, '--')):
        v = [float(r[key]) for r in res]
        ax.plot(xs, v, color=col, ls=ls, lw=2, marker='o', ms=6, label=lab)
    ax.axhline(0, color=INK, lw=0.8)
    ax.set_xticks(xs)
    ax.set_xticklabels(['現況\n0.01', '升級\n0.001', '理想\n0.0001'])
    ax.set_xlim(-0.3, len(res) - 0.7)
    ax.set_ylim(-0.3, 0.7)
    ax.legend(loc='upper left', fontsize=8, frameon=False)
    ax.text(0.98, 0.315, '換 pH 計幾乎沒差：量化雜訊平均後只剩約 0.0007，\n'
            '底線是不規則的慢速漂移（約 0.007 pH；\n不是溫度，泵週期只佔 6–8%）。',
            transform=ax.transAxes, fontsize=8.5, color=INK2, ha='right', va='bottom')
    style(ax, 'c　換更好的 pH 計有沒有用', 'pH 計解析度', '穩健 R²（預測生物）')

    fig.suptitle('pH 是唯一有用的現有訊號——但它解決的是「溶解」，不是「生物 vs 洩漏」\n'
                 '（機理模擬＋真實殘差，保守雜訊 N2；穩健＝相關結構相反的先驗 B1／B2 中較差者）',
                 fontweight='bold', x=0.06, ha='left', y=1.05, fontsize=11)
    path = os.path.join(FIGDIR, 'fig60_ph_analysis.png')
    fig.savefig(path)
    plt.close(fig)
    print('-> %s' % path)


if __name__ == '__main__':
    main()
