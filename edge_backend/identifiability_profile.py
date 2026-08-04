# -*- coding: utf-8 -*-
"""決定性檢定：直接對「生物份額」本身做 profile likelihood（2026-08-04）。

── 為何這是正確的檢定 ─────────────────────────────────────
先前的可辨識性討論都在談 rb、kLa、Peq 等模型參數，但論文真正要宣稱的量
是「生物佔總氣體移除的份額」。正確做法是直接把該份額固定在各個值，
其餘參數全部自由最佳化，看擬合品質是否隨之改變：

    平坦  -> 資料無法決定份額 -> 不可辨識（不論用什麼模型）
    碗狀  -> 份額可由資料決定 -> 可辨識

本檔用雙狀態氣相模型（H2 與 CO2 各自演化，振幅受 4:1 化學計量約束）
作為承載模型，因為它是本研究試過的模型中結構最豐富的一個。

── 結果 ───────────────────────────────────────────────────
1min 批全域懲罰僅 0.7%、10min 批 5.0% -> 平坦、不可辨識。
只有 5min 批呈現 32% 的結構（偏好高生物份額）。
=> 壓力軌跡單獨無法決定生物份額，需要獨立觀測（純 CO2 對照或可靠的 H2 量測）。

輸出 -> docs/analysis_charts_3batch/fig23
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import optimize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (  # noqa: E402
    BATCHES, OUT, BCOL, RED, AQUA, INK, INK2, MUTED, BASELINE, style)
from analyze_new_methods import collect  # noqa: E402
from two_state_gas_model import cycle_data, p_two_state, sse  # noqa: E402

BOUNDS = [(1e-3, 2.0), (1e-5, 0.5), (0.0, 0.9), (0.05, 0.9), (0.0, 0.5)]
STARTS = ([0.10, 0.02, 0.45, 0.60, 0.15],
          [0.50, 0.005, 0.60, 0.40, 0.05],
          [0.05, 0.05, 0.30, 0.80, 0.20])
SHARES = np.linspace(0.0, 1.0, 11)


def bio_of(th, data):
    kla, k_b, c_sat, f, m0 = th
    lam = 4 * k_b
    return sum(f * max(P0 - m0, 1e-6) * (1 - np.exp(-lam * t[-1]))
               for t, P, P0 in data)


def sse_at_share(data, tot_drop, share):
    """把生物份額釘在 share，其餘參數自由最佳化，回傳最佳 SSE。"""
    def obj(th):
        pen = ((bio_of(th, data) / tot_drop - share) / 0.01) ** 2
        return sse(p_two_state, th, data) + pen * 1e-4
    best = np.inf
    for st in STARTS:
        r = optimize.minimize(obj, st, method='Nelder-Mead', bounds=BOUNDS,
                              options=dict(maxiter=8000, fatol=1e-14))
        best = min(best, sse(p_two_state, r.x, data))
    return best


def main():
    cycles = collect()
    prof = {}
    print('對「生物份額」本身做 profile：固定份額、其餘參數自由最佳化\n')
    for name, cycs in cycles.items():
        data = cycle_data(cycs)
        n = sum(len(t) for t, *_ in data)
        tot = sum(P[0] - P[-1] for _, P, _ in data)
        vals = np.array([sse_at_share(data, tot, s) for s in SHARES])
        rel = (vals - vals.min()) / vals.min() * 100
        prof[name] = (SHARES, rel, np.sqrt(vals / n))
        print(f'{name}（總壓降 {tot:.3f}、{len(data)} 循環）')
        for s, r_, rm in zip(SHARES, rel, np.sqrt(vals / n)):
            print(f'   份額 {s*100:5.0f}%   RMSE={rm:.5f}   相對最佳 {r_:+6.2f}%')
        verdict = '可辨識' if rel.max() > 10 else '★ 平坦 → 不可辨識'
        print(f'   → 全域最大懲罰 {rel.max():.1f}%   {verdict}\n')

    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    for name in BATCHES:
        s, rel, _ = prof[name]
        ax.plot(s * 100, rel, 'o-', ms=6, lw=2.2, color=BCOL[name], label=name)
    ax.axhline(10, color=RED, ls='--', lw=1.5)
    ax.annotate('可辨識門檻（相對懲罰 10%）', xy=(2, 11.5),
                color=RED, fontsize=9.5, fontweight='bold')
    ax.set_ylim(-1, max(35, max(prof[n][1].max() for n in BATCHES) * 1.1))
    style(ax, '圖23  對「生物份額」本身的 Profile Likelihood',
          '生物佔總氣體移除的份額 (%)', 'SSE 相對最佳值增加 (%)')
    ax.legend(frameon=False, fontsize=9.5)
    fig.text(0, -0.10,
             '做法：把生物份額固定在橫軸各值，模型其餘參數（kLa、k_b、c_sat、H2 分率、初始 CH4）全部自由最佳化。\n'
             '曲線平坦 = 不論生物份額設 0% 或 100%，壓力軌跡都能被同等擬合 = 資料無法決定該份額。\n'
             '結果：1min 批全域懲罰僅 0.7%、10min 批 5.0%（皆平坦）；僅 5min 批呈現 32% 的結構。\n'
             '結論：壓力軌跡單獨無法決定生物份額——這不是模型不夠好，是資訊不存在。'
             '需要獨立觀測（純 CO2 對照使 rb≡0，或可靠的 H2 量測）。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig23_bio_share_identifiability.png')
    plt.close(fig)
    print(f'圖 → {OUT}/fig23_bio_share_identifiability.png')


if __name__ == '__main__':
    main()
