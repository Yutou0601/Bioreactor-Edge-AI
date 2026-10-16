# -*- coding: utf-8 -*-
"""批次 PINN 的圖（讀 out_pinn_batched/ 的 CSV；計算在 Jetson、畫圖在有中文字型的電腦）。

  fig57_pinn_batched.png       合成資料：速度、簡併谷底、三個參數被鎖住的程度
  fig58_pinn_real_cycles.png   29 個真實循環：A、kLa、r̄_b 在 16 個模型間的散布

用法：python fig_pinn_batched.py
"""
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, RESEARCH)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import matplotlib                                         # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt                           # noqa: E402
from matplotlib import rcParams                           # noqa: E402

# ⚠ 配色與 style() 抄自 analyze_three_batches.py（分析圖的共用樣式）。不直接 import：
#   那支在模組層級就去找 Testing_data，沒有原始資料的電腦連畫圖都畫不了。
#   色盲可辨識度以 dataviz 的 validate_palette.js 檢查過（2026-10-16：全部通過；
#   AQUA、YELLOW 對底色對比 < 3:1 → 這兩色的系列一律直接加文字標籤，並另附表格 CSV）。
BLUE, RED, AQUA, YELLOW = '#2a78d6', '#e34948', '#1baf7a', '#eda100'
SURFACE, INK, INK2, MUTED = '#fcfcfb', '#0b0b0b', '#52514e', '#898781'
GRID, BASELINE = '#e1e0d9', '#c3c2b7'
OUT = os.path.abspath(os.path.join(RESEARCH, '..', 'docs', 'analysis_charts_3batch'))
rcParams.update({
    'font.family': ['Microsoft JhengHei', 'DejaVu Sans'], 'axes.unicode_minus': False,
    'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
    'savefig.facecolor': SURFACE, 'text.color': INK,
    'axes.labelcolor': INK2, 'xtick.color': MUTED, 'ytick.color': MUTED,
    'axes.edgecolor': BASELINE, 'grid.color': GRID,
    'font.size': 10, 'axes.titlesize': 11,
    'savefig.dpi': 200, 'savefig.bbox': 'tight',
})


def style(ax, title=None, xlabel=None, ylabel=None):
    if title:
        ax.set_title(title, color=INK, fontweight='bold', loc='left', pad=10)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, linewidth=0.6, alpha=0.9)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    return ax

DATA = os.path.join(HERE, 'out_pinn_batched')
# 與 pinn_batched.py 的合成問題相同
T_SYN, KLA_TRUE, PEQ_TRUE = 6.0, 1.4, 0.75
RB_TRUE = float(np.mean(0.012 * np.exp(-0.7 * np.linspace(0, T_SYN, 60) / T_SYN * 3)))
A_TRUE = PEQ_TRUE - RB_TRUE / KLA_TRUE
RB_PAPER = (0.0125, 0.0112, 0.0139)          # 論文 r_b 與 95% 區間
LAM_COL = {0.01: BLUE, 0.1: AQUA, 1.0: YELLOW, 10.0: RED}
BATCH_COL = {'tau1': BLUE, 'tau5': YELLOW, 'tau10': AQUA}     # 與 analyze_three_batches 的 BCOL 相同
BATCH_NAME = {'tau1': 'τ=1 分', 'tau5': 'τ=5 分', 'tau10': 'τ=10 分'}


def plain_log_ticks(ax, axis='y'):
    """對數軸刻度寫成 0.01、0.1、1，不用 10⁻² —— mathtext 的減號在這套字型會變方框。"""
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: ('%g' % v))
    getattr(ax, axis + 'axis').set_major_formatter(fmt)
    getattr(ax, axis + 'axis').set_minor_formatter(matplotlib.ticker.NullFormatter())


def read(name):
    with open(os.path.join(DATA, name), encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def fig57():
    bench = read('bench.csv')
    q = read('quality_cuda_fp32_fp64refine.csv')          # 預設精度組合
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.8), gridspec_kw={'wspace': 0.32})

    # a　速度
    ax = axes[0]
    combos = [('cuda', 'fp32', BLUE, 'GPU fp32'), ('cuda', 'fp64', AQUA, 'GPU fp64'),
              ('cpu', 'fp32', YELLOW, 'CPU fp32'), ('cpu', 'fp64', RED, 'CPU fp64')]
    for dev, dt, col, lab in combos:
        rows = [r for r in bench if r['device'] == dev and r['dtype'] == dt]
        M = [int(r['M']) for r in rows]
        thr = [float(r['model_steps_per_s']) for r in rows]
        ax.plot(M, thr, color=col, lw=2, marker='o', ms=5, label=lab)
        ax.text(M[-1] * 1.12, thr[-1], lab, color=INK2, fontsize=9, va='center')
    base = float([r for r in bench if r['device'] == 'cpu' and r['dtype'] == 'fp32'
                  and r['M'] == '1'][0]['model_steps_per_s'])
    g64 = float([r for r in bench if r['device'] == 'cuda' and r['dtype'] == 'fp32'
                 and r['M'] == '64'][0]['model_steps_per_s'])
    ax.annotate('一次訓練 64 個：\n原本做法的 %.0f 倍' % (g64 / base), xy=(64, g64),
                xytext=(3, g64 * 1.1), fontsize=9, color=INK2,
                arrowprops=dict(arrowstyle='-', color=MUTED, lw=0.8))
    ax.annotate('原本的做法\n（CPU、一次一個）', xy=(1, base), xytext=(1.15, base * 9),
                fontsize=9, color=INK2, arrowprops=dict(arrowstyle='-', color=MUTED, lw=0.8))
    ax.set_xscale('log', base=2)
    ax.set_yscale('log')
    plain_log_ticks(ax)
    ax.set_xlim(0.8, 700)
    ax.set_xticks([1, 4, 16, 64, 256])
    ax.set_xticklabels(['1', '4', '16', '64', '256'])
    style(ax, 'a　一次訓練越多個，GPU 越划算', '同時訓練的模型數', '模型·步／秒（對數）')

    # b　簡併谷底
    ax = axes[1]
    # 簡併線用模型自己鎖定的 A 與 kLa（中位數）畫：點都落在這條線上。
    # 真值星號不在線上是因為擬合的 A 比真值高 0.0006（不到量化步階 0.01 的十分之一）。
    kla_med = np.median([float(r['kla']) for r in q])
    A_med = np.median([float(r['A']) for r in q])
    xs = np.linspace(0, 0.0072, 50)
    ax.plot(xs, A_med + xs / kla_med, color=BASELINE, lw=7, solid_capstyle='round', zorder=1)
    ax.text(0.0037, A_med + 0.0037 / kla_med - 0.0013,
            '簡併線 P_eq − r̄_b/kLa ＝ %.4f\n線上每一點擬合得一樣好' % A_med,
            fontsize=8.5, color=INK2, ha='left', va='top')
    ax.annotate('真值的 A＝%.4f\n只差 %.4f（＜量化步階 1/10）' % (A_TRUE, A_med - A_TRUE),
                xy=(RB_TRUE, PEQ_TRUE), xytext=(0.0041, PEQ_TRUE - 0.0007),
                fontsize=8.5, color=INK2, ha='left', va='top',
                arrowprops=dict(arrowstyle='-', color=MUTED, lw=0.8))
    for lam, col in LAM_COL.items():
        pts = [(float(r['rb_mean']), float(r['peq'])) for r in q if float(r['lambda']) == lam]
        ax.scatter(*zip(*pts), s=34, color=col, edgecolor='white', linewidth=1, zorder=3,
                   label='λ=%g' % lam)
    ax.scatter([RB_TRUE], [PEQ_TRUE], marker='*', s=260, color=INK, edgecolor='white',
               linewidth=1.2, zorder=5, label='真正的答案')
    ax.legend(loc='upper left', fontsize=8.5, frameon=False)
    style(ax, 'b　64 個模型都落在同一條線上，位置由起點決定',
          'r̄_b：平均生物速率（kg/cm²/hr）', 'P_eq：平衡壓力（kg/cm²）')

    # c　三個參數被資料鎖住的程度
    ax = axes[2]
    params = [('A', A_TRUE, 'A＝P_eq − r̄_b/kLa'), ('kla', KLA_TRUE, 'kLa'),
              ('rb_mean', RB_TRUE, 'r̄_b')]
    rng = np.random.default_rng(0)
    for i, (key, truth, lab) in enumerate(params):
        v = np.array([float(r[key]) for r in q]) / truth
        jit = rng.uniform(-0.18, 0.18, len(v))
        cols = [LAM_COL[float(r['lambda'])] for r in q]
        ax.scatter(i + jit, v, s=16, c=cols, alpha=0.85, linewidth=0)
        lo, hi = v.min(), v.max()
        ax.text(i, hi * 1.9 if key == 'rb_mean' else hi * 1.25,
                '%.3f – %.3f' % (lo, hi) if key != 'rb_mean' else '%.4f – %.2f' % (lo, hi),
                ha='center', fontsize=8.5, color=INK2)
    ax.axhline(1, color=INK, lw=1, ls='--')
    ax.text(-0.55, 0.8, '虛線＝真值', fontsize=8.5, color=INK2, ha='left', va='top')
    ax.set_yscale('log')
    ax.set_ylim(5e-4, 20)
    plain_log_ticks(ax)
    ax.set_xticks(range(3))
    ax.set_xticklabels([p[2] for p in params])
    ax.set_xlim(-0.6, 2.6)
    ax.text(0.02, 0.03, 'A 與 kLa：64 個模型都在真值附近\nr̄_b：散布兩個數量級，且多半低估',
            transform=ax.transAxes, fontsize=9, color=INK2, va='bottom')
    style(ax, 'c　資料決定 A 與 kLa，不決定 r̄_b', None, '估計值 ÷ 真值（對數）')

    fig.suptitle('批次 PINN：GPU 一次訓練 64 個模型，直接量出「資料決定了什麼」（合成資料，答案已知）',
                 fontweight='bold', x=0.06, ha='left', y=1.02)
    path = os.path.join(OUT, 'fig57_pinn_batched.png')
    fig.savefig(path)
    plt.close(fig)
    print('-> %s' % os.path.relpath(path, os.path.dirname(RESEARCH)))


def fig58():
    path_csv = os.path.join(DATA, 'real_cycles.csv')
    if not os.path.exists(path_csv):
        print('（還沒有 real_cycles.csv，略過 fig58）')
        return
    rows = read('real_cycles.csv')
    keys = []
    for r in rows:
        k = (r['batch'], int(r['cycle']))
        if k not in keys:
            keys.append(k)
    order = {'tau1': 0, 'tau5': 1, 'tau10': 2}
    keys.sort(key=lambda k: (order[k[0]], k[1]))
    summ = []
    for k in keys:
        g = [r for r in rows if (r['batch'], int(r['cycle'])) == k]
        A = np.array([float(r['A']) for r in g])
        kla = np.array([float(r['kla']) for r in g])
        rb = np.array([float(r['rb_mean']) for r in g])
        rmse = np.array([float(r['rmse']) for r in g])
        summ.append(dict(batch=k[0], cycle=k[1], hours=float(g[0]['hours']), n=len(g),
                         A=A, kla=kla, rb=rb, rmse=rmse,
                         kT=float(np.median(kla)) * float(g[0]['hours'])))

    # 曲線近乎直線（kLa·T 小）時沒有曲率可抓，連 A 都定不了——圖上用空心點標出
    STRAIGHT = 0.15
    n_str = sum(s['kT'] < STRAIGHT for s in summ)
    n_lock = sum((s['A'].max() - s['A'].min()) <= 0.005 for s in summ)
    rb_med_all = float(np.median([np.median(s['rb']) for s in summ]))
    FLOOR_RB = 1e-7               # real_cycles.csv 舊版只存到小數 7 位，更小的值成了 0

    fig, axes = plt.subplots(3, 1, figsize=(13.5, 11), sharex=True,
                             gridspec_kw={'hspace': 0.34})
    x = np.arange(len(summ))
    specs = [('A', 'a　A＝P_eq − r̄_b/kLa：%d／%d 個循環被鎖死（16 個模型的範圍 ≤ 0.005）；'
                   '空心＝曲線近乎直線的 %d 個，連 A 都定不了' % (n_lock, len(summ), n_str),
              'A（kg/cm²）', False),
             ('kla', 'b　kLa：同一循環內穩定，但只有 0.01–0.13 /hr——時間常數 8–100 小時，比循環本身還長',
              'kLa（1/hr）', False),
             ('rb', 'c　r̄_b：幾乎全部塌到 0（各循環中位數的中位 %.0e，論文值的 1/%d）'
                    % (rb_med_all, round(RB_PAPER[0] / rb_med_all, -2)),
              'r̄_b（kg/cm²/hr，對數）', True)]
    for ax, (key, title, ylab, logy) in zip(axes, specs):
        if key == 'rb':
            ax.axhspan(RB_PAPER[1], RB_PAPER[2], color=BASELINE, alpha=0.45, lw=0)
            ax.axhline(RB_PAPER[0], color=INK, lw=1, ls='--')
            ax.text(len(summ) - 0.4, RB_PAPER[0] * 1.25, '論文 r_b 0.0125（95% 區間）',
                    fontsize=8.5, color=INK2, ha='right', va='bottom')
            ax.axhline(FLOOR_RB, color=MUTED, lw=0.8, ls=':')
        for i, s in enumerate(summ):
            v = np.maximum(s[key], FLOOR_RB) if key == 'rb' else s[key]
            col = BATCH_COL[s['batch']]
            hollow = s['kT'] < STRAIGHT
            ax.plot([i, i], [v.min(), v.max()], color=col, lw=5, solid_capstyle='round',
                    alpha=0.55, zorder=2)
            ax.scatter([i], [np.median(v)], s=40, color='white' if hollow else col,
                       edgecolor=col if hollow else 'white', linewidth=1.6, zorder=3)
        if logy:
            ax.set_yscale('log')
            ax.set_ylim(FLOOR_RB / 2, 0.05)
            plain_log_ticks(ax)
        style(ax, title, None, ylab)
    axes[0].set_title(axes[0].get_title(loc='left'), loc='left', color=INK, fontweight='bold',
                      pad=26)                                  # 留空間給上方的批次標籤
    axes[2].text(0.0, -0.22,
                 'PINN 把壓降幾乎全部歸給「一階物理項＋很低的平衡壓力」。常數 r_b 可以整個被 P_eq 吸收（簡併），\n'
                 '所以這是谷底的哪一端被選中，不是「沒有生物」的證據；也不能拿來支持或反駁論文的 r_b。'
                 '點線＝記錄下限 1e-7（更小的值畫在線上）',
                 transform=axes[2].transAxes, fontsize=9, color=INK2, va='top')
    # 批次分隔與標籤
    for ax in axes:
        prev = None
        for i, s in enumerate(summ):
            if prev is not None and s['batch'] != prev:
                ax.axvline(i - 0.5, color=BASELINE, lw=1)
            prev = s['batch']
    for b in ('tau1', 'tau5', 'tau10'):
        idx = [i for i, s in enumerate(summ) if s['batch'] == b]
        if idx:
            axes[0].text(np.mean(idx), 1.02, '%s（%d 個循環）' % (BATCH_NAME[b], len(idx)),
                         transform=axes[0].get_xaxis_transform(), ha='center', va='bottom',
                         fontsize=9.5, color=BATCH_COL[b] if b != 'tau5' else INK2,
                         fontweight='bold')
    axes[-1].set_xticks(x)
    axes[-1].set_xticklabels(['%d' % s['cycle'] for s in summ], fontsize=8)
    axes[-1].set_xlabel('循環（各批內依時間順序）')
    fig.suptitle('29 個真實循環 × 16 個模型（464 個 PINN，Jetson GPU 44 分鐘）：資料能決定與不能決定的\n'
                 '每一欄＝一個循環；粗線＝16 個模型（8 個起點 × λ 0.1、1）的最小到最大；點＝中位數',
                 fontweight='bold', x=0.06, ha='left', y=0.985, fontsize=11)
    path = os.path.join(OUT, 'fig58_pinn_real_cycles.png')
    fig.savefig(path)
    plt.close(fig)
    print('-> %s' % os.path.relpath(path, os.path.dirname(RESEARCH)))

    # 表格版（圖的文字替代）
    tpath = os.path.join(DATA, 'real_cycles_summary.csv')
    with open(tpath, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        # rb 低於 1e-7 的在舊版 CSV 裡已被捨入成 0，只能寫「<1e-7」，比值也只能給下界
        w.writerow(['batch', 'cycle', 'hours', 'n_models', 'kla_x_hours', 'rmse_median',
                    'A_median', 'A_min', 'A_max', 'kla_median', 'kla_min', 'kla_max',
                    'rb_median', 'rb_min', 'rb_max', 'rb_max_over_min'])
        for s in summ:
            rbmin = s['rb'].min()
            w.writerow([s['batch'], s['cycle'], s['hours'], s['n'], round(s['kT'], 3),
                        round(np.median(s['rmse']), 5),
                        round(np.median(s['A']), 5), round(s['A'].min(), 5), round(s['A'].max(), 5),
                        round(np.median(s['kla']), 4), round(s['kla'].min(), 4), round(s['kla'].max(), 4),
                        '%.2g' % np.median(s['rb']) if np.median(s['rb']) >= FLOOR_RB else '<1e-7',
                        '%.2g' % rbmin if rbmin >= FLOOR_RB else '<1e-7', '%.2g' % s['rb'].max(),
                        ('%.0f' % (s['rb'].max() / rbmin)) if rbmin >= FLOOR_RB
                        else '>%.0f' % (s['rb'].max() / FLOOR_RB)])
    print('-> %s' % os.path.relpath(tpath, os.path.dirname(RESEARCH)))
    return summ


if __name__ == '__main__':
    fig57()
    fig58()
