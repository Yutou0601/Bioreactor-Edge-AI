# -*- coding: utf-8 -*-
"""可部署 LSTM 的三項部署決策分析（2026-08-04）。

不是為了好看，是為了回答三個實際的部署問題：

  D1 預測地平線：能可靠預測到多久之後？（決定補氣排程的提前量）
  D2 感測器消融：ORP / pH 這兩支感測器是否值得裝？（決定硬體成本）
  D3 循環內誤差分布：預測在循環的哪個階段最不準？（決定何時該保守）

模型固定為**因果單向 LSTM**（唯一可即時部署者），
以 GroupKFold（依循環分組）評估，避免同一循環同時出現在訓練與測試。

輸出 -> docs/analysis_charts_3batch/fig29
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.model_selection import GroupKFold

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (  # noqa: E402
    OUT, RED, AQUA, BLUE, INK, INK2, MUTED, BASELINE, style)
from analyze_new_methods import collect  # noqa: E402

W = 60
HORIZONS = (15, 30, 60, 120, 240)
SENSORS = {'僅壓力': [0], '壓力+ORP': [0, 1], '壓力+ORP+pH': [0, 1, 2]}
NFOLD, EPOCHS, SEED = 3, 30, 0


def build(cycles, H):
    """回傳 X(視窗), y(H 分鐘後壓力), g(循環 id), frac(循環內相對位置)。"""
    Xs, ys, gs, fr = [], [], [], []
    gid = 0
    for name, cycs in cycles.items():
        for c in cycs:
            p = c.p_reactor.values.astype(float)
            o = c.orp.values.astype(float)
            h = c.ph.values.astype(float)
            n = len(p)
            for i in range(0, n - W - H):
                Xs.append(np.stack([p[i:i + W], o[i:i + W], h[i:i + W]], -1))
                ys.append(p[i + W + H - 1])
                gs.append(gid)
                fr.append((i + W) / n)
            gid += 1
    return (np.array(Xs, np.float32), np.array(ys, np.float32),
            np.array(gs), np.array(fr))


def run_lstm(Xtr, ytr, Xte, cols):
    import torch
    import torch.nn as nn
    torch.manual_seed(SEED)
    Xtr, Xte = Xtr[:, :, cols], Xte[:, :, cols]
    mu = Xtr.reshape(-1, len(cols)).mean(0)
    sd = Xtr.reshape(-1, len(cols)).std(0) + 1e-8

    class Net(nn.Module):
        def __init__(self, nin, hid=32):
            super().__init__()
            self.l = nn.LSTM(nin, hid, batch_first=True)
            self.h = nn.Linear(hid, 1)

        def forward(self, x):
            o, _ = self.l(x)
            return self.h(o[:, -1]).squeeze(-1)

    net = Net(len(cols))
    opt = torch.optim.Adam(net.parameters(), lr=3e-3)
    lf = nn.MSELoss()
    Xt = torch.tensor((Xtr - mu) / sd)
    yt = torch.tensor(ytr)
    n = len(Xt)
    for _ in range(EPOCHS):
        perm = torch.randperm(n)
        for i in range(0, n, 256):
            b = perm[i:i + 256]
            opt.zero_grad()
            lf(net(Xt[b]), yt[b]).backward()
            opt.step()
    net.eval()
    with torch.no_grad():
        return net(torch.tensor((Xte - mu) / sd)).numpy()


def cv_rmse(X, y, g, cols, extra=None):
    """回傳整體 RMSE，並可另外回傳逐樣本誤差。"""
    err = np.empty(len(y))
    for tr, te in GroupKFold(n_splits=NFOLD).split(X, y, g):
        err[te] = run_lstm(X[tr], y[tr], X[te], cols) - y[te]
    return float(np.sqrt(np.mean(err ** 2))), err


def main():
    cycles = collect()

    print('══ D1 預測地平線：能可靠預測到多久之後？══')
    d1 = []
    for H in HORIZONS:
        X, y, g, fr = build(cycles, H)
        r, _ = cv_rmse(X, y, g, [0, 1, 2])
        # 平凡基準：persistence
        pers = float(np.sqrt(np.mean((X[:, -1, 0] - y) ** 2)))
        d1.append(dict(H=H, rmse=r, persistence=pers, gain=pers / r, n=len(X)))
        print(f'   H={H:3d} 分鐘：LSTM RMSE={r:.5f}  persistence={pers:.5f}'
              f'  優於基準 {pers/r:.1f}x   (n={len(X)})')
    D1 = pd.DataFrame(d1)

    print('\n══ D2 感測器消融：ORP / pH 值不值得裝？══')
    X, y, g, fr = build(cycles, 60)
    d2 = []
    base = None
    for lab, cols in SENSORS.items():
        r, err = cv_rmse(X, y, g, cols)
        if base is None:
            base = r
        d2.append(dict(config=lab, ncols=len(cols), rmse=r,
                       improve=(base - r) / base * 100))
        print(f'   {lab:14s} RMSE={r:.5f}   相對僅壓力改善 {(base-r)/base*100:+5.1f}%')
        if lab == '壓力+ORP+pH':
            err_full = err
    D2 = pd.DataFrame(d2)

    print('\n══ D3 循環內誤差分布：何時最不準？══')
    q = pd.qcut(fr, 5, labels=False)
    d3 = []
    for b in range(5):
        m = q == b
        d3.append(dict(bin=b, frac_lo=fr[m].min(), frac_hi=fr[m].max(),
                       rmse=float(np.sqrt(np.mean(err_full[m] ** 2))),
                       n=int(m.sum())))
        print(f'   循環內 {fr[m].min():.2f}~{fr[m].max():.2f}：'
              f'RMSE={d3[-1]["rmse"]:.5f}  (n={d3[-1]["n"]})')
    D3 = pd.DataFrame(d3)

    for df, fn in ((D1, 'ml_horizon'), (D2, 'ml_sensor_ablation'),
                   (D3, 'ml_error_by_phase')):
        df.to_csv(f'{OUT}/{fn}.csv', index=False, encoding='utf-8-sig')
    figures(D1, D2, D3)
    print(f'\n輸出 → {OUT}')


def figures(D1, D2, D3):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))

    ax = axes[0]
    ax.plot(D1.H, D1.rmse * 1000, 'o-', ms=8, lw=2.2, color=AQUA, label='因果 LSTM')
    ax.plot(D1.H, D1.persistence * 1000, 's--', ms=7, lw=1.8, color=MUTED,
            label='persistence 基準')
    for _, r in D1.iterrows():
        ax.annotate(f'{r.gain:.1f}x', xy=(r.H, r.rmse * 1000), xytext=(0, -16),
                    textcoords='offset points', ha='center',
                    fontsize=9, color=INK, fontweight='bold')
    style(ax, '(D1) 預測地平線：能看多遠？',
          '預測地平線 H (分鐘)', 'RMSE (×10⁻³ kg/cm²)')
    ax.legend(frameon=False, fontsize=9)

    ax = axes[1]
    c = [MUTED, BLUE, AQUA]
    ax.bar(range(len(D2)), D2.rmse * 1000, color=c, width=0.55)
    for i, r in D2.iterrows():
        ax.annotate(f'{r.rmse*1000:.2f}' +
                    (f'\n({r.improve:+.1f}%)' if i else ''),
                    xy=(i, r.rmse * 1000), xytext=(0, 4),
                    textcoords='offset points', ha='center', fontsize=9.5)
    ax.set_xticks(range(len(D2)), D2.config, fontsize=9.5)
    style(ax, '(D2) 感測器消融：多裝的感測器值不值得？',
          None, 'RMSE (×10⁻³ kg/cm²)')

    ax = axes[2]
    mid = (D3.frac_lo + D3.frac_hi) / 2
    ax.plot(mid, D3.rmse * 1000, 'o-', ms=8, lw=2.2, color=RED)
    style(ax, '(D3) 循環內誤差分布：何時最不準？',
          '循環內相對位置（0=補氣後、1=谷底）', 'RMSE (×10⁻³ kg/cm²)')

    fig.suptitle('圖29  可部署因果 LSTM 的三項部署決策分析',
                 fontweight='bold', x=0.05, ha='left')
    fig.text(0, -0.10,
             '模型固定為因果單向 LSTM（唯一可即時部署者），GroupKFold 依循環分組。\n'
             '(D1) 決定補氣排程可提前多久發出；(D2) 決定 ORP/pH 感測器的硬體投資是否划算；'
             '(D3) 決定在循環的哪個階段該對預測保守。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig29_ml_deployment.png', bbox_inches='tight')
    plt.close(fig)
    print('  圖 29 完成')


if __name__ == '__main__':
    main()
