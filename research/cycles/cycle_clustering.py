# -*- coding: utf-8 -*-
"""群聚檢定：壓降曲線的「形狀」認不認得出碳源什麼時候用完？

2026-09-21。補 co2_exhaustion_test.py 的不足。

════════════════════════════════════════════════════════════════════════
為什麼要做這個

  co2_exhaustion_test.py 只比了**一個數字**（平均下降速率），得到虛無。
  但生物活動可能不改變平均速率、卻改變曲線的**形狀**（例如彎曲程度、
  前後半段的快慢、殘差結構）。只比一個數字看不到這種差別。

  所以改問一個不預設答案的問題：把每個循環變成一組特徵，**完全不告訴
  演算法哪些是碳源充足、哪些是碳源用完**，讓它自己分兩群。然後才去看
  分出來的群和真實時期對不對得上。

      對得上  -> 碳源狀態在曲線形狀裡留下痕跡 -> 生物確實有貢獻
      對不上  -> 形狀上分不出來 -> 支持「壓降主要不是生物造成的」

  這是把分類器雙樣本檢定（見 simulator_validation_ar1）改成非監督版本：
  非監督更保守，因為它不會為了配合標籤而過度擬合。

  ⚠ 虛無若沒有檢定力就不是證據。故一併做：
    (a) 置換虛無：打散時期標籤 2000 次，看真實的吻合度落在哪
    (b) 陽性對照：拿同一批特徵去分「長循環 vs 短循環」，確認方法本身抓得到
        真的存在的結構（若連這個都抓不到，是方法壞了不是沒有訊號）

輸出 -> docs/analysis_charts_3batch/cycle_clustering.csv
"""
import csv
import datetime as dt
import glob
import os
import sys

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from co2_exhaustion_test import (                       # noqa: E402
    AUTO, ATM, CUT_A, CUT_B, OUT, descents, load)

FEATS = ['時長', '降幅', '平均速率', '起始壓力', '彎曲程度',
         '前半段比後半段快', '殘差大小', '直線貼合度']


def features(ts, hh, p, s, e):
    """一個循環 -> 一組特徵。刻意只用壓力，不用任何氣體讀數（否則是循環論證）。"""
    t = hh[s:e + 1] - hh[s]
    y = p[s:e + 1]
    dur, drop = float(t[-1]), float(y[0] - y[-1])
    A = np.vstack([t, np.ones_like(t)]).T
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    res = y - A @ coef
    st = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float(res @ res) / st if st > 0 else np.nan
    # 彎曲程度：二次項係數（正 = 先快後慢，像指數鬆弛）
    c2 = np.polyfit(t, y, 2)[0]
    half = len(t) // 2
    r_first = (y[0] - y[half]) / max(t[half], 1e-6)
    r_second = (y[half] - y[-1]) / max(t[-1] - t[half], 1e-6)
    return [dur, drop, drop / dur, float(y[0]), float(c2),
            r_first / r_second if r_second > 1e-9 else np.nan,
            float(res.std(ddof=1)), r2]


def kmeans2(Z, seed=0, n_init=50):
    """k=2 的 k-means（純 numpy，避免多帶一個部署端不可用的相依）。"""
    rng = np.random.default_rng(seed)
    best, best_sse = None, np.inf
    for _ in range(n_init):
        ctr = Z[rng.choice(len(Z), 2, replace=False)]
        for _ in range(100):
            d = ((Z[:, None, :] - ctr[None, :, :]) ** 2).sum(2)
            lab = d.argmin(1)
            if len(set(lab)) < 2:
                break
            new = np.array([Z[lab == k].mean(0) for k in range(2)])
            if np.allclose(new, ctr):
                ctr = new
                break
            ctr = new
        d = ((Z[:, None, :] - ctr[None, :, :]) ** 2).sum(2)
        lab = d.argmin(1)
        sse = d.min(1).sum()
        if sse < best_sse:
            best, best_sse = lab, sse
    return best


def agreement(lab, truth):
    """兩群與真實時期的最佳吻合率（兩種對應取較高者）。"""
    a = (lab == truth).mean()
    return max(a, 1 - a)


def pca2(Z):
    U, S, Vt = np.linalg.svd(Z - Z.mean(0), full_matrices=False)
    return (Z - Z.mean(0)) @ Vt[:2].T, (S ** 2 / (S ** 2).sum())[:2], Vt[:2]


def main():
    ts, hh, p, c, m = load(AUTO)
    segs = descents(hh, p)
    X, truth, meta = [], [], []
    for s, e in segs:
        d = ts[s].date()
        if CUT_A < d < CUT_B:                 # 08-23/24 過渡期不用
            continue
        f = features(ts, hh, p, s, e)
        if not np.all(np.isfinite(f)):
            continue
        X.append(f)
        truth.append(0 if d <= CUT_A else 1)
        meta.append((ts[s], d, float(np.median(c[s:e + 1]))))
    X = np.array(X)
    truth = np.array(truth)
    print('循環 %d（碳源充足 %d／碳源用完 %d），特徵 %d 個'
          % (len(X), (truth == 0).sum(), (truth == 1).sum(), X.shape[1]))
    print('特徵：' + '、'.join(FEATS))

    Z = (X - X.mean(0)) / X.std(0, ddof=1)
    P, var, comp = pca2(Z)
    print('\n前兩個主成分解釋 %.0f%% 的變異' % (var.sum() * 100))

    lab = kmeans2(Z)
    acc = agreement(lab, truth)
    base = max(truth.mean(), 1 - truth.mean())
    print('\n── 主檢定：不給標籤，自己分兩群 ──')
    print('   分出的群 vs 真實時期　吻合率 %.1f%%（全猜多數類的基線 %.1f%%）'
          % (acc * 100, base * 100))

    rng = np.random.default_rng(1)
    null = np.array([agreement(lab, rng.permutation(truth)) for _ in range(2000)])
    pv = (null >= acc).mean()
    print('   置換虛無：打散時期標籤 2000 次 → 吻合率 %.1f%% ± %.1f%%，p = %.3f'
          % (null.mean() * 100, null.std() * 100, pv))
    print('   → %s' % ('形狀分得出來' if pv < 0.05 else
                       '形狀分不出來：碳源狀態沒有在壓降曲線上留下可辨識的痕跡'))

    print('\n── 陽性對照：同一套方法去分「長循環 vs 短循環」──')
    long_short = (np.array([x[0] for x in X]) > np.median([x[0] for x in X])).astype(int)
    acc2 = agreement(lab, long_short)
    null2 = np.array([agreement(lab, rng.permutation(long_short)) for _ in range(2000)])
    print('   吻合率 %.1f%%，p = %.3f → %s'
          % (acc2 * 100, (null2 >= acc2).mean(),
             '方法抓得到真的存在的結構' if (null2 >= acc2).mean() < 0.05 else '⚠ 連陽性對照都抓不到，方法有問題'))

    print('\n── 靈敏度更高的監督式檢定（分類器雙樣本檢定）──')
    print('   群聚只看得到最強的結構；這裡直接問「有沒有任何分類器分得出來」。')
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import roc_auc_score

    def cv_auc(y, seed=0):
        """分層 5 折交叉驗證的 AUC。用交叉驗證才不會被過度擬合騙。"""
        skf = StratifiedKFold(5, shuffle=True, random_state=seed)
        oof = np.zeros(len(y))
        for tr, te in skf.split(Z, y):
            clf = RandomForestClassifier(300, min_samples_leaf=3,
                                         random_state=seed, n_jobs=1).fit(Z[tr], y[tr])
            oof[te] = clf.predict_proba(Z[te])[:, 1]
        return roc_auc_score(y, oof)

    auc = float(np.mean([cv_auc(truth, s_) for s_ in range(5)]))
    rng2 = np.random.default_rng(7)
    nullA = np.array([cv_auc(rng2.permutation(truth), 0) for _ in range(120)])
    pA = float((nullA >= auc).mean())
    print('   交叉驗證 AUC = %.3f（0.5 = 完全分不出）　置換虛無 %.3f ± %.3f　p = %.3f'
          % (auc, nullA.mean(), nullA.std(), pA))
    if pA < 0.05:
        clf = RandomForestClassifier(300, min_samples_leaf=3, random_state=0).fit(Z, truth)
        imp = clf.feature_importances_
        order = np.argsort(imp)[::-1]
        print('   → 分得出來。最有貢獻的特徵：'
              + '、'.join('%s(%.2f)' % (FEATS[i], imp[i]) for i in order[:3]))
        print('   ⚠ 但「分得出來」不等於「生物造成的」：兩個時期在時間上前後相接，')
        print('     任何隨時間漂移的東西（菌齡、液位、管路、室溫）都會被分出來。')

        # ── 安慰劑：把「碳源充足」那段自己切兩半，兩半碳源都充足 ──
        #    若這樣也分得出來，上面的 AUC 就是時間漂移，不是碳源狀態。
        i0 = np.flatnonzero(truth == 0)
        half = i0[len(i0) // 2]
        fake = np.where(np.arange(len(truth)) <= half, 0, 1)[i0]
        Zc, Zall = Z[i0], Z
        def cv_auc_sub(Zs, y, seed=0):
            skf = StratifiedKFold(5, shuffle=True, random_state=seed)
            oof = np.zeros(len(y))
            for tr, te in skf.split(Zs, y):
                cl = RandomForestClassifier(300, min_samples_leaf=3,
                                            random_state=seed, n_jobs=1).fit(Zs[tr], y[tr])
                oof[te] = cl.predict_proba(Zs[te])[:, 1]
            return roc_auc_score(y, oof)
        aucP = float(np.mean([cv_auc_sub(Zc, fake, s_) for s_ in range(5)]))
        rng3 = np.random.default_rng(11)
        nullP = np.array([cv_auc_sub(Zc, rng3.permutation(fake), 0) for _ in range(120)])
        pP = float((nullP >= aucP).mean())
        print('\n   ── 安慰劑：碳源充足期自己切兩半（兩半碳源都充足）──')
        print('      AUC = %.3f　p = %.3f　→ %s'
              % (aucP, pP,
                 '⚠ 安慰劑也分得出來 → 前面的 AUC 是時間漂移，不能歸因於碳源'
                 if pP < 0.05 else '安慰劑分不出來 → 前面的 AUC 確實跟著碳源狀態走'))
    else:
        print('   → 連監督式分類器都分不出來，虛無比群聚版更有力。')

    print('\n── 各特徵在兩個時期的中位數 ──')
    print('   %-16s %12s %12s %8s'  % ('特徵', '碳源充足', '碳源用完', '差異'))
    for j, nm in enumerate(FEATS):
        a, b = np.median(X[truth == 0, j]), np.median(X[truth == 1, j])
        print('   %-16s %12.4f %12.4f %+7.1f%%'
              % (nm, a, b, (b / a - 1) * 100 if a else 0))

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'cycle_clustering.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['起始時刻', '日期', 'CO2中位', '時期', '分群', 'PC1', 'PC2'] + FEATS)
        for i, (t0, d, cc) in enumerate(meta):
            w.writerow([t0.strftime('%Y-%m-%d %H:%M'), d, round(cc, 2),
                        '碳源充足' if truth[i] == 0 else '碳源用完', int(lab[i]),
                        round(P[i, 0], 4), round(P[i, 1], 4)]
                       + [round(v, 5) for v in X[i]])
    print('\n逐循環明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(meta)))
    return X, truth, lab, P, var


if __name__ == '__main__':
    main()
