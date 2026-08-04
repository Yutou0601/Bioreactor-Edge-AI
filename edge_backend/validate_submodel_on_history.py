# -*- coding: utf-8 -*-
"""外部驗證：以 1/5/10min 三批（2026-07~08）建立的子模型，預測更早期的獨立資料。

設計理由（由使用者提出）：同樣 H2:CO2 = 4:1、同樣循環時間設定，但屬不同時期、
不同菌齡與液體的獨立批次。若子模型能預測它們，即為真正的外部效度，
遠強於同一資料內的交叉驗證。

重要：本驗證只用「壓力下降速率」，而下降速率是壓力的**差分**，
      與壓力基準（錶壓／絕對壓）無關，故不受該未決問題影響。

輸出 -> docs/analysis_charts_3batch/fig16_external_validation.png
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (  # noqa: E402
    BATCHES, OUT, BCOL, BLUE, RED, AQUA, INK, INK2, MUTED, BASELINE,
    load_txt, find_cycles, style)

TD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Testing_data')

# 歷史獨立資料集（同為 H2:CO2 = 4:1）
# 注意：0301-0416 資料夾同時含「無循環」與「有循環 5min」兩段。
# 由資料可清楚辨識切換點在 2026-04-07：該日之前循環長 25~29 hr、速率約 0.013~0.017；
# 之後驟降為 8~12 hr、速率 0.040~0.047。此推論待與洪博確認。
CIRC_ON = '2026-04-07'
HISTORY = {
    '歷史 無循環 (03-01~04-06)': (os.path.join(TD, '0301-0416_無循環與有循環_5mins'),
                                 0.0, None, CIRC_ON),
    '歷史 5min (04-07~04-16)': (os.path.join(TD, '0301-0416_無循環與有循環_5mins'),
                               5.0, CIRC_ON, None),
    '歷史 10min (04-20~04-27)': (os.path.join(TD, '0417-0427_有循環_10mins_74%'),
                                10.0, None, None),
}
# 歷史批次的補氣帶與新批次不同（壓降約 0.37 vs 0.25），故壓降過濾範圍需放寬
HIST_DROP = (0.15, 0.90)


def load_folder(folder):
    files = sorted(glob.glob(os.path.join(folder, '*.txt')))
    if not files:
        raise ValueError(f'{folder} 無 txt 檔')
    df = pd.concat([load_txt(p) for p in files], ignore_index=True)
    return df.sort_values('ts').drop_duplicates('ts').reset_index(drop=True)


def cycle_rates(df):
    """抽出完整循環，回傳每循環的下降速率與起訖。"""
    rows = []
    for cyc, _pre in find_cycles(df):
        hrs = (cyc.ts.iloc[-1] - cyc.ts.iloc[0]).total_seconds() / 3600
        drop = cyc.p_reactor.iloc[0] - cyc.p_reactor.iloc[-1]
        if hrs <= 0:
            continue
        rows.append(dict(start=cyc.ts.iloc[0], hours=hrs, drop=drop,
                         p0=cyc.p_reactor.iloc[0], rate=drop / hrs))
    return pd.DataFrame(rows)


def main():
    # ── 1. 訓練：三批新資料的每循環下降速率 ──
    from analyze_three_batches import load_all
    new = load_all()
    train = []
    for name, (a, b, tau) in BATCHES.items():
        s = new[(new.ts >= a) & (new.ts <= b)].reset_index(drop=True)
        cycles = find_cycles(s)
        for i, (cyc, _) in enumerate(cycles):
            drop = cyc.p_reactor.iloc[0] - cyc.p_reactor.iloc[-1]
            hrs = (cyc.ts.iloc[-1] - cyc.ts.iloc[0]).total_seconds() / 3600
            if not (0.15 <= drop <= 0.35) or i == len(cycles) - 1:
                continue
            train.append(dict(batch=name, tau=tau, rate=drop / hrs))
    T = pd.DataFrame(train)
    X = np.column_stack([np.ones(len(T)), 1 / T.tau.values])
    beta = np.linalg.pinv(X) @ T.rate.values
    print(f'子模型（訓練於 2026-07~08 三批，n={len(T)}）：')
    print(f'  下降速率 = {beta[0]:.4f} - {abs(beta[1]):.4f}/τ')
    print(T.groupby('tau').rate.agg(['mean', 'std', 'size']).round(4).to_string())

    # ── 2. 外部驗證：歷史資料 ──
    print('\n外部驗證（獨立時期、同為 4:1）：')
    res = {}
    for label, (folder, tau, t0, t1) in HISTORY.items():
        df = load_folder(folder)
        if t0:
            df = df[df.ts >= t0]
        if t1:
            df = df[df.ts < t1]
        C = cycle_rates(df.reset_index(drop=True))
        C = C[(C['drop'].between(*HIST_DROP)) & (C.hours >= 2)]
        if not len(C):
            print(f'  {label}: 無合格循環')
            continue
        pred = beta[0] + beta[1] / tau if tau > 0 else np.nan
        C = C.sort_values('start')
        early = C.rate.values[:max(3, len(C) // 3)]   # 該期最早 1/3（菌況最接近新批）
        err = C.rate.values - pred
        res[label] = dict(tau=tau, obs=C.rate.values, pred=pred, C=C, early=early)
        print(f'     該期前段(最早1/3) 中位={np.median(early):.4f}  '
              f'該期末段 中位={np.median(C.rate.values[-max(3, len(C)//3):]):.4f}'
              f'  期內衰減 {C.rate.values[0]/max(C.rate.values[-1],1e-9):.1f} 倍')
        print(f'  {label}  n={len(C)}  期間 {C.start.min():%Y-%m-%d} → '
              f'{C.start.max():%Y-%m-%d}')
        print(f'     預測={pred:.4f}   實測 中位={np.median(C.rate):.4f} '
              f'平均={C.rate.mean():.4f} ± {C.rate.std():.4f}')
        print(f'     RMSE={np.sqrt(np.mean(err**2)):.4f}  '
              f'偏誤={err.mean():+.4f}  相對偏誤={err.mean()/pred*100:+.0f}%')

    # ── 3. 圖 ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 4.8),
                                   gridspec_kw={'width_ratios': [1.1, 1]})
    xs = np.linspace(0.8, 11, 200)
    ax1.plot(xs, beta[0] + beta[1] / xs, lw=2, ls='--', color=RED,
             label='子模型（訓練於 2026-07~08）')
    for name, (a, b, tau) in BATCHES.items():
        g = T[T.batch == name]
        ax1.scatter(np.full(len(g), tau), g.rate, s=42, color=BCOL[name],
                    alpha=0.85, zorder=4,
                    label=f'訓練：{name}')
    marks = ['s', 'D', '^', 'v']
    for mi, (label, r) in enumerate(res.items()):
        ax1.scatter(np.full(len(r['obs']), r['tau']) + 0.35, r['obs'],
                    s=55, marker=marks[mi % len(marks)], facecolor='none',
                    edgecolor=INK, linewidth=1.5, zorder=5, label=f'驗證：{label}')
    # 飽和型主模型：可涵蓋 tau=0（無循環），且不會在 tau->0 發散
    allt, allr = list(T.tau.values), list(T.rate.values)
    for label, r in res.items():
        allt += [r['tau']] * len(r['obs'])
        allr += list(r['obs'])
    allt, allr = np.array(allt), np.array(allr)
    from scipy import optimize

    def sat(tau, r0, rmax, K):
        return r0 + rmax * tau / (K + tau)
    try:
        pv, _ = optimize.curve_fit(sat, allt, allr, p0=[0.015, 0.025, 2.0],
                                   bounds=([0, 0, 0.01], [0.1, 0.2, 50]),
                                   maxfev=40000)
        ax1.plot(np.linspace(0, 11, 200), sat(np.linspace(0, 11, 200), *pv),
                 lw=2, color=AQUA,
                 label=f'飽和型主模型 r0+rmax·τ/(K+τ)  K={pv[2]:.2f}')
        print(f'\n飽和型主模型（含無循環 τ=0，全部 {len(allt)} 循環）：')
        print(f'  下降速率 = {pv[0]:.4f} + {pv[1]:.4f}·τ/({pv[2]:.2f}+τ)')
        print(f'  半飽和 K = {pv[2]:.2f} 分/小時 → 超過約 {2*pv[2]:.0f} 分/小時後增益已小')
    except Exception as e:
        print('飽和型擬合失敗', e)
    ax1.set_xlim(-0.4, 11.2)
    style(ax1, '圖16a  子模型 vs 獨立歷史資料（同為 4:1）',
          '循環時間 τ (分/小時)', '下降速率 (kg/cm²/hr)')
    ax1.legend(frameon=False, fontsize=8, loc='upper left', ncol=1)

    labels, preds, obs_m, obs_s = [], [], [], []
    for label, r in res.items():
        labels.append(label.replace(' (', '\n('))
        preds.append(r['pred'])
        obs_m.append(np.median(r['obs']))
        obs_s.append(r['obs'].std())
    xp = np.arange(len(labels))
    w = 0.35
    preds = [p_ if np.isfinite(p_) else 0 for p_ in preds]
    ax2.bar(xp - w / 2, preds, width=w, color=RED, alpha=0.85, label='子模型預測')
    ax2.bar(xp + w / 2, obs_m, width=w, color=AQUA, label='歷史實測（中位）',
            yerr=obs_s, capsize=5, ecolor=INK2)
    for i, (p_, o_) in enumerate(zip(preds, obs_m)):
        ax2.annotate(f'{p_:.4f}', xy=(i - w / 2, p_), xytext=(0, 4),
                     textcoords='offset points', ha='center', fontsize=9)
        ax2.annotate(f'{o_:.4f}', xy=(i + w / 2, o_), xytext=(0, 4),
                     textcoords='offset points', ha='center', fontsize=9)
    ax2.set_xticks(xp, labels, fontsize=9)
    style(ax2, '圖16b  預測 vs 實測', None, '下降速率 (kg/cm²/hr)')
    ax2.legend(frameon=False, fontsize=9)

    fig.text(0, -0.09,
             '訓練集：2026-07-22~08-03 的 1/5/10min 三批（26 循環）；'
             '驗證集：2026-03~04 的獨立批次，同為 H2:CO2=4:1、同樣循環時間設定，'
             '但菌齡與液體皆不同。\n'
             '本驗證僅用壓力「下降速率」（壓力的差分），故與錶壓／絕對壓的未決問題無關。\n'
             '※ 歷史批次與訓練批次相隔 3~5 個月，菌群狀態不同；'
             '預測偏誤同時包含模型誤差與批次間生物狀態差異，無法區分。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig16_external_validation.png')
    plt.close(fig)
    print(f'\n圖 → {OUT}/fig16_external_validation.png')


if __name__ == '__main__':
    main()
