
# -*- coding: utf-8 -*-
"""
模擬器驗證：模擬出來的循環，跟真的分不分得出來？
════════════════════════════════════════════════════════════════════════

**為什麼這一步不能跳過**：SBI（模擬式推論）的後驗只在模擬器正確時才正確。
若模擬器錯了，SBI 會給出**又窄又錯**的後驗——比現在的硬門檻做法更危險，
因為錯誤被藏在「看起來很有信心」的分布裡。

**檢定方式：分類器雙樣本檢定。**
訓練分類器分辨「真實循環」與「模擬循環」。
  AUC ≈ 0.5  ⇒ 分不出來，模擬器可用
  AUC ≫ 0.5  ⇒ 分得出來，模擬器與真實資料有系統性差異

特別檢查三個模擬器常翻船的地方：
  · 殘差的 lag-1 自相關——真實感測雜訊有相關，高斯雜訊是白的
  · 量化特徵——相異值個數、最常見值的佔比
  · 連段長度——相同讀數連續出現幾次（感測器與記錄器的指紋）

**分得出來就停，不要往下做 SBI。**

輸出 -> docs/analysis_charts_3batch/simulator_check.csv
"""
import os
import sys
import csv
import glob

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import TD                                 # noqa: E402
from multivariate_increments import load4                          # noqa: E402
from clean_and_form import seg_clean, SKIP_MIN                     # noqa: E402

QUANT = 0.01
KGRID = np.arange(0.01, 3.001, 0.02)
RNG = np.random.default_rng(5150)
TRIM_MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0


def fit_LE(t, y):
    best = None
    for k in KGRID:
        A = np.vstack([np.exp(-k*t), t, np.ones_like(t)]).T
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y-A@c
        s = float(r @ r)
        if best is None or s < best[0]:
            best = (s, c, k, r)
    s, c, k, r = best
    return dict(amp=c[0], rb=-c[1], peq=c[2], k=k, resid=r,
                sd=np.sqrt(s/max(len(t)-4, 1)))


def features(t, y):
    """摘要特徵——模擬器要能重現這些才算過。"""
    n = len(y)
    amp = y[0]-y[-1]
    if amp <= 0 or n < 20:
        return None
    f = fit_LE(t, y)
    r = f['resid']
    # 殘差 lag-1 自相關
    ac = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if r.std() > 0 else 0.0
    # 量化指紋
    q = np.round(y/QUANT).astype(int)
    _, cnt = np.unique(q, return_counts=True)
    runs, cur = [], 1
    for i in range(1, n):
        if q[i] == q[i-1]:
            cur += 1
        else:
            runs.append(cur); cur = 1
    runs.append(cur)
    tn = (t-t[0])/(t[-1]-t[0])
    return dict(
        curv=float(np.interp(0.5, tn, (y[0]-y)/amp)),
        resid_sd=f['sd'],
        resid_ac1=ac,
        n_levels=len(cnt)/n,                    # 相異量化值佔比
        top_share=float(cnt.max())/n,           # 最常見值佔比
        mean_run=float(np.mean(runs)),
        max_run=float(np.max(runs))/n,
        amp=amp,
        dur=t[-1],
        mono=float(np.mean(np.diff(y) <= 0)),   # 單調下降的比例
    )


def main():
    # ── 收集真實循環 ────────────────────────────────────
    # ⚠ 2026-08-24：原本自行掃 Testing_data 的資料夾，等於跑在全部 351
    #   段上——含重複副本、未套條件排除、也未套曲率預篩。但本檔驗的是
    #   「模擬器像不像 Algorithm 2 實際模擬的那批循環」，那批是資料集 C
    #   預篩後的 207 段。族群不同，AUC 就答非所問。改為同一個集合。
    #
    #   ⚠ 尾端裁切的原始註記寫「最後一點偏低 −0.0675」，那個數字是**未
    #   經曲率預篩**的族群；預篩後只剩 −0.0067（見論文 §5.3）。
    from dataset_c import collect_c
    from degeneracy_matched import CURV_MIN
    from rb_recovery_study import curvature

    real = []
    for _tag, t2, y2 in collect_c():
        cv = curvature(t2, y2)
        if not np.isfinite(cv) or cv < CURV_MIN:
            continue
        t2 = np.asarray(t2, dtype=float)
        y2 = np.asarray(y2, dtype=float)
        if TRIM_MIN > 0:
            kp = t2 <= (t2[-1]-TRIM_MIN/60.0)
            if kp.sum() < 20:
                continue
            t2, y2 = t2[kp], y2[kp]
        real.append((t2, y2))
    print('══ 模擬器驗證：分類器雙樣本檢定 ══\n')
    print(f'   尾端裁切 {TRIM_MIN} 分鐘')
    print(f'   真實循環 {len(real)} 個')

    # ── 雜訊模型 ────────────────────────────────────────
    # ⚠ 初版用**白**高斯雜訊，AUC = 0.977 被輕易分辨。三個失敗特徵
    #   （殘差自相關 0.262 vs 0.000、連段長度、單調比例）都指向同一病因：
    #   真實感測雜訊在時間上相關。改 AR(1) 後 AUC 降到 0.847，但仍分得出來
    #   ——量化會再削弱一次自相關，所以 φ 要往上補償。
    #
    # ⚠ **循環論證的防線**：若一路調模擬器直到它通過自己的檢定，這個檢定就
    #   失去意義。因此把循環切成兩半：φ 的補償係數只在 CAL 半邊校準，
    #   AUC 檢定只在**沒看過的** TEST 半邊算。
    def make_sim(cycles, mult):
        out = []
        for t, y in cycles:
            f = fit_LE(t, y)
            r = f['resid']
            phi = float(np.corrcoef(r[:-1], r[1:])[0, 1]) \
                if r.std() > 0 else 0.0
            phi = float(np.clip(phi*mult, 0.0, 0.98))
            sd = max(f['sd'], QUANT/4)
            e = RNG.normal(0, sd*np.sqrt(1-phi**2), len(t))
            nz = np.empty(len(t)); nz[0] = RNG.normal(0, sd)
            for i in range(1, len(t)):
                nz[i] = phi*nz[i-1]+e[i]
            yy = f['peq']+f['amp']*np.exp(-f['k']*t)-f['rb']*t+nz
            out.append((t, np.round(yy/QUANT)*QUANT))
        return out

    order = RNG.permutation(len(real))
    cal = [real[i] for i in order[:len(real)//2]]
    tst = [real[i] for i in order[len(real)//2:]]
    print(f'   切半：校準 {len(cal)} 個 / 檢定 {len(tst)} 個')

    def med(cycles, key):
        v = [f[key] for f in (features(t, y) for t, y in cycles) if f]
        return float(np.median(v))

    print('\n── 在 CAL 半邊校準 φ 的補償係數 ──')
    print(f'   {"乘數":>6}{"ac1":>9}{"mono":>9}{"mean_run":>10}{"失配":>9}')
    print('   '+'-'*43)
    tgt = {k: med(cal, k) for k in ('resid_ac1', 'mono', 'mean_run')}
    best_m, best_loss = 1.0, np.inf
    for m in (1.0, 1.3, 1.6, 2.0, 2.4, 2.8, 3.3):
        sc = make_sim(cal, m)
        got = {k: med(sc, k) for k in tgt}
        loss = sum(abs(got[k]-tgt[k])/max(abs(tgt[k]), 1e-9) for k in tgt)
        print(f'   {m:>6.1f}{got["resid_ac1"]:>9.3f}{got["mono"]:>9.3f}'
              f'{got["mean_run"]:>10.3f}{loss:>9.3f}'
              f'{"  ←" if loss < best_loss else ""}')
        if loss < best_loss:
            best_m, best_loss = m, loss
    print(f'   目標（真實）{tgt["resid_ac1"]:>9.3f}{tgt["mono"]:>9.3f}'
          f'{tgt["mean_run"]:>10.3f}')
    print(f'   → 採用乘數 {best_m}（只由 CAL 決定）')

    def logistic_auc(Ztr, ytr, Zte, yte, iters=400, lr=0.3):
        w = np.zeros(Ztr.shape[1]+1)
        A = np.c_[Ztr, np.ones(len(Ztr))]
        for _ in range(iters):
            p = 1/(1+np.exp(-A@w))
            w -= lr*(A.T@(p-ytr))/len(ytr)
        s = np.c_[Zte, np.ones(len(Zte))]@w
        pos, neg = s[yte == 1], s[yte == 0]
        if len(pos) == 0 or len(neg) == 0:
            return np.nan
        return float(np.mean(
            (pos[:, None] > neg[None, :]).astype(float)
            + 0.5*(pos[:, None] == neg[None, :])))

    def c2st(real_c, sim_c):
        """回傳 (AUC, ±SD, 特徵表)。特徵表只在最終模型用得到。"""
        FR = [features(t, y) for t, y in real_c]
        FS = [features(t, y) for t, y in sim_c]
        ks = list(FR[0].keys())
        XR = np.array([[f[k] for k in ks] for f in FR if f])
        XS = np.array([[f[k] for k in ks] for f in FS if f])
        m = min(len(XR), len(XS))
        XR, XS = XR[:m], XS[:m]
        X = np.vstack([XR, XS])
        yv = np.r_[np.ones(len(XR)), np.zeros(len(XS))]
        Z = (X-X.mean(0))/(X.std(0)+1e-12)
        ix = RNG.permutation(len(yv))
        Z, yv = Z[ix], yv[ix]
        folds = np.array_split(np.arange(len(yv)), 5)
        a = []
        for i in range(5):
            te = folds[i]
            tr = np.setdiff1d(np.arange(len(yv)), te)
            a.append(logistic_auc(Z[tr], yv[tr], Z[te], yv[te]))
        a = np.array([v for v in a if np.isfinite(v)])
        return a.mean(), a.std(ddof=1), ks, XR, XS

    # ── 三個雜訊模型的 AUC（全部在 TEST 半邊評分）──────
    # ⚠ 論文要報的「AUC 逐步下降」必須可重現，所以三個模型都用同一份
    #   TEST 資料、同一個分類器重跑，不能引用開發過程中舊版程式的數字。
    real = tst
    print(f'\n   TEST 半邊：真實 {len(real)} 個')
    print('\n── 三個雜訊模型的分類器雙樣本檢定（5 折 CV AUC）──')
    print(f'   {"雜訊模型":<34}{"AUC":>8}{"±SD":>8}   判定')
    print('   '+'-'*58)
    models = [('white Gaussian', 0.0),
              ('AR(1), phi from residuals', 1.0),
              (f'AR(1), phi x {best_m} (calibrated on CAL)', best_m)]
    aucs_all, keys, XR, XS = [], None, None, None
    for nm, mult in models:
        sc = make_sim(real, mult)
        a, s, ks, xr, xs = c2st(real, sc)
        aucs_all.append((nm, mult, a, s))
        if mult == best_m:
            keys, XR, XS = ks, xr, xs
        print(f'   {nm:<34}{a:>8.3f}{s:>8.3f}   '
              f'{"✓ 分不出來" if a < 0.65 else "✘ 分得出來"}')
    auc = aucs_all[-1][2]
    ok = auc < 0.65

    # ── 最終模型的逐特徵比較 ────────────────────────────
    print(f'\n── 最終模型的逐特徵比較（真實 vs 模擬）──')
    print(f'   {"特徵":<14}{"真實中位":>12}{"模擬中位":>12}'
          f'{"標準化差":>11}   判定')
    print('   '+'-'*54)
    rows = []
    for j, k in enumerate(keys):
        a_, b_ = XR[:, j], XS[:, j]
        pooled = np.sqrt((a_.var(ddof=1)+b_.var(ddof=1))/2)
        d = (np.median(a_)-np.median(b_))/pooled if pooled > 0 else np.inf
        print(f'   {k:<14}{np.median(a_):>12.4f}{np.median(b_):>12.4f}'
              f'{d:>11.2f}   {"✘ 差異大" if abs(d) > 0.5 else "✓"}')
        rows.append([k, f'{np.median(a_):.5f}', f'{np.median(b_):.5f}',
                     f'{d:.3f}'])

    print(f'\n   → {"✓ 模擬器可用" if ok else "✘ **仍分得出來，模擬器與真實資料有系統性差異**"}')

    if not ok:
        print('\n   ⇒ **不要往下做 SBI**。模擬器錯了，學出來的後驗會又窄又錯。')
        print('     上表中「✘ 差異大」的特徵指出模擬器缺了什麼。')

    with open(f'{OUT}/simulator_check.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['feature', 'real_median', 'sim_median', 'std_diff'])
        w.writerows(rows)
        w.writerow([])
        w.writerow(['noise_model', 'phi_mult', 'auc', 'auc_sd'])
        for nm, mult, a_, s_ in aucs_all:
            w.writerow([nm, f'{mult:.2f}', f'{a_:.4f}', f'{s_:.4f}'])
        w.writerow([]); w.writerow(['trim_min', f'{TRIM_MIN:.0f}'])
    print(f'\n輸出 → {OUT}/simulator_check.csv')


if __name__ == '__main__':
    main()
