
# -*- coding: utf-8 -*-
"""2026-09-12 明細版日報的圖（對應表 A~F）。

⚠ 資料一律取自 research/cycles/detail_tables.py 的計算函式，與表格
  **共用同一份計算**。圖與表對不上是最糟的狀況——讀的人會兩邊都不信。

⚠ 中文字型（微軟正黑體）沒有下標字元（₂ ₄）與負號，圖上一律寫 CH4／CO2，
  並設 axes.unicode_minus=False。（fig_weekly_0911.py 踩過。）

⚠ 標註一律加白底框。圖上線條密，文字落在資料上就讀不出來——而且是
  「看起來有字但看不清楚」這種不會被回報的壞法。

輸出 → docs/reports/fig_daily_0912/
"""
import datetime as dt
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                    # noqa: E402
import numpy as np                                                 # noqa: E402

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # docs/
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'reports', 'fig_daily_0912')
sys.path.insert(0, os.path.join(REPO, 'research', 'cycles'))
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))

import detail_tables as DT                                         # noqa: E402

COL = {'tau1': '#2E7D32', 'tau5': '#EF6C00', 'tau10': '#1565C0'}


def style():
    plt.rcParams.update({
        'font.sans-serif': ['Microsoft JhengHei', 'Microsoft YaHei',
                            'SimHei', 'DejaVu Sans'],
        'axes.unicode_minus': False,
        'font.size': 10, 'axes.labelsize': 10.5, 'axes.titlesize': 11.5,
        'xtick.labelsize': 9, 'ytick.labelsize': 9, 'legend.fontsize': 9,
        'axes.grid': True, 'grid.alpha': 0.25, 'grid.linewidth': 0.6,
        'axes.spines.top': False, 'axes.spines.right': False,
        'figure.dpi': 110,
    })


def box(c):
    return dict(boxstyle='round,pad=0.34', fc='white', ec=c, alpha=0.93, lw=0.8)


# ── 圖 1（表 B）循環泵的逐分鐘節奏，三批對照 ──────────────────
def fig_pump():
    ts, h, p, co2, ch4 = DT.load(DT.TAU_DIR)
    fig, axes = plt.subplots(3, 1, figsize=(9.2, 7.4), sharex=True)
    for ax, (nm, tau, d0, d1) in zip(axes, DT.BATCHES):
        t2, h2, p2, _, _ = DT.sub(ts, h, p, co2, ch4, d0, d1)
        mu, se, n = DT.minute_profile(t2, h2, p2)
        on, off, gap = DT.pump_window(mu)
        x = np.arange(60)
        ax.axvspan(on, off, color=COL[nm], alpha=0.13, zorder=0)
        ax.errorbar(x, mu, yerr=se, fmt='o-', color=COL[nm], lw=1.3, ms=3.2,
                    capsize=2, elinewidth=0.8)
        ax.axhline(0, color='#888', lw=0.8)
        ax.set_ylabel('每分鐘壓降\n(kg/cm²)')
        ax.set_title('%s　宣稱 τ = %d 分／小時　→　實測泵窗 第 %d–%d 分（%d 分鐘）'
                     % (nm, tau, on, off, gap), loc='left', fontsize=10.5)
        ax.annotate('泵開', xy=(on, mu[on]), xytext=(on + 6, mu[on] * 0.92),
                    fontsize=9, color=COL[nm], fontweight='bold',
                    bbox=box(COL[nm]),
                    arrowprops=dict(arrowstyle='->', color=COL[nm], lw=1.1))
        ax.annotate('泵停', xy=(off, mu[off]), xytext=(off + 6, mu[off] * 1.6),
                    fontsize=9, color='#C62828', fontweight='bold',
                    bbox=box('#C62828'),
                    arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.1))
    axes[-1].set_xlabel('小時內的第幾分鐘')
    axes[-1].set_xlim(-1, 60)
    fig.suptitle('圖 1　循環泵的節奏：泵運轉時間＝該批的 τ（對應表 B）',
                 fontsize=12, y=0.995)
    fig.tight_layout()
    return fig, 'fig1_泵節奏三批對照'


# ── 圖 2（表 F）τ 槓桿 ────────────────────────────────────────
def fig_tau():
    ts, h, p, co2, ch4 = DT.load(DT.TAU_DIR)
    taus, gaps, rates = [], [], []
    for nm, tau, d0, d1 in DT.BATCHES:
        t2, h2, p2, _, _ = DT.sub(ts, h, p, co2, ch4, d0, d1)
        segs = DT.descents(h2, p2)
        amp = np.array([p2[s] - p2[e] for s, e in segs])
        dur = np.array([h2[e] - h2[s] for s, e in segs])
        mu, _, _ = DT.minute_profile(t2, h2, p2)
        on, off, gap = DT.pump_window(mu)
        taus.append(tau)
        gaps.append(gap)
        rates.append(np.median(amp / dur))

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.4, 3.9))
    a1.plot([0, 11], [0, 11], '--', color='#999', lw=1.2, zorder=0)
    for t_, g_, nm in zip(taus, gaps, [b[0] for b in DT.BATCHES]):
        a1.plot(t_, g_, 'o', color=COL[nm], ms=11)
        a1.annotate(nm, xy=(t_, g_), xytext=(t_ + 0.5, g_ - 1.1), fontsize=9.5,
                    color=COL[nm], fontweight='bold', bbox=box(COL[nm]))
    a1.set_xlabel('宣稱的 τ（分鐘／小時）')
    a1.set_ylabel('實測泵窗長度（分鐘）')
    a1.set_xlim(0, 11.5)
    a1.set_ylim(0, 11.5)
    a1.set_title('（a）泵窗長度＝τ　相關 1.000', fontsize=10.5)
    a1.text(5.6, 2.0, '虛線為 y = x\n三點完全落在線上', fontsize=9,
            color='#555', bbox=box('#999'))

    for t_, r_, nm in zip(taus, rates, [b[0] for b in DT.BATCHES]):
        a2.plot(t_, r_, 'o', color=COL[nm], ms=11)
        a2.annotate('%s\n%.4f' % (nm, r_), xy=(t_, r_),
                    xytext=(t_ + 0.4, r_ - 0.004), fontsize=9.5,
                    color=COL[nm], fontweight='bold', bbox=box(COL[nm]))
    a2.set_xlabel('宣稱的 τ（分鐘／小時）')
    a2.set_ylabel('壓力下降速率中位數\n(kg/cm²/hr)')
    a2.set_xlim(0, 12.5)
    a2.set_ylim(0.012, 0.045)
    a2.set_title('（b）下降速率隨 τ 單調上升', fontsize=10.5)
    fig.suptitle('圖 2　τ 槓桿：泵運轉時間直接決定氣液接觸時間（對應表 F）',
                 fontsize=12, y=1.00)
    fig.tight_layout()
    return fig, 'fig2_tau槓桿'


# ── 圖 3（表 A+C）13 個自動循環：一致性與內部剖面 ──────────────
def fig_cycles():
    ts, h, p, co2, ch4 = DT.load(DT.TAU_DIR)
    t2, h2, p2, _, _ = DT.sub(ts, h, p, co2, ch4, *DT.BATCHES[2][2:])
    segs = DT.descents(h2, p2)
    reg = [(s, e) for s, e in segs
           if 5.0 <= h2[e] - h2[s] <= 8.5 and 0.20 <= p2[s] - p2[e] <= 0.30]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.4, 4.0))
    for s, e in reg:
        a1.plot(h2[s:e + 1] - h2[s], p2[s:e + 1] - p2[s], '-',
                color='#1565C0', alpha=0.35, lw=1.0)
    G = np.arange(0, 6.01, 0.5)
    M = np.array([np.interp(G, h2[s:e + 1] - h2[s], p2[s:e + 1] - p2[s])
                  for s, e in reg])
    mu = M.mean(axis=0)
    se = M.std(axis=0, ddof=1) / np.sqrt(len(M))
    a1.errorbar(G, mu, yerr=se * 3, fmt='o-', color='#C62828', lw=2.2, ms=5,
                capsize=3, label='疊加平均（誤差棒 ×3）', zorder=5)
    a1.set_xlabel('循環內經過時間（小時）')
    a1.set_ylabel('累計壓降（kg/cm²）')
    a1.legend(loc='lower left')
    a1.set_title('（a）13 個自動循環疊合', fontsize=10.5)
    a1.text(3.4, -0.03, '降幅 0.252 ± 0.009\n時長 6.83 ± 0.76 hr',
            fontsize=9, color='#1565C0', bbox=box('#1565C0'))

    d1 = np.diff(mu) / np.diff(G)
    base = -d1.mean()
    ctr = (G[:-1] + G[1:]) / 2
    rel = -d1 / base
    a2.bar(ctr, rel, width=0.42,
           color=['#C62828' if v > 1 else '#90A4AE' for v in rel])
    a2.axhline(1.0, color='#333', lw=1.2, ls='--')
    a2.set_xlabel('循環內經過時間（小時）')
    a2.set_ylabel('相對速率（1.0 = 全段平均）')
    a2.set_title('（b）循環內速率並非等速', fontsize=10.5)
    a2.text(2.6, 1.55, '高低交替＝泵的節奏\n含泵窗的半小時速率高',
            fontsize=9, color='#C62828', bbox=box('#C62828'))
    a2.set_ylim(0, 2.0)
    fig.suptitle('圖 3　自動循環的一致性與內部結構（對應表 A、C）',
                 fontsize=12, y=1.00)
    fig.tight_layout()
    return fig, 'fig3_循環一致性與內部剖面'


# ── 圖 4（表 E）估計量比較 ────────────────────────────────────
def fig_est():
    d = DT.data_E()
    ph = {}
    cur = None
    for r in d['rows']:
        if r[0]:
            cur = r[0]
            ph[cur] = []
        v = r[6].split('±')
        val = float(v[0].strip().rstrip('%'))
        err = float(v[1].strip().rstrip('%')) if len(v) > 1 else 0.0
        ph[cur].append((r[4], val, err))
    fig, ax = plt.subplots(figsize=(9.0, 4.2))
    labels = ['單筆端點', '兩端各 6 hr', '兩端各 12 hr', '兩端各 24 hr']
    cols = ['#90A4AE', '#2E7D32', '#EF6C00', '#C62828']
    xs = np.arange(len(ph))
    w = 0.2
    for j, lab in enumerate(labels):
        vals, errs = [], []
        for k in ph:
            m = [x for x in ph[k] if x[0] == lab]
            vals.append(m[0][1] if m else np.nan)
            errs.append(m[0][2] if m else 0.0)
        ax.bar(xs + (j - 1.5) * w, vals, w, yerr=errs, capsize=3,
               color=cols[j], alpha=0.88, label=lab)
    ax.axhline(0, color='#333', lw=1.0)
    ax.axhline(100, color='#1565C0', ls='--', lw=1.4)
    ax.text(2.45, 104, '化學計量上限 100%', fontsize=9, color='#1565C0',
            ha='right', bbox=box('#1565C0'))
    ax.set_xticks(xs)
    ax.set_xticklabels(list(ph))
    ax.set_ylabel('生物份額（%）')
    # ⚠ 圖例不可放 lower left——那裡正好是負值長條下方，會與紅色標註疊在
    #   一起（第一版就是這樣，兩段字互相蓋掉）。改放左上的空白區。
    ax.legend(ncol=2, loc='upper left', fontsize=8.8, framealpha=0.95)
    ax.set_ylim(-64, 128)
    ax.annotate('負值＝該期間沒有甲烷在產生，\n現有的正被補進來的氣體稀釋',
                xy=(2.16, -30), xytext=(1.30, -56), fontsize=9,
                color='#C62828', fontweight='bold', bbox=box('#C62828'),
                arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.2))
    ax.annotate('只有 2 天，估計量之間差異極大\n不應引用',
                xy=(1.19, 70), xytext=(1.30, 104), fontsize=9,
                color='#EF6C00', fontweight='bold', bbox=box('#EF6C00'),
                arrowprops=dict(arrowstyle='->', color='#EF6C00', lw=1.2))
    ax.set_title('圖 4　同一段資料、四種估計量的差異（對應表 E）')
    fig.tight_layout()
    return fig, 'fig4_估計量比較'


def main():
    style()
    os.makedirs(OUT, exist_ok=True)
    for fn in (fig_pump, fig_tau, fig_cycles, fig_est):
        fig, name = fn()
        path = os.path.join(OUT, name + '.png')
        fig.savefig(path, dpi=200, bbox_inches='tight')
        plt.close(fig)
        print('   ✓', name)
    print('輸出 →', OUT)


if __name__ == '__main__':
    main()
