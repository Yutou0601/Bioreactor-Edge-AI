
# -*- coding: utf-8 -*-
"""B2 從「假設」改成「反推」：ρ 要多大的 k 依賴才配得上？
════════════════════════════════════════════════════════════════════════

degeneracy_matched.py 的 B2 有循環論證：斜率是從**實測的 (r̂_b, k̂) 配對**
迴歸來的，而 ρ(r̂_b, k̂) 正是我們要解釋的量。拿被解釋量算出來的參數餵回去
當真值，ρ 保證會高，所以 0.797 不構成證據。

這裡改成反推，就是論文其他地方已經在用的間接推論：
  1. 把真值參數化為 r_b(k) = R0 (k/k_med)^β
     · β=0 就是 B0（恆定）；β>0 表示隨 k 上升
     · **冪次形式恆正**，修掉原本線性 log k 會給出負 r_b 的非物理問題
     · 中位數不變：median(r_b(k_i)) = R0 (k_med/k_med)^β = R0，
       所以不同 β 的「投入真值中位」完全可比，偏誤才有意義
  2. 掃 β 網格，每個 β 跑完整配對管線，得校準曲線 ρ(β)
  3. 在實測 ρ 反解 β̂，並由校準散布給區間

同時回答一個對主結果攸關的問題：**若真值真的隨 k 變，聚合中位數還準嗎？**
主結果 median r_b = 0.0117 的無偏性是在 β=0 下驗的；若 β̂ 明顯大於 0，
就必須在 β̂ 下重驗一次，否則頭條數字的偏誤宣稱不成立。

輸出 -> docs/analysis_charts_3batch/degeneracy_invert.csv
"""
import os
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from simulator_check import fit_LE, QUANT                          # noqa: E402
# ⚠ 資料集 C：條件一致的循環。舊版跑在 collect() 的全部 351 個上，那是
#   跨異質條件合併（1:1 進氣、含無循環時段、中位 r_b 為負的批次都在內）。
from dataset_c import collect_c as collect                        # noqa: E402
from rb_recovery_study import curvature                            # noqa: E402
from degeneracy_matched import sp, ar1, CURV_MIN                   # noqa: E402

RNG = np.random.default_rng(112358)
NREP = 12
BETAS = np.array([0.0, .05, .10, .15, .20, .25, .30, .40, .50, .65, .80])


def build_fits():
    fits = []
    for tag, t, y in collect():
        cv = curvature(t, y)
        if not np.isfinite(cv) or cv < CURV_MIN:
            continue
        f = fit_LE(t, y)
        r = f['resid']
        phi = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if r.std() > 0 else 0.
        fits.append(dict(t=t, k=f['k'], amp=f['amp'], peq=f['peq'],
                         rb=f['rb'], sd=max(f['sd'], QUANT/4),
                         phi=float(np.clip(phi*1.3, 0, 0.98))))
    return fits


def hl_median(v):
    """對離散平台不敏感的位置量：Hodges–Lehmann 估計量（兩兩平均之中位）。

    ⚠ 為何不用一般中位數：真值 R0·(k/k_med)^β 在 k 恰等於中位數的循環上
      恆等於 R0，而 k 的網格在中位數處有 13/239 個點堆積。樣本中位數因此
      被鎖在這個平台上——篩選明明掉了 3–8 個循環，「留下的真值中位」卻
      到小數第六位都不動，使「選擇效應」恆為 0.0 %，與估計偏誤無法分離。
      Hodges–Lehmann 用的是全部兩兩平均，平台不再主導，位移量得以顯現。
    """
    a = np.sort(np.asarray(v, float))
    n = len(a)
    if n < 2:
        return float(a[0]) if n else float('nan')
    # 兩兩平均的中位數；n 大時抽樣以免 O(n²) 爆掉
    if n <= 400:
        w = (a[:, None] + a[None, :])[np.triu_indices(n, 1)]
    else:
        i = RNG.integers(0, n, 80000); j = RNG.integers(0, n, 80000)
        w = (a[i] + a[j]) / 2.0
        return float(np.median(w))
    return float(np.median(w / 2.0))


def run_beta(fits, beta, R0, kmed):
    """一個 β 的完整配對管線，回傳每次重複的 (ρ, 回收中位)。"""
    rhos, meds, truemeds = [], [], []
    for _ in range(NREP):
        rr, kk, tt = [], [], []
        for f in fits:
            rb_true = R0*(f['k']/kmed)**beta
            t = f['t']
            y = f['peq']+f['amp']*np.exp(-f['k']*t)-rb_true*t \
                + ar1(len(t), f['sd'], f['phi'])
            y = np.round(y/QUANT)*QUANT          # 與實測相同的量化
            cv = curvature(t, y)
            if not np.isfinite(cv) or cv < CURV_MIN:
                continue                          # 與實測相同的篩選
            g = fit_LE(t, y)
            rr.append(g['rb']); kk.append(g['k'])
            # ⚠ 分母必須是**通過篩選那批**的真值中位，不是全體的 R0。
            #   曲率篩選偏好高 k；若 r_b 隨 k 上升，留下來的真值本來就偏高，
            #   拿全體 R0 當分母會把「選擇效應」誤記成「估計偏誤」。
            tt.append(rb_true)
        rhos.append(sp(rr, kk))
        meds.append(float(np.median(rr)))
        truemeds.append(hl_median(tt))
    return np.array(rhos), np.array(meds), np.array(truemeds)


def invert(betas, rho_mean, rho_sd, target):
    """在校準曲線上反解 β，並以 ±1 個校準散布給區間。"""
    def solve(y):
        if y <= rho_mean[0]:
            return 0.0
        if y >= rho_mean[-1]:
            return float('nan')
        j = int(np.searchsorted(rho_mean, y))
        x0, x1 = betas[j-1], betas[j]
        y0, y1 = rho_mean[j-1], rho_mean[j]
        return float(x0+(y-y0)*(x1-x0)/(y1-y0))
    s = float(np.mean(rho_sd))
    return solve(target), solve(target-s), solve(target+s)


def main():
    fits = build_fits()
    rb_obs = np.array([f['rb'] for f in fits])
    k_obs = np.array([f['k'] for f in fits])
    rho_obs = sp(rb_obs, k_obs)
    R0 = float(np.median(rb_obs))
    kmed = float(np.median(k_obs))

    print('══ B2 反推：ρ 需要多強的 k 依賴 ══\n')
    print(f'   循環 {len(fits)}   實測 ρ = {rho_obs:+.3f}   '
          f'r_b 中位 = {R0:.5f}   k 中位 = {kmed:.4f}\n')
    print(f'   {"β":>6}{"ρ 均值":>12}{"ρ 標準差":>11}'
          f'{"留下真值中位":>14}{"回收中位":>11}{"估計偏誤":>10}'
          f'{"選擇效應":>10}')
    print('   '+'-'*74)

    rows, rho_mean, rho_sd = [], [], []
    for b in BETAS:
        rh, md, tm = run_beta(fits, b, R0, kmed)
        bias = md.mean()/tm.mean()-1          # 對「通過篩選那批」的真值
        seln = tm.mean()/R0-1                 # 篩選本身造成的位移
        rho_mean.append(rh.mean()); rho_sd.append(rh.std(ddof=1))
        rows.append([f'{b:.2f}', f'{rh.mean():.4f}', f'{rh.std(ddof=1):.4f}',
                     f'{tm.mean():.5f}', f'{md.mean():.5f}',
                     f'{bias*100:.1f}', f'{seln*100:.1f}'])
        print(f'   {b:>6.2f}{rh.mean():>12.3f}{rh.std(ddof=1):>11.3f}'
              f'{tm.mean():>14.5f}{md.mean():>11.5f}'
              f'{bias*100:>9.1f}%{seln*100:>9.1f}%')

    rho_mean = np.array(rho_mean); rho_sd = np.array(rho_sd)
    bhat, blo, bhi = invert(BETAS, rho_mean, rho_sd, rho_obs)

    print('\n══ 反解 ══')
    if not np.isfinite(bhat):
        print(f'   實測 ρ={rho_obs:+.3f} 超出網格上界 '
              f'(β={BETAS[-1]:.2f} 只到 {rho_mean[-1]:.3f})')
        print('   ⇒ 需要把網格往上延伸才能定值；但已可說「β 顯著大於 0」。')
    else:
        print(f'   實測 ρ={rho_obs:+.3f} 對應 β̂ = {bhat:.2f} '
              f'[{blo:.2f}, {bhi:.2f}]')
        print(f'   β=0（恆定真值）只給 ρ={rho_mean[0]:.3f}，'
              f'與實測差 {rho_obs-rho_mean[0]:+.3f}'
              f' = {(rho_obs-rho_mean[0])/rho_sd[0]:.1f} 個標準差')
        j = int(np.argmin(np.abs(BETAS-bhat)))
        print(f'\n   ⚠ 主結果自檢：在 β≈{BETAS[j]:.2f} 下聚合中位數偏誤 '
              f'{float(rows[j][5]):+.1f}%')
        print('     （主結果的 0% 無偏是在 β=0 驗的；此處若明顯不為 0，'
              '頭條數字必須改口徑）')

    path = os.path.join(OUT, 'degeneracy_invert.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['rho_obs', f'{rho_obs:.4f}'])
        w.writerow(['R0', f'{R0:.5f}'])
        w.writerow(['k_med', f'{kmed:.4f}'])
        w.writerow(['beta_hat', f'{bhat:.3f}'])
        w.writerow([])
        w.writerow(['beta', 'rho_mean', 'rho_sd', 'true_median_kept',
                    'median_rec', 'bias_pct', 'selection_pct'])
        w.writerows(rows)
    print(f'\n   → {path}')


if __name__ == '__main__':
    main()
