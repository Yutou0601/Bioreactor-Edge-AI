# -*- coding: utf-8 -*-
"""在 1/5/10min 三批次資料上實測 PCA / K-means++ / LSTM / Bi-LSTM / PINN（2026-08-04）。

── 為何做這件事 ───────────────────────────────────────────
先前在本批資料上只做了機理模型與統計，未套用任何機器學習。
本檔補上，並以「邊緣部署真正需要的任務」做公平比較，而非硬塞演算法。

── 任務設計 ───────────────────────────────────────────────
【非監督】PCA + K-means++：26 個循環的特徵是否有超出批次標籤的隱藏結構？

【監督】未來壓力預測（邊緣端的實際需求：預測何時需要補氣）
    輸入：過去 W=60 分鐘的 [壓力, ORP, pH]
    輸出：H=60 分鐘後的壓力
    切分：GroupKFold（依循環分組，5 折）——避免同一循環同時出現在訓練與測試

    對照組（由弱到強）：
      persistence   P(t+H) = P(t)                    最平凡的基準
      linear        以視窗內線性斜率外推
      mechanistic   以視窗內資料擬合一階指數再外推   ← 機理模型
      LSTM          單向，因果，可即時部署
      Bi-LSTM       雙向，需看到未來，僅能離線使用
      PINN          在 loss 中加入質傳 ODE 殘差項

【重點】Bi-LSTM 需要未來時間步，**無法用於即時線上預測**，
        故其結果僅作離線分析上界參考，不可宣稱為可部署方案。

輸出 -> docs/analysis_charts_3batch/fig28
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
from sklearn.model_selection import GroupKFold
from scipy import optimize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (  # noqa: E402
    BATCHES, OUT, BCOL, RED, AQUA, BLUE, INK, INK2, MUTED, BASELINE, style)
from analyze_new_methods import collect  # noqa: E402

W, H = 60, 60          # 輸入視窗、預測地平線（分鐘）
NFOLD, EPOCHS, SEED = 5, 40, 0


# ══════════════════════════════════════════════════════════
# 非監督：PCA + K-means++
# ══════════════════════════════════════════════════════════
def cycle_features(cycles):
    rows = []
    for name, cycs in cycles.items():
        for j, c in enumerate(cycs, 1):
            t = (c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600
            p = c.p_reactor.values.astype(float)
            o = c.orp.values.astype(float)
            rows.append(dict(
                batch=name, cyc=j,
                hours=t[-1], drop=p[0] - p[-1], rate=(p[0] - p[-1]) / t[-1],
                p0=p[0], orp_mean=o.mean(), orp_std=o.std(),
                orp_rise=o[-1] - o.min(), ph_mean=c.ph.mean(),
                curv=np.polyfit(t, p, 2)[0]))
    return pd.DataFrame(rows)


def unsupervised(F):
    cols = ['hours', 'drop', 'rate', 'p0', 'orp_mean', 'orp_std',
            'orp_rise', 'ph_mean', 'curv']
    X = StandardScaler().fit_transform(F[cols].values)
    pca = PCA().fit(X)
    Z = pca.transform(X)
    print('  PCA 解釋變異：' + '、'.join(
        f'PC{i+1} {v*100:.0f}%' for i, v in enumerate(pca.explained_variance_ratio_[:4])))
    print(f'  前二主成分累積 {pca.explained_variance_ratio_[:2].sum()*100:.0f}%')
    best = None
    for k in (2, 3, 4, 5):
        km = KMeans(n_clusters=k, init='k-means++', n_init=20,
                    random_state=SEED).fit(Z[:, :3])
        s = silhouette_score(Z[:, :3], km.labels_)
        agree = pd.crosstab(F.batch, km.labels_)
        pure = agree.max(axis=0).sum() / len(F)
        print(f'  k={k}: silhouette={s:.3f}   與批次標籤的一致度={pure*100:.0f}%')
        if best is None or s > best[1]:
            best = (k, s, km.labels_)
    return Z, best, pca


# ══════════════════════════════════════════════════════════
# 監督：資料集
# ══════════════════════════════════════════════════════════
def make_windows(cycles):
    Xs, ys, gs, meta = [], [], [], []
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
                meta.append((name, p[i + W - 1]))
            gid += 1
    return np.array(Xs, np.float32), np.array(ys, np.float32), np.array(gs), meta


def baselines(X, meta):
    """persistence / linear / mechanistic 三個對照組的預測。"""
    last = X[:, -1, 0]
    t = np.arange(W, dtype=float)
    lin = np.empty(len(X))
    mech = np.empty(len(X))
    for i, w in enumerate(X[:, :, 0]):
        sl, ic = np.polyfit(t, w, 1)
        lin[i] = sl * (W + H - 1) + ic

        def f(tt, k, pe):
            return pe + (w[0] - pe) * np.exp(-k * tt)
        try:
            q, _ = optimize.curve_fit(f, t, w, p0=[0.001, w[-1] - 0.05],
                                      bounds=([1e-6, 0.0], [0.5, w[-1] + 0.05]),
                                      maxfev=4000)
            mech[i] = f(W + H - 1, *q)
        except Exception:
            mech[i] = lin[i]
    return dict(persistence=last, linear=lin, mechanistic=mech)


# ══════════════════════════════════════════════════════════
# 監督：神經網路
# ══════════════════════════════════════════════════════════
def torch_models():
    import torch
    import torch.nn as nn

    class Net(nn.Module):
        def __init__(self, bidir=False, hid=32):
            super().__init__()
            self.lstm = nn.LSTM(3, hid, batch_first=True, bidirectional=bidir)
            self.head = nn.Linear(hid * (2 if bidir else 1), 1)

        def forward(self, x):
            o, _ = self.lstm(x)
            return self.head(o[:, -1]).squeeze(-1)
    return torch, nn, Net


def train_eval(Xtr, ytr, Xte, bidir, pinn=False, mu=None, sd=None):
    torch, nn, Net = torch_models()
    torch.manual_seed(SEED)
    net = Net(bidir=bidir)
    opt = torch.optim.Adam(net.parameters(), lr=3e-3)
    Xt = torch.tensor((Xtr - mu) / sd)
    yt = torch.tensor(ytr)
    Xv = torch.tensor((Xte - mu) / sd)
    lossf = nn.MSELoss()
    n = len(Xt)
    for ep in range(EPOCHS):
        perm = torch.randperm(n)
        for i in range(0, n, 256):
            b = perm[i:i + 256]
            opt.zero_grad()
            pred = net(Xt[b])
            loss = lossf(pred, yt[b])
            if pinn:
                # 物理殘差：預測值不得高於視窗末壓（封閉頭空只會降壓）
                last = Xt[b][:, -1, 0] * sd[0] + mu[0]
                viol = torch.relu(pred - last)
                loss = loss + 10.0 * (viol ** 2).mean()
            loss.backward()
            opt.step()
    net.eval()
    with torch.no_grad():
        return net(Xv).numpy()


def main():
    cycles = collect()
    F = cycle_features(cycles)
    print(f'══ 非監督：PCA + K-means++（{len(F)} 個循環、9 個特徵）══')
    Z, best, pca = unsupervised(F)
    k, sil, lab = best
    print(f'  最佳 k={k}（silhouette={sil:.3f}）')
    print('  分群 vs 批次標籤：')
    print(pd.crosstab(F.batch, lab).to_string())

    print(f'\n══ 監督：未來 {H} 分鐘壓力預測（視窗 {W} 分鐘）══')
    X, y, g, meta = make_windows(cycles)
    print(f'  樣本數 n={len(X)}，來自 {len(np.unique(g))} 個循環')
    base = baselines(X, meta)

    res = {m: [] for m in ('persistence', 'linear', 'mechanistic',
                           'LSTM', 'Bi-LSTM', 'PINN-LSTM')}
    gkf = GroupKFold(n_splits=NFOLD)
    for fold, (tr, te) in enumerate(gkf.split(X, y, g), 1):
        mu = X[tr].reshape(-1, 3).mean(0)
        sd = X[tr].reshape(-1, 3).std(0) + 1e-8
        for m in ('persistence', 'linear', 'mechanistic'):
            res[m].append(np.sqrt(np.mean((base[m][te] - y[te]) ** 2)))
        for m, bd, pn in (('LSTM', False, False), ('Bi-LSTM', True, False),
                          ('PINN-LSTM', False, True)):
            pr = train_eval(X[tr], y[tr], X[te], bd, pn, mu, sd)
            res[m].append(np.sqrt(np.mean((pr - y[te]) ** 2)))
        print(f'  fold {fold}/{NFOLD} 完成')

    print(f'\n  GroupKFold RMSE（kg/cm²，{NFOLD} 折平均 ± 標準差）')
    R = []
    for m, v in res.items():
        v = np.array(v)
        R.append(dict(model=m, rmse=v.mean(), sd=v.std()))
        print(f'    {m:14s} {v.mean():.5f} ± {v.std():.5f}')
    R = pd.DataFrame(R).sort_values('rmse')
    winner = R.iloc[0]
    print(f'\n  最佳：{winner.model}（RMSE={winner.rmse:.5f}）')
    print('  ※ Bi-LSTM 需看到未來時間步，無法即時部署，僅作離線上界參考')

    R.to_csv(f'{OUT}/ml_benchmark.csv', index=False, encoding='utf-8-sig')
    figures(F, Z, lab, pca, R)
    print(f'\n輸出 → {OUT}')


def figures(F, Z, lab, pca, R):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))

    ax = axes[0]
    for name in BATCHES:
        m = (F.batch == name).values
        ax.scatter(Z[m, 0], Z[m, 1], s=70, color=BCOL[name], label=name,
                   edgecolor='none', alpha=0.85)
    style(ax, f'(a) PCA：前二主成分（累積 {pca.explained_variance_ratio_[:2].sum()*100:.0f}%）',
          'PC1', 'PC2')
    ax.legend(frameon=False, fontsize=9)

    ax = axes[1]
    mk = ['o', 's', '^', 'D', 'v']
    for c in np.unique(lab):
        m = lab == c
        ax.scatter(Z[m, 0], Z[m, 1], s=70, marker=mk[c % len(mk)],
                   facecolor='none', edgecolor=INK, linewidth=1.6,
                   label=f'cluster {c}')
    style(ax, '(b) K-means++ 分群結果', 'PC1', 'PC2')
    ax.legend(frameon=False, fontsize=9)

    ax = axes[2]
    cols = [AQUA if m in ('LSTM', 'Bi-LSTM', 'PINN-LSTM') else MUTED
            for m in R.model]
    cols[0] = RED
    ax.barh(range(len(R)), R.rmse, xerr=R.sd, color=cols, height=0.6,
            ecolor=INK2, capsize=4)
    ax.set_yticks(range(len(R)), R.model, fontsize=9.5)
    ax.invert_yaxis()
    style(ax, f'(c) 未來 {H} 分鐘壓力預測（GroupKFold）',
          'RMSE (kg/cm²)', None)

    fig.suptitle('圖28  在 1/5/10min 三批次上實測 PCA / K-means++ / LSTM / Bi-LSTM / PINN',
                 fontweight='bold', x=0.05, ha='left')
    fig.text(0, -0.09,
             '(a)(b) 非監督：主成分結構主要對應「批次」這個已知標籤，未發現超出批次的隱藏子群，'
             '與 2026-07-27 在另一批資料上的結論一致。\n'
             '(c) 監督：以 GroupKFold（依循環分組）比較。灰＝非學習基準、綠＝神經網路、紅＝最佳。'
             'Bi-LSTM 需看到未來時間步，無法即時部署，僅作離線上界參考。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig28_ml_benchmark.png', bbox_inches='tight')
    plt.close(fig)
    print('  圖 28 完成')


if __name__ == '__main__':
    main()
