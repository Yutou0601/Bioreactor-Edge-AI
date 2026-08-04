# -*- coding: utf-8 -*-
"""物理／生物分離：CH4 化學計量錨點 + Nernst 對數空間的 ORP 探針。

兩條互補路徑（皆不依賴 tau 槓桿）：

【路徑 A】CH4 目測錨點（批次層級、絕對值、無需校準）
  CH4 幾乎不溶 -> 整批累積於反應槽頂空 -> 排氣目測 CH4% 即累積產量。
  依 CO2 + 4H2 -> CH4 + 2H2O：每生成 1 CH4，氣相淨移除 4 mol。
    生物淨氣體移除 = 4 x p_CH4(累積)
    生物 CO2 消耗  = 1 x p_CH4(累積)
  體積可消去（CH4% 與壓力同指反應槽頂空），故只需壓力與 CH4%。

【路徑 B】Nernst 對數空間的 ORP（每循環層級）
  Nernst：E = A - S*ln(p_H2)，S = RT/(nF)，n=2、T=303K -> S = 13.05 mV。
  零階消耗 p_H2(t) = p0*(1 - phi*t) 代入：
    E(t) = C - S*ln(1 - phi*t)，  C = A - S*ln(p0)
  重點：phi（H2 分率消耗速率, 1/hr）**不需任何校準即可由 ORP 單獨定出**；
        絕對速率 r_H2 = phi * p_H2,0，其中 p_H2,0 由壓力與 CH4 稀釋給出。
  這正是「以不同化學物種的觀測恢復可辨識性」的具體實作。

輸出 -> docs/analysis_charts_3batch/
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import optimize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (  # noqa: E402
    BATCHES, VENT_VISUAL, OUT, BCOL, BLUE, RED, AQUA, INK, INK2, MUTED,
    BASELINE, load_all, find_cycles, style, cyc_ts)

# ── 物理常數與假設 ──
R_GAS, F_FARADAY, T_K, N_E = 8.314, 96485.0, 303.15, 2
S_NERNST = R_GAS * T_K / (N_E * F_FARADAY) * 1000      # mV per ln unit ~= 13.05
H2_FRAC_FEED = 0.8            # 進氣 H2:CO2 = 4:1 -> H2 佔 80%
PRESSURE_IS_ABSOLUTE = True   # 見報告：錶壓假設會使生物份額 >100%，物理上不可能
ATM = 1.033


# ══════════════════════════════════════════════════════════
# 路徑 A：CH4 化學計量錨點
# ══════════════════════════════════════════════════════════
def total_gas_removed(df, a, b):
    """整批的總氣體移除量（反應槽壓力單位）。

    每批只有一次排氣，故整段期間內：
        移除量 = 期間內所有補氣加入量 + (期初壓力 - 期末壓力)
    以「補氣加總」而非「循環壓降加總」計算，才能涵蓋未納入循環分析的時段
    （記錄中斷、批次首尾殘段），與 CH4 所對應的整批時長一致。
    """
    s = df[(df.ts >= a) & (df.ts <= b)].reset_index(drop=True)
    p = s.p_reactor.values.astype(float)
    d = np.diff(p)
    added = float(d[d > RISE_MIN].sum())        # 所有補氣加入的氣體
    return added + float(p[0] - p[-1]), len(s), p[0], p[-1]


RISE_MIN = 0.03


def ch4_anchor(df, batch_cycles):
    """每批的生物／物理速率分解（絕對值，無需校準）。

    生物項＝整批「淨累積」的 CH4：排氣目測值扣掉進氣後的殘留（洗管線後讀值），
    因後者為前一批未排淨的殘氣，非本批所產。
    """
    rows = []
    for name, (a, b, tau) in BATCHES.items():
        hrs = (pd.Timestamp(b) - pd.Timestamp(a)).total_seconds() / 3600
        removed, n_rows, p_first, p_last = total_gas_removed(df, a, b)

        v = VENT_VISUAL[name]
        p_vent, p_start = v['p_vent'], v['p_start']
        if not PRESSURE_IS_ABSOLUTE:
            p_vent, p_start = p_vent + ATM, p_start + ATM
        p_ch4_end = v['ch4'] / 100 * p_vent            # 排氣前頂空 CH4 分壓
        p_ch4_ini = v['ch4_initial'] / 100 * p_start   # 進氣後殘留 CH4 分壓
        p_ch4 = p_ch4_end - p_ch4_ini                  # 本批淨產生

        bio_removed = 4 * p_ch4
        phys_removed = removed - bio_removed
        rows.append(dict(
            batch=name, tau=tau, hours=hrs, n_cyc=len(batch_cycles[name]),
            p_ch4_ini=p_ch4_ini, p_ch4_end=p_ch4_end, p_ch4=p_ch4,
            total_removed=removed, bio_removed=bio_removed,
            phys_removed=phys_removed,
            bio_share=bio_removed / removed,
            rb=bio_removed / hrs,
            rb_co2=p_ch4 / hrs,
            rd=phys_removed / hrs))
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════
# 路徑 B：Nernst 對數空間 ORP
# ══════════════════════════════════════════════════════════
def nernst_model(t, C, phi):
    """E(t) = C - S*ln(1 - phi*t)；phi = H2 分率消耗速率 (1/hr)。"""
    return C - S_NERNST * np.log(np.clip(1 - phi * t, 1e-6, None))


def fit_nernst(cyc, smooth=21):
    """對單一循環的 ORP 擬合 Nernst 零階耗竭模型。

    自補氣後 ORP 崩谷起算（崩谷 = 還原劑最充足的時刻）。
    回傳 phi (1/hr)、C、R2、崩谷後時長。
    """
    t_all = (cyc.ts - cyc.ts.iloc[0]).dt.total_seconds().values / 3600
    e_raw = cyc.orp.values.astype(float)
    e = pd.Series(e_raw).rolling(smooth, center=True, min_periods=1).median().values

    head = max(5, min(len(e) // 4, 120))
    j = int(np.argmin(e[:head]))               # 崩谷
    t, y = t_all[j:] - t_all[j], e[j:]
    if len(t) < 40 or t[-1] < 1.0:
        return dict(phi=np.nan, C=np.nan, r2=np.nan, hours=np.nan, n=len(t))

    try:
        popt, _ = optimize.curve_fit(
            nernst_model, t, y, p0=[y[0], 0.3 / max(t[-1], 1)],
            bounds=([y.min() - 100, 1e-4], [y.max() + 100, 0.999 / t[-1]]),
            maxfev=40000)
    except Exception:
        return dict(phi=np.nan, C=np.nan, r2=np.nan, hours=t[-1], n=len(t))
    resid = y - nernst_model(t, *popt)
    r2 = 1 - resid.var() / y.var() if y.var() > 0 else np.nan
    return dict(phi=popt[1], C=popt[0], r2=r2, hours=t[-1], n=len(t))


def h2_partial_at_refill(cyc, p_ch4_now):
    """補氣後的 H2 分壓：頂空扣掉已累積的 CH4，其餘視為 4:1 進氣。"""
    p0 = cyc.p_reactor.iloc[0]
    if not PRESSURE_IS_ABSOLUTE:
        p0 += ATM
    return max(H2_FRAC_FEED * (p0 - p_ch4_now), 1e-3)


def orp_probe(batch_cycles, anchor, n_iter=3):
    """每循環的絕對生物速率：r_H2 = phi * p_H2,0，並以 CH4 累積迭代修正稀釋。"""
    rows = []
    for name, (a, b, tau) in BATCHES.items():
        cycs = batch_cycles[name]
        A = anchor.set_index('batch').loc[name]
        fits = [fit_nernst(c) for c in cycs]
        hrs = np.array([(c.ts.iloc[-1] - c.ts.iloc[0]).total_seconds() / 3600
                        for c in cycs])

        # CH4 累積：初值以時間線性內插，再依算出的生物速率迭代
        weight = hrs / hrs.sum()
        cum_frac = np.cumsum(weight) - weight / 2      # 各循環中點的累積比例
        for _ in range(n_iter):
            p_ch4_mid = A.p_ch4 * cum_frac
            r_h2, r_b = [], []
            for f, c, pm in zip(fits, cycs, p_ch4_mid):
                ph2 = h2_partial_at_refill(c, pm)
                rh = f['phi'] * ph2 if np.isfinite(f['phi']) else np.nan
                r_h2.append(rh)
                r_b.append(rh / 4 if np.isfinite(rh) else np.nan)
            prod = np.array([rb_ * h if np.isfinite(rb_) else np.nan
                             for rb_, h in zip(r_b, hrs)])
            if np.all(np.isnan(prod)):
                break
            tot = np.nansum(prod)
            w = np.where(np.isfinite(prod), prod, np.nanmean(prod))
            cum_frac = (np.cumsum(w) - w / 2) / max(tot, 1e-9)

        for i, (f, c) in enumerate(zip(fits, cycs)):
            ph2 = h2_partial_at_refill(c, A.p_ch4 * cum_frac[i])
            rows.append(dict(
                batch=name, tau=tau, cycle=i + 1, start=c.ts.iloc[0],
                phi=f['phi'], nernst_r2=f['r2'], orp_hours=f['hours'],
                p_h2_0=ph2,
                r_h2=f['phi'] * ph2 if np.isfinite(f['phi']) else np.nan,
                r_b_orp=f['phi'] * ph2 / 4 if np.isfinite(f['phi']) else np.nan,
                hours=hrs[i],
                drop_rate=(c.p_reactor.iloc[0] - c.p_reactor.iloc[-1]) / hrs[i]))
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════
def main():
    print('載入資料 …')
    df = load_all()
    batch_cycles = {}
    for name, (a, b, tau) in BATCHES.items():
        s = df[(df.ts >= a) & (df.ts <= b)].reset_index(drop=True)
        cycles = find_cycles(s)
        keep = [c for i, (c, _) in enumerate(cycles)
                if 0.15 <= c.p_reactor.iloc[0] - c.p_reactor.iloc[-1] <= 0.35
                and i != len(cycles) - 1]
        batch_cycles[name] = keep
        print(f'  {name}: {len(keep)} 個循環')

    print(f'\nNernst 斜率 S = RT/(nF) = {S_NERNST:.2f} mV/ln 單位'
          f'（n={N_E}, T={T_K:.1f}K）＝ {S_NERNST*np.log(10):.1f} mV/decade')
    print(f'壓力基準假設：{"絕對壓" if PRESSURE_IS_ABSOLUTE else "錶壓"}')

    # ── 路徑 A ──
    A = ch4_anchor(df, batch_cycles)
    print('\n══ 路徑 A：CH4 化學計量錨點（批次層級、絕對值、無需校準）══')
    print(A[['batch', 'tau', 'hours', 'p_ch4_ini', 'p_ch4_end', 'p_ch4',
             'total_removed', 'bio_removed', 'phys_removed', 'bio_share',
             'rb', 'rb_co2', 'rd']].round(4).to_string(index=False))

    # ── 路徑 B ──
    B = orp_probe(batch_cycles, A)
    print('\n══ 路徑 B：Nernst 對數空間 ORP（每循環）══')
    print(B[['batch', 'cycle', 'phi', 'nernst_r2', 'p_h2_0', 'r_b_orp',
             'drop_rate']].round(4).to_string(index=False))

    g = B.groupby('batch').agg(n=('cycle', 'size'),
                               phi=('phi', 'median'),
                               r2=('nernst_r2', 'median'),
                               r_b_orp=('r_b_orp', 'median'))
    g['r_b_CH4錨點'] = A.set_index('batch').rb_co2
    g['比值 ORP/CH4'] = g.r_b_orp / g['r_b_CH4錨點']
    print('\n══ 交叉驗證：兩條獨立路徑的生物 CO2 消耗率 ══')
    print(g.round(4).to_string())
    ratio = g['比值 ORP/CH4']
    cv = ratio.std() / ratio.mean() * 100
    print(f'\n  比值三批 CV = {cv:.0f}%'
          f'  → {"一致，ORP 可作定量生物探針" if cv < 30 else "仍發散，見報告討論"}')
    print(f'  Nernst 擬合 R2 中位數：{B.nernst_r2.median():.3f}'
          f'（有效循環 {B.phi.notna().sum()}/{len(B)}）')

    A.to_csv(f'{OUT}/separation_ch4_anchor.csv', index=False, encoding='utf-8-sig')
    B.to_csv(f'{OUT}/separation_orp_nernst.csv', index=False, encoding='utf-8-sig')
    figures(A, B, g, batch_cycles)
    print(f'\n輸出 → {OUT}')
    return A, B, g


def figures(A, B, g, batch_cycles):
    # ── 圖11：CH4 錨點分離 ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6))
    x = np.arange(3)
    ax1.bar(x, A.phys_removed, width=0.55, color=BLUE, label='物理溶解')
    ax1.bar(x, A.bio_removed, width=0.55, bottom=A.phys_removed,
            color=AQUA, label='生物消耗（4 x 累積 CH4）')
    for i, r in A.iterrows():
        ax1.annotate(f'生物 {r.bio_share*100:.0f}%',
                     xy=(i, r.phys_removed + r.bio_removed / 2), ha='center',
                     fontsize=10, fontweight='bold', color='white')
    ax1.set_xticks(x, [f'{t:.0f} min' for t in A.tau])
    style(ax1, '圖11a  以 CH4 化學計量錨點分解總氣體移除量',
          '循環時間 τ', '整批累積移除量 (kg/cm²)')
    ax1.legend(frameon=False, fontsize=9)

    w = 0.35
    ax2.bar(x - w / 2, A.rd, width=w, color=BLUE, label='物理 rd')
    ax2.bar(x + w / 2, A.rb, width=w, color=AQUA, label='生物 rb')
    for i, r in A.iterrows():
        ax2.annotate(f'{r.rd:.4f}', xy=(i - w / 2, r.rd), xytext=(0, 3),
                     textcoords='offset points', ha='center', fontsize=8.5)
        ax2.annotate(f'{r.rb:.4f}', xy=(i + w / 2, r.rb), xytext=(0, 3),
                     textcoords='offset points', ha='center', fontsize=8.5)
    ax2.set_xticks(x, [f'{t:.0f} min' for t in A.tau])
    style(ax2, '圖11b  分離後的兩條速率（皆為氣體淨移除速率）',
          '循環時間 τ', '速率 (kg/cm²/hr)')
    ax2.legend(frameon=False, fontsize=9)
    fig.text(0, -0.09,
             '生物項由「排氣目測 CH4%」經化學計量 CO2+4H2->CH4+2H2O 直接算出，'
             '不需 ORP 校準、不需 τ 槓桿；體積因 CH4% 與壓力同指反應槽頂空而消去。\n'
             '記帳原則：分子分母對齊同一段完整批次時長——總移除以「整批補氣加總＋期初期末壓差」計，'
             '生物項扣除進氣後殘留 CH4（洗管線後 9.50/8.56/8.41%）。\n'
             f'物理項 rd = {"／".join(f"{v:.4f}" for v in A.rd)}：1->5min 大增、5->10min 反降，'
             f'即已飽和；生物項 rb = {"／".join(f"{v:.4f}" for v in A.rb)}，'
             '5min 與 10min 僅差 6%，不隨 τ 單調變化。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig11_ch4_anchor_separation.png')
    plt.close(fig)

    # ── 圖12：Nernst 擬合示例 ──
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.3))
    for ax, name in zip(axes, BATCHES):
        sub = B[B.batch == name].dropna(subset=['phi'])
        if not len(sub):
            continue
        i = int(sub.nernst_r2.idxmax())
        row = B.loc[i]
        cyc = batch_cycles[name][int(row.cycle) - 1]
        t_all = (cyc.ts - cyc.ts.iloc[0]).dt.total_seconds().values / 3600
        e = pd.Series(cyc.orp.values.astype(float)).rolling(
            21, center=True, min_periods=1).median().values
        head = max(5, min(len(e) // 4, 120))
        j = int(np.argmin(e[:head]))
        t = t_all[j:] - t_all[j]
        ax.plot(t, cyc.orp.values[j:], lw=0.5, color=MUTED, alpha=0.5)
        ax.plot(t, e[j:], lw=1.4, color=BCOL[name])
        ax.plot(t, nernst_model(t, row.C if 'C' in row else e[j], row.phi),
                lw=2, ls='--', color=RED)
        style(ax, f'{name}  循環{int(row.cycle)}\n'
                  f'φ={row.phi:.4f}/hr  R²={row.nernst_r2:.3f}',
              'ORP 崩谷後時間 (hr)', 'ORP (mV)' if ax is axes[0] else None)
    fig.suptitle('圖12  Nernst 對數模型 E(t) = C - S·ln(1 - φt) 擬合（各批最佳循環）',
                 fontweight='bold', x=0.06, ha='left')
    fig.text(0, -0.06,
             f'S = RT/nF = {S_NERNST:.2f} mV/ln 單位（n=2, T=30°C）為物理常數、非擬合參數。'
             'φ 為 H2 分率消耗速率，**不需任何校準即可由 ORP 單獨定出**——\n'
             '這是三訊號融合恢復可辨識性的關鍵：ORP 提供的是與壓力不同的化學物種資訊。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig12_nernst_orp_fits.png')
    plt.close(fig)

    # ── 圖13：兩路徑交叉驗證 ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6))
    for name in BATCHES:
        sub = B[B.batch == name]
        ax1.scatter(sub.cycle, sub.r_b_orp, s=45, color=BCOL[name], label=name)
        anc = A.set_index('batch').loc[name, 'rb_co2']
        ax1.axhline(anc, color=BCOL[name], ls='--', lw=1.4, alpha=0.7)
    ax1.annotate('虛線 = 各批 CH4 錨點值（批次平均）\n點 = ORP 每循環估計',
                 xy=(0.04, 0.9), xycoords='axes fraction', fontsize=9.5,
                 color=INK, va='top')
    style(ax1, '圖13a  ORP 每循環生物速率 vs CH4 錨點批次平均',
          '批次內補氣次數', '生物 CO2 消耗率 (kg/cm²/hr)')
    ax1.legend(frameon=False, fontsize=8.5)

    ax2.scatter(g['r_b_CH4錨點'], g.r_b_orp, s=110,
                color=[BCOL[b] for b in g.index], zorder=5)
    lim = [0, max(g['r_b_CH4錨點'].max(), g.r_b_orp.max()) * 1.25]
    ax2.plot(lim, lim, ls=':', lw=1.5, color=BASELINE)
    for b_, r in g.iterrows():
        ax2.annotate(b_.split()[1], xy=(r['r_b_CH4錨點'], r.r_b_orp),
                     xytext=(8, 4), textcoords='offset points',
                     fontsize=9.5, fontweight='bold')
    ax2.set_xlim(lim)
    ax2.set_ylim(lim)
    style(ax2, '圖13b  兩條獨立路徑是否一致（虛線=完全一致）',
          'CH4 錨點 rb (kg/cm²/hr)', 'ORP Nernst rb (kg/cm²/hr)')
    ratio = g['比值 ORP/CH4']
    fig.text(0, -0.06,
             f'兩路徑比值：' +
             '、'.join(f'{b.split()[1]} {v:.2f}' for b, v in ratio.items()) +
             f'（CV={ratio.std()/ratio.mean()*100:.0f}%）。'
             '兩者資訊來源完全獨立——CH4 錨點來自化學計量與目測，'
             'ORP 來自 Nernst 電位；\n若一致即為分離成立的交叉驗證，若系統性偏離則指出'
             '模型假設（零階消耗、H2 不溶、電極響應）中何者需修正。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig13_two_route_crossvalidation.png')
    plt.close(fig)
    # ── 圖14：兩套獨立方法的交會（最強證據）──
    from analyze_three_batches import pooled_fit
    kla = []
    for name in BATCHES:
        k, peq, _, _ = pooled_fit(batch_cycles[name])
        kla.append(k)
    kla = np.array(kla)
    rd = A.rd.values

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.7))
    taus = A.tau.values
    ax1.plot(taus, rd / rd[0], 'o-', ms=10, lw=2.2, color=BLUE,
             label='物理速率 r_d（來源：CH4 化學計量）')
    ax1.plot(taus, kla / kla[0], 's--', ms=10, lw=2.2, color=RED,
             label='質傳係數 kLa（來源：壓力曲率擬合）')
    for t, a_, b_ in zip(taus, rd / rd[0], kla / kla[0]):
        ax1.annotate(f'{a_:.2f}', xy=(t, a_), xytext=(0, 9),
                     textcoords='offset points', ha='center',
                     fontsize=9.5, color=BLUE, fontweight='bold')
        ax1.annotate(f'{b_:.2f}', xy=(t, b_), xytext=(0, -18),
                     textcoords='offset points', ha='center',
                     fontsize=9.5, color=RED, fontweight='bold')
    ax1.axvspan(5, 10, color=MUTED, alpha=0.10, lw=0)
    ax1.annotate('兩者同時飽和', xy=(7.5, 4.45), ha='center',
                 fontsize=10.5, color=INK, fontweight='bold')
    ax1.set_ylim(0.6, 4.75)
    style(ax1, '圖14a  兩套獨立方法的 τ 響應（各自對 1min 正規化）',
          '循環時間 τ (分/小時)', '相對 1min 的倍數')
    ax1.legend(frameon=False, fontsize=9, loc='lower right',
               bbox_to_anchor=(1.0, 0.02))

    ax2.scatter(kla, rd, s=150, color=[BCOL[b] for b in A.batch], zorder=5)
    sl, ic = np.polyfit(kla, rd, 1)
    xs = np.linspace(0, kla.max() * 1.15, 50)
    ax2.plot(xs, sl * xs + ic, ls='--', lw=1.6, color=BASELINE)
    r = np.corrcoef(kla, rd)[0, 1]
    for k_, d_, b_, t_ in zip(kla, rd, A.batch, taus):
        ax2.annotate(f'{t_:.0f}min', xy=(k_, d_), xytext=(9, -4),
                     textcoords='offset points', fontsize=9.5, fontweight='bold')
    ax2.annotate(f'r = {r:.3f}', xy=(0.06, 0.88), xycoords='axes fraction',
                 fontsize=12, color=INK, fontweight='bold')
    style(ax2, '圖14b  物理速率 vs 質傳係數：應成正比', 'kLa (1/hr)',
          '物理速率 r_d (kg/cm²/hr)')

    fig.text(0, -0.07,
             '兩者沒有共用任何參數：r_d 來自「排氣目測 CH4% + 化學計量 + 整批氣體記帳」，'
             'kLa 來自「壓力軌跡的指數曲率擬合」。\n'
             '兩條路徑各自算出「循環時間槓桿在 5min 之後飽和」——這是本研究最強的交叉驗證，'
             '因為單一方法的系統性偏誤不可能同時出現在兩套完全不同的量測與模型上。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig14_independent_confirmation.png')
    plt.close(fig)

    # ── 圖15：分離結果總表（簡報用）──
    fig, ax = plt.subplots(figsize=(11.5, 5.2))
    xb = np.arange(3)
    wid = 0.62
    share_bio = A.bio_share.values * 100
    ax.bar(xb, 100 - share_bio, width=wid, color=BLUE, label='物理溶解 r_d')
    ax.bar(xb, share_bio, width=wid, bottom=100 - share_bio,
           color=AQUA, label='生物消耗 r_b')
    for i in range(3):
        ax.annotate(f'{100-share_bio[i]:.1f}%\n物理', xy=(i, (100 - share_bio[i]) / 2),
                    ha='center', va='center', fontsize=12,
                    color='white', fontweight='bold')
        ax.annotate(f'{share_bio[i]:.1f}%\n生物', xy=(i, 100 - share_bio[i] / 2),
                    ha='center', va='center', fontsize=12,
                    color='white', fontweight='bold')
        ax.annotate(f'r_d={A.rd.iloc[i]:.4f}\nr_b={A.rb.iloc[i]:.4f}',
                    xy=(i, 103), ha='center', fontsize=9.5, color=INK2)
    ax.set_xticks(xb, [f'批次 {b.split()[0]}\nτ = {t:.0f} 分/小時\n{h:.1f} hr'
                       for b, t, h in zip(A.batch, A.tau, A.hours)])
    ax.set_ylim(0, 112)
    style(ax, '圖15  三批次物理／生物分離結果總表（CH4 化學計量錨點）',
          None, '佔總氣體移除量的比例 (%)')
    # 不放圖例：長條內已直接標示「物理／生物」
    fig.text(0, -0.08,
             '單位：kg/cm²/hr（反應槽壓力單位的氣體淨移除速率）。壓力採絕對壓（錶壓假設會使 1min 批生物份額破 100%）。\n'
             '生物份額隨 τ 下降並非生物活性下降，而是物理質傳被 τ 大幅增強所稀釋：'
             'r_b 三批僅 0.0081/0.0140/0.0132，而 r_d 由 0.0075 增至 0.0252。\n'
             '待驗證：無菌對照下本方法應算出生物份額 0%，此為對整套方法最強的否證檢驗。',
             fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig15_separation_summary.png')
    plt.close(fig)

    print('  圖 11–15 完成')


if __name__ == '__main__':
    main()
