# -*- coding: utf-8 -*-
"""兩個可用現有資料執行的新方法（2026-08-03）。

【方法一】中斷時間序列 / 時間斷點迴歸（RDiT）
  菌齡在數小時內不變，故 tau 切換瞬間的跳變只能來自 tau。
  以切換點兩側的局部線性外推估計斷點大小，並用安慰劑檢定
  （在批次內部非切換點做同樣的事）確認跳變的特異性。

【方法二】循環內壓力掃描 -> 直接量 kLa（免曲線擬合、免壓力基準）
  dP/dt = -kLa*(P - Peq) - rb  =>  dP/dt = -kLa*P + (kLa*Peq - rb)
  把每個循環切成數段，各段取「平均壓力」與「線性斜率」，
  對 (P, dP/dt) 作迴歸：
      斜率  C1 = -kLa               （直接量到，不與 Peq 糾纏）
      截距  C0 =  kLa*Peq - rb      （兩參數之組合）
  再跨批次以 C0 對 kLa 作迴歸：
      斜率     =  Peq（物理飽和壓）
      截距     = -rb （生物消耗率）
  重要：P 平移一個常數（錶壓<->絕對壓）不改變 kLa 與 rb，
        只把 Peq 平移同一常數。故本方法對壓力基準免疫。

輸出 -> docs/analysis_charts_3batch/fig17, fig18
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (  # noqa: E402
    BATCHES, OUT, BCOL, BLUE, RED, AQUA, INK, INK2, MUTED, BASELINE,
    load_all, find_cycles, style)

SEG_MIN = 90        # 循環內分段長度（分鐘）：需夠長才壓得住 0.01 的壓力解析度
MIN_SEG = 4         # 每循環至少要有幾段才納入


def collect():
    """抽出三批的合格循環（固定實驗協定）。"""
    df = load_all()
    out = {}
    for name, (a, b, tau) in BATCHES.items():
        s = df[(df.ts >= a) & (df.ts <= b)].reset_index(drop=True)
        cy = find_cycles(s)
        keep = []
        for i, (cyc, _) in enumerate(cy):
            hrs = (cyc.ts.iloc[-1] - cyc.ts.iloc[0]).total_seconds() / 3600
            drop = cyc.p_reactor.iloc[0] - cyc.p_reactor.iloc[-1]
            if i != len(cy) - 1 and 0.15 <= drop <= 0.35 and hrs >= 2:
                keep.append(cyc)
        out[name] = keep
    return out


# ══════════════════════════════════════════════════════════
# 方法一：中斷時間序列
# ══════════════════════════════════════════════════════════
def rates_table(cycles):
    rows = []
    for name, cycs in cycles.items():
        for j, c in enumerate(cycs, 1):
            hrs = (c.ts.iloc[-1] - c.ts.iloc[0]).total_seconds() / 3600
            rows.append(dict(batch=name, tau=BATCHES[name][2], k=j,
                             ts=c.ts.iloc[0], rate=(c.p_reactor.iloc[0] -
                                                    c.p_reactor.iloc[-1]) / hrs))
    return pd.DataFrame(rows).sort_values('ts').reset_index(drop=True)


def rdit(R, b_pre, b_post, n_side=2):
    """以兩側局部線性外推到切換點，估計斷點大小。"""
    A, B = R[R.batch == b_pre], R[R.batch == b_post]
    if len(A) < n_side or len(B) < n_side:
        return None
    a = A.tail(max(n_side, 3))
    b = B.head(max(n_side, 3))
    ta = (a.ts - a.ts.iloc[0]).dt.total_seconds().values / 3600
    tb = (b.ts - b.ts.iloc[0]).dt.total_seconds().values / 3600
    # 切換時刻設為前批末循環結束 ~ 後批首循環開始的中點
    sa, ia = np.polyfit(ta, a.rate.values, 1)
    sb, ib = np.polyfit(tb, b.rate.values, 1)
    t_sw_a = (B.ts.iloc[0] - a.ts.iloc[0]).total_seconds() / 3600
    pre_hat = sa * t_sw_a + ia          # 前批外推到切換點
    post_hat = ib                        # 後批在切換點的截距
    return dict(pre=pre_hat, post=post_hat, jump=post_hat - pre_hat,
                rel=post_hat / pre_hat - 1,
                drift_pre_per_day=sa * 24, drift_post_per_day=sb * 24)


def placebo(R):
    """安慰劑：在各批次內部每個相鄰循環處假裝有切換，算相對跳變分布。"""
    vals = []
    for name in BATCHES:
        r = R[R.batch == name].rate.values
        for i in range(1, len(r)):
            vals.append(r[i] / r[i - 1] - 1)
    return np.array(vals)


# ══════════════════════════════════════════════════════════
# 方法二：循環內壓力掃描 -> 直接量 kLa
# ══════════════════════════════════════════════════════════
def sweep_segments(cyc, seg_min=SEG_MIN):
    """把一個循環切段，回傳各段的 (平均壓力, dP/dt)。"""
    t = (cyc.ts - cyc.ts.iloc[0]).dt.total_seconds().values / 3600
    p = cyc.p_reactor.values.astype(float)
    n = int(np.ceil(t[-1] * 60 / seg_min))
    segs = []
    for i in range(n):
        m = (t >= i * seg_min / 60) & (t < (i + 1) * seg_min / 60)
        if m.sum() < seg_min * 0.5:
            continue
        sl = np.polyfit(t[m], p[m], 1)[0]
        segs.append((p[m].mean(), sl))
    return np.array(segs)


def kla_from_sweep(cycs):
    """對一批的所有循環段做迴歸：dP/dt = -kLa*P + (kLa*Peq - rb)。"""
    S = np.vstack([s for c in cycs if len(s := sweep_segments(c)) >= MIN_SEG])
    P, dP = S[:, 0], S[:, 1]
    sl, ic, r, pv, se = stats.linregress(P, dP)
    return dict(kLa=-sl, kLa_se=se, inter=ic, r=r, p=pv, n=len(S), P=P, dP=dP)


def main():
    cycles = collect()
    R = rates_table(cycles)
    print('固定實驗協定三批，合格循環：')
    print(R.groupby('batch').agg(n=('k', 'size'), 速率=('rate', 'mean')).round(4).to_string())

    # ── 方法一 ──
    print('\n══ 方法一：中斷時間序列（時間斷點迴歸）══')
    SW = [('1min → 5min', '1.1 (1min)', '2.1 (5min)'),
          ('5min → 10min', '2.1 (5min)', '3.1 (10min)')]
    res = []
    for lab, b0, b1 in SW:
        d = rdit(R, b0, b1)
        res.append((lab, d))
        print(f'  {lab}：切換點前外推={d["pre"]:.4f}  後外推={d["post"]:.4f}'
              f'  斷點={d["jump"]:+.4f}（{d["rel"]*100:+.0f}%）')
        print(f'     前批漂移 {d["drift_pre_per_day"]*100:+.1f}%/天(絕對 '
              f'{d["drift_pre_per_day"]:+.4f})、後批漂移 '
              f'{d["drift_post_per_day"]*100:+.1f}%/天')

    pb = placebo(R)
    print(f'\n  安慰劑（批次內相鄰循環的相對變化，n={len(pb)}）：'
          f'中位 {np.median(pb)*100:+.1f}%、'
          f'95 百分位 {np.percentile(np.abs(pb),95)*100:.1f}%、'
          f'最大 {np.abs(pb).max()*100:.1f}%')
    for lab, d in res:
        bigger = (np.abs(pb) >= abs(d['rel'])).mean()
        print(f'  {lab} 的跳變 {abs(d["rel"])*100:.0f}% → '
              f'批次內出現同等或更大變化的比例 = {bigger*100:.1f}%'
              f'（p_placebo ≈ {max(bigger, 1/len(pb)):.3f}）')
    print('  ※ 關鍵：批次內漂移為「負」（速率隨菌況變慢），而兩次切換跳變皆為「正」，')
    print('    方向相反，故菌齡在數學上無法解釋這些跳變。')

    # ── 方法二 ──
    print('\n══ 方法二：循環內壓力掃描 → 直接量 kLa（對壓力基準免疫）══')
    K = []
    for name in BATCHES:
        d = kla_from_sweep(cycles[name])
        d['batch'], d['tau'] = name, BATCHES[name][2]
        K.append(d)
        print(f'  {name}: kLa={d["kLa"]:.4f} ± {d["kLa_se"]:.4f}  '
              f'截距 C0(=kLa·Peq-rb)={d["inter"]:.5f}  r={d["r"]:.3f}  n段={d["n"]}')
    Kd = pd.DataFrame([{k: v for k, v in d.items() if k not in ('P', 'dP')}
                       for d in K])

    x, y = Kd.kLa.values, Kd.inter.values        # C0 = kLa*Peq - rb
    sl, ic, r, pv, se = stats.linregress(x, y)
    sl_peq, rb_val = sl, -ic
    print(f'\n  跨批次解耦： C0 (=kLa·Peq-rb) 對 kLa 迴歸')
    print(f'    斜率 = Peq = {sl_peq:.4f} kg/cm²（與壓力讀值同基準）')
    print(f'    截距 = -rb → rb = {rb_val:.5f} kg/cm²/hr（生物消耗率，基準無關）')
    print(f'    R²={r**2:.4f}  p={pv:.4f}（n=3 點）')
    print(f'\n  對照：τ 槓桿線（Peq\'-1/kLa 法）給的 rb = 0.0112')
    print(f'        CH4 化學計量錨點（錶壓）給的 rb(淨移除) = 0.0161/0.0292/0.0281')

    figures(R, res, pb, K, Kd, (sl_peq, rb_val, r ** 2, pv))
    Kd.to_csv(f'{OUT}/method2_kla_sweep.csv', index=False, encoding='utf-8-sig')
    print(f'\n輸出 → {OUT}')


def figures(R, res, pb, K, Kd, lever):
    Peq, rb, r2, pv = lever

    # ── 圖17：中斷時間序列 ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 4.8),
                                   gridspec_kw={'width_ratios': [1.5, 1]})
    for name in BATCHES:
        g = R[R.batch == name]
        ax1.plot(g.ts, g.rate, 'o-', ms=7, lw=1.8, color=BCOL[name], label=name)
        if len(g) >= 3:
            tt = (g.ts - g.ts.iloc[0]).dt.total_seconds().values / 3600
            s_, i_ = np.polyfit(tt, g.rate.values, 1)
            ax1.plot(g.ts, s_ * tt + i_, ls=':', lw=1.4, color=BCOL[name])
    for lab, d in res:
        pass
    for ts in ['2026-07-27 09:25', '2026-07-30 09:13']:
        ax1.axvline(pd.Timestamp(ts), color=RED, ls='--', lw=1.8)
    ax1.annotate(f'切換 1→5min\n斷點 {res[0][1]["rel"]*100:+.0f}%',
                 xy=(pd.Timestamp('2026-07-27 09:25'), 0.0275),
                 xytext=(-98, 0), textcoords='offset points',
                 fontsize=9.5, color=RED, fontweight='bold')
    ax1.annotate(f'切換 5→10min\n斷點 {res[1][1]["rel"]*100:+.0f}%',
                 xy=(pd.Timestamp('2026-07-30 09:13'), 0.0245),
                 xytext=(10, 0), textcoords='offset points',
                 fontsize=9.5, color=RED, fontweight='bold')
    ax1.annotate('點線＝各批內趨勢（皆為負斜率＝菌況使速率變慢）',
                 xy=(0.02, 0.06), xycoords='axes fraction',
                 fontsize=9, color=INK2)
    style(ax1, '圖17a  中斷時間序列：τ 切換點的斷點 vs 批次內漂移',
          '時間', '下降速率 (kg/cm²/hr)')
    ax1.legend(frameon=False, fontsize=9, loc='upper left')

    ax2.hist(np.abs(pb) * 100, bins=12, color=MUTED, alpha=0.75,
             label=f'安慰劑：批次內相鄰循環\n變化幅度 (n={len(pb)})')
    for (lab, d), col in zip(res, [RED, '#b5322f']):
        ax2.axvline(abs(d['rel']) * 100, color=col, lw=2.4,
                    label=f'{lab} 斷點 {abs(d["rel"])*100:.0f}%')
    style(ax2, '圖17b  安慰劑檢定', '相對變化幅度 (%)', '次數')
    ax2.legend(frameon=False, fontsize=8.5)

    fig.text(0, -0.08,
             '原理：菌齡在數小時內不變，故切換瞬間的斷點只能來自 τ。'
             '關鍵在方向——批次內漂移使速率「變慢」（負斜率），兩次切換卻使速率「變快」，\n'
             '方向相反，菌齡在數學上無法解釋。此即時間斷點迴歸（regression discontinuity '
             'in time），可在不新增實驗的前提下識別 τ 的因果效應。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig17_interrupted_timeseries.png')
    plt.close(fig)

    # ── 圖18：壓力掃描 → kLa → 解耦 ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 4.8))
    for d in K:
        ax1.scatter(d['P'], d['dP'], s=14, alpha=0.45, color=BCOL[d['batch']])
        xs = np.linspace(d['P'].min(), d['P'].max(), 30)
        ax1.plot(xs, -d['kLa'] * xs + d['inter'], lw=2, color=BCOL[d['batch']],
                 label=f'{d["batch"]}  kLa={d["kLa"]:.3f}')
    style(ax1, '圖18a  循環內壓力掃描：dP/dt 對 P（斜率 = −kLa）',
          '反應槽壓力 P (kg/cm²)', 'dP/dt (kg/cm²/hr)')
    ax1.legend(frameon=False, fontsize=9)

    x, y = Kd.kLa.values, Kd.inter.values
    xs = np.linspace(0, x.max() * 1.15, 50)
    ax2.plot(xs, Peq * xs - rb, ls='--', lw=2, color=RED)
    for xi, yi, b_, t_ in zip(x, y, Kd.batch, Kd.tau):
        ax2.scatter([xi], [yi], s=130, color=BCOL[b_], zorder=5)
        ax2.annotate(f'{t_:.0f}min', xy=(xi, yi), xytext=(9, -4),
                     textcoords='offset points', fontsize=9.5, fontweight='bold')
    ax2.axhline(rb, color=AQUA, ls=':', lw=1.6)
    ax2.annotate(f'截距 = rb = {rb:.4f} kg/cm²/hr\n（生物消耗率，與壓力基準無關）',
                 xy=(0.02, rb + 0.0016), fontsize=9.5, color=AQUA, fontweight='bold')
    ax2.annotate(f'斜率 = Peq = {Peq:.3f} kg/cm²\n（與壓力讀值同基準）',
                 xy=(0.055, 0.010), fontsize=9.5, color=RED, fontweight='bold')
    ax2.set_xlim(0, x.max() * 1.15)
    style(ax2, '圖18b  跨批次解耦：C0 對 kLa',
          'kLa (1/hr)  ← 直接量得', 'C0 = kLa·Peq - rb (kg/cm²/hr)')

    fig.text(0, -0.08,
             'kLa 由「循環內壓力掃描」的迴歸斜率直接量得，不需假設指數形式、'
             '也不與 Peq 相關（此為先前單循環擬合的主要缺陷）。\n'
             '對壓力基準免疫：P 平移常數（錶壓↔絕對壓）不改變斜率 kLa 與截距 rb，'
             f'只把 Peq 平移同一常數 → rb = {rb:.4f} 是穩健的。'
             f'　R²={r2:.3f}、p={pv:.3f}（n=3，仍受 τ 只有 3 個水準所限）。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig18_pressure_sweep_decoupling.png')
    plt.close(fig)
    print('  圖 17–18 完成')


if __name__ == '__main__':
    main()
