
# -*- coding: utf-8 -*-
"""2026-09-11 週報的圖（中文標籤，供 Word 使用）。

⚠ 與 research/paper_style.py 分開：那支是論文用的——英文、LNCS 單欄 4.8 吋、
  7 pt 字。週報是給設備方閱讀的中文文件，放進 Word 約 15 cm 寬，字要大得多。

⚠ 本檔一律以 Write 工具寫入，不走 shell heredoc——heredoc 會吃掉反斜線並被
  內容中的引號截斷（docs/build/build_weekly.py 檔頭也記了同一件事）。

輸出 → docs/reports/fig_weekly_0911/
"""
import datetime as dt
import glob
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
OUT = os.path.join(HERE, 'reports', 'fig_weekly_0911')
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))

ATM = 1.033
VHEAD = 1.00          # 頭空體積 L（總容積 1.99 L 的約一半，由兩支壓力計反推）
R_GAS = 8.314462618
KGF_PA = 98066.5

# ⚠ 所有標註文字一律加白底框。圖上線條密（壓力每分鐘一筆、二十天），
#   文字只要落在資料上就讀不出來，而且是「看起來有字但看不清楚」這種
#   不會被發現的壞法。白底框讓文字不論背後是什麼都清楚。
def box(color):
    return dict(boxstyle='round,pad=0.34', fc='white', ec=color,
                alpha=0.93, lw=0.8)


# 三個階段（由資料與現場照片共同認定）
PHASES = [
    ('建立期', dt.date(2026, 8, 11), dt.date(2026, 8, 23), '#2E7D32'),
    ('氫氣耗盡', dt.date(2026, 8, 24), dt.date(2026, 8, 25), '#C62828'),
    ('衰退期', dt.date(2026, 8, 26), dt.date(2026, 8, 31), '#EF6C00'),
]


# ⚠ y 軸標籤裡不可出現「體」字。matplotlib 把字串轉 90 度時，
#   這個字會被畫成約六成大小並偏移，看起來像兩字疊在一起（已踩過）。
#   橫排正常，所以標題、圖例、標註照用無妨；只有 set_ylabel / supylabel 要避。
def style():
    plt.rcParams.update({
        'font.sans-serif': ['Microsoft JhengHei', 'Microsoft YaHei',
                            'SimHei', 'Arial Unicode MS', 'DejaVu Sans'],
        # ⚠ 兩個都會變方框：負號，以及下標字元（2 4）。中文字型沒有那些
        #   字。所以圖上一律寫 CH4／CO2／H2，不用下標。
        'axes.unicode_minus': False,
        'font.size': 10,
        'axes.labelsize': 10.5,
        'axes.titlesize': 11.5,
        'xtick.labelsize': 9,
        'ytick.labelsize': 9,
        'legend.fontsize': 9,
        'axes.grid': True,
        'grid.alpha': 0.25,
        'grid.linewidth': 0.6,
        'axes.spines.top': False,
        'axes.spines.right': False,
        'figure.dpi': 110,
    })


def load():
    from core.cycle_store import read_series_full
    d = os.path.join(REPO, 'research', 'Testing_data',
                     '0825-0831_氫氣不夠暫停進氣__自動化測試')
    got = read_series_full(sorted(glob.glob(os.path.join(d, '*.csv'))))
    if got is None:
        raise SystemExit('讀不到資料：%s' % d)
    ts, h, p, temp, co2, ch4 = got
    a = np.array([v if v is not None else 0.0 for v in ch4])
    b = np.array([v if v is not None else 0.0 for v in co2])
    return ts, np.asarray(h), np.asarray(p), a, b


def descents(h, p):
    """以補氣（單步跳升 > 0.03）為界切出下降段。

    ⚠ 不可用「所有負的相鄰差加總」當消耗量——感測器有 ±0.01 的抖動，
      一小時累加下來會得到 0.11，而實測下降速率只有 0.03。
    """
    segs, valley, start = [], p[0], 0
    for i in range(1, len(p)):
        if h[i] - h[i - 1] > 1.0 or p[i] - valley > 0.03:
            if i - 1 > start:
                segs.append((start, i - 1))
            start, valley = i, p[i]
        elif p[i] < valley:
            valley = p[i]
    segs.append((start, len(p) - 1))
    return [(s, e) for s, e in segs if e > s + 3 and p[s] > p[e]]


def shade_phases(ax, d0, d1):
    for nm, a0, b0, col in PHASES:
        lo = max(a0, d0)
        hi = min(b0, d1)
        if lo <= hi:
            ax.axvspan(lo, hi + dt.timedelta(days=1), color=col, alpha=0.07,
                       zorder=0)


def fig1_daily(ts, p, ch4, co2):
    """逐日的甲烷與二氧化碳——本週最重要的一張圖。"""
    days = sorted(set(t.date() for t in ts))
    idx = {d: [] for d in days}
    for i, t in enumerate(ts):
        idx[t.date()].append(i)
    mc = [np.median(ch4[idx[d]]) for d in days]
    mo = [np.median(co2[idx[d]]) for d in days]

    fig, ax = plt.subplots(figsize=(9.0, 4.3))
    shade_phases(ax, days[0], days[-1])
    ax.plot(days, mc, 'o-', color='#1565C0', lw=2.0, ms=5, label='甲烷 CH4')
    ax.plot(days, mo, 's-', color='#C62828', lw=1.8, ms=4.5, label='二氧化碳 CO2')
    ax.set_ylabel('反應器裡量到的濃度（%）')
    ax.set_ylim(-3.5, 52)
    ax.legend(loc='center right', framealpha=0.92)

    # 關鍵標註
    ax.annotate('甲烷從 0.7% 一路升到 39.6%\n但每天增加的量越來越少\n（+10.2 → +0.3）＝快要飽和了',
                xy=(dt.date(2026, 8, 15), 27.3),
                xytext=(dt.date(2026, 8, 11), 50.8),
                ha='left', va='top',
                fontsize=9, color='#1565C0', bbox=box('#1565C0'),
                arrowprops=dict(arrowstyle='->', color='#1565C0', lw=1.1))
    ax.annotate('二氧化碳歸零\n8/23 起就是 0.0%\n沒有原料了',
                xy=(dt.date(2026, 8, 23), 0.3),
                xytext=(dt.date(2026, 8, 17), 14.5),
                ha='left', va='top',
                fontsize=9, color='#C62828', fontweight='bold', bbox=box('#C62828'),
                arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.2))
    ax.annotate('8/24 氫氣耗盡',
                xy=(dt.date(2026, 8, 24), 23.0),
                xytext=(dt.date(2026, 8, 25, ), 13),
                fontsize=9, color='#C62828', bbox=box('#C62828'),
                arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.0))
    ax.annotate('甲烷開始往下掉\n42.8% → 31.3%\n＝已經沒在產甲烷了',
                xy=(dt.date(2026, 8, 29), 37.6),
                xytext=(dt.date(2026, 8, 24), 45.5),
                fontsize=9, color='#EF6C00', fontweight='bold', bbox=box('#EF6C00'),
                arrowprops=dict(arrowstyle='->', color='#EF6C00', lw=1.2))
    for nm, a0, b0, col in PHASES:
        ax.text(a0 + (b0 - a0) / 2, -1.6, nm, ha='center', va='top',
                fontsize=9.5, color=col, fontweight='bold')
    ax.set_title('圖 1　甲烷漲到 40% 就停住了，二氧化碳在 8/23 用完歸零')
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    return fig, 'fig1_甲烷和二氧化碳每天怎麼變'


def fig2_pressure(ts, h, p):
    """壓力軌跡：自動化的規律，以及 8/24 的中斷。"""
    fig, ax = plt.subplots(figsize=(9.0, 3.4))
    shade_phases(ax, ts[0].date(), ts[-1].date())
    ax.plot(ts, p, '-', color='#37474F', lw=0.55)
    ax.set_ylabel('反應器壓力（kg/cm²，錶壓）')
    ax.set_ylim(0.45, 1.30)
    ax.axhspan(1.11, 1.20, color='#2E7D32', alpha=0.10, zorder=0)
    # ⚠ 這段標註不可放 y=1.235——ylim 上緣才 1.30，白底框會頂到標題（已踩過）。
    #   改放色帶正下方的空白處，緊鄰它所描述的那條帶。
    ax.text(ts[len(ts) // 6], 1.045,
            '這條線平常就在上面綠帶裡來回\n1.11 ~ 1.20，只有 9 格（感測器一格 0.01）',
            va='top', fontsize=9, color='#2E7D32', bbox=box('#2E7D32'))
    ax.annotate('8/24 氫氣耗盡\n當日僅補氣 1 次\n壓力掉到 0.69',
                xy=(dt.datetime(2026, 8, 24, 20), 0.70),
                xytext=(dt.datetime(2026, 8, 14), 0.60),
                fontsize=9, color='#C62828', fontweight='bold', bbox=box('#C62828'),
                arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.2))
    # 三個色帶要標名字，否則讀者只看到三塊不同顏色的底色而不知道那是什麼。
    for nm, a0, b0, col in PHASES:
        ax.text(a0 + (b0 - a0) / 2, 0.475, nm, ha='center', va='bottom',
                fontsize=9, color=col, fontweight='bold')
    ax.set_title('圖 2　壓力平常只在 1.11 ~ 1.20 這 9 格裡走；8/24 沒補氣才掉到 0.69')
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    return fig, 'fig2_二十天的壓力'


def fig3_share(ts, h, p, ch4):
    """各階段有多少壓降是菌吃掉的。"""
    segs = descents(h, p)
    rows = []
    for nm, a0, b0, col in PHASES:
        ix = [i for i, t in enumerate(ts) if a0 <= t.date() <= b0]
        if not ix:
            continue
        lo, hi = ix[0], ix[-1]
        cons = sum(p[s] - p[e] for s, e in segs if s >= lo and e <= hi)
        f0, f1 = ch4[lo] / 100.0, ch4[hi] / 100.0
        gain = f1 * (p[hi] + ATM) - f0 * (p[lo] + ATM)
        rows.append((nm, col, gain / cons if cons > 0 else 0.0, cons, gain))

    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    xs = np.arange(len(rows))
    vals = [r[2] for r in rows]
    bars = ax.bar(xs, vals, color=[r[1] for r in rows], width=0.55, alpha=0.85)
    ax.axhline(0.25, color='#1565C0', ls='--', lw=1.6)
    ax.text(len(rows) - 0.45, 0.256,
            '理論上最多就是 0.25\nCO2 + 4H2 → CH4\n每 4 分氣體只換到 1 分甲烷',
            fontsize=9, color='#1565C0', ha='right', bbox=box('#1565C0'))
    ax.axhline(0, color='#555', lw=1.0)
    ax.set_xticks(xs)
    ax.set_xticklabels(['%s\n%s' % (r[0], lbl) for r, lbl in
                        zip(rows, ['8/11–8/23', '8/24–8/25\n（只有 2 天，數字不準）',
                                   '8/26–8/31'])])
    ax.set_ylabel('每用掉 1 份氣，產生多少甲烷')
    ax.set_ylim(-0.13, 0.30)
    for x, r in zip(xs, rows):
        # ⚠「菌吃掉 -31%」講不通——負值不是「吃掉負的」，是「根本沒在產」。
        #   負值改寫成白話，不要硬套同一個句型。
        share = r[2] / 0.25 * 100
        note = ('（菌吃掉 %.0f%%）' % share) if r[2] >= 0 else '（等於完全沒產甲烷）'
        va = 'bottom' if r[2] >= 0 else 'top'
        off = 0.008 if r[2] >= 0 else -0.008
        ax.text(x, r[2] + off, '%.3f\n%s' % (r[2], note),
                ha='center', va=va, fontsize=9.5, fontweight='bold')
    # ⚠ 警語不可放在負值長條正下方——會與該長條的數值標籤疊在一起（已踩過）。
    #   改放左側空白處，用箭頭指過去。
    ax.annotate('算出負的＝這段時間根本沒在產甲烷，\n   現有的甲烷正被補進來的新氣體稀釋',
                xy=(1.70, -0.050), xytext=(-0.44, -0.083),
                ha='left', fontsize=9.5, color='#C62828', fontweight='bold', bbox=box('#C62828'),
                arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.3))
    ax.set_title('圖 3　壓力掉掉的氣體，前期約 %.0f%% 是菌吃掉的；後期算出負的＝沒在產甲烷'
                 % (rows[0][2] / 0.25 * 100))
    fig.tight_layout()
    return fig, 'fig3_有多少是菌吃掉的'


def fig4_window(ts, h, p):
    """視窗長度 vs 可量測性——說明「10 分鐘量不到」。"""
    segs = descents(h, p)
    widths = [10, 20, 30, 60, 120, 180, 240]
    frac, med = [], []
    for W in widths:
        drops = []
        for s, e in segs:
            t, y = h[s:e + 1], p[s:e + 1]
            t0 = t[0]
            while t0 + W / 60.0 <= t[-1]:
                m = (t >= t0) & (t < t0 + W / 60.0)
                if m.sum() >= 2:
                    drops.append(y[m][0] - y[m][-1])
                t0 += W / 60.0
        d = np.array(drops) if drops else np.array([0.0])
        frac.append((np.abs(d) < 0.01).mean() * 100)
        med.append(np.median(d))

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(9.4, 3.6))
    ax.plot(widths, frac, 'o-', color='#C62828', lw=2, ms=6)
    ax.axhline(50, color='#999', ls=':', lw=1.2)
    ax.set_xlabel('區間長度（分鐘）')
    ax.set_ylabel('壓力一個數字都沒動的比例（%）')
    ax.set_ylim(-4, 100)
    # ⚠ 不要把比例寫死成「六成」——實際是 frac[0]，換批資料就對不上。
    ax.annotate('10 分鐘：%.0f%% 的時段\n壓力一個數字都沒動' % frac[0],
                xy=(10, frac[0]), xytext=(52, 76), fontsize=9,
                color='#C62828', fontweight='bold', bbox=box('#C62828'),
                arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.2))
    ax.annotate('3 小時：看得出來了', xy=(180, frac[5]), xytext=(112, 24),
                fontsize=9, color='#2E7D32', fontweight='bold', bbox=box('#2E7D32'),
                arrowprops=dict(arrowstyle='->', color='#2E7D32', lw=1.2))
    ax.set_title('（a）有多少時段完全看不出變化')

    ax2.plot(widths, med, 'o-', color='#1565C0', lw=2, ms=6)
    ax2.axhline(0.01, color='#C62828', ls='--', lw=1.5)
    ax2.text(238, 0.0185, '感測器一格就是 0.01，比這小就量不到', fontsize=9,
             color='#C62828', ha='right', bbox=box('#C62828'))
    ax2.set_xlabel('區間長度（分鐘）')
    ax2.set_ylabel('這段時間壓力掉了多少（kg/cm²）')
    ax2.set_title('（b）實際掉了多少')
    fig.suptitle('圖 4　為什麼 10 分鐘太短——壓力根本還沒掉到感測器看得見',
                 fontsize=11.5, y=1.00)
    fig.tight_layout()
    return fig, 'fig4_為什麼10分鐘太短'


def fig5_balance(ts, h, p, ch4):
    """氣體總帳：投入、最多可產、實際增加、對不上的部分。"""
    segs = descents(h, p)
    cons = sum(p[s] - p[e] for s, e in segs)
    ch4_max = cons * 0.25
    f0, f1 = ch4[0] / 100.0, ch4[-1] / 100.0
    gain = f1 * (p[-1] + ATM) - f0 * (p[0] + ATM)
    gap = ch4_max - gain

    def ml(dp):
        return dp * KGF_PA * VHEAD * 1e-3 / (R_GAS * 303.15) * 22400

    fig, ax = plt.subplots(figsize=(8.4, 3.9))
    labels = ['總共補進去\n也用掉的氣體', '如果全部變成甲烷\n最多這麼多',
              '實際上甲烷\n只增加這些', '對不上的部分']
    vals = [cons, ch4_max, gain, gap]
    cols = ['#37474F', '#1565C0', '#2E7D32', '#C62828']
    bars = ax.bar(np.arange(4), vals, color=cols, width=0.58, alpha=0.88)
    for i, (v, c) in enumerate(zip(vals, cols)):
        ax.text(i, v + 0.12, '%.2f kg/cm²\n(%.0f mL)' % (v, ml(v)),
                ha='center', fontsize=9.5, fontweight='bold', color=c)
    ax.set_ylabel('換算成壓力（kg/cm²）')
    ax.set_xticks(np.arange(4))
    ax.set_xticklabels(labels)
    ax.set_ylim(0, cons * 1.22)
    # ⚠ 這段說明原本畫在紅色長條**內部**（白字），與長條上方的數值標籤
    #   疊在一起，「(2349 mL)」與「佔上限的 80%」互相蓋掉（已踩過）。
    #   長條只有 2.70 高而字有三行，放得下是錯覺。改放右上空白處並拉線。
    ax.annotate('對不上的這 %.0f%%\n最可能是二氧化碳直接溶進水裡\n'
                '（氣體確實用掉了，但沒變成甲烷）' % (gap / ch4_max * 100),
                # ⚠ 箭頭指長條**左緣偏下**，不要指正上方——正上方是該長條的
                #   數值標籤，箭頭會從字上穿過去。
                xy=(2.76, gap * 0.45), xytext=(2.16, cons * 0.60),
                ha='center', fontsize=9.5, color='#C62828', fontweight='bold',
                bbox=box('#C62828'),
                arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.3))
    ax.set_title('圖 5　二十天補進去的氣體，只有 %.0f%% 變成甲烷留在反應器裡'
                 % (gain / cons * 100))
    fig.tight_layout()
    return fig, 'fig5_氣體總帳'


def main():
    style()
    os.makedirs(OUT, exist_ok=True)
    ts, h, p, ch4, co2 = load()
    print('讀入 %d 筆  %s ~ %s' % (len(ts), ts[0], ts[-1]))
    for fn in (lambda: fig1_daily(ts, p, ch4, co2),
               lambda: fig2_pressure(ts, h, p),
               lambda: fig3_share(ts, h, p, ch4),
               lambda: fig4_window(ts, h, p),
               lambda: fig5_balance(ts, h, p, ch4)):
        fig, name = fn()
        path = os.path.join(OUT, name + '.png')
        fig.savefig(path, dpi=200, bbox_inches='tight')
        plt.close(fig)
        print('   ✓', os.path.basename(path))
    print('輸出 →', OUT)


if __name__ == '__main__':
    main()
