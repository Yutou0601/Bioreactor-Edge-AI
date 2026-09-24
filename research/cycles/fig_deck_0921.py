# -*- coding: utf-8 -*-
"""簡報專用的圖（2026-09-21）。與報告用圖分開，不要混用。

════════════════════════════════════════════════════════════════════════
為什麼不能把報告的圖直接放進簡報

  報告圖是照 A4 版面設計的：寬 14.5 吋、字級 9pt，列印在 160mm 寬剛好。
  同一張放進 16:9 投影片貼到 26cm 寬時，縮放比只有 0.71，
  字高剩下約 6.4pt —— 投影出來看不清楚。三到四個面板更是一頁看不完。

  所以簡報圖另做一套，規則是：

    1. **一張圖一個訊息**，面板最多兩個
    2. 圖寬 12 吋（= 30.5cm），貼到 26cm 時縮放 0.85，字級幾乎不損失
    3. 基礎字級 15pt、標題 19pt、重點標註 17pt
    4. 線加粗、點加大；說明文字盡量搬到投影片本文，圖上只留必要的
    5. 用顏色與位置引導視線，不要靠圖例讓人對照

輸出 -> docs/analysis_charts_3batch/deck1~6_*.png
"""
import datetime as dt
import glob
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402
from matplotlib import rcParams                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, YELLOW, AQUA, RED, INK, INK2, MUTED, BASELINE, OUT)

# ── 簡報用的字級（比報告大一倍以上）──
rcParams.update({
    'font.size': 15, 'axes.titlesize': 19, 'axes.labelsize': 16,
    'xtick.labelsize': 14, 'ytick.labelsize': 14, 'legend.fontsize': 14,
})
FIGW = 12.0          # 吋。貼到投影片 26cm 時縮放 0.85


def style(ax, title=None, xlabel=None, ylabel=None):
    if title:
        ax.set_title(title, color=INK, fontweight='bold', loc='left', pad=12)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    return ax


def save(fig, name):
    p = os.path.join(OUT, name + '.png')
    fig.savefig(p)
    plt.close(fig)
    print('  ->', name + '.png')


# ═══════════════════════════════════════════════════════════════
def deck1_sensor():
    """氣體讀數什麼時候可信。左：一次排氣的實際讀數；右：補氣稀釋檢定。"""
    from core.cycle_store import read_series_full
    d = os.path.join(REPO, 'research', 'Testing_data', '202607至08最新循環研究')
    ts, hh, p, temp, co2, ch4 = read_series_full(sorted(glob.glob(d + '/*.csv')))
    g = lambda v: np.array([x if x is not None else 0.0 for x in v], float)
    co2, ch4 = g(co2), g(ch4)
    i = min(range(len(ts)),
            key=lambda k: abs((ts[k] - dt.datetime(2026, 7, 30, 9, 6)).total_seconds()))

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(FIGW, 5.0),
                                 gridspec_kw={'wspace': 0.26})
    mins = np.arange(-6, 10)
    sl = slice(i - 6, i + 10)
    a1.plot(mins, ch4[sl], color=AQUA, lw=3.2, marker='o', ms=8, label='甲烷')
    a1.plot(mins, co2[sl], color=YELLOW, lw=3.2, marker='s', ms=7, label='二氧化碳')
    a1.axvspan(-0.5, 1.5, color=RED, alpha=0.13, lw=0)
    a1.axvline(0, color=RED, lw=2.4, ls='--')
    a1.set_ylim(-4, 70)
    a1.annotate('排氣閥一開，讀數才跳上來', xy=(0.6, 35), xytext=(1.6, 62),
                color=RED, fontsize=16, fontweight='bold', ha='left',
                arrowprops=dict(arrowstyle='->', color=RED, lw=2))
    # 放在兩條曲線都已走平的右下空白區，避免橫跨紅線與陡升段
    a1.text(2.6, 0.5, '排氣前讀數接近 0：那是管路殘氣，\n不是容器裡的氣',
            color=INK2, fontsize=13.5, ha='left', va='bottom')
    a1.legend(loc='center right', frameon=False)
    style(a1, 'a　排氣前後的實際讀數', '距排氣幾分鐘', '濃度 (%)')

    # 右：補氣稀釋檢定
    from co2_exhaustion_test import ATM, AUTO, GAPH, RISE, load
    ts2, hh2, p2, c2, m2 = load(AUTO)
    dx, dP = [], []
    for j in range(1, len(ts2)):
        if (p2[j] - p2[j - 1] > RISE and hh2[j] - hh2[j - 1] < GAPH
                and m2[j] > 5 and m2[j - 1] > 5):
            dx.append(np.log(m2[j] / m2[j - 1]))
            dP.append(np.log((p2[j] + ATM) / (p2[j - 1] + ATM)))
    dx, dP = np.array(dx), np.array(dP)
    A = np.vstack([np.ones(len(dP)), dP]).T
    b, *_ = np.linalg.lstsq(A, dx, rcond=None)
    a2.scatter(dP, dx, s=46, color=MUTED, alpha=0.55, lw=0)
    xs = np.linspace(0, dP.max() * 1.05, 20)
    a2.plot(xs, -xs, color=RED, lw=3.2, ls='--')
    a2.plot(xs, b[0] + b[1] * xs, color=BLUE, lw=3.2)
    a2.axhline(0, color=BASELINE, lw=1.2)
    a2.text(xs[-1] * 0.98, -xs[-1] * 0.98, '真的量到容器裡的氣\n應該落在這條線上 ',
            color=RED, fontsize=14.5, ha='right', va='top')
    a2.text(xs[-1] * 0.5, 0.06, '實際量到的：幾乎沒有反應',
            color=BLUE, fontsize=16, fontweight='bold', ha='center', va='bottom')
    a2.set_ylim(-0.42, 0.20)
    style(a2, 'b　補氣時，甲烷有沒有被稀釋', '壓力變化（取對數）', '甲烷濃度變化（取對數）')
    save(fig, 'deck1_sensor')


# ═══════════════════════════════════════════════════════════════
def deck2_hydrogen():
    """★核心圖。左：CO2 vs H2 散點與 1:4 線；右：比值分布。"""
    from feed_ratio_drift import (FEED_RATIO, P_H2O_KPA, KGF_TO_KPA, ATM,
                                  find_vents, load_with_gas)
    ts, hh, p, orp, ph, co2, ch4 = load_with_gas()
    ev = find_vents(ts, hh, p, co2, ch4)
    C, Hh, R = [], [], []
    for i in ev:
        Pa = p[i - 1] + ATM
        f = P_H2O_KPA / (Pa * KGF_TO_KPA) * 100
        h2 = 100 - co2[i] - ch4[i] - f
        if h2 <= 1:
            continue
        C.append(co2[i]); Hh.append(h2); R.append(co2[i] / h2)
    C, Hh, R = np.array(C), np.array(Hh), np.array(R)

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(FIGW, 5.2),
                                 gridspec_kw={'wspace': 0.26, 'width_ratios': [1.1, 1]})
    xs = np.linspace(0, max(Hh) * 1.08, 20)
    a1.fill_between(xs, FEED_RATIO * xs, max(C) * 1.55, color=RED, alpha=0.07, lw=0)
    a1.plot(xs, FEED_RATIO * xs, color=RED, lw=3.4, ls='--')
    a1.scatter(Hh, C, s=95, color=BLUE, alpha=0.82, lw=0, zorder=4)
    # ⚠ 先把座標拉高再放字，否則字會落在點雲裡
    a1.set_xlim(0, xs[-1])
    a1.set_ylim(0, max(C) * 1.55)
    # 紅線「下方」幾乎沒有資料點，紅線的說明放那裡才不會壓到點
    a1.text(xs[-1] * 0.97, max(C) * 0.035,
            '只有產甲烷時，應該落在這條線上', color=RED, fontsize=14.5,
            ha='right', va='bottom')
    a1.text(xs[-1] * 0.50, max(C) * 1.50,
            '幾乎每一次都在線的上方\n= 氫氣比二氧化碳消失得更快',
            color=INK, fontsize=16.5, fontweight='bold', ha='center', va='top')
    style(a1, 'a　每次排氣量到的兩種氣體', '剩下的氫氣 (%)', '剩下的二氧化碳 (%)')

    hi = float(np.percentile(R, 90))
    a2.hist(np.clip(R, None, hi), bins=np.linspace(0, hi, 18),
            color=BLUE, alpha=0.85, lw=0)
    a2.set_ylim(0, a2.get_ylim()[1] * 1.42)
    top = a2.get_ylim()[1]
    a2.axvline(FEED_RATIO, color=RED, lw=3.2, ls='--')
    a2.annotate('進料比 0.25', xy=(FEED_RATIO, top * 0.52),
                xytext=(hi * 0.30, top * 0.93), color=RED, fontsize=15.5,
                fontweight='bold', ha='left', va='top',
                arrowprops=dict(arrowstyle='->', color=RED, lw=2))
    a2.axvline(np.median(R), color=INK, lw=3.2)
    a2.annotate('實際中位 %.2f\n= 進料比的 %.1f 倍' % (np.median(R), np.median(R) / FEED_RATIO),
                xy=(np.median(R), top * 0.30), xytext=(hi * 0.38, top * 0.62),
                color=INK, fontsize=15.5, fontweight='bold', ha='left', va='top',
                arrowprops=dict(arrowstyle='->', color=INK, lw=2))
    style(a2, 'b　二氧化碳 ÷ 氫氣', '比值', '排氣次數')
    save(fig, 'deck2_hydrogen')


# ═══════════════════════════════════════════════════════════════
def deck3_co2cut():
    """碳源斷掉，壓降照舊。上：兩種氣體；下：每循環速率。"""
    from co2_exhaustion_test import (AUTO, CUT_A, CUT_B, descents, load,
                                     perm_median_p)
    ts, hh, p, c, m = load(AUTO)
    segs = descents(hh, p)
    t0 = [ts[s] for s, e in segs]
    rate = np.array([(p[s] - p[e]) / (hh[e] - hh[s]) for s, e in segs])
    grp = np.array([0 if ts[s].date() <= CUT_A else (1 if ts[s].date() >= CUT_B else -1)
                    for s, e in segs])
    SPLIT = dt.datetime(2026, 8, 23, 12)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(FIGW, 6.6), sharex=True,
                                 gridspec_kw={'hspace': 0.22, 'height_ratios': [1, 1.15]})
    for ax in (a1, a2):
        ax.axvline(SPLIT, color=RED, lw=2.4, ls='--')
        ax.axvspan(SPLIT, ts[-1], color=RED, alpha=0.06, lw=0)

    a1.plot(ts, m, color=AQUA, lw=2.4, label='甲烷（產物）')
    a1.plot(ts, c, color=YELLOW, lw=2.4, label='二氧化碳（原料）')
    a1.fill_between(ts, 0, c, color=YELLOW, alpha=0.2, lw=0)
    a1.set_ylim(-2, 78)
    a1.legend(loc='upper left', frameon=False, ncol=2)
    a1.text(SPLIT, 74, ' 原料沒了 ', color=RED, fontsize=16, fontweight='bold',
            ha='left', va='top')
    style(a1, 'a　容器裡的兩種氣體', None, '佔氣體的 %')

    for g, col, lab in ((0, MUTED, '還有原料'), (1, BLUE, '沒有原料了')):
        ix = grp == g
        a2.scatter(np.array(t0)[ix], rate[ix], s=62, color=col, alpha=0.8, lw=0,
                   label='%s（%d 個循環）' % (lab, ix.sum()))
    for g, col, x0, x1 in ((0, MUTED, ts[0], SPLIT), (1, BLUE, SPLIT, ts[-1])):
        v = np.median(rate[grp == g])
        a2.hlines(v, x0, x1, color=col, lw=4, zorder=5)
        a2.text(x0 + (x1 - x0) * 0.13, v + 0.010, '%.4f' % v, color=col,
                fontsize=18, fontweight='bold', ha='left', va='bottom')
    a2.set_ylim(0.004, 0.085)
    a2.legend(loc='lower left', frameon=False, ncol=2)
    a2.text(0.5, 0.97, '兩邊一樣高（p = %.2f）——原料沒了，壓力照樣以同樣速度掉'
            % perm_median_p(rate[grp == 0], rate[grp == 1]),
            transform=a2.transAxes, color=INK, fontsize=16.5, fontweight='bold',
            ha='center', va='top')
    style(a2, 'b　每個循環的壓力下降速度', None, 'kg/cm² 每小時')
    import matplotlib.dates as mdates
    a2.xaxis.set_major_locator(mdates.DayLocator(interval=4))
    a2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    save(fig, 'deck3_co2cut')


# ═══════════════════════════════════════════════════════════════
def deck4_shape():
    """壓降曲線幾乎是直線。單一面板。"""
    from shape_clustering import NGRID, descents, load_all, shape, bow
    ts, hh, p, c, m = load_all()
    S = []
    for s, e in descents(hh, p):
        sv, grid = shape(hh, p, s, e)
        if np.all(np.isfinite(sv)):
            S.append(sv)
    S = np.array(S)
    grid = np.linspace(0, 1, NGRID)
    bows = np.array([bow(v, grid) for v in S])
    near = np.abs(bows) < 0.15

    fig, ax = plt.subplots(figsize=(FIGW, 5.6))
    for v in S[near][:200]:
        ax.plot(grid, v, color=MUTED, lw=0.7, alpha=0.13)
    ax.plot(grid, S[near].mean(0), color=BLUE, lw=4.5,
            label='實際的平均形狀（%d 條，佔 %.0f%%）' % (near.sum(), near.mean() * 100))
    ax.plot(grid, 1 - grid, color=INK, lw=3, ls='--', label='完全的直線')
    ax.legend(loc='upper right', frameon=False)
    ax.text(0.30, 0.30, '兩條幾乎重合',
            color=INK, fontsize=19, fontweight='bold', ha='left', va='top')
    ax.text(0.30, 0.20,
            '氣體溶進液體會讓曲線明顯彎曲；\n定速移除才是直線——而洩漏正是定速。',
            color=INK2, fontsize=15, ha='left', va='top')
    ax.set_xlim(0, 1); ax.set_ylim(-0.02, 1.02)
    style(ax, '把每條下降曲線拉成同樣大小後疊起來', '一個循環走完的進度',
          '壓力還剩多少（1 = 剛補完氣）')
    save(fig, 'deck4_shape')


# ═══════════════════════════════════════════════════════════════
def deck5_orp():
    """ORP 是操作訊號。左：補氣當下；右：碳源斷掉前後。"""
    from orp_substrate_vs_activity import (AUTO_A, AUTO_B, auto_descents,
                                           refills, stack_around)
    from ph_orp_discriminator import load_full
    ts, hh, p, orp, ph = load_full()

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(FIGW, 5.2),
                                 gridspec_kw={'wspace': 0.28})
    off, mu, se, n = stack_around(refills(ts, hh, p), hh, orp)
    a1.fill_between(off, mu - 2 * se, mu + 2 * se, color=BLUE, alpha=0.22, lw=0)
    a1.plot(off, mu, color=BLUE, lw=3.4)
    a1.axvline(0, color=RED, lw=2.4, ls='--')
    a1.axhline(0, color=BASELINE, lw=1.2)
    a1.set_ylim(-14, 62)
    a1.text(2, 57, ' 補氣', color=RED, fontsize=16, fontweight='bold',
            ha='left', va='top')
    a1.text(-58, 52, '補氣後 ORP\n立刻跳 +37 mV\n一小時後才回來',
            color=INK, fontsize=15.5, fontweight='bold', ha='left', va='top')
    style(a1, 'a　補氣前後的 ORP（%d 次疊加）' % n, '距補氣幾分鐘', 'ORP 變化 (mV)')

    res = {}
    for lab, (da, db) in (('還有原料', AUTO_A), ('原料斷掉', AUTO_B)):
        ix = np.flatnonzero(np.array([da <= t.date() <= db for t in ts]))
        exc = []
        for s, e in auto_descents(hh, p):
            if not (ix[0] <= s and e <= ix[-1]):
                continue
            t_ = hh[s:e + 1]
            if len(t_) > 20 and t_.std() > 0:
                exc.append(float(np.polyfit(t_ - t_[0], orp[s:e + 1], 1)[0]
                                 * (t_[-1] - t_[0])))
        res[lab] = np.array(exc)
    labs = list(res)
    cols = [MUTED, RED]
    for i, lab in enumerate(labs):
        v = res[lab]
        x = np.full(len(v), i) + np.random.default_rng(i).uniform(-0.13, 0.13, len(v))
        a2.scatter(x, v, s=58, color=cols[i], alpha=0.72, lw=0)
        a2.hlines(np.median(v), i - 0.28, i + 0.28, color=INK, lw=4, zorder=5)
        # 左組的標籤往左、右組的往右，才不會撞到另一組的點雲
        dx, ha = (-0.36, 'right') if i == 0 else (0.36, 'left')
        a2.text(i + dx, np.median(v), '%+.0f mV' % np.median(v), color=INK,
                fontsize=17, fontweight='bold', ha=ha, va='center')
    a2.axhline(0, color=BASELINE, lw=1.2)
    a2.set_xticks(range(2)); a2.set_xticklabels(labs)
    a2.set_xlim(-1.05, 1.75)
    lo, hiy = a2.get_ylim()
    a2.set_ylim(lo - (hiy - lo) * 0.45, hiy)      # 下方留給說明文字
    a2.text(0.5, 0.06, '原料斷掉、產甲烷必須停止的時段，\nORP 照常變化，甚至幅度更大',
            transform=a2.transAxes, color=INK, fontsize=15.5, fontweight='bold',
            ha='center', va='bottom')
    style(a2, 'b　一個循環裡 ORP 走了多少', None, 'mV')
    save(fig, 'deck5_orp')


# ═══════════════════════════════════════════════════════════════
def deck6_pinn():
    """PINN 撈不回已知答案。單一面板。"""
    import curvature_inverse  # noqa: F401  （確保共用樣式已載入）
    from pinn_rb_recovery import LAMBDAS, synth, train_pinn
    T, NP = 6.0, 360
    rb_true = lambda tt: 0.012 * np.exp(-0.7 * tt / T * 3)
    t, P, obs = synth(T, NP, rb_true, 1.4, 0.75, 1.17)
    fig, ax = plt.subplots(figsize=(FIGW, 5.6))
    g = None
    COLS = [BLUE, AQUA, YELLOW, RED]
    for col, lam in zip(COLS, LAMBDAS):
        g, rb_hat, _, _, _, _ = train_pinn(t, obs, T, lam=lam)
        ax.plot(g, rb_hat, color=col, lw=3,
                label='設定 λ=%g' % lam)
    ax.plot(g, rb_true(g * T), color=INK, lw=4.5, ls='--', zorder=6,
            label='真正的答案')
    ax.legend(loc='upper right', frameon=False, ncol=2)
    lo, hiy = ax.get_ylim()
    ax.set_ylim(lo - (hiy - lo) * 0.30, hiy)
    ax.text(0.03, 0.06,
            '同一批資料，只改一個平滑設定，算出來的生物速率就完全不同。\n'
            '而交叉驗證會挑到誤差 87% 的那一個（真正最好的誤差 36%）。',
            transform=ax.transAxes, color=INK, fontsize=15.5, fontweight='bold',
            ha='left', va='bottom')
    style(ax, '拿「答案已知」的假資料測 PINN：撈不回來',
          '一個循環走完的進度', '生物速率 (kg/cm²/hr)')
    save(fig, 'deck6_pinn')


def main():
    print('產生簡報專用圖（字級放大、面板減量）：')
    deck1_sensor()
    deck2_hydrogen()
    deck3_co2cut()
    deck4_shape()
    deck5_orp()
    deck6_pinn()


if __name__ == '__main__':
    main()
