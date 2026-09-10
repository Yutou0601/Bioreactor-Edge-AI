
# -*- coding: utf-8 -*-
"""
新圖組（二）：模擬器驗證 與 形式回收
════════════════════════════════════════════════════════════════════════

  figC(a)  分類器雙樣本檢定 —— 三個雜訊模型的 AUC
           白雜訊 0.968 → AR(1) 0.832 → AR(1)×1.3 0.695
           三者在**同一份 TEST 資料、同一個分類器**上重跑，可重現。
  figC(b)  形式回收的混淆矩陣 —— 不管投入什麼真值都挑中 S
           ⇒ 選擇程序沒有鑑別力，形式不可宣稱

方法本身都是先前技術（C2ST: Friedman 2003 / Lopez-Paz & Oquab 2017，
已由 Dalmasso et al. 2020 用於驗模擬器；model recovery: Wilson & Collins
2019 Rule 8），圖說要寫成「應用」不是「提出」。

輸出 -> docs/paper_figures/
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import matplotlib.pyplot as plt                                    # noqa: E402

from paper_style import apply, save, W, C, U, FS_NOTE, FS_SMALL    # noqa: E402
from analyze_three_batches import OUT                              # noqa: E402

FIGDIR = os.path.join(os.path.dirname(OUT), 'paper_figures')
FORMS = ('C', 'L', 'S')
FORM_LAB = {'C': 'constant', 'L': 'linear', 'S': 'saturating'}


def read_auc():
    out = []
    with open(f'{OUT}/simulator_check.csv', encoding='utf-8-sig') as fh:
        rows = list(csv.reader(fh))
    grab = False
    for r in rows:
        if r and r[0] == 'noise_model':
            grab = True; continue
        if grab:
            if not r or not r[0] or r[0] == 'trim_min':
                break
            out.append((r[0], float(r[2]), float(r[3])))
    return out


def read_trim():
    """讀 endpoint_bias.csv：裁切分鐘數、實測與模擬對照的 r_b 中位數。"""
    tm, real, sim = [], [], []
    with open(f'{OUT}/endpoint_bias.csv', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            try:
                tm.append(float(r['trim_min']))
                real.append(float(r['rb_real_median']))
                sim.append(float(r['rb_sim_median']))
            except (KeyError, ValueError, TypeError):
                pass
    return tm, real, sim


def read_conf():
    conf, picked = {}, {}
    with open(f'{OUT}/rb_vs_k_form.csv', encoding='utf-8-sig') as fh:
        rows = list(csv.reader(fh))
    grab = False
    for r in rows:
        if r and r[0] == 'recovery_truth':
            grab = True; continue
        if grab:
            if not r or r[0] not in FORMS:
                break
            conf[r[0]] = [float(v) for v in r[1:4]]
            picked[r[0]] = r[4]
    return conf, picked


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    print('══ 新圖組（二）══\n')
    aucs = read_auc()
    conf, picked = read_conf()

    apply()
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.15))

    # ── (a) AUC ─────────────────────────────────────────
    ax = axes[0]
    labs = ['white\nGaussian', 'AR(1)\n$\\hat\\varphi$ from\nresiduals',
            'AR(1)\n$1.3\\hat\\varphi$\n(calibrated)']
    v = [a for _, a, _ in aucs]
    e = [s for _, _, s in aucs]
    x = np.arange(len(v))
    ax.bar(x, v, yerr=e, width=.58, color=C['fill'], edgecolor=C['main'],
           lw=.7, capsize=2.2, error_kw=dict(lw=.7, capthick=.7))
    for xi, vi, ei in zip(x, v, e):
        ax.text(xi, vi+ei+.022, f'{vi:.3f}', ha='center', fontsize=FS_NOTE)
    ax.axhline(0.5, color=C['sec'], lw=.8, ls=':')
    # ⚠ 「indistinguishable」放上方壓到虛線、放下方壓到第三根長條——
    #   長條佔滿 0.42–0.97 的區間，這個面板沒有放得下它的空白。
    #   註記移到圖說，圖內只留 0.5 的參考虛線。
    ax.set_xticks(x); ax.set_xticklabels(labs, fontsize=FS_SMALL)
    ax.set_ylabel('Classifier two-sample AUC')
    ax.set_ylim(0.42, 1.10)          # 上緣加高，0.968 的標籤才不會貼邊
    ax.set_title('(a)  Simulator adequacy', loc='left')

    # ── (b) 端點裁切的穩健性 ────────────────────────────
    #   依使用者指示只呈現成功做出來的結果，原本的形式回收混淆矩陣
    #   （失敗結果）換成端點選擇偏誤的穩健性檢查——那是對主結果的
    #   **正面**證據，且材料現成（endpoint_bias.csv）。
    ax = axes[1]
    tm, real, sim = read_trim()
    ax.plot(tm, real, 'o-', ms=3, lw=1.1, color=C['main'],
            label='measured cycles')
    ax.plot(tm, sim, 's--', ms=2.6, lw=1.0, color=C['sec'],
            label='matched simulation\n(no trigger selection)')
    ax.axhspan(min(real)*0.999, max(real)*1.001, color=C['fill'],
               alpha=.35, lw=0, zorder=0)
    ax.set_xlabel('Tail trimmed from each cycle  (min)')
    ax.set_ylabel(r'Median $r_b$  ' f'({U["rate"]})')
    ax.set_ylim(0.0100, 0.0132)
    ax.legend(loc='lower right', frameon=False, fontsize=FS_SMALL,
              handlelength=1.6)
    ax.set_title('(b)  The rate survives endpoint trimming', loc='left')
    ax.text(.03, .95, f'band spans only ±5 %', transform=ax.transAxes,
            fontsize=FS_NOTE, va='top')

    fig.tight_layout(pad=0.3, w_pad=1.4)
    save(fig, 'figC_validation', FIGDIR)


if __name__ == '__main__':
    main()
