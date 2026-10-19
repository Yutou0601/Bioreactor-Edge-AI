# -*- coding: utf-8 -*-
"""日報 2026-10-18 的 NPE 總結圖：7 組設定 × 三個目標 × 三種先驗的 R² 與 80% 涵蓋率。

資料：research/ml/out_npe/job2~job8_*/results.json（Jetson 實驗排程 #2–#8）。
輸出 -> docs/reports/fig_daily_1018/fig1_npe_summary.png
"""
import glob
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, 'docs', 'reports', 'fig_daily_1018')
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Noto Sans CJK TC', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

NAMES = {'job2': '① 壓力＋pH', 'job3': '② 只用壓力', 'job4': '③ 無雜訊＋pH', 'job5': '④ 無雜訊・壓力',
         'job6': '⑤ 8 循環無雜訊', 'job7': '⑥ 8 循環真實', 'job8': '⑦ 訓練 12 萬'}
TARGETS = [('bio', '生物'), ('leak', '洩漏'), ('diss', '溶解')]
PRIORS = [('A', '#555555'), ('B1', '#d0602f'), ('B2', '#2f6fd0')]


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for d in sorted(glob.glob(os.path.join(REPO, 'research', 'ml', 'out_npe', 'job[2-8]_*'))):
        key = os.path.basename(d).split('_')[0]
        r = json.load(open(os.path.join(d, 'results.json'), encoding='utf-8'))
        rows.append((NAMES[key], r['summary']))
    fig, ax = plt.subplots(2, 3, figsize=(16, 8.4), sharey='row')
    x = np.arange(len(rows))
    w = 0.26
    for j, (t, tn) in enumerate(TARGETS):
        a = ax[0, j]
        for i, (p, col) in enumerate(PRIORS):
            v = [s[p][t]['r2'] for _, s in rows]
            e = [s[p][t]['r2_sd'] for _, s in rows]
            a.bar(x + (i - 1) * w, v, w, yerr=e, color=col, label='測試先驗 %s' % p, capsize=2)
        a.axhline(0, color='#999', lw=0.8)
        a.set_title('%s：R²（3 折平均 ± 標準差）' % tn)
        a.set_xticks(x, [n for n, _ in rows], rotation=35, ha='right', fontsize=8.5)
        a.set_ylim(-0.35, 1.0)
        b = ax[1, j]
        b.axhspan(0.70, 0.90, color='#cfe8cf', alpha=0.7, lw=0, label='校準通過帶 0.70–0.90')
        for i, (p, col) in enumerate(PRIORS[1:]):
            v = [s[p][t]['cov80'] for _, s in rows]
            b.bar(x + (i - 0.5) * w, v, w, color=col, label='先驗 %s' % p)
        ok = [s['passed_all_folds'][t] for _, s in rows]
        for k, o in enumerate(ok):
            b.text(x[k], 1.01, '通過' if o else '未過', ha='center', fontsize=9, color='#2a7a2a' if o else '#b33')
        b.set_title('%s：80%% 區間實際涵蓋率（標「通過」＝三折皆通過）' % tn)
        b.set_xticks(x, [n for n, _ in rows], rotation=35, ha='right', fontsize=8.5)
        b.set_ylim(0.4, 1.08)
    ax[0, 0].set_ylabel('R²')
    ax[1, 0].set_ylabel('80% 區間涵蓋率')
    ax[0, 0].legend(frameon=False, fontsize=8)
    ax[1, 0].legend(frameon=False, fontsize=8, loc='lower left')
    for a in ax.flat:
        a.spines[['top', 'right']].set_visible(False)
    fig.suptitle('圖 1　NPE（pH＋壓力）分離：只有「溶解」在所有設定與先驗下都校準通過；生物與洩漏在 B1 過度自信', fontsize=12)
    fig.tight_layout()
    p = os.path.join(OUT, 'fig1_npe_summary.png')
    fig.savefig(p, dpi=130)
    print('->', p)


if __name__ == '__main__':
    main()
