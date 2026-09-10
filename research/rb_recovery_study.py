
# -*- coding: utf-8 -*-
"""
回收研究：什麼樣的循環才能可靠地估出 r_b？
════════════════════════════════════════════════════════════════════════

`rb_diagnostics.py` 證明 r_b 完全由擬合出的 k 決定（分層散布 827 %），
機制是 k·T 小時 e^(−kt) ≈ 1 − kt，**指數項自己就是線性項**，兩項不可分辨。

**不能用擬合出的 k 來篩選**——那是拿結果篩結果。需要一個
**擬合前就能算、與模型無關**的準則，而且門檻要由**已知真值的合成資料**定，
不是拍腦袋。

準則採用**正規化中點曲率**（只看軌跡形狀，不需擬合）：

    curv = (P0 − P(T/2)) / (P0 − P(T))
    0.50 = 完美直線（簡併）；越大 = 指數項越彎（可辨識）

本檔：
  R1  以真實資料的參數範圍產生合成循環（真值 r_b 已知）
  R2  對每個合成循環算曲率、擬合 LE、記錄回收誤差
  R3  找出「回收誤差可接受」對應的曲率門檻
  R4  把門檻套回真實資料，看剩下多少循環
  R5  在篩選後的子集重估 r_b，並在**同一子集**重跑設定誤差虛無

輸出 -> docs/analysis_charts_3batch/rb_recovery_study.csv
"""
import os
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402

QUANT = 0.01
KGRID = np.arange(0.01, 3.001, 0.01)
RNG = np.random.default_rng(90210)


def curvature(t, y):
    """正規化中點曲率：只看形狀，與模型無關。"""
    amp = y[0]-y[-1]
    if amp <= 0:
        return np.nan
    tn = (t-t[0])/(t[-1]-t[0])
    return float(np.interp(0.5, tn, (y[0]-y)/amp))


def fit_LE(t, y):
    best = None
    for k in KGRID:
        A = np.vstack([np.exp(-k*t), t, np.ones_like(t)]).T
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y-A@c
        s = float(r @ r)
        if best is None or s < best[0]:
            best = (s, c, k)
    s, c, k = best
    return -c[1], k                      # r_b, k


PHI = 0.26          # 真實殘差的 lag-1 自相關（simulator_check.py 實測中位）


def simulate(rb_true, k_true, T, P0, amp_exp, noise, dt_h=1/60):
    """產生一個合成循環（含量化與 AR(1) 雜訊）。

    ⚠ 初版用**白**高斯雜訊校準曲率門檻，而 `simulator_check.py` 實測真實
      殘差的 lag-1 自相關是 0.26，不是 0。白雜訊模擬器被分類器以
      AUC 0.977 輕易分辨；改 AR(1) 後十項邊際特徵全部對上。
      相關雜訊的低頻成分更容易被誤認成曲率，**白雜訊會把門檻校得太鬆**。
    """
    t = np.arange(0, T, dt_h)
    if len(t) < 20:
        return None
    y = (P0-amp_exp)+amp_exp*np.exp(-k_true*t)-rb_true*t
    e = RNG.normal(0, noise*np.sqrt(1-PHI**2), len(t))
    nz = np.empty(len(t)); nz[0] = RNG.normal(0, noise)
    for i in range(1, len(t)):
        nz[i] = PHI*nz[i-1]+e[i]
    return t, np.round((y+nz)/QUANT)*QUANT


def main():
    # ── 由真實資料取參數範圍 ────────────────────────────
    real = []
    with open(f'{OUT}/rb_per_cycle.csv', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            try:
                real.append((float(r['dur_hr']), float(r['peq']),
                             float(r['rmse']), float(r['k'])))
            except Exception:
                pass
    dur = np.array([x[0] for x in real])
    rmse = np.array([x[2] for x in real])
    print('══ 回收研究：什麼樣的循環才估得出 r_b？ ══\n')
    print(f'   真實資料：{len(real)} 個循環')
    print(f'   時長  中位 {np.median(dur):.1f} hr'
          f'   [{np.quantile(dur,.1):.1f}, {np.quantile(dur,.9):.1f}]')
    print(f'   殘差  中位 {np.median(rmse):.5f}'
          f'   [{np.quantile(rmse,.1):.5f}, {np.quantile(rmse,.9):.5f}]')

    # ── R1／R2 合成與回收 ───────────────────────────────
    print('\n── R1／R2  合成循環的回收表現 ──')
    RB_TRUE = 0.012                       # 設定一個已知真值
    sims = []
    for _ in range(3000):
        T = float(RNG.choice(dur))
        k = float(np.exp(RNG.uniform(np.log(0.01), np.log(2.0))))
        amp = float(RNG.uniform(0.05, 0.45))
        nz = float(RNG.choice(rmse))
        s = simulate(RB_TRUE, k, T, 1.05, amp, nz)
        if s is None:
            continue
        t, y = s
        if y[0]-y[-1] <= 0.05:
            continue
        cv = curvature(t, y)
        if not np.isfinite(cv):
            continue
        rb_hat, k_hat = fit_LE(t, y)
        # ⚠ 初版只存 k_true，丟掉 k_hat，於是算不出「真值固定時
        #   ρ(r̂_b, k̂) 本來就會有多大」——沒有這個基準，真實資料的
        #   ρ = 0.829 無法判讀成假影或真簡併。
        sims.append((cv, rb_hat, k, k*T, T, k_hat))
    sims = np.array(sims)
    print(f'   合成 {len(sims)} 個循環，真值 r_b = {RB_TRUE}')

    # ── R3 找曲率門檻 ──────────────────────────────────
    print('\n── R3  依曲率分層的回收表現 ──')
    print(f'   {"曲率區間":<16}{"n":>5}{"r_b 中位":>11}{"偏誤":>10}'
          f'{"IQR 寬度":>11}{"k·T 中位":>10}   判定')
    print('   '+'-'*68)
    edges = [0.45, 0.52, 0.56, 0.60, 0.66, 0.75, 1.01]
    ok_thr = None
    for i in range(len(edges)-1):
        m = (sims[:, 0] >= edges[i]) & (sims[:, 0] < edges[i+1])
        if m.sum() < 30:
            continue
        v = sims[m, 1]
        med = np.median(v)
        bias = (med-RB_TRUE)/RB_TRUE
        q = np.quantile(v, [.25, .75])
        iqr = (q[1]-q[0])/RB_TRUE
        good = abs(bias) < 0.25 and iqr < 1.0
        if good and ok_thr is None:
            ok_thr = edges[i]
        print(f'   [{edges[i]:.2f}, {edges[i+1]:.2f}){"":<4}{m.sum():>5}'
              f'{med:>11.5f}{bias*100:>9.0f}%{iqr*100:>10.0f}%'
              f'{np.median(sims[m,3]):>10.2f}   '
              f'{"✓ 可用" if good else "✘"}')
    print(f'\n   → 曲率門檻 = {ok_thr}'
          if ok_thr else '\n   → 所有曲率區間都不可靠')
    if ok_thr is None:
        print('   ⇒ 以現有取樣與雜訊，**任何曲率都估不出 r_b**')
        return

    # ── R4 套回真實資料 ────────────────────────────────
    print(f'\n── R4  把門檻 {ok_thr} 套回真實資料 ──')
    from regime_changepoints import TD                             # noqa: E402
    from multivariate_increments import load4                      # noqa: E402
    from clean_and_form import seg_clean, SKIP_MIN                 # noqa: E402
    import glob
    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if glob.glob(os.path.join(p, '*.csv')):
            folders.append((p, d))
        for s in sorted(os.listdir(p)):
            sp = os.path.join(p, s)
            if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                folders.append((sp, f'{d}/{s}'))
    keep = []
    for path, tag in folders:
        try:
            raw = load4(path)
        except Exception:
            continue
        if len(raw) < 500:
            continue
        ts = [r[0] for r in raw]
        P = np.array([r[1] for r in raw]); O = np.array([r[2] for r in raw])
        h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
        cyc, wash = seg_clean(h, P, ts)
        for a, b in cyc:
            if ts[a].date() in wash:
                continue
            t = h[a:b+1]-h[a]
            sel = t >= SKIP_MIN
            if sel.sum() < 20:
                continue
            t2 = t[sel]-t[sel][0]; y2 = P[a:b+1][sel]
            cv = curvature(t2, y2)
            if np.isfinite(cv) and cv >= ok_thr:
                keep.append((tag, ts[a], t2, y2, O[a:b+1][sel], cv))
    print(f'   通過門檻的循環：{len(keep)} / 351'
          f'（{len(keep)/351*100:.0f} %）')
    if len(keep) < 20:
        print('   ⇒ 樣本不足，無法在子集上重估')
        return
    import collections
    byf = collections.Counter(k[0] for k in keep)
    for f, n in byf.most_common():
        print(f'      {f[:38]:<40}{n:>4}')

    # ── R5 子集重估 ＋ 同子集虛無 ──────────────────────
    print('\n── R5  在篩選後的子集重估 r_b ──')
    rb, ks = [], []
    for tag, t0, t, y, o, cv in keep:
        r, k = fit_LE(t, y)
        rb.append(r); ks.append(k)
    rb = np.array(rb); ks = np.array(ks)
    print(f'   r_b 中位 {np.median(rb):+.5f}'
          f'   IQR [{np.quantile(rb,.25):+.5f}, {np.quantile(rb,.75):+.5f}]')
    print(f'   正值比例 {np.mean(rb > 0)*100:.1f} %'
          f'   k 中位 {np.median(ks):.3f}   k·T 中位 '
          f'{np.median([k*kk[2][-1] for k, kk in zip(ks, keep)]):.2f}')

    # ── 簡併檢查：實測 ρ 必須跟「真值固定」的基準比 ────
    # ⚠ 只看實測 ρ 是**無法判讀**的：即使真值固定，擬合出的 r̂_b 與 k̂
    #   也必然相關（兩者共同吸收同一段下降量）。要問的是
    #   「實測的 ρ 有沒有**超過**真值固定時本來就會有的 ρ」。
    def sp(a, b):
        ra_ = np.argsort(np.argsort(a)).astype(float)
        rb_ = np.argsort(np.argsort(b)).astype(float)
        return float(np.corrcoef(ra_, rb_)[0, 1])

    rho = sp(rb, ks)
    msk = sims[:, 0] >= ok_thr
    rho_null = sp(sims[msk, 1], sims[msk, 5])
    print(f'\n   ── 簡併檢查 ──')
    print(f'   實測      ρ(r̂_b, k̂) = {rho:+.3f}   n = {len(rb)}')
    print(f'   真值固定  ρ(r̂_b, k̂) = {rho_null:+.3f}   n = {int(msk.sum())}'
          f'   ← 同曲率門檻下的基準')
    excess = rho-rho_null
    print(f'   超額 = {excess:+.3f}')
    print(f'   → {"✘ 實測明顯超過基準，簡併未解除" if excess > 0.15 else "✓ 實測未超過基準，該相關是估計本身的假影"}')

    # 同子集的設定誤差虛無
    print('\n   同子集的設定誤差虛無（純指數為真相）：')
    med_null = []
    for _ in range(40):
        v = []
        for tag, t0, t, y, o, cv in keep:
            A = np.vstack([np.exp(-1.0*t), np.ones_like(t)]).T
            bestE = None
            for k in KGRID:
                A = np.vstack([np.exp(-k*t), np.ones_like(t)]).T
                c, *_ = np.linalg.lstsq(A, y, rcond=None)
                r_ = y-A@c
                s_ = float(r_ @ r_)
                if bestE is None or s_ < bestE[0]:
                    bestE = (s_, c, k)
            s_, c, k = bestE
            sd = np.sqrt(s_/max(len(t)-2, 1))
            yy = c[1]+c[0]*np.exp(-k*t)+RNG.normal(0, max(sd, QUANT/2), len(t))
            v.append(fit_LE(t, np.round(yy/QUANT)*QUANT)[0])
        med_null.append(np.median(v))
    med_null = np.array(med_null)
    obs = float(np.median(rb))
    p = (np.sum(med_null >= obs)+1)/(len(med_null)+1)
    print(f'      虛無中位 {med_null.mean():+.5f} ± {med_null.std(ddof=1):.5f}')
    print(f'      實測中位 {obs:+.5f}   置換 p = {p:.4f}'
          f'   {"✓" if p < 0.05 else "✘"}')

    with open(f'{OUT}/rb_recovery_study.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['curv_threshold', ok_thr])
        w.writerow(['n_kept', len(keep), 'of', 351])
        w.writerow(['rb_median', f'{obs:.6f}'])
        w.writerow(['rb_pos_frac', f'{np.mean(rb>0):.4f}'])
        w.writerow(['spearman_rb_k', f'{rho:.4f}'])
        w.writerow(['null_median', f'{med_null.mean():.6f}'])
        w.writerow(['perm_p', f'{p:.4f}'])
    print(f'\n輸出 → {OUT}/rb_recovery_study.csv')


if __name__ == '__main__':
    main()
