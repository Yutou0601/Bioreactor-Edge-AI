# -*- coding: utf-8 -*-
"""各演算法的示意圖：每張圖給幾個「指定情況」，數字全部由專案自己的函式算出來。

2026-10-17。配合 docs/公式與演算法總整理_2026-10-17.md。

資料是合成的（所以答案已知），但切段、曲率、擬合、bootstrap、ORP 處理、化學計量
都直接呼叫 edge_backend 與 research 裡的實際函式——圖上顯示的結果就是程式的行為，
不是另外手畫的。

⚠ matplotlib 3.11 旋轉 90° 的「體」字會畫錯（memory: matplotlib_rotated_cjk_glyph_bug），
  y 軸標籤避開這個字。

用法：python fig_algorithm_explainers.py   → docs/algorithm_figures/A01_*.png …
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                   # noqa: E402
from matplotlib import rcParams                                   # noqa: E402
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
REPO = os.path.dirname(RESEARCH)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, os.path.join(RESEARCH, 'cycles'))
sys.path.insert(0, os.path.join(RESEARCH, 'ml'))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from core import cycle_estimator as ce                           # noqa: E402
from core import descent_report as dr                            # noqa: E402
from core.signal_processor import ORPSignalProcessor             # noqa: E402

OUT = os.path.join(REPO, 'docs', 'algorithm_figures')
BLUE, RED, AQUA, YELLOW = '#2a78d6', '#e34948', '#1baf7a', '#eda100'
SURFACE, INK, INK2, MUTED = '#fcfcfb', '#0b0b0b', '#52514e', '#898781'
GRID, BASELINE = '#e1e0d9', '#c3c2b7'
rcParams.update({
    'font.family': ['Microsoft JhengHei', 'DejaVu Sans'], 'axes.unicode_minus': False,
    'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
    'text.color': INK, 'axes.labelcolor': INK2, 'xtick.color': MUTED, 'ytick.color': MUTED,
    'axes.edgecolor': BASELINE, 'grid.color': GRID, 'font.size': 10, 'axes.titlesize': 11,
    'axes.spines.top': False, 'axes.spines.right': False, 'savefig.dpi': 170,
})
RESULTS = {}            # 每張圖算出的關鍵數字，最後印出來給說明文字用


def title(ax, s):
    ax.set_title(s, loc='left', fontweight='bold', color=INK, pad=8)


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, name), bbox_inches='tight')
    plt.close(fig)
    print('  ->', name)


def ar1(rng, n, sd, phi):
    e = rng.normal(0, sd * np.sqrt(1 - phi * phi), n)
    z = np.empty(n)
    z[0] = rng.normal(0, sd)
    for i in range(1, n):
        z[i] = phi * z[i - 1] + e[i]
    return z


def q(y):
    return np.round(y / ce.QUANT) * ce.QUANT


def logticks(ax, ticks=(0.01, 0.03, 0.1, 0.3, 1, 3)):
    """對數軸用一般數字標刻度（預設的 10^-2 寫法在 JhengHei 缺負號字形，會變成 10¤2）。"""
    ax.set_xticks(list(ticks))
    ax.set_xticklabels(['%g' % v for v in ticks])
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())


def sse_profile(t, y):
    out = []
    for k in ce.KGRID:
        A = np.vstack([np.exp(-k * t), t, np.ones_like(t)]).T
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y - A @ c
        out.append(float(r @ r))
    return np.array(out)


# ══════════════════════════════════════════════════════════
# A01 循環切段
# ══════════════════════════════════════════════════════════
def fig_segment():
    rng = np.random.default_rng(1)
    pieces = [  # (起點 h, 時長 h, P_eq, A, k, r_b)
        (0.0, 7.0, 0.75, 0.42, 0.45, 0.012),
        (7.0, 3.0, 0.75, 0.42, 0.45, 0.012),
        (10.0, 6.0, 1.12, 0.05, 0.30, 0.003),
        (17.5, 9.0, 0.75, 0.42, 0.45, 0.012),
    ]
    H, P = [], []
    for s, d, peq, A, k, rb in pieces:
        t = np.arange(0, d, 1 / 60)
        y = peq + A * np.exp(-k * t) - rb * t
        y = y - y[0] + 1.17
        H.append(s + t)
        P.append(q(y + ar1(rng, len(t), 0.003, 0.3)))
    h, p = np.concatenate(H), np.concatenate(P)

    # 與 ce.segment 相同的掃描，但保留所有候選段以便標出被淘汰的原因
    cand, valley, start, cuts = [], p[0], 0, []
    for i in range(1, len(p)):
        if h[i] - h[i - 1] > ce.GAP_HR:
            cand.append((start, i - 1)); cuts.append((i, 'gap'))
            start, valley = i, p[i]
            continue
        if p[i] - valley > ce.REFILL_RISE:
            cand.append((start, i - 1)); cuts.append((i, 'refill'))
            start, valley = i, p[i]
        elif p[i] < valley:
            valley = p[i]
    cand.append((start, len(p) - 1))
    kept = set(ce.segment(h, p))

    fig, ax = plt.subplots(figsize=(11, 4.2))
    hp, pp = h.astype(float).copy(), p.astype(float).copy()
    gi = np.flatnonzero(np.diff(h) > ce.GAP_HR) + 1          # 中斷處斷開線，不要畫出假的連線
    ax.plot(np.insert(hp, gi, np.nan), np.insert(pp, gi, np.nan), color=BLUE, lw=1.1)
    for a, b in cand:
        dur, drop = h[b] - h[a], p[a] - p[b]
        ok = (a, b) in kept
        ax.axvspan(h[a], h[b], color=AQUA if ok else MUTED, alpha=0.13 if ok else 0.10, lw=0)
        if ok:
            msg = '✓ 保留\n%.1f h、落差 %.2f' % (dur, drop)
        elif dur < ce.MIN_HR:
            msg = '✗ 太短\n%.1f h < %.0f h' % (dur, ce.MIN_HR)
        else:
            msg = '✗ 太淺\n落差 %.2f < %.2f' % (drop, ce.MIN_AMP)
        ax.text((h[a] + h[b]) / 2, 1.235, msg, ha='center', va='bottom', fontsize=9,
                color=AQUA if ok else RED, fontweight='bold')
    n_ref = 0
    for i, kind in cuts:
        if kind == 'refill':
            xy_text = (h[i] - 2.6, 0.97) if n_ref == 0 else (h[i] + 0.8, 0.98)
            n_ref += 1
            ax.annotate('補氣：升幅 > 0.03\n→ 切段', (h[i], p[i] - 0.02), xy_text, fontsize=8.5,
                        color=RED, arrowprops=dict(arrowstyle='->', color=RED, lw=0.9))
        else:
            ax.axvspan(h[i - 1], h[i], color=YELLOW, alpha=0.25, lw=0)
            ax.text((h[i - 1] + h[i]) / 2, 0.90, '取樣中斷\n%.1f h > 1 h\n→ 強制切段' % (h[i] - h[i - 1]),
                    ha='center', fontsize=8.5, color=INK2)
    ax.set_ylim(0.6, 1.36)
    ax.set_xlabel('時間（小時）')
    ax.set_ylabel('反應槽壓力（kgf/cm²）')
    ax.grid(alpha=0.6)
    title(ax, '循環切段：補氣或中斷就切；段長 ≥ 4 小時、落差 ≥ 0.10 才保留（每段開頭再掐掉 3 分鐘）')
    RESULTS['segment'] = [(round(h[b] - h[a], 2), round(p[a] - p[b], 2), (a, b) in kept) for a, b in cand]
    save(fig, 'A01_segment.png')


# ══════════════════════════════════════════════════════════
# A02 ORP 突波處理
# ══════════════════════════════════════════════════════════
def fig_orp():
    rng = np.random.default_rng(2)
    n = 120
    x = 534 + np.round(rng.normal(0, 1.0, n))
    x[30:36] = [489, 495, 505, 515, 524, 532]          # 情況一：淺跌、很快回升
    x[70:92] = 455 + np.round(rng.normal(0, 1.0, 22))  # 情況二：深跌 79 mV、停 22 分
    proc = ORPSignalProcessor()
    pts = []
    for i in range(n):
        pts += proc.process('2026-01-01 00:%02d:%02d' % (i // 60, i % 60), float(x[i]))
    pts += proc.flush()
    raw = np.array([pt.raw for pt in pts])
    cln = np.array([pt.cleaned for pt in pts])
    ema = np.array([pt.ema for pt in pts])
    an = np.array([pt.is_anomaly for pt in pts])
    m = np.arange(len(pts))

    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.plot(m, raw, color=MUTED, lw=1, label='原始（記錄器存的正值；真值＝−記錄值）')
    ax.plot(m, cln, color=BLUE, lw=1.6, label='清理後（突波段線性內插）')
    ax.plot(m, ema, color=RED, lw=1.6, label='EMA（N = 10，α = 2/11）')
    ax.scatter(m[an], raw[an], s=16, color=YELLOW, zorder=5, label='判為突波的點')
    ax.annotate('情況一：一分鐘跌 45 mV（< −20）→ 進入突波\n'
                '一回升且 ≥ 起點的 90%% 就結束\n→ 只標 %d 點、內插補平' % an[25:40].sum(),
                (30, 489), (8, 470), fontsize=8.5, arrowprops=dict(arrowstyle='->', color=INK2))
    ax.annotate('情況二：跌 79 mV 後停在低處\n一直 < 起點的 90% → 不算回升\n'
                '滿 15 分鐘逾時強制結束：\n之後的低值被當成真值接受',
                (85, 455), (95, 480), fontsize=8.5, arrowprops=dict(arrowstyle='->', color=INK2))
    ax.set_xlabel('分鐘')
    ax.set_ylabel('ORP 記錄值（mV）')
    ax.set_ylim(440, 552)
    ax.legend(frameon=False, fontsize=8.5, loc='lower left', ncol=2)
    ax.grid(alpha=0.6)
    title(ax, 'ORP 即時處理：突波偵測 → 線性內插 → EMA')
    RESULTS['orp'] = dict(case1_flagged=int(an[25:40].sum()), case2_flagged=int(an[65:100].sum()))
    save(fig, 'A02_orp_spike.png')


# ══════════════════════════════════════════════════════════
# A03 模型分解與曲率篩選
# ══════════════════════════════════════════════════════════
def fig_model_curvature():
    t = np.linspace(0, 10, 601)
    peq, A, k, rb = 0.75, 0.35, 0.5, 0.012
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.3), gridspec_kw=dict(width_ratios=[1, 1.15]))
    a1.plot(t, peq + A * np.exp(-k * t) - rb * t, color=BLUE, lw=2.2, label='P(t) 合計')
    a1.plot(t, peq + A * np.exp(-k * t), color=AQUA, lw=1.3, ls='--', label='P_eq + A·e^(−kt)（物理弛豫）')
    a1.plot(t, peq - rb * t + A * 0, color=RED, lw=1.3, ls='--', label='P_eq − r_b·t（零階移除）')
    a1.axhline(peq, color=MUTED, lw=0.9, ls=':')
    a1.text(9.9, peq + 0.006, 'P_eq', ha='right', fontsize=8.5, color=MUTED)
    a1.set_xlabel('補氣後時間 t（小時）'); a1.set_ylabel('壓力（kgf/cm²）')
    a1.legend(frameon=False, fontsize=8.5); a1.grid(alpha=0.6)
    title(a1, '(a) 模型 P = P_eq + A·e^(−kt) − r_b·t')

    cases = [('純直線（只有 r_b）', 1.10 - 0.04 * t, MUTED),
             ('k = 0.1', 0.75 + 0.35 * np.exp(-0.1 * t) - 0.01 * t, YELLOW),
             ('k = 0.5', 0.75 + 0.35 * np.exp(-0.5 * t) - 0.01 * t, AQUA),
             ('k = 1.5', 0.75 + 0.35 * np.exp(-1.5 * t) - 0.01 * t, BLUE),
             ('後段加速（凸形）', 1.10 - 0.004 * t ** 2, RED)]
    a2.axhspan(0, ce.CURV_MIN, xmin=0.47, xmax=0.53, color=RED, alpha=0.12)
    res = []
    for name, y, col in cases:
        c = ce.curvature(t, y)
        yn = (y[0] - y) / (y[0] - y[-1])
        a2.plot(t / t[-1], yn, color=col, lw=1.8,
                label='%s：c = %.3f %s' % (name, c, '通過' if c >= ce.CURV_MIN else '擋掉'))
        a2.scatter([0.5], [c], color=col, s=30, zorder=5)
        res.append((name, round(c, 3)))
    a2.axvline(0.5, color=INK2, lw=0.8, ls=':')
    a2.axhline(ce.CURV_MIN, color=RED, lw=0.9, ls='--')
    a2.text(0.02, ce.CURV_MIN + 0.015, 'c* = 0.45', color=RED, fontsize=8.5)
    a2.set_xlabel('正規化時間 (t − t₀)/(t_end − t₀)')
    a2.set_ylabel('已完成的壓降比例')
    a2.legend(frameon=False, fontsize=8.5, loc='upper left', bbox_to_anchor=(1.01, 1.0))
    a2.grid(alpha=0.6)
    title(a2, '(b) 曲率 c ＝ 時間過半時已完成幾成壓降')
    a2.text(1.03, 0.30, '⚠ 直線 c = 0.50 會「通過」。\n篩掉的是後段加速\n（彎錯方向）的段，\n不是直線。',
            transform=a2.transAxes, fontsize=9, color=RED, va='top')
    RESULTS['curvature'] = res
    save(fig, 'A03_model_curvature.png')


# ══════════════════════════════════════════════════════════
# A04 剖面最小平方：k 在網格內 vs 撞網格邊界
# ══════════════════════════════════════════════════════════
def fig_profile():
    rng = np.random.default_rng(4)
    t = np.arange(0, 8, 1 / 60)
    specs = [('彎的段（真值 k = 0.6）', 0.75, 0.30, 0.6, 0.012, BLUE),
             ('幾乎直線（真值 k = 0.03）', 0.75, 0.30, 0.03, 0.012, RED)]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.0))
    out = []
    for name, peq, A, k, rb, col in specs:
        y = q(peq + A * np.exp(-k * t) - rb * t + ar1(rng, len(t), 0.004, 0.3))
        y = y[t >= ce.SKIP_MIN]; tt = t[t >= ce.SKIP_MIN] - t[t >= ce.SKIP_MIN][0]
        s = sse_profile(tt, y)
        f = ce.fit_le(tt, y)
        edge = f['k'] <= ce.KGRID[0] + 1e-9 or f['k'] >= ce.KGRID[-1] - 1e-9
        axes[0].plot(ce.KGRID, s / s.min(), color=col, lw=1.8,
                     label='%s：k̂ = %.2f%s' % (name, f['k'], '（撞邊界）' if edge else ''))
        axes[0].scatter([f['k']], [1], color=col, zorder=5)
        out.append(dict(name=name, k_true=k, rb_true=rb, k_hat=f['k'], rb_hat=round(f['rb'], 4),
                        edge=edge, curv=round(ce.curvature(tt, y), 3)))
        if col == RED:
            ax = axes[2]
            ax.plot(tt, y, color=MUTED, lw=0.8, label='資料（量化 0.01）')
            ax.plot(tt, peq + A * np.exp(-k * tt) - rb * tt + (y[0] - (peq + A)), color=AQUA, lw=2,
                    label='真值：k=%.2f、r_b=%.3f' % (k, rb))
            ax.plot(tt, f['peq'] + f['amp'] * np.exp(-f['k'] * tt) - f['rb'] * tt, color=RED, lw=1.6,
                    ls='--', label='最佳擬合：k̂=%.2f、r̂_b=%.3f' % (f['k'], f['rb']))
            ax.set_xlabel('t（小時）'); ax.set_ylabel('壓力（kgf/cm²）')
            ax.legend(frameon=False, fontsize=8.5); ax.grid(alpha=0.6)
            title(ax, '(c) 直線段：兩組參數幾乎同一條線')
        else:
            ax = axes[1]
            ax.plot(tt, y, color=MUTED, lw=0.8, label='資料')
            ax.plot(tt, f['peq'] + f['amp'] * np.exp(-f['k'] * tt) - f['rb'] * tt, color=BLUE, lw=1.8,
                    label='擬合：k̂=%.2f、r̂_b=%.4f' % (f['k'], f['rb']))
            ax.set_xlabel('t（小時）'); ax.set_ylabel('壓力（kgf/cm²）')
            ax.legend(frameon=False, fontsize=8.5); ax.grid(alpha=0.6)
            title(ax, '(b) 彎的段：k 被資料約束住')
    axes[0].set_xscale('log'); axes[0].set_ylim(0.98, 1.5)
    logticks(axes[0])
    axes[0].axvline(ce.KGRID[0], color=MUTED, ls=':', lw=0.8)
    axes[0].axvline(ce.KGRID[-1], color=MUTED, ls=':', lw=0.8)
    axes[0].text(ce.KGRID[0] * 1.08, 1.12, '網格下限 0.01', fontsize=8, color=MUTED, rotation=90)
    axes[0].text(ce.KGRID[-1] * 0.93, 1.12, '網格上限 2.99', fontsize=8, color=MUTED, rotation=90, ha='right')
    axes[0].set_xlabel('k（1/小時，150 點網格）'); axes[0].set_ylabel('SSE(k) / 最小值')
    axes[0].legend(frameon=False, fontsize=8.5, loc='upper right'); axes[0].grid(alpha=0.6)
    title(axes[0], '(a) 掃過 k 的殘差平方和')
    RESULTS['profile'] = out
    save(fig, 'A04_profile_ls.png')


# ══════════════════════════════════════════════════════════
# A05 區塊 bootstrap
# ══════════════════════════════════════════════════════════
def fig_bootstrap():
    rng = np.random.default_rng(5)
    t = np.arange(0, 10, 1 / 60)
    y = q(0.75 + 0.30 * np.exp(-0.4 * t) - 0.012 * t + ar1(rng, len(t), 0.004, 0.6))
    f = ce.fit_le(t, y)
    yhat = f['peq'] + f['amp'] * np.exp(-f['k'] * t) - f['rb'] * t
    r = y - yhat
    b = ce.bootstrap_rb(t, y, n_boot=400, block_min=30, seed=0)
    # 對照：逐點（iid）重抽
    g = np.random.default_rng(0)
    Yi = yhat[None, :] + r[g.integers(0, len(r), (400, len(r)))]
    rbi = ce.BatchFitter(t).fit(Yi)['rb']
    lo_i, hi_i = np.percentile(rbi, [2.5, 97.5])
    # 重算區塊版的抽樣分布（與 bootstrap_rb 同一做法）以便畫直方圖
    L = 30
    starts = np.random.default_rng(0).integers(0, len(t) - L, size=(400, int(np.ceil(len(t) / L))))
    idx = (starts[:, :, None] + np.arange(L)[None, None, :]).reshape(400, -1)[:, :len(t)]
    rbb = ce.BatchFitter(t).fit(yhat[None, :] + r[idx])['rb']

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.0))
    a1.plot(t, r, color=MUTED, lw=0.8, label='殘差')
    for x in np.arange(0, 10, 0.5):
        a1.axvline(x, color=GRID, lw=0.8)
    a1.plot(t, r[idx[0]], color=BLUE, lw=0.8, alpha=0.8, label='一次重抽（30 分鐘區塊拼接）')
    a1.set_xlabel('t（小時）'); a1.set_ylabel('殘差（kgf/cm²）')
    a1.legend(frameon=False, fontsize=8.5); a1.grid(False)
    title(a1, '(a) 殘差切成 30 分鐘區塊、隨機起點重抽拼回')
    bins = np.linspace(min(rbi.min(), rbb.min()), max(rbi.max(), rbb.max()), 40)
    a2.hist(rbb, bins=bins, color=BLUE, alpha=0.6, label='區塊：95%% [%.4f, %.4f]' % (b['ci_lo'], b['ci_hi']))
    a2.hist(rbi, bins=bins, color=YELLOW, alpha=0.6, label='逐點：95%% [%.4f, %.4f]' % (lo_i, hi_i))
    a2.axvline(f['rb'], color=RED, lw=1.5, label='點估計 r̂_b = %.4f' % f['rb'])
    a2.axvline(0.012, color=INK, lw=1, ls='--', label='真值 0.012')
    a2.set_xlabel('重抽的 r̂_b'); a2.set_ylabel('次數')
    a2.legend(frameon=False, fontsize=8.5); a2.grid(alpha=0.6)
    title(a2, '(b) 殘差有自相關時，逐點重抽的區間窄得不實')
    RESULTS['bootstrap'] = dict(rb=round(f['rb'], 4), block=(round(b['ci_lo'], 4), round(b['ci_hi'], 4)),
                                iid=(round(lo_i, 4), round(hi_i, 4)),
                                lag1=round(float(np.corrcoef(r[:-1], r[1:])[0, 1]), 2))
    save(fig, 'A05_block_bootstrap.png')


# ══════════════════════════════════════════════════════════
# 合成「循環族群」：給 Algorithm 2／3
# ══════════════════════════════════════════════════════════
def population(rng, n=70):
    segs = []
    for _ in range(n):
        T = rng.uniform(6, 12)
        t = np.arange(0, T, 1 / 60)
        segs.append(dict(t=t, k=float(np.exp(rng.normal(np.log(0.2), 0.9))),
                         A=rng.uniform(0.2, 0.4), peq=rng.uniform(0.65, 0.8),
                         sd=0.004, phi=0.35))
    return segs


def fig_alg2():
    rng = np.random.default_rng(6)
    segs = population(rng)
    R0 = 0.0125
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.0), sharey=True)
    out = {}
    for ax, mode in zip(axes, ('B0', 'B1', 'B2')):
        kh, rh, kt = [], [], []
        for s in segs:
            if mode == 'B0':
                rbt = R0
            elif mode == 'B1':
                rbt = R0 + rng.normal(0, 0.006)
            else:
                rbt = 0.006 + 0.004 * np.log(s['k'] / 0.2) + R0 - 0.006
            t = s['t']
            y = q(s['peq'] + s['A'] * np.exp(-s['k'] * t) - rbt * t + ar1(rng, len(t), s['sd'], s['phi']))
            g = ce.fit_le(t, y)
            kh.append(g['k']); rh.append(g['rb']); kt.append(rbt)
        kh, rh = np.array(kh), np.array(rh)
        rho = float(np.corrcoef(np.argsort(np.argsort(rh)), np.argsort(np.argsort(kh)))[0, 1])
        ax.scatter(kh, rh, s=14, color=BLUE, alpha=0.75, label='擬合值 (k̂, r̂_b)')
        if mode == 'B2':
            kk = np.geomspace(0.02, 3, 50)
            ax.plot(kk, 0.006 + 0.004 * np.log(kk / 0.2) + R0 - 0.006, color=AQUA, lw=1.5, label='真值隨 ln k 變')
        else:
            ax.axhline(R0, color=AQUA, lw=1.5, label='真值中位 0.0125')
        ax.set_xscale('log'); ax.grid(alpha=0.6)
        logticks(ax)
        ax.set_xlabel('k̂（1/小時）')
        lab = {'B0': 'B0：真值恆定', 'B1': 'B1：真值隨機散布', 'B2': 'B2：真值隨 k 變'}[mode]
        title(ax, '%s　ρ = %.2f' % (lab, rho))
        ax.legend(frameon=False, fontsize=8.5, loc='lower right')
        out[mode] = dict(rho=round(rho, 3), median=round(float(np.median(rh)), 4))
    axes[0].set_ylabel('r̂_b（kgf/cm²/小時）')
    axes[0].set_ylim(-0.04, 0.06)
    fig.suptitle('Algorithm 2：用已知真值重新合成、量化、再擬合——即使真值恆定（B0），簡併也會造出 ρ(r̂_b, k̂)',
                 x=0.01, ha='left', fontweight='bold', fontsize=10.5, y=1.03)
    RESULTS['alg2'] = out
    save(fig, 'A06_algorithm2.png')


def fig_alg3():
    rng = np.random.default_rng(7)
    segs = population(rng)
    D = 300
    obs_rb, null_meds = [], np.zeros(D)
    per_seg = []
    for s in segs:
        t = s['t']
        y = q(s['peq'] + s['A'] * np.exp(-s['k'] * t) - 0.0125 * t + ar1(rng, len(t), s['sd'], s['phi']))
        if ce.curvature(t, y) >= ce.CURV_MIN:
            obs_rb.append(ce.fit_le(t, y)['rb'])
        # 純物理擬合（r_b ≡ 0）的參數，再合成 D 條
        best = None
        for k in ce.KGRID:
            X = np.vstack([np.exp(-k * t), np.ones_like(t)]).T
            c, *_ = np.linalg.lstsq(X, y, rcond=None)
            rr = y - X @ c
            if best is None or rr @ rr < best[0]:
                best = (rr @ rr, c, k)
        _, c, k = best
        Z = np.stack([q(c[1] + c[0] * np.exp(-k * t) + ar1(rng, len(t), s['sd'], s['phi'])) for _ in range(D)])
        ok = np.array([ce.curvature(t, z) >= ce.CURV_MIN for z in Z])
        rb = np.full(D, np.nan)
        if ok.any():
            rb[ok] = ce.BatchFitter(t).fit(Z[ok])['rb']
        per_seg.append(rb)
    M = np.array(per_seg)
    null_meds = np.nanmedian(M, axis=0)
    obs = float(np.median(obs_rb))
    p = (1 + int((null_meds >= obs).sum())) / (1 + D)

    fig, ax = plt.subplots(figsize=(10, 3.9))
    ax.hist(null_meds, bins=40, color=MUTED, alpha=0.8, label='純物理虛無：%d 次抽樣的中位 r̂_b' % D)
    ax.axvline(obs, color=RED, lw=2, label='「實測」中位 r̂_b = %.4f' % obs)
    ax.set_xlabel('各段 r̂_b 的中位數（kgf/cm²/小時）'); ax.set_ylabel('次數')
    ax.set_xlim(null_meds.min() - 0.001, obs + 0.0015)
    ax.legend(frameon=False, fontsize=9, loc='upper left', bbox_to_anchor=(0.22, 1.0)); ax.grid(alpha=0.6)
    ax.text(0.22, 0.72, 'p = (1 + #{虛無 ≥ 實測}) / (1 + D)\n  = (1 + %d) / (1 + %d) = %.4f\n'
            'p 的下限 = 1/(D+1)：D = 41 時只能到 0.024' % (int((null_meds >= obs).sum()), D, p),
            transform=ax.transAxes, ha='left', va='top', fontsize=9, color=INK2)
    title(ax, 'Algorithm 3：真值 r_b ≡ 0 時，簡併本身能造出多大的 r̂_b？（⚠ 洩漏也是定速項，此檢定排除不了洩漏）')
    RESULTS['alg3'] = dict(obs=round(obs, 4), null_median=round(float(np.median(null_meds)), 5),
                           null_max=round(float(null_meds.max()), 5), p=round(p, 4))
    save(fig, 'A07_algorithm3.png')


# ══════════════════════════════════════════════════════════
# A08 化學計量與排氣甲烷對帳
# ══════════════════════════════════════════════════════════
def fig_stoich():
    drop, p1, p2 = 0.40, 1.17, 0.77
    cases = []
    for name, f1, f2 in [('全是生物', 0.050, None), ('生物 40%', 0.050, None),
                         ('讀數有誤：份額 > 100%', 0.050, None), ('讀數有誤：CH4 不升反降', 0.050, 0.040)]:
        cases.append([name, f1, f2])
    # 依目標份額反推期末 CH4 分率：share = (f2·(p2+ATM) − f1·(p1+ATM)) / drop / 0.25
    for c, share in zip(cases[:3], (1.0, 0.40, 1.30)):
        c[2] = (share * 0.25 * drop + c[1] * (p1 + dr.ATM)) / (p2 + dr.ATM)
    res = [(n, dr.stoichiometry(drop, f1, f2, p1, p2)) for n, f1, f2 in cases]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.2), gridspec_kw=dict(width_ratios=[1.35, 1], wspace=0.55))
    names = [n for n, _ in res]
    shares = [r['bio_share'] * 100 for _, r in res]
    cols = [AQUA, BLUE, RED, RED]
    a1.barh(names, shares, color=cols, alpha=0.85)
    a1.axvline(100, color=INK2, ls='--', lw=0.9)
    a1.axvline(0, color=INK2, lw=0.8)
    for i, (n, r) in enumerate(res):
        a1.text(max(shares[i], 0) + 3, i,
                'ΔpCH4 = %.4f → 份額 %.0f%%%s' % (r['ch4_gain_kgf_cm2'], r['bio_share'] * 100,
                                                 '（%s）' % ('超過上限' if r['bio_share'] > 1 else
                                                            'CH4 不會減少' if r['bio_share'] < 0 else '')
                                                 if not 0 <= r['bio_share'] <= 1 else ''),
                va='center', fontsize=8.5)
    a1.set_xlim(-50, 260)
    a1.set_xlabel('生物份額 =（ΔpCH4 / 總壓降）/ 0.25（%）')
    a1.invert_yaxis()
    title(a1, '(a) 同一段壓降 0.40，排氣 CH4 讀數不同的四種情況')

    V = np.array([0.60, 1.00, 2.14])
    mm = [1000 * dr.moles_from_pressure(0.10, v, 30.0) for v in V]
    a2.bar(['頭空 0.60 L\n(四分位下緣)', '1.00 L\n(採用值)', '2.14 L\n(四分位上緣)'], mm,
           color=[MUTED, BLUE, MUTED], alpha=0.85)
    for i, v in enumerate(mm):
        a2.text(i, v + 0.1, '%.2f mmol' % v, ha='center', fontsize=9)
    a2.set_ylabel('壓降 0.10 對應的莫耳數（mmol）')
    title(a2, '(b) n = ΔP·V/(RT)：份額不需體積，絕對量差 3.6 倍')
    a2.grid(alpha=0.6, axis='y')
    RESULTS['stoich'] = [(n, round(r['bio_share'], 3), round(r['ch4_gain_kgf_cm2'], 4)) for n, r in res]
    RESULTS['mmol'] = [round(v, 2) for v in mm]
    save(fig, 'A08_stoichiometry.png')


# ══════════════════════════════════════════════════════════
# A09 殘餘組成 CO2:H2 在各種情況下怎麼走
# ══════════════════════════════════════════════════════════
def fig_residual():
    PABS, D, NC = 1.17 + dr.ATM, 0.40, 12
    scen = [('只有產甲烷、補氣 1:4', 1.0, 0.0, 0.0, 0.25 / 1.25, AQUA),
            ('補氣比偏 1:3.85（只產甲烷）', 1.0, 0.0, 0.0, 1 / 4.85, YELLOW),
            ('生物 40% ＋ H2 選擇性流失 60%', 0.40, 0.60, 0.0, 0.25 / 1.25, RED),
            ('生物 95% ＋ CO2 溶解 5%', 0.95, 0.0, 0.05, 0.25 / 1.25, BLUE)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 4.2), gridspec_kw=dict(width_ratios=[1.3, 1]))
    out = {}
    for name, fb, fl, fd, fc, col in scen:
        c, h, m = 0.2 * PABS, 0.8 * PABS, 0.0
        ratios = [c / h]
        for _ in range(NC):
            x = fb * D / 4                       # 生物：CO2 消耗 x、H2 4x、CH4 +x（淨降 4x）
            c -= x; h -= 4 * x; m += x
            h -= fl * D                          # H2 洩漏
            c -= fd * D                          # CO2 溶解
            add = PABS - (c + h + m)             # 補氣回到同一個絕對壓
            c += fc * add; h += (1 - fc) * add
            if c <= 0 or h <= 0:                 # 某一種氣體被抽乾：模擬到此為止
                break
            ratios.append(c / h)
        a1.plot(range(len(ratios)), np.array(ratios) / 0.25, color=col, lw=2, marker='o', ms=3, label=name)
        out[name] = (round(ratios[-1] / 0.25, 2), len(ratios) - 1)
    a1.axhspan(1.33, 2.79, color=MUTED, alpha=0.15)
    a1.text(0.2, 2.6, '實測範圍 1.33–2.79 倍（35 次排氣）', fontsize=8.5, color=INK2)
    a1.axhline(1, color=INK2, lw=0.8, ls='--')
    a1.set_xlabel('補氣次數'); a1.set_ylabel('殘餘 CO2:H2 ÷ 0.25（倍）')
    a1.legend(frameon=False, fontsize=8.5, loc='upper left', bbox_to_anchor=(0, 0.88)); a1.grid(alpha=0.6)
    title(a1, '(a) 只有產甲烷時殘餘比恆為 0.25；偏高要有東西額外拿走 H2')

    procs = ['只有產甲烷', '補入 d（組成 c,h）', 'CO2 溶解 d', '碳酸鹽脫氣 d', 'H2 洩漏 L']
    vals = [0, None, -1, 1, 0.25]
    labels = ['0（不變量）', '(c − 0.25h)·d', '−d', '+d', '+0.25 L']
    cols = [AQUA, YELLOW, BLUE, BLUE, RED]
    a2.barh(procs, [0, 0.0075 / 0.1, -1, 1, 0.25], color=cols, alpha=0.85)
    for i, s in enumerate(labels):
        a2.text(1.05 if i != 2 else -1.05, i, s, va='center', ha='left' if i != 2 else 'right', fontsize=9)
    a2.axvline(0, color=INK2, lw=0.8)
    a2.set_xlim(-1.7, 1.9); a2.invert_yaxis(); a2.set_xticks([])
    title(a2, '(b) E = P_abs·(x_CO2 − 0.25·x_H2) 對各過程的反應 dE')
    RESULTS['residual'] = out
    save(fig, 'A09_residual_ratio.png')


# ══════════════════════════════════════════════════════════
# A10 泵窗：逐日剖面 vs 逐小時
# ══════════════════════════════════════════════════════════
def fig_pump():
    from pump_rhythm import pump_window
    rng = np.random.default_rng(10)
    fig, axes = plt.subplots(1, 4, figsize=(14, 3.7), gridspec_kw=dict(width_ratios=[1, 1, 1, 1.15]))
    out = {}
    for ax, (tau, on) in zip(axes[:3], ((1, 50), (5, 25), (10, 13))):
        mu = np.full(60, 0.009 / 60)                       # 泵停期 r_off ≈ 0.009 /h
        drop = 0.0035 * min(tau, 5) ** 0.5
        mu[on] += drop
        for j in range(1, tau):
            mu[(on + j) % 60] += drop * 0.25
        mu[(on + tau) % 60] -= drop * 0.4                  # 停泵回升 ≈ 驟降的 1/3~1/2
        mu += rng.normal(0, 0.00006, 60)                   # 逐日平均後的殘餘雜訊
        a, b, run = pump_window(mu)
        cols = [RED if (m - a) % 60 < run else MUTED for m in range(60)]
        ax.bar(range(60), mu * 1000, color=cols, width=0.9)
        ax.set_title('τ = %d：開 %d 分、停 %d 分 → 運轉 %d 分' % (tau, a, b, run), loc='left',
                     fontsize=9.5, fontweight='bold')
        ax.set_xlabel('小時內第幾分'); ax.grid(alpha=0.5, axis='y')
        out[tau] = (a, b, run)
    axes[0].set_ylabel('平均每分鐘壓降（×10⁻³）')
    # 逐小時：一小時的原始壓降幾乎全是 0 / 0.01 的量化跳動
    ax = axes[3]
    h = np.zeros(60)
    pos = rng.choice(60, 5, replace=False)
    h[pos] = 0.01
    h[25] = 0.01
    h[rng.choice(60, 2, replace=False)] = -0.01
    a, b, run = pump_window(h)
    ax.bar(range(60), h * 1000, color=[YELLOW if (m - a) % 60 < run else MUTED for m in range(60)], width=0.9)
    ax.set_title('單一小時（真值 τ=5、開 25 分）\n規則法：開 %d、停 %d → 運轉 %d 分 ✗' % (a, b, run),
                 loc='left', fontsize=9.5, fontweight='bold', color=RED)
    ax.set_xlabel('小時內第幾分'); ax.grid(alpha=0.5, axis='y')
    fig.suptitle('泵窗：開泵分 = argmax（驟降尖峰）、停泵分 = argmin（回升尖峰）。逐日平均才看得見；單一小時被 0.01 量化淹沒',
                 x=0.01, ha='left', fontweight='bold', fontsize=10.5, y=1.05)
    RESULTS['pump'] = dict(day=out, hour=(a, b, run))
    save(fig, 'A10_pump_window.png')


# ══════════════════════════════════════════════════════════
# A11 PINN／定速模型的可辨識性：只有 P_eq − r_b/kLa 被鎖住
# ══════════════════════════════════════════════════════════
def fig_identifiability():
    rng = np.random.default_rng(11)
    kla, peq0, rb0, P0 = 0.3, 0.75, 0.012, 1.17
    t = np.arange(0, 8, 1 / 60)
    sol = lambda peq, rb: (peq - rb / kla) + (P0 - peq + rb / kla) * np.exp(-kla * t)
    y = q(sol(peq0, rb0) + rng.normal(0, 0.004, len(t)))
    PE, RB = np.meshgrid(np.linspace(0.55, 0.95, 161), np.linspace(-0.03, 0.09, 161))
    Ainf = PE - RB / kla
    # 解只取決於 A∞，所以 SSE 只是 A∞ 的函數（逐點算太慢，改算 A∞ 的一維函數再查表）
    agrid = np.linspace(Ainf.min(), Ainf.max(), 600)
    sse1 = np.array([np.sum((y - (a + (P0 - a) * np.exp(-kla * t))) ** 2) for a in agrid])
    SSE = np.interp(Ainf, agrid, sse1)
    a_hat = agrid[np.argmin(sse1)]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.3))
    cs = a1.contourf(PE, RB, np.log10(SSE), levels=20, cmap='Greys_r')
    a1.plot(PE[0], (PE[0] - a_hat) * kla, color=RED, lw=2, label='谷底：P_eq − r_b/kLa = %.3f' % a_hat)
    pts = [(0.62, None), (0.75, None), (0.90, None)]
    pts = [(pe, (pe - a_hat) * kla) for pe, _ in pts]
    for (pe, rb), col in zip(pts, (BLUE, AQUA, YELLOW)):
        a1.scatter([pe], [rb], color=col, s=50, zorder=5, edgecolor='white')
    a1.scatter([peq0], [rb0], marker='x', color=INK, s=50, zorder=6, label='真值 (0.75, 0.012)')
    a1.set_ylim(RB.min(), RB.max())
    a1.set_xlabel('P_eq'); a1.set_ylabel('r_b（kgf/cm²/小時）')
    a1.legend(frameon=False, fontsize=8.5, loc='upper left')
    title(a1, '(a) 殘差平方和（log）在 (P_eq, r_b) 平面：一整條谷')
    a2.plot(t, y, color=MUTED, lw=0.8, label='資料')
    for (pe, rb), col in zip(pts, (BLUE, AQUA, YELLOW)):
        a2.plot(t, sol(pe, rb), color=col, lw=2.2 if col == BLUE else 1.5,
                ls='-' if col == BLUE else '--', label='P_eq=%.2f、r_b=%+.3f' % (pe, rb))
    a2.set_xlabel('t（小時）'); a2.set_ylabel('壓力（kgf/cm²）')
    a2.legend(frameon=False, fontsize=8.5); a2.grid(alpha=0.6)
    title(a2, '(b) 谷上三點：曲線完全重合（r_b 從負到正）')
    fig.suptitle('dP/dt = −kLa(P − P_eq) − r_b（r_b 恆定）的解只依賴 A∞ = P_eq − r_b/kLa：資料能決定 A∞，決定不了 r_b',
                 x=0.01, ha='left', fontweight='bold', fontsize=10.5, y=1.03)
    RESULTS['identifiability'] = dict(A_hat=round(a_hat, 4), points=[(pe, round(rb, 4)) for pe, rb in pts])
    save(fig, 'A11_identifiability.png')


# ══════════════════════════════════════════════════════════
# A12 機理模型方塊圖（separation_sim）
# ══════════════════════════════════════════════════════════
def box(ax, x, y, w, h, text, fc, ec=None, fs=9.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.02,rounding_size=0.06',
                                fc=fc, ec=ec or BASELINE, lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha='center', va='center', fontsize=fs,
            fontweight='bold' if bold else 'normal', color=INK)


def arrow(ax, p1, p2, text='', col=INK2, off=(0, 0.08), fs=8.5, rad=0.0):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle='-|>', mutation_scale=12, color=col, lw=1.4,
                                 connectionstyle='arc3,rad=%g' % rad))
    if text:
        ax.text((p1[0] + p2[0]) / 2 + off[0], (p1[1] + p2[1]) / 2 + off[1], text, ha='center',
                fontsize=fs, color=col)


def fig_mechanistic():
    fig, ax = plt.subplots(figsize=(12, 5.2))
    ax.set_xlim(0, 12); ax.set_ylim(0, 5.4); ax.axis('off')
    box(ax, 0.3, 3.4, 5.6, 1.7, '', '#eef4fb', ec=BLUE)
    ax.text(0.45, 4.85, '頂空（氣相）', fontsize=10, fontweight='bold', color=BLUE)
    for i, (s, n) in enumerate([('h', 'H2'), ('c', 'CO2'), ('m', 'CH4'), ('n', '惰性')]):
        box(ax, 0.55 + i * 1.35, 3.6, 1.15, 0.9, '%s\n%s' % (s, n), 'white')
    box(ax, 0.3, 0.5, 5.6, 1.6, '', '#eefaf4', ec=AQUA)
    ax.text(0.45, 1.85, '液相', fontsize=10, fontweight='bold', color=AQUA)
    box(ax, 1.9, 0.7, 2.4, 0.9, 'L（液相 CO2 存量）\nx = L / γ', 'white')
    arrow(ax, (2.6, 3.55), (2.6, 1.65), 'F = kLa(t)·γ·(c − x)\n溶解（泵開時 kLa 大）', BLUE, off=(-1.15, 0))
    # 生物反應放在氣相與液相之間的右側：H2 從氣相進、CO2 從液相進、CH4 回到氣相
    box(ax, 6.5, 2.15, 2.5, 1.0, 'R = k_b·h·x/(x + K_x)\n產甲烷（生物）', '#fff6e0', ec=YELLOW)
    arrow(ax, (5.9, 3.75), (6.75, 3.15), 'H2：−4R', YELLOW, off=(0.55, 0.05))
    arrow(ax, (7.75, 3.15), (5.9, 4.45), 'CH4：+R', YELLOW, off=(0.75, 0.25), rad=0.25)
    arrow(ax, (4.3, 1.15), (6.75, 2.15), 'CO2（液相）：−R', YELLOW, off=(0.35, -0.35))
    box(ax, 9.4, 4.0, 2.4, 1.1, '洩漏 λ·w_i·p_i\n（w_i：整體流 ~ Graham 1/√M）', '#fdeeee', ec=RED, fs=8.8)
    arrow(ax, (5.9, 4.85), (9.4, 4.75), '各氣體依權重漏出', RED, off=(0.2, 0.12))
    box(ax, 9.4, 0.4, 2.4, 3.2, '量測\n\nP = h+c+m+n − 1.033\n\npH = pH₀ − log₁₀(x/x₀)\n\n'
        'ORP = O₀ − 61.1(pH−pH₀)\n− 30.6·log₁₀(h/h₀)', '#f3f3f1', fs=8.8)
    ax.text(0.3, 0.05, '總壓降 ＝ (F − R) ＋ 4R ＋ 漏 ＝ 溶解（液相淨增）＋ 生物 ＋ 洩漏，三者恰好相加。'
            '⚠ 程式的 Nernst 常數用 35 °C（61.1／30.6），反應器為 30 °C（60.1／30.1）。',
            fontsize=8.8, color=INK2)
    title(ax, '機理模擬 separation_sim：五個狀態、三條移除途徑、三種量測')
    save(fig, 'A12_mechanistic_model.png')


# ══════════════════════════════════════════════════════════
# A13 軟感測器採樣設計：固定間隔 vs 主動學習
# ══════════════════════════════════════════════════════════
def fig_softsensor():
    import softsensor_anchor_design as sd
    s = sd.simulate(0.5, 'const', 1001)
    E = sd.reduce(sd.hand_features(s))
    r = s['r_hour']
    N = 16
    v_f, R_f, y_f = sd.run_policy(E, r, 'fixed', N, None, np.random.default_rng(1))
    v_a, R_a, y_a = sd.tune_theta(E, r, 'infogain', N, 1)
    H = len(r)
    day = lambda x: x[:len(x) // 24 * 24].reshape(-1, 24).mean(1)

    def preds(v, R, y):
        m, _ = sd.blr(R, y, (sd.ANCHOR_REL * np.mean(y)) ** 2)
        soft = (np.c_[np.ones(H), E] @ m) * 0.01
        interp = np.empty(H)
        for (a, b), val in zip(zip(v[:-1], v[1:]), y):
            interp[a:b] = val * 0.01
        interp[v[-1]:] = y[-1] * 0.01
        return soft, interp

    soft_f, int_f = preds(v_f, R_f, y_f)
    soft_a, _ = preds(v_a, R_a, y_a)
    ev_f = sd.evaluate(E, r, v_f, R_f, y_f)
    ev_a = sd.evaluate(E, r, v_a, R_a, y_a)
    d = np.arange(len(day(r)))
    fig, ax = plt.subplots(figsize=(12, 4.3))
    ax.plot(d, day(r) * 1000, color=INK, lw=2, label='真值 r_bio（日平均）')
    ax.plot(d, day(int_f) * 1000, color=MUTED, lw=1.4, drawstyle='steps-mid',
            label='直接內插錨點（固定間隔）：誤差 %.2f / 之後 %.2f' % (ev_f[2], ev_f[3]))
    ax.plot(d, day(soft_f) * 1000, color=BLUE, lw=1.6,
            label='軟感測器＋固定間隔：誤差 %.2f / 之後 %.2f' % (ev_f[0], ev_f[1]))
    ax.plot(d, day(soft_a) * 1000, color=RED, lw=1.4, ls='--',
            label='軟感測器＋資訊增益：誤差 %.2f / 之後 %.2f' % (ev_a[0], ev_a[1]))
    top = ax.get_ylim()[1]
    for x in v_f[1:]:
        ax.plot([x / 24] * 2, [top * 0.96, top], color=BLUE, lw=1.2)
    for x in v_a[1:]:
        ax.plot([x / 24] * 2, [top * 0.90, top * 0.94], color=RED, lw=1.2)
    ax.text(sd.CAMPAIGN_DAYS + 0.6, top * 0.98, '← 固定間隔排氣（%d 次）' % (len(v_f) - 1),
            fontsize=8, color=BLUE, va='center')
    ax.text(sd.CAMPAIGN_DAYS + 0.6, top * 0.92, '← 資訊增益排氣（%d 次）' % (len(v_a) - 1),
            fontsize=8, color=RED, va='center')
    ax.axvspan(sd.CAMPAIGN_DAYS, d[-1] + 1, color=YELLOW, alpha=0.10)
    ax.text(sd.CAMPAIGN_DAYS + 0.5, top * 0.75, '之後 20 天\n不排氣', fontsize=9, color=INK2)
    ax.set_xlabel('天'); ax.set_ylabel('r_bio（×10⁻³ kgf/cm²/小時）')
    ax.legend(frameon=False, fontsize=8.5, loc='lower left'); ax.grid(alpha=0.6)
    title(ax, '採樣設計（模擬，c_bio = 0.5、非生物項恆定、16 次排氣）：主動學習把排氣擠在前段；誤差為日平均相對 RMSE')
    RESULTS['softsensor'] = dict(fixed=[round(x, 3) for x in ev_f], infogain=[round(x, 3) for x in ev_a])
    save(fig, 'A13_softsensor_design.png')


# ══════════════════════════════════════════════════════════
# A14 Bi-LSTM 泵標記器流程
# ══════════════════════════════════════════════════════════
def fig_tagger():
    fig, ax = plt.subplots(figsize=(12.5, 4.0))
    ax.set_xlim(0, 12.5); ax.set_ylim(0, 4); ax.axis('off')
    box(ax, 0.2, 2.2, 2.3, 1.4, '逐分鐘輸入\nΔP、ΔORP、ΔpH\n＋斷點旗標', '#eef4fb', ec=BLUE)
    box(ax, 3.0, 2.2, 2.3, 1.4, '穩健標準化\nz = (x − 中位)/(1.4826·MAD)\n截斷 ±50', 'white')
    box(ax, 5.8, 2.2, 2.4, 1.4, 'Bi-LSTM\n2 層 × 32\n序列 180 分鐘', '#fff6e0', ec=YELLOW, bold=True)
    box(ax, 8.7, 2.2, 3.5, 1.4, '每分鐘 3 類\n泵停 ／ 泵開 ／ 補氣\n交叉熵，類別權重 N/(3·N_c)', '#eefaf4', ec=AQUA)
    for a, b in ((2.5, 3.0), (5.3, 5.8), (8.2, 8.7)):
        arrow(ax, (a, 2.9), (b, 2.9))
    box(ax, 0.2, 0.25, 4.6, 1.4, '⚠ 輸入不給「小時內第幾分」\n否則模型只會背時刻表，等於把標籤餵回去', '#fdeeee', ec=RED, fs=9)
    box(ax, 5.2, 0.25, 3.6, 1.4, '標籤（弱標籤）\n逐日剖面 argmax／argmin → 泵窗\n補氣：ΔP > 0.03', '#f3f3f1', fs=9)
    box(ax, 9.2, 0.25, 3.1, 1.4, '驗證：留一 τ 批\n指標：F1、逐小時運轉誤差、\n3 月無泵期誤報率', '#f3f3f1', fs=9)
    arrow(ax, (7.0, 1.65), (7.0, 2.2), '監督', INK2, off=(0.35, -0.12))
    title(ax, 'Bi-LSTM 泵標記器（pump_tagger.py）：τ=5、10 留出時逐小時運轉誤差 2–3 分（規則法 17–18 分）；τ=1 外推失敗')
    save(fig, 'A14_bilstm_tagger.png')


# ══════════════════════════════════════════════════════════
# A15–A17 水汽凝結：傳輸方程、供應上限、排氣膨脹降溫
# ══════════════════════════════════════════════════════════
KGF, ATM_PA = 98066.5, 1.033 * 98066.5
R_GAS, M_W = 8.314462618, 18.015


def psat(Tc):
    """水的飽和蒸氣壓（Pa），Antoine，1–100 °C。"""
    return 133.322 * 10 ** (8.07131 - 1730.63 / (233.426 + Tc))


def fuller_D(T, P_atm, MA, MB, vA, vB):
    """Fuller–Schettler–Giddings 二元擴散係數（cm²/s）。"""
    return 1e-3 * T ** 1.75 * np.sqrt(1 / MA + 1 / MB) / (P_atm * (vA ** (1 / 3) + vB ** (1 / 3)) ** 2)


def D_water_mix(T, P_atm, y_h2=0.8, y_co2=0.2):
    """水汽在 H2/CO2 混合氣中的擴散係數（Blanc 混合律；Fuller 擴散體積 H2O 13.1、H2 6.12、CO2 26.9）。"""
    d_h = fuller_D(T, P_atm, 18.015, 2.016, 13.1, 6.12)
    d_c = fuller_D(T, P_atm, 18.015, 44.01, 13.1, 26.9)
    return 1.0 / (y_h2 / d_h + y_co2 / d_c), d_h, d_c


def fig_boundary_layer():
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw=dict(width_ratios=[1.25, 1]))
    a1.set_xlim(0, 10); a1.set_ylim(0, 6); a1.axis('off')
    a1.add_patch(FancyBboxPatch((0.2, 0.3), 0.6, 5.2, boxstyle='square,pad=0', fc='#d9d8d2', ec=BASELINE))
    a1.text(0.5, 5.7, '冷壁\nT_wall', ha='center', fontsize=9, color=INK2)
    y = np.linspace(0.4, 5.4, 200)
    xw = 0.8 + 3.0 * (1 - np.exp(-(y - 0.4) / 1.2)) ** 0.0 * 0 + 0.8
    xs = np.linspace(0.8, 9.6, 300)
    prof = 0.8 + 4.6 * (1 - np.exp(-(xs - 0.8) / 1.4))
    a1.plot(xs, prof, color=BLUE, lw=2)
    a1.text(9.6, 5.62, 'C_w（主流水汽濃度）', ha='right', fontsize=9, color=BLUE)
    a1.text(0.95, 0.55, 'C_sat(T_wall)', fontsize=9, color=BLUE)
    a1.axvspan(0.8, 3.4, ymin=0.05, ymax=0.92, color=YELLOW, alpha=0.12)
    a1.text(2.1, 3.1, '濃度邊界層\n厚度 δ_c', ha='center', fontsize=9, color=INK2)
    for yy in (1.6, 2.6, 3.6):
        a1.annotate('', (0.85, yy), (2.9, yy), arrowprops=dict(arrowstyle='->', color=RED, lw=1.3))
    a1.text(4.0, 0.95, "壁面凝結通量：\nṁ'' = −ρD/(1−ω_w)·∂ω/∂n|_w\n     ≈ k_m·(C_w − C_sat)",
            fontsize=9.5, color=RED, fontweight='bold', va='center')
    a1.text(1.95, 1.15, '← 凝結通量\n（流向壁面）', ha='center', fontsize=8.5, color=RED)
    a1.text(4.0, 3.0, '要解的方程（主流＋邊界層）：\n'
            '連續：∇·(ρu) = 0\n'
            '動量（N–S）：ρ(∂u/∂t + u·∇u) = −∇p + μ∇²u + ρg\n'
            '水汽：∂(ρω)/∂t + ∇·(ρuω) = ∇·(ρD∇ω)\n'
            '能量：含凝結潛熱與壁面熱傳\n\n'
            'k_m = Sh·D / L，Sh = f(Re 或 Gr, Sc)\n'
            '＝ 把上面這組解「包裝」成一個係數',
            fontsize=9, color=INK, va='center')
    title(a1, '(a) k_m 是 N–S＋物種＋能量方程在壁面邊界層的解')

    P = np.linspace(1.0, 2.4, 50)                   # atm
    a2.plot(P, 1 / P, color=BLUE, lw=2, label='D ∝ 1/P（擴散係數）')
    a2.plot(P, 1 / P, color=AQUA, lw=1.4, ls='--', label='ν ∝ 1/P（動黏度）')
    a2.plot(P, np.ones_like(P), color=INK2, lw=1.6, label='Sc = ν/D：與壓力無關')
    a2.plot(P, P ** 2, color=RED, lw=2, label='Gr ∝ ρ² ∝ P²（自然對流）')
    a2.axvspan(1.70, 2.13, color=YELLOW, alpha=0.15)
    a2.text(1.915, 4.2, '本裝置\n錶壓 0.72–1.17', ha='center', fontsize=8.5, color=INK2)
    a2.set_xlabel('絕對壓（atm）'); a2.set_ylabel('相對於 1 atm 的倍數')
    a2.legend(frameon=False, fontsize=8.5, loc='upper left'); a2.grid(alpha=0.6)
    title(a2, '(b) 微正壓不改變方程，只改變各無因次數')
    D_mix, d_h, d_c = D_water_mix(303.15, 2.203 / 1.033)
    RESULTS['diffusion'] = dict(D_h2o_h2_1atm=round(fuller_D(303.15, 1, 18.015, 2.016, 13.1, 6.12), 3),
                                D_h2o_co2_1atm=round(fuller_D(303.15, 1, 18.015, 44.01, 13.1, 26.9), 3),
                                D_mix_2p13atm=round(D_mix, 3))
    save(fig, 'A15_boundary_layer.png')


def fig_supply_vs_flux():
    """加壓段取樣管：通量公式估的凝結量 vs 質量平衡上限（假設值標在圖上）。"""
    d_cm, L_cm, Tw, t_vent = 0.4, 100.0, 25.0, 30.0
    P_atm = 2.203 / 1.033
    D_mix, *_ = D_water_mix(303.15, P_atm)
    km = 3.66 * D_mix / d_cm                                         # cm/s，層流完全發展
    dC = (psat(30.0) - psat(Tw)) * M_W / (R_GAS * 303.15) * 1e-6        # Pa·(g/mol)/(J/mol) = g/m³ → g/cm³
    flux = km * dC                                                   # g/(cm²·s)
    area = np.pi * d_cm * L_cm
    m_flux = flux * area * t_vent * 1000                             # mg
    n_gas = 0.6 * KGF * 1e-3 / (R_GAS * 303.15)                      # mol（排 0.6 kgf/cm²、頭空 1 L）
    y_w = psat(30.0) / (1.17 * KGF + ATM_PA)
    m_vap = n_gas * y_w * M_W * 1000                                 # mg
    m_cap = m_vap * (1 - psat(Tw) / psat(30.0))                      # 超過壁溫飽和的部分才可能凝結
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 4.0), gridspec_kw=dict(width_ratios=[1, 1.2]))
    names = ['通量公式 × 管壁面積 × 排氣時間', '排出氣體裡的全部水汽', '質量平衡上限\n（超過 25 °C 飽和的部分）']
    vals = [m_flux, m_vap, m_cap]
    a1.barh(names, vals, color=[RED, MUTED, AQUA], alpha=0.85)
    a1.set_xscale('log')
    for i, v in enumerate(vals):
        a1.text(v * 1.15, i, '%.1f mg' % v, va='center', fontsize=9.5)
    a1.set_xlim(0.5, 400); a1.invert_yaxis()
    a1.set_xlabel('每次排氣（mg，對數軸）')
    title(a1, '(a) 每次排氣：通量公式高估 %.0f 倍' % (m_flux / m_cap))
    a2.axis('off')
    a2.text(0.0, 0.98, '假設（現場數值待確認）', fontsize=10, fontweight='bold', va='top')
    a2.text(0.0, 0.86,
            '・加壓段取樣管：內徑 %.0f mm、長 %.0f m、壁溫 %.0f °C\n'
            '・排氣 0.6 kgf/cm²、頭空 1.00 L、排氣時間 %.0f 秒\n'
            '・水汽在 H2:CO2 = 4:1 中的擴散係數（Fuller＋Blanc）：\n'
            '    2.13 atm、30 °C 下 D = %.3f cm²/s\n'
            '・層流完全發展 Sh = 3.66 → k_m = %.2f cm/s\n'
            "・ṁ'' = k_m·(C_w − C_sat) = %.1e g/(cm²·s)\n\n"
            '判讀：通量公式假設主流濃度一直維持 C_w；\n'
            '但排出的氣體總共只帶 %.1f mg 水汽，\n'
            '能凝結的最多 %.1f mg → 凝結量由「供應」決定，\n'
            '估「會積多少水」用質量平衡即可，不必解 N–S。\n'
            '只有要知道「凝在哪一段」時才需要流場。'
            % (d_cm * 10, L_cm / 100, Tw, t_vent, D_mix, km, flux, m_vap, m_cap),
            fontsize=9.3, va='top', color=INK2, linespacing=1.55)
    RESULTS['supply'] = dict(D_mix=round(D_mix, 3), km=round(km, 2), flux=float('%.2e' % flux),
                             m_flux_mg=round(m_flux, 1), m_vap_mg=round(m_vap, 2), m_cap_mg=round(m_cap, 2))
    save(fig, 'A16_supply_vs_flux.png')


def vent_sim(r, P1, P2, gam=1.374, n_steps=4000, t_end_tau=6.0):
    """0 維排氣：看壓力錶排到 P2 就關閥（壓力控制，符合現場操作）。
    排氣流率固定為「等溫時剛好 t_v 排完」的速率；與器壁／液面熱交換 dT/dt = (T_w − T)/τ_h。
    時間以 τ_h 為單位，r = t_v/τ_h。
    開放系統能量平衡（流出不帶熱進來）：dT/dt = (γ−1)·T·(ṅ/n) + (T_w − T)/τ_h。
    ⚠ 若改成「排固定莫耳數」，絕熱時最終壓力會低於 P2、溫度低於下面的絕熱極限
      —— 第一版就是這樣寫錯，算出比絕熱極限還冷的不可能值。
    水汽莫耳分率在排氣中不變（不計排氣中的蒸發＝過飽和的上限）。"""
    Tw = 303.15
    t_end = max(t_end_tau, 3 * r)
    # 步長要解析排氣本身（≤ t_v/200），否則一步就衝過 P2、算出比絕熱極限還冷的值
    n_steps = max(n_steps, int(t_end / (r / 200)) + 1)
    t = np.linspace(0, t_end, n_steps)
    dt = t[1] - t[0]
    n1 = 1.0
    n = np.empty_like(t); T = np.empty_like(t)
    n[0], T[0] = n1, Tw
    rate = (n1 - P2 / P1) / r
    open_ = True
    for i in range(1, len(t)):
        if open_ and P1 * (n[i - 1] / n1) * (T[i - 1] / Tw) <= P2:
            open_ = False                              # 壓力到了就關閥
        ndot = -rate if open_ else 0.0
        n[i] = n[i - 1] + ndot * dt
        T[i] = T[i - 1] + dt * ((gam - 1) * T[i - 1] * ndot / n[i - 1] + (Tw - T[i - 1]))
    P = P1 * (n / n1) * (T / Tw)
    y_w = psat(30.0) / P1
    S = y_w * P / psat(T - 273.15)
    return t, T, P, S


def fig_vent_cooling():
    P1 = 1.17 * KGF + ATM_PA
    cases = [('排到錶壓 0.57（排 0.6）', 0.57 * KGF + ATM_PA, BLUE),
             ('排到大氣壓（全排）', ATM_PA, RED)]
    rs = np.geomspace(0.01, 100, 17)
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(14, 4.2))
    out = {}
    for name, P2, col in cases:
        Tmin, Smax = [], []
        for r in rs:
            _, T, _, S = vent_sim(r, P1, P2, n_steps=3000)
            Tmin.append(T.min() - 273.15); Smax.append(S.max())
        a1.plot(rs, Tmin, color=col, lw=2, marker='o', ms=3, label=name)
        a2.plot(rs, Smax, color=col, lw=2, marker='o', ms=3, label=name)
        Tad = 303.15 * (P2 / P1) ** ((1.374 - 1) / 1.374) - 273.15
        a1.axhline(Tad, color=col, lw=0.8, ls=':')
        a1.text(rs[-1], Tad + 1, '絕熱極限 %.0f °C' % Tad, ha='right', fontsize=8, color=col)
        out[name] = dict(T_adiabatic=round(Tad, 1),
                         Tmin_r=[(round(r, 2), round(v, 1)) for r, v in zip(rs[::6], Tmin[::6])])
    for ax in (a1, a2):
        ax.set_xscale('log'); ax.grid(alpha=0.6)
        ax.set_xticks([0.01, 0.1, 1, 10, 100]); ax.set_xticklabels(['0.01', '0.1', '1', '10', '100'])
        ax.set_xlabel('排氣時間 / 熱交換時間常數（t_v / τ_h）')
    a1.axhline(30, color=INK2, lw=0.8, ls='--'); a1.text(0.012, 30.6, '液溫 30 °C', fontsize=8, color=INK2)
    a1.set_ylabel('排氣過程中頭空最低溫度（°C）')
    a1.legend(frameon=False, fontsize=8.5, loc='center right')
    title(a1, '(a) 排得越快（比值越小）越接近絕熱')
    a2.axhline(1, color=INK2, lw=0.9, ls='--')
    a2.text(0.012, 1.05, 'S = 1：開始凝結（起霧）', fontsize=8, color=INK2)
    a2.set_yscale('log'); a2.set_ylabel('最大過飽和比 S = p_w / P_sat(T)')
    a2.legend(frameon=False, fontsize=8.5, loc='upper right')
    title(a2, '(b) 過飽和比（不計排氣中蒸發＝上限）')
    for r, ls in ((0.1, '-'), (1.0, '--'), (10.0, ':')):
        t, T, P, S = vent_sim(r, P1, cases[0][1], t_end_tau=14.0)
        a3.plot(t, T - 273.15, color=BLUE, lw=1.6, ls=ls, label='t_v/τ_h = %g' % r)
    a3.set_xlim(0, 14); a3.axhline(30, color=INK2, lw=0.8, ls='--')
    a3.set_xlabel('時間（以 τ_h 為單位）'); a3.set_ylabel('頭空溫度（°C）')
    a3.legend(frameon=False, fontsize=8.5, loc='lower right'); a3.grid(alpha=0.6)
    title(a3, '(c) 排 0.6 的溫度歷程；關閥後回溫＝壓力回升')
    fig.suptitle('排氣膨脹降溫（0 維能量平衡；γ = 1.374，H2:CO2 = 4:1）：τ_h 未知，所以用比值 t_v/τ_h 掃過所有情況',
                 x=0.01, ha='left', fontweight='bold', fontsize=10.5, y=1.04)
    RESULTS['vent'] = out
    save(fig, 'A17_vent_cooling.png')


def main():
    only = [a for a in sys.argv[1:] if a.startswith('fig_')]
    for f in (fig_segment, fig_orp, fig_model_curvature, fig_profile, fig_bootstrap, fig_alg2,
              fig_alg3, fig_stoich, fig_residual, fig_pump, fig_identifiability, fig_mechanistic,
              fig_softsensor, fig_tagger, fig_boundary_layer, fig_supply_vs_flux, fig_vent_cooling):
        if only and f.__name__ not in only:
            continue
        print(f.__name__)
        f()
    print('\n== 關鍵數字 ==')
    for k, v in RESULTS.items():
        print(k, v)


if __name__ == '__main__':
    main()
