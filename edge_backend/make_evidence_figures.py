# -*- coding: utf-8 -*-
"""產生證據鏈文件的圖表 → docs/figures/

每張圖對應 docs/證據鏈_CO2溶解與生物消耗分離_2026-07-16.md 的一個章節。
只用可信訊號（壓力x2/ORP/pH）作圖；CO2/CH4 僅出現在「說明它為何無效」的圖裡。
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import rcParams
from scipy import stats, signal

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import co2_separation_analysis as sep

OUT = '../docs/figures'
os.makedirs(OUT, exist_ok=True)

# ── 設計系統（dataviz skill 的 reference palette，已通過 validate_palette）──
BLUE, RED, AQUA, YELLOW = '#2a78d6', '#e34948', '#1baf7a', '#eda100'
CRITICAL = '#d03b3b'
SURFACE, INK, INK2, MUTED = '#fcfcfb', '#0b0b0b', '#52514e', '#898781'
GRID, BASELINE = '#e1e0d9', '#c3c2b7'

rcParams['font.family'] = 'Microsoft JhengHei'
rcParams['axes.unicode_minus'] = False
rcParams['figure.facecolor'] = SURFACE
rcParams['axes.facecolor'] = SURFACE
rcParams['savefig.facecolor'] = SURFACE
rcParams['text.color'] = INK
rcParams['axes.labelcolor'] = INK2
rcParams['xtick.color'] = MUTED
rcParams['ytick.color'] = MUTED
rcParams['axes.edgecolor'] = BASELINE
rcParams['grid.color'] = GRID
rcParams['font.size'] = 10
rcParams['axes.titlesize'] = 11
rcParams['savefig.dpi'] = 200
rcParams['savefig.bbox'] = 'tight'


def style(ax, title=None, xlabel=None, ylabel=None):
    """統一的圖表外觀：格線收斂、去掉多餘邊框。"""
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


print('載入資料...')
DF = sep.load_folder_combined('Testing_data/0301-0416_無循環與有循環_5mins')
DF = DF.sort_values('timestamp').reset_index(drop=True)
RP = DF['reactor_pressure'].values.astype(float)
REFILL = np.where(np.diff(RP, prepend=RP[0]) > 0.05)[0]
BOUNDS = np.concatenate([[0], np.where(np.diff(RP, prepend=RP[0]) > 0.03)[0], [len(DF)-1]])


def windows(min_rows=200, min_drop=0.05):
    out = []
    for a, b in zip(BOUNDS[:-1], BOUNDS[1:]):
        seg = DF.iloc[a+1:b]
        if len(seg) < min_rows:
            continue
        p = seg['reactor_pressure'].values.astype(float)
        if p[0] - p[-1] < min_drop:
            continue
        out.append(seg)
    return out


# ══════════════════════════════════════════════════════════
# 圖1：CO2/CH4 為何無效（§1）
# ══════════════════════════════════════════════════════════
def fig1():
    w = DF[(DF.timestamp >= '2026-04-07 09:00') & (DF.timestamp <= '2026-04-07 13:00')]
    t = (w.timestamp - w.timestamp.iloc[0]).dt.total_seconds().values/60
    co2 = w['co2_pct'].values.astype(float)
    ch4 = w['ch4_pct'].values.astype(float)
    pc, ph_ = int(np.nanargmax(co2)), int(np.nanargmax(ch4))

    fig, (ax, axz) = plt.subplots(1, 2, figsize=(12, 4.4),
                                   gridspec_kw={'width_ratios': [2.2, 1]})

    # 左：全景，直接標線（不靠圖例配對顏色）
    ax.axvspan(t[pc], t[-1], color=CRITICAL, alpha=0.07, lw=0)
    ax.plot(t, co2, lw=2, color=BLUE)
    ax.plot(t, ch4, lw=2, color=AQUA)
    ax.annotate('CO2', xy=(t[-1], co2[-1]), xytext=(6, -2), textcoords='offset points',
                color=BLUE, fontsize=10, fontweight='bold', va='center')
    ax.annotate('CH4', xy=(t[-1], ch4[-1]), xytext=(6, 0), textcoords='offset points',
                color=AQUA, fontsize=10, fontweight='bold', va='center')
    ax.annotate('拖尾 = 閘門關閉後氣體向外流失\n不反映反應槽 → 無效資料',
                xy=(t[pc]+70, 33), color=CRITICAL, fontsize=10, fontweight='bold')
    ax.annotate('← 全部有效資料\n     只在這一瞬間', xy=(t[pc]+3, 5),
                color=INK, fontsize=9.5, fontweight='bold')
    style(ax, '圖1a  一次排氣事件的全貌（4 小時）', '距 09:00 的分鐘數', '濃度 (%)')

    # 右：放大峰值，證明「1 分鐘取樣只抓到 1~2 點」
    m = (t >= t[pc]-3) & (t <= t[pc]+6)
    axz.plot(t[m], co2[m], 'o-', ms=6, lw=2, color=BLUE)
    axz.plot(t[m], ch4[m], 'o-', ms=6, lw=2, color=AQUA)
    axz.scatter([t[pc]], [co2[pc]], s=150, facecolor='none', edgecolor=BLUE, linewidth=2.2, zorder=6)
    axz.scatter([t[ph_]], [ch4[ph_]], s=150, facecolor='none', edgecolor=AQUA, linewidth=2.2, zorder=6)
    axz.annotate(f'CO2 峰 {co2[pc]:.1f}', xy=(t[pc], co2[pc]), xytext=(-52, -26),
                 textcoords='offset points', color=BLUE, fontsize=9.5, fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=BLUE, lw=1.1))
    axz.annotate(f'CH4 峰 {ch4[ph_]:.1f}', xy=(t[ph_], ch4[ph_]), xytext=(8, 4),
                 textcoords='offset points', color=AQUA, fontsize=9.5, fontweight='bold')
    axz.annotate('每個點 = 1 分鐘\n峰只有 1~2 點\n→ 很可能整個錯過', xy=(t[pc]+2.5, 8),
                 color=INK, fontsize=9)
    style(axz, '圖1b  放大峰值：取樣率不足', '距 09:00 的分鐘數', None)

    fig.text(0, -0.04, '資料：2026-04-07 一次排氣事件（圖1a 的紅底區＝無效）。全部 375,070 筆中僅 93 筆 (0.025%) '
             '落在排氣峰值上，其餘 99.98% 為無效資料。\n即使抓到的峰值也只是真實峰值的「下界」——'
             '1 分鐘取樣可能抓到的是上升段或已開始衰減的點，故峰值亦僅供參考、不得作為證據。',
             fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig1_co2_invalid.png')
    plt.close(fig)
    print('  fig1 ok')


# ══════════════════════════════════════════════════════════
# 圖2：固定振幅弛豫振盪器（§2.1）
# ══════════════════════════════════════════════════════════
def fig2():
    w = DF[(DF.timestamp >= '2026-03-20') & (DF.timestamp <= '2026-03-26')]
    t = (w.timestamp - w.timestamp.iloc[0]).dt.total_seconds().values/3600
    p = w['reactor_pressure'].values.astype(float)

    ws = windows()
    drop = np.array([s['reactor_pressure'].values[0]-s['reactor_pressure'].values[-1] for s in ws])
    dur = np.array([len(s)/60 for s in ws])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={'width_ratios': [1.5, 1]})

    ax1.plot(t, p, lw=1.6, color=BLUE)
    ax1.axhline(0.71, lw=1.6, color=RED, ls='--')
    ax1.annotate('補氣下限 0.71\n跨 12 個月 / 所有條件皆不變', xy=(t[-1]*0.42, 0.735),
                 color=RED, fontsize=9.5, fontweight='bold')
    style(ax1, '圖2a  壓力軌跡：灌到上限 → 掉到 0.71 → 自動補氣',
          '小時', '反應槽壓力 (kg/cm²)')

    ax2.scatter(dur, drop, s=34, color=BLUE, alpha=0.8, edgecolor=SURFACE, linewidth=0.8)
    ax2.axhspan(np.percentile(drop, 25), np.percentile(drop, 75), color=RED, alpha=0.09, lw=0)
    ax2.annotate(f'壓降被控制器鎖死\nIQR {np.percentile(drop,25):.3f}~{np.percentile(drop,75):.3f}',
                 xy=(19, 0.62), color=RED, fontsize=9, fontweight='bold')
    ax2.annotate('週期長度變異 4.7 倍\n← 唯一帶資訊的量', xy=(7.5, 0.13),
                 color=INK, fontsize=9)
    style(ax2, '圖2b  壓降不帶資訊，時間才帶', '週期長度 (小時)', '總壓降 (kg/cm²)')

    fig.text(0, -0.05, '推論：總壓降是控制器設定值而非動力學結果 → 「總壓降/時間」≈ 常數/時間 ≈ 只在量時間。'
             '這是當日 12 種方法全數敗給此平凡基準的共同根因。', fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig2_relaxation_oscillator.png')
    plt.close(fig)
    print('  fig2 ok')


# ══════════════════════════════════════════════════════════
# 圖3：ORP 補氣響應（§2.2、§2.3）
# ══════════════════════════════════════════════════════════
def fig3():
    PRE, POST = 120, 300
    stack_o, stack_p = [], []
    for i in REFILL:
        if i-PRE < 0 or i+POST >= len(DF):
            continue
        o = DF['ORP (mV)'].values[i-PRE:i+POST+1].astype(float)
        p = DF['reactor_pressure'].values[i-PRE:i+POST+1].astype(float)
        if np.isnan(o).any() or np.isnan(p).any():
            continue
        tt = np.arange(-PRE, POST+1, dtype=float)
        pre = tt < 0
        stack_o.append(o - np.polyval(np.polyfit(tt[pre], o[pre], 1), tt))
        stack_p.append(p - p[:PRE].mean())
    A = np.array(stack_o); B = np.array(stack_p)
    t = np.arange(-PRE, POST+1)
    m, se = A.mean(axis=0), A.std(axis=0)/np.sqrt(len(A))
    mp = B.mean(axis=0)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True,
                                    gridspec_kw={'height_ratios': [2, 1]})
    ax1.axvline(0, color=BASELINE, lw=1.2)
    ax1.fill_between(t, m-2*se, m+2*se, color=BLUE, alpha=0.18, lw=0)
    ax1.plot(t, m, lw=2, color=BLUE)
    j = int(np.argmin(m))
    ax1.scatter([t[j]], [m[j]], s=70, color=RED, zorder=5, edgecolor=SURFACE, linewidth=2)
    ax1.annotate(f'ΔORP = {m[j]:.1f} mV\n17.3 σ', xy=(t[j], m[j]),
                 xytext=(40, m[j]+8), color=RED, fontsize=10, fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=RED, lw=1.2))
    half = np.where(m[PRE:] > m[j]/2)[0]
    if len(half):
        ax1.annotate(f'恢復半衰期 ~{half[0]} 分鐘', xy=(half[0], m[j]/2),
                     xytext=(120, -55), color=INK, fontsize=9.5,
                     arrowprops=dict(arrowstyle='->', color=INK2, lw=1))
    style(ax1, f'圖3  補氣瞬間 ORP 的巨大響應（{len(A)} 次事件疊加，帶 ±2SE）',
          None, 'ΔORP (mV)')

    ax2.axvline(0, color=BASELINE, lw=1.2)
    ax2.plot(t, mp, lw=2, color=AQUA)
    ax2.annotate('壓力：補氣跳升後，20 小時尺度緩降', xy=(150, 0.30), color=INK2, fontsize=9)
    style(ax2, None, '距補氣事件的分鐘數', 'Δ壓力 (kg/cm²)')

    fig.text(0, -0.03, 'ORP 恢復半衰期 ~26 分鐘 vs 壓力下降的 20 小時 → 差一個數量級。'
             '恢復速率隨菌群成熟度顯著不同（3.04 vs 1.05 mV/min, p=0.0118），'
             '但控制壓力速率後 p=0.073，未通過決定性檢定。', fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig3_orp_refill_response.png')
    plt.close(fig)
    print('  fig3 ok')


# ══════════════════════════════════════════════════════════
# 圖4：04-07 體制轉換（§3.2）
# ══════════════════════════════════════════════════════════
def fig4():
    rows = []
    for s in windows():
        o = s['ORP (mV)'].values.astype(float)
        p = s['reactor_pressure'].values.astype(float)
        rows.append(dict(t0=s.timestamp.iloc[0], dur=len(s)/60,
                         rate=(p[0]-p[-1])/(len(s)/60), orp=np.nanmean(o)))
    r = pd.DataFrame(rows).sort_values('t0')
    post = r[r.t0 >= '2026-04-07']
    ss = r[(r.t0 >= '2026-03-20') & (r.t0 < '2026-04-07') & (r.dur > 20)]
    ss_rate = ss.rate.median()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.5, 6), sharex=True)
    for ax in (ax1, ax2):
        ax.axvline(pd.Timestamp('2026-04-07'), color=RED, ls='--', lw=1.6)

    ax1.plot(r.t0, r.dur, 'o-', ms=4, lw=1.5, color=BLUE)
    ax1.annotate('04-07 體制轉換\n(疑似換液，待確認)', xy=(pd.Timestamp('2026-04-07'), 27),
                 xytext=(pd.Timestamp('2026-03-22'), 8), color=RED, fontsize=9.5, fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=RED, lw=1.2))
    ax1.annotate('之後 9 天單調恢復 8.0 → 20.2 hr', xy=(pd.Timestamp('2026-04-10'), 9),
                 color=INK, fontsize=9)
    style(ax1, '圖4  2026-04-07 體制轉換與其後的單調恢復', None, '週期長度 (小時)')

    ax2.plot(r.t0, r.orp, 'o-', ms=4, lw=1.5, color=YELLOW)
    ax2.annotate('ORP 飆到 647 (氧化態=生物活性低)\n之後單調降回 583', xy=(pd.Timestamp('2026-04-08'), 640),
                 xytext=(pd.Timestamp('2026-03-21'), 620), color=INK, fontsize=9,
                 arrowprops=dict(arrowstyle='->', color=INK2, lw=1))
    style(ax2, None, None, 'ORP 平均 (mV)')

    fig.text(0, -0.03, '關鍵反證：若變慢是「菌群恢復中」，速率應越來越快；實測越來越慢 → '
             f'快速起始不可能是生物造成的。恢復期首週期為穩態({ss_rate:.4f} kg/cm²/hr)的 3.38 倍 → 末週期 1.34 倍。'
             '\n積分超出穩態的部分 → 溶解 48.6% / 生物 51.4%（n=1，「換液」屬推測）。', fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig4_regime_change_0407.png')
    plt.close(fig)
    print('  fig4 ok')


# ══════════════════════════════════════════════════════════
# 圖5：k_ph 純溶解校正（§3.3）
# ══════════════════════════════════════════════════════════
def fig5():
    t = np.arange(7)
    orp = np.array([491, 460, 465, 467, 467, 466, 464], float)
    pres = np.array([1.47, 1.15, 1.15, 1.16, 1.16, 1.16, 1.16])
    ph = np.array([6.88, 6.91, 6.91, 6.88, 6.84, 6.82, 6.80])
    co2 = np.array([49.2, 48.9, 53.4, 73.0, 90.2, 94.6, 95.6])
    pco2 = pres*co2/100
    sl, ic, rv, pv, se = stats.linregress(pco2[1:], ph[1:])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    ax1.plot(t, ph, 'o-', ms=5, lw=2, color=BLUE, label='pH')
    ax1.set_ylabel('pH', color=BLUE)
    style(ax1, '圖5a  純 CO2 注入：pH 單調酸化、ORP 不動', '分鐘', 'pH')
    ax1.annotate('pH 6.91 → 6.80\n(CO2 溶入 → 酸化)', xy=(4, 6.845), color=BLUE, fontsize=9.5)
    axb = ax1.twiny()   # 僅用於放 ORP 註記，不畫第二個 y 軸（避免雙軸圖）
    axb.set_xticks([]); axb.spines[:].set_visible(False)
    ax1.annotate(f'ORP 460→464 mV 幾乎不動\n→ 無 H2 → 無生物反應\n→ ΔpH 純由物理溶解造成',
                 xy=(0.35, 6.895), color=INK, fontsize=9, fontweight='bold')

    ax2.scatter(pco2[1:], ph[1:], s=60, color=BLUE, zorder=5, edgecolor=SURFACE, linewidth=1.2)
    xs = np.linspace(pco2[1:].min(), pco2[1:].max(), 50)
    ax2.plot(xs, sl*xs+ic, lw=2, color=RED)
    ax2.annotate(f'k_ph = {sl:.3f} ± {se:.3f}\nR² = {rv**2:.3f},  p = {pv:.4f}',
                 xy=(0.72, 6.895), color=RED, fontsize=10, fontweight='bold')
    style(ax2, '圖5b  校正：pH vs CO2 分壓', 'p_CO2 (kg/cm²)', 'pH')

    fig.text(0, -0.05, '資料：old data/co溶入液體，2025-09-02，7 分鐘純 CO2 注入實驗（僅 6 點入迴歸）。'
             '這是當日唯一乾淨、顯著的量測，並證實洪博報告「pH 會先酸變化」。'
             '\n註: 兩個待確認：(1) p_CO2 的計算用到 CO2%（需確認當時是否為連續流通量測）；'
             '(2) 2025 年壓力欄位對調規則未驗證（另一解讀給 -0.604）。', fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig5_kph_calibration.png')
    plt.close(fig)
    print('  fig5 ok')


# ══════════════════════════════════════════════════════════
# 圖6：檢定力分析（§5）
# ══════════════════════════════════════════════════════════
def fig6():
    rows = []
    for s in windows():
        p = s['reactor_pressure'].values.astype(float)
        rows.append(dict(t0=s.timestamp.iloc[0], rate=(p[0]-p[-1])/(len(s)/60)))
    r = pd.DataFrame(rows)
    st = r[(r.t0 >= '2026-03-20') & (r.t0 < '2026-04-07')]
    med = st.rate.median()
    mad = stats.median_abs_deviation(st.rate, scale='normal')
    clean = st[np.abs((st.rate-med)/mad) <= 3].rate.values
    sd_clean, mu = clean.std(ddof=1), np.median(clean)
    sd_all = st.rate.std(ddof=1)

    def power(n, eff, sd, nsim=8000):
        rng = np.random.default_rng(0)
        a = rng.normal(0, sd, (nsim, n)); b = rng.normal(eff, sd, (nsim, n))
        return (stats.ttest_ind(a, b, axis=1)[1] < 0.05).mean()

    pcts = np.linspace(0.05, 0.35, 13)
    fig, ax = plt.subplots(figsize=(9, 4.6))
    for n, col, lab in [(6, BLUE, 'n=6（n 主效應：每水準 3劑量×2重複）'),
                        (8, AQUA, 'n=8（劑量主效應：每水準 4個n×2重複）')]:
        ax.plot(pcts*100, [power(n, mu*p, sd_clean) for p in pcts], lw=2.2, color=col, label=lab)
    ax.plot(pcts*100, [power(8, mu*p, sd_all) for p in pcts], lw=2, color=RED, ls='--',
            label='n=8 但「未排除異常批次」(CV 71%)')

    ax.axhline(0.8, color=BASELINE, lw=1.4, ls=':')
    ax.annotate('80% 檢定力', xy=(5.5, 0.82), color=INK2, fontsize=9)
    ax.axvline(14, color=MUTED, lw=1.2, ls=':')
    ax.annotate('14%\n(當日實測的\n循環效應量級)', xy=(14.6, 0.14), color=INK, fontsize=9)

    style(ax, '圖6  檢定力分析（用當日實測變異數）：24 次實驗足夠，前提是排除異常批次',
          '效應大小（相對於中位速率 %）', '檢定力')
    ax.set_ylim(0, 1.03)
    ax.legend(frameon=False, loc='lower right', fontsize=9)
    fig.text(0, -0.05, f'排除異常批次後 CV = {sd_clean/mu:.1%}（n={len(clean)}）；含異常批次則 CV = {sd_all/med:.0%}。'
             '異常批次 = 壓降非正常 0.36（掉到 0.33/0.22 才補氣，屬人為介入）。'
             '\n→ 真正殺死檢定力的是異常批次，不是樣本數。紀錄表必須標記並排除。', fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig6_power_analysis.png')
    plt.close(fig)
    print('  fig6 ok')


if __name__ == '__main__':
    print('產生圖表 →', os.path.abspath(OUT))
    fig1(); fig2(); fig3(); fig4(); fig5(); fig6()
    print('完成')
