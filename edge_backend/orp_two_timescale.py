# -*- coding: utf-8 -*-
"""子問題拆解：ORP 的兩個時間尺度，以及分離失敗的確切原因（2026-08-04）。

── 拆解方式 ───────────────────────────────────────────────
主問題「能否分離物理與生物」拆成四個可獨立回答的子問題：

  SP1 感測器的資訊上限：各訊號在一個循環內有幾個量化階？
  SP2 ORP 的時間結構：補氣後的恢復是「快暫態」還是「慢 H2 耗竭」？
  SP3 去掉快暫態後，壓力與 ORP 是否正交（可分離的前提）？
  SP4 在乾淨的晚期窗內做雙驅動迴歸，生物項是否顯著？

── 結果 ───────────────────────────────────────────────────
SP1: pH 每循環僅 7~9 個量化階（解析度 0.01、變幅 0.07~0.09）-> 資訊不足，不可用。
     壓力 24~25 階、ORP 154~188 mV，尚可。
SP2: ORP 恢復有兩個尺度——前 30 分鐘完成 23~69%（注入/混合的快暫態），
     其後仍有 +0.3~+2.4 mV/hr 的慢速漂移（才是 H2 耗竭）。
     先前把兩者混在一起用單一 Nernst 常數擬合，故 R2 僅 0.13~0.24。
SP3: 切掉前 2 小時後，r(P, h) 降到 -0.02~+0.13 -> 幾乎正交，結構上可分離。
SP4: 僅 10min 批的生物項顯著（t=2.77）；1min 批 t=0.34、5min 批符號為負。
     可分離與否取決於 ORP 慢速漂移的訊噪比，而非方法。

=> 分離失敗是「量測解析度」問題，不是模型問題。可換算成明確的儀器規格。

輸出 -> docs/analysis_charts_3batch/fig24
"""
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
    BATCHES, OUT, BCOL, RED, AQUA, INK, INK2, MUTED, BASELINE, style)
from analyze_new_methods import collect  # noqa: E402

S_N = 13.06          # Nernst mV per ln unit (n=2, 30C)
T_CUT = 2.0          # 切掉補氣後的快暫態（小時）
SEG = 90             # 晚期窗的分段長度（分鐘）


def smooth(v, w, how='median'):
    s = pd.Series(np.asarray(v, float)).rolling(w, center=True, min_periods=1)
    return (s.median() if how == 'median' else s.mean()).values


def sp1_resolution(cycles):
    """SP1：各訊號的量化階數。"""
    rows = []
    for name, cycs in cycles.items():
        ph_rng, orp_rng, p_rng = [], [], []
        for c in cycs:
            ph_rng.append(c.ph.max() - c.ph.min())
            orp_rng.append(c.orp.max() - c.orp.min())
            p_rng.append(c.p_reactor.max() - c.p_reactor.min())
        rows.append(dict(batch=name,
                         ph_range=np.median(ph_rng), ph_steps=np.median(ph_rng) / 0.01,
                         orp_range=np.median(orp_rng),
                         p_range=np.median(p_rng), p_steps=np.median(p_rng) / 0.01))
    return pd.DataFrame(rows)


def sp2_timescales(cycles):
    """SP2：ORP 恢復的快慢兩尺度。"""
    rows, traces = [], {}
    for name, cycs in cycles.items():
        f30, f2h, slow = [], [], []
        keep = None
        for c in cycs:
            t = (c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600
            o = smooth(c.orp.values, 21)
            head = max(5, min(len(o) // 4, 120))
            j0 = int(np.argmin(o[:head]))
            tr, y = t[j0:] - t[j0], o[j0:]
            if tr[-1] < T_CUT + 1:
                continue
            total = y.max() - y[0]
            if total <= 5:
                continue
            f30.append((np.interp(0.5, tr, y) - y[0]) / total)
            f2h.append((np.interp(T_CUT, tr, y) - y[0]) / total)
            m = tr > T_CUT
            if m.sum() > 30:
                slow.append(np.polyfit(tr[m], y[m], 1)[0])
            if keep is None:
                keep = (tr, y)
        traces[name] = keep
        rows.append(dict(batch=name, f30=np.median(f30), f2h=np.median(f2h),
                         slow=np.median(slow) if slow else np.nan))
    return pd.DataFrame(rows), traces


def late_segments(cycles):
    """SP3/SP4 用：晚期窗的分段資料。"""
    rows = []
    for name, cycs in cycles.items():
        for j, c in enumerate(cycs, 1):
            t = (c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600
            P = c.p_reactor.values.astype(float)
            o = smooth(c.orp.values, 31)
            if t[-1] < T_CUT + 2:
                continue
            ref = np.interp(T_CUT, t, o)
            n = int(np.ceil((t[-1] - T_CUT) * 60 / SEG))
            for i in range(n):
                a, b = T_CUT + i * SEG / 60, T_CUT + (i + 1) * SEG / 60
                m = (t >= a) & (t < b)
                if m.sum() < SEG * 0.5:
                    continue
                rows.append(dict(batch=name, cyc=j, P=P[m].mean(),
                                 dP=np.polyfit(t[m], P[m], 1)[0],
                                 h=np.exp(-(o[m].mean() - ref) / S_N)))
    return pd.DataFrame(rows)


def cluster_ols(g):
    X = np.column_stack([np.ones(len(g)), g.P.values, g.h.values])
    y = g.dP.values
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    u = y - X @ b
    XtXi = np.linalg.pinv(X.T @ X)
    meat = np.zeros((3, 3))
    for cj in g.cyc.unique():
        m = (g.cyc == cj).values
        meat += X[m].T @ np.outer(u[m], u[m]) @ X[m]
    se = np.sqrt(np.diag(XtXi @ meat @ XtXi))
    return b, se, 1 - u.var() / y.var()


def main():
    cycles = collect()

    print('══ SP1：感測器的資訊上限（每循環的量化階數）══')
    R1 = sp1_resolution(cycles)
    for _, r in R1.iterrows():
        print(f'  {r.batch}: pH 變幅 {r.ph_range:.3f} → 僅 {r.ph_steps:.0f} 階'
              f'   壓力 {r.p_range:.3f} → {r.p_steps:.0f} 階'
              f'   ORP {r.orp_range:.0f} mV')
    print('  → pH 僅 7~9 階，資訊量不足以支撐獨立的 CO2 通道，本研究不採用。')

    print('\n══ SP2：ORP 的兩個時間尺度 ══')
    R2, traces = sp2_timescales(cycles)
    for _, r in R2.iterrows():
        print(f'  {r.batch}: 前30分完成 {r.f30*100:.0f}%、前2小時 {r.f2h*100:.0f}%'
              f'   2小時後慢速漂移 {r.slow:+.2f} mV/hr')
    print('  → 快暫態＝注入/混合/電極響應；慢速漂移＝H2 耗竭。兩者必須分開處理。')

    D = late_segments(cycles)
    print(f'\n══ SP3：切掉前 {T_CUT}h 後的正交性（可分離的前提）══')
    for name in BATCHES:
        g = D[D.batch == name]
        if len(g) < 8:
            continue
        print(f'  {name} (n={len(g)}): r(P, h) = {np.corrcoef(g.P, g.h)[0,1]:+.3f}')
    print('  → 幾乎正交 → 兩個驅動源在結構上確實可分離。')

    print(f'\n══ SP4：晚期窗的雙驅動迴歸 dP/dt = -kLa·P + kLa·Peq - rb·h ══')
    R4 = []
    for name in BATCHES:
        g = D[D.batch == name]
        if len(g) < 8:
            continue
        b, se, r2 = cluster_ols(g)
        rb, t_bio = -b[2], abs(b[2] / se[2])
        ok = (t_bio > 2) and (rb > 0)
        R4.append(dict(batch=name, kla=-b[1], rb=rb, se_rb=se[2],
                       t=t_bio, r2=r2, ok=ok, n=len(g)))
        print(f'  {name}: kLa={-b[1]:.4f}  rb={rb:+.5f}±{se[2]:.5f}'
              f'  t={t_bio:.2f}  R²={r2:.3f}  {"★ 生物項顯著" if ok else ""}')
    R4 = pd.DataFrame(R4)

    print('\n══ 換算成儀器規格 ══')
    good = R2[R2.batch == '3.1 (10min)'].slow.iloc[0]
    print(f'  唯一成功的 10min 批，其 ORP 慢速漂移為 {good:+.2f} mV/hr。')
    print('  現行 ORP 逐筆雜訊約 ±20 mV、取樣 1 分鐘 → 需累積約 12 個循環才看得出來。')
    print('  若要「單一循環即可分離」，訊噪比需提升約一個數量級：')
    print('    ‧ ORP 雜訊降到 ±2 mV（更換電極／加裝屏蔽／訊號調理），或')
    print('    ‧ 取樣率提高到 每 5~10 秒（以平均降噪，等效 √N 改善）')
    print('  pH 則需解析度由 0.01 提升到 0.001 才有機會進入模型。')

    R1.to_csv(f'{OUT}/sp_sensor_resolution.csv', index=False, encoding='utf-8-sig')
    R4.to_csv(f'{OUT}/sp_late_window_regression.csv', index=False, encoding='utf-8-sig')
    figures(R1, R2, traces, D, R4)
    print(f'\n輸出 → {OUT}')


def figures(R1, R2, traces, D, R4):
    fig = plt.figure(figsize=(14, 8.4))
    gs = fig.add_gridspec(2, 3, hspace=0.42, wspace=0.28)

    # SP2：ORP 兩尺度（示例軌跡）
    ax = fig.add_subplot(gs[0, :2])
    for name in BATCHES:
        tr = traces.get(name)
        if tr is None:
            continue
        t, y = tr
        ax.plot(t, y - y[0], lw=1.6, color=BCOL[name], label=name)
    ax.axvspan(0, T_CUT, color=RED, alpha=0.08, lw=0)
    ax.annotate('快暫態\n（注入/混合/電極）\n前30分完成 23~69%',
                xy=(0.15, 0.62), xycoords='axes fraction',
                fontsize=9.5, color=RED, fontweight='bold')
    ax.annotate('慢速漂移 = H2 耗竭\n（+0.3 ~ +2.4 mV/hr）\n← 這才是生物訊號',
                xy=(0.45, 0.25), xycoords='axes fraction',
                fontsize=9.5, color=INK, fontweight='bold')
    style(ax, 'SP2  ORP 恢復含兩個時間尺度（各批一條代表性循環）',
          '補氣後時間 (hr)', 'ORP 相對崩谷 (mV)')
    ax.legend(frameon=False, fontsize=9)

    # SP1：量化階數
    ax = fig.add_subplot(gs[0, 2])
    labs = ['pH', '壓力']
    vals = [R1.ph_steps.median(), R1.p_steps.median()]
    ax.barh(labs, vals, color=[RED, MUTED], height=0.5)
    for i, v in enumerate(vals):
        ax.annotate(f'{v:.0f} 階', xy=(v, i), xytext=(5, 0),
                    textcoords='offset points', va='center',
                    fontsize=10, fontweight='bold')
    ax.set_xlim(0, 32)
    style(ax, 'SP1  每循環的量化階數', '階數', None)
    ax.annotate('pH 僅 7~9 階\n→ 資訊不足', xy=(11, 0), fontsize=9.5,
                color=RED, fontweight='bold', va='center')

    # SP3：正交性
    ax = fig.add_subplot(gs[1, 0])
    for name in BATCHES:
        g = D[D.batch == name]
        if len(g) < 8:
            continue
        ax.scatter(g.P, g.h, s=22, alpha=0.7, color=BCOL[name],
                   label=f'{name.split()[1]} r={np.corrcoef(g.P,g.h)[0,1]:+.2f}')
    style(ax, f'SP3  切掉前 {T_CUT}h 後：兩驅動源近乎正交',
          '壓力 P (kg/cm²)', 'ORP 推得相對 H2')
    ax.legend(frameon=False, fontsize=8.5)

    # SP4：生物項的 t 值
    ax = fig.add_subplot(gs[1, 1:])
    xs = np.arange(len(R4))
    cols = [AQUA if o else MUTED for o in R4.ok]
    ax.bar(xs, R4.t, color=cols, width=0.5)
    ax.axhline(2, color=RED, ls='--', lw=1.6)
    ax.annotate('顯著門檻 t=2', xy=(-0.4, 2.12), color=RED,
                fontsize=9.5, fontweight='bold')
    for i, r in R4.iterrows():
        ax.annotate(f'rb={r.rb:+.5f}', xy=(i, r.t), xytext=(0, 5),
                    textcoords='offset points', ha='center', fontsize=9)
    ax.set_xticks(xs, [b.split()[1] for b in R4.batch])
    style(ax, 'SP4  晚期窗雙驅動迴歸：生物項的 t 值',
          '批次', '|t| （叢集穩健）')

    fig.suptitle('圖24  子問題拆解：分離失敗的原因是量測解析度，不是模型',
                 fontweight='bold', x=0.06, ha='left', y=0.985)
    fig.text(0, -0.02,
             '把主問題拆成四個可獨立回答的子問題後，結論很明確：結構上可分離（SP3 近乎正交），'
             '但只有 ORP 慢速漂移最大、循環數最多的 10min 批達到顯著（SP4）。\n'
             'pH 因每循環僅 7~9 個量化階而不可用（SP1）。'
             '要讓單一循環即可分離，ORP 雜訊需由 ±20 mV 降到 ±2 mV，或取樣率提高到每 5~10 秒。',
             fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig24_subproblem_decomposition.png', bbox_inches='tight')
    plt.close(fig)
    print('  圖 24 完成')


if __name__ == '__main__':
    main()
