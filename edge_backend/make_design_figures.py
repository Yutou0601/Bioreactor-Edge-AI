# -*- coding: utf-8 -*-
"""產生「實驗設計決策」的統計圖 → docs/figures/
回答三個問題：(1) 循環總時間多久 (2) 排氣壓力該不該更低 (3) K-means 分群。
只用可信訊號（壓力/ORP）。
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import rcParams
from scipy import stats
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import co2_separation_analysis as sep

OUT = '../docs/figures'
os.makedirs(OUT, exist_ok=True)

BLUE, RED, AQUA, YELLOW = '#2a78d6', '#e34948', '#1baf7a', '#eda100'
VIOLET = '#4a3aa7'
SURFACE, INK, INK2, MUTED = '#fcfcfb', '#0b0b0b', '#52514e', '#898781'
GRID, BASELINE = '#e1e0d9', '#c3c2b7'

rcParams['font.family'] = 'Microsoft JhengHei'
rcParams['axes.unicode_minus'] = False
for k, v in {'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
             'text.color': INK, 'axes.labelcolor': INK2, 'xtick.color': MUTED, 'ytick.color': MUTED,
             'axes.edgecolor': BASELINE, 'grid.color': GRID, 'font.size': 10, 'axes.titlesize': 11,
             'savefig.dpi': 200, 'savefig.bbox': 'tight'}.items():
    rcParams[k] = v


def style(ax, title=None, xlabel=None, ylabel=None):
    if title: ax.set_title(title, color=INK, fontweight='bold', loc='left', pad=10)
    if xlabel: ax.set_xlabel(xlabel)
    if ylabel: ax.set_ylabel(ylabel)
    ax.grid(True, linewidth=0.6, alpha=0.9); ax.set_axisbelow(True)
    for s in ('top', 'right'): ax.spines[s].set_visible(False)
    return ax


print('載入...')
DF = sep.load_folder_combined('Testing_data/0301-0416_無循環與有循環_5mins').sort_values('timestamp').reset_index(drop=True)
RP = DF['reactor_pressure'].values.astype(float)
BOUNDS = np.concatenate([[0], np.where(np.diff(RP, prepend=RP[0]) > 0.03)[0], [len(DF)-1]])

wins = []
for a, b in zip(BOUNDS[:-1], BOUNDS[1:]):
    seg = DF.iloc[a+1:b]
    if len(seg) < 200: continue
    p = seg['reactor_pressure'].values.astype(float)
    if p[0]-p[-1] < 0.05: continue
    wins.append(dict(seg=seg, dur=len(seg)/60, p0=p[0], pend=p[-1], drop=p[0]-p[-1],
                     rate=(p[0]-p[-1])/(len(seg)/60), orp=np.nanmean(seg['ORP (mV)'].values.astype(float))))
W = pd.DataFrame(wins)
med = W.rate.median(); mad = stats.median_abs_deviation(W.rate, scale='normal')
CLEAN = W[np.abs((W.rate-med)/mad) <= 3].reset_index(drop=True)
RATE = CLEAN.rate.median()
FEED = 1.2   # 進氣目標
targets = [1.1, 1.0, 0.9, 0.8, 0.71]


# ── 圖D1：循環時間指引 ──────────────────────────────
def figD1():
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    # 疊上實際衰減曲線（對齊補氣峰，取乾淨的長週期）
    long_cycles = CLEAN[CLEAN.dur > 15].nlargest(12, 'dur')
    for _, row in long_cycles.iterrows():
        seg = row['seg']; p = seg['reactor_pressure'].values.astype(float)
        t = np.arange(len(p))/60
        ax.plot(t, p, lw=0.9, color=BLUE, alpha=0.22)
    # 用中位速率從 1.2 畫參考線
    t_line = np.linspace(0, 35, 100)
    ax.plot(t_line, FEED - RATE*t_line, lw=2.4, color=RED, zorder=5,
            label=f'中位速率參考線 ({RATE:.4f} kg/cm²/hr)')
    ax.axhline(FEED, color=INK2, lw=1, ls=':')
    ax.annotate('進氣至 1.2', xy=(0.5, FEED), xytext=(0.5, FEED+0.02), color=INK, fontsize=9)

    for tgt in targets:
        tt = (FEED-tgt)/RATE
        ax.axhline(tgt, color=BASELINE, lw=0.8, ls='--')
        ax.scatter([tt], [tgt], s=45, color=RED, zorder=6, edgecolor=SURFACE, linewidth=1.2)
        ax.annotate(f'排氣至 {tgt:.2f} → {tt:.0f} hr', xy=(tt, tgt), xytext=(tt+0.6, tgt+0.008),
                    color=INK, fontsize=9)
    style(ax, '圖D1  進氣至 1.2 後，循環到各排氣目標需要多久',
          '循環時間（小時）', '反應槽壓力 (kg/cm²)')
    ax.set_ylim(0.6, 1.26); ax.set_xlim(0, 35)
    ax.legend(frameon=False, loc='upper right', fontsize=9)
    fig.text(0, -0.04, '淡藍線＝12 條實際衰減曲線（起始 ~1.08）；紅線＝以中位速率從 1.2 外推。'
             '註：進氣到 1.2 起始溶解驅動力更大、初期實際會掉更快，故上列時間偏保守（偏長）。'
             '速率取自歷史資料，反映當時的循環設定。', fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/figD1_circulation_time.png'); plt.close(fig)
    print('  D1 ok')


# ── 圖D2：排氣目標壓力的權衡 ───────────────────────
def figD2():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.3))
    wins_win = [FEED-t for t in targets]
    times = [(FEED-t)/RATE for t in targets]
    levels = [int((FEED-t)/0.01) for t in targets]
    labels = [f'{t:.2f}' for t in targets]
    x = np.arange(len(targets))

    bars = ax1.bar(x, levels, color=BLUE, width=0.62)
    ax1.axhline(20, color=RED, lw=1.4, ls='--')
    ax1.annotate('20 格 (=窗口 0.2)\n訊號偏窄的參考線', xy=(0.1, 21), color=RED, fontsize=9, fontweight='bold')
    for xi, lv in zip(x, levels):
        ax1.annotate(f'{lv}', xy=(xi, lv), xytext=(0, 3), textcoords='offset points',
                     ha='center', color=INK, fontsize=9.5, fontweight='bold')
    ax1.set_xticks(x); ax1.set_xticklabels(labels)
    style(ax1, '圖D2a  排氣目標 → 訊號窗口（解析度格數）', '排氣目標壓力 (kg/cm²)', '解析度格數 (窗口/0.01)')

    ax2.bar(x, times, color=AQUA, width=0.62)
    for xi, tv in zip(x, times):
        ax2.annotate(f'{tv:.0f} hr', xy=(xi, tv), xytext=(0, 3), textcoords='offset points',
                     ha='center', color=INK, fontsize=9.5, fontweight='bold')
    ax2.set_xticks(x); ax2.set_xticklabels(labels)
    style(ax2, '圖D2b  排氣目標 → 每循環所需時間', '排氣目標壓力 (kg/cm²)', '循環時間（小時）')

    fig.text(0, -0.05, '權衡：排氣到 1.0 只有 19 格訊號但省時（14 hr）；排氣到 0.9 訊號提升到 29 格、但耗時增 50%（20 hr）。'
             '\n建議：若追求訊號品質，排氣目標設在 0.9 附近較佳；若追求循環次數，1.0 較快。最終值建議與洪博確認。',
             fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/figD2_vent_tradeoff.png'); plt.close(fig)
    print('  D2 ok')


# ── 圖D3：K-means 分群（循環消耗氣體量，不分溶解/消耗）──
def figD3():
    feat = CLEAN[['rate', 'dur', 'orp']].copy()
    X = StandardScaler().fit_transform(feat)
    km = KMeans(2, n_init=20, random_state=0).fit(X)
    lab = km.labels_
    # 讓 0=快 1=慢
    if CLEAN.rate[lab == 0].median() < CLEAN.rate[lab == 1].median():
        lab = 1 - lab
    cols = np.where(lab == 0, YELLOW, VIOLET)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4), gridspec_kw={'width_ratios': [1.3, 1]})
    ax1.scatter(CLEAN.dur, CLEAN.rate, s=55, c=cols, alpha=0.85, edgecolor=SURFACE, linewidth=0.8)
    ax1.annotate('快群\n(週期短、ORP 高)', xy=(15, 0.024), color=YELLOW, fontsize=10, fontweight='bold')
    ax1.annotate('慢群\n(週期長、ORP 低)', xy=(9, 0.0122), color=VIOLET, fontsize=10, fontweight='bold')
    style(ax1, '圖D3a  K-means 分群：循環消耗氣體的快慢', '週期長度（小時）', '壓力下降速率 (kg/cm²/hr)')

    # 各群「到排氣目標 1.0 所需時間」的差異
    fast_rate = CLEAN.rate[lab == 0].median()
    slow_rate = CLEAN.rate[lab == 1].median()
    tgt = 1.0; win = FEED - tgt
    tf, ts = win/fast_rate, win/slow_rate
    ax2.bar([0, 1], [tf, ts], color=[YELLOW, VIOLET], width=0.6)
    for xi, tv in zip([0, 1], [tf, ts]):
        ax2.annotate(f'{tv:.1f} hr', xy=(xi, tv), xytext=(0, 3), textcoords='offset points',
                     ha='center', color=INK, fontsize=10, fontweight='bold')
    ax2.set_xticks([0, 1]); ax2.set_xticklabels(['快群', '慢群'])
    style(ax2, '圖D3b  同樣排氣到 1.0，兩群耗時差 1.5 倍', None, '所需時間（小時）')

    fig.text(0, -0.05, f'資料裡自然分成快/慢兩群（快群速率為慢群的約 {fast_rate/slow_rate:.1f} 倍，與菌群成熟度 ORP 相關）。'
             '\n設計含意：菌群狀態會讓下降快慢變動 → 用「固定循環時間」排氣，終點壓力會不一致；'
             '用「壓力閾值」排氣（現行做法）比較穩定。', fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/figD3_kmeans_clusters.png'); plt.close(fig)
    print('  D3 ok')


if __name__ == '__main__':
    print('產生設計決策圖 →', os.path.abspath(OUT))
    figD1(); figD2(); figD3()
    print('完成')
