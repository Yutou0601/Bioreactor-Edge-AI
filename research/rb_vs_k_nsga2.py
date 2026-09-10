
# -*- coding: utf-8 -*-
"""r_b(k) 的多目標校準逼近（NSGA-II）
════════════════════════════════════════════════════════════════════════

**動機（來自使用者）**：混合菌群在不同階段、不同菌種活性不同，沒有理由
服從一個兩參數的乾淨定律。硬套 Monod 或線性是把生物學的異質性塞進方便的
數學殼裡；用算法逼近一條**無形式**的曲線更誠實。

**為何是多目標**：`rb_vs_k_pointwise.py` 只比對**一個**統計量（分層中位數）。
同時要求候選曲線重現多個互不等價的統計量，對曲線的約束強得多；
而 **Pareto 前緣的寬度本身就是不確定度的報告**——前緣窄代表曲線被定住，
前緣寬代表資料撐不起這麼細的描述。

  目標 1  各 k̂ 分層的 r̂_b 中位數
  目標 2  ρ(r̂_b, k̂)                    實測 0.831
  目標 3  r̂_b > 0 的比例
  目標 4  r̂_b 的四分位距（分布寬度）

**決策變數**：對數等距 5 個節點上的 r_b 值，節點間線性內插。
⚠ **不強制單調**。單調雖有物理理由（傳質越好、氫氣越多），但那仍是假設；
  讓資料自己決定，事後再報告前緣上的曲線是否恰好單調——那是發現不是前提。

⚠ **共同亂數（common random numbers）**：AR(1) 雜訊**只產生一次**並固定重用。
  否則每次評估的雜訊不同，目標函數帶雜訊，NSGA-II 的支配關係會被雜訊翻轉
  而選出「剛好抽到好雜訊」的個體。固定雜訊使比較公平且目標確定性。

⚠ NSGA-II 是**最佳化器，不是可辨識性的解藥**。若資料撐不住，前緣會很寬——
  那是結果，不是失敗。

純 numpy 實作（監控電腦 60 MB 預算裝不下 pymoo）。

輸出 -> docs/analysis_charts_3batch/rb_vs_k_nsga2.csv
"""
import os
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from simulator_check import QUANT                                  # noqa: E402
from rb_vs_k_form import fit_LE_fast, prep, ar1, summary, NBIN     # noqa: E402
from residual_structure import collect                             # noqa: E402
from rb_recovery_study import curvature                            # noqa: E402

RNG = np.random.default_rng(20260808)
CURV_MIN = 0.45
K_MIN = 0.03                    # 低於此為簡併廢區，目標函數一律排除
NKNOT = 5
LO, HI = -0.005, 0.060          # 各節點 r_b 的搜尋範圍
POP, GEN = 24, 18


def spearman(a, b):
    ra = np.argsort(np.argsort(np.asarray(a, float))).astype(float)
    rb = np.argsort(np.argsort(np.asarray(b, float))).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


# ══ 前向模擬（共同亂數）═══════════════════════════════════════
def make_evaluator(fits, edges, knots, obs):
    """回傳 evaluate(theta) -> 四個目標值（越小越好）。"""
    # ⚠ 雜訊只產生一次，之後所有候選共用，目標函數才是確定性的。
    for f in fits:
        f['e'] = ar1(len(f['t']), f['sd'], f['phi'])
    lk = np.log(knots)

    def rb_of(theta, k):
        return float(np.interp(np.log(max(k, knots[0])), lk, theta))

    def evaluate(theta):
        rr, kk = [], []
        for f in fits:
            t = f['t']
            y = f['peq']+f['amp']*np.exp(-f['k']*t)-rb_of(theta, f['k'])*t \
                + f['e']
            y = np.round(y/QUANT)*QUANT
            if curvature(t, y) < CURV_MIN:
                continue
            g = fit_LE_fast(t, y)
            # ⚠ k̂ < K_MIN 是簡併廢區：該區間實測中位數為 −0.093，
            #   是簡併造成的假影，**任何合理的 r_b 都重現不出來**。
            #   初版把它留在目標函數裡，最佳化器就一直在追一個追不到的靶，
            #   目標 1 卡在 0.341 不動、並犧牲它去滿足其餘三項。
            #   逐區間分析早已依「校準映射不可逆」原則排除同一區間，
            #   此處對齊該原則，非為湊答案。
            if g and g['k'] >= K_MIN:
                rr.append(g['rb']); kk.append(g['k'])
        if len(rr) < 3*NBIN:
            return np.array([1e3]*4)
        rr = np.array(rr); kk = np.array(kk)
        s = summary(rr, kk, edges)
        m = np.isfinite(s) & np.isfinite(obs['med'])
        o1 = float(np.sqrt(np.nanmean(((s[m]-obs['med'][m])/obs['sc'])**2)))
        o2 = abs(spearman(rr, kk)-obs['rho'])/0.05
        o3 = abs(float(np.mean(rr > 0))-obs['pos'])/0.03
        q = np.quantile(rr, [.25, .75])
        o4 = abs((q[1]-q[0])-obs['iqr'])/obs['iqr']
        return np.array([o1, o2, o3, o4])
    return evaluate


# ══ NSGA-II ═══════════════════════════════════════════════════
def nds(F):
    """非支配排序，回傳每個個體的前緣編號。"""
    n = len(F)
    dom = [[] for _ in range(n)]
    cnt = np.zeros(n, int)
    rank = np.zeros(n, int)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if np.all(F[i] <= F[j]) and np.any(F[i] < F[j]):
                dom[i].append(j)
            elif np.all(F[j] <= F[i]) and np.any(F[j] < F[i]):
                cnt[i] += 1
    cur = [i for i in range(n) if cnt[i] == 0]
    k = 0
    while cur:
        nxt = []
        for i in cur:
            rank[i] = k
            for j in dom[i]:
                cnt[j] -= 1
                if cnt[j] == 0:
                    nxt.append(j)
        cur = nxt; k += 1
    return rank


def crowding(F):
    n, m = F.shape
    d = np.zeros(n)
    for j in range(m):
        o = np.argsort(F[:, j])
        d[o[0]] = d[o[-1]] = np.inf
        rng = F[o[-1], j]-F[o[0], j]
        if rng <= 0:
            continue
        for a in range(1, n-1):
            d[o[a]] += (F[o[a+1], j]-F[o[a-1], j])/rng
    return d


def evolve(evaluate, nvar, pop=POP, gen=GEN):
    X = RNG.uniform(LO, HI, (pop, nvar))
    F = np.array([evaluate(x) for x in X])
    for g in range(gen):
        r = nds(F); c = crowding(F)
        # 二元競賽選擇
        idx = []
        for _ in range(pop):
            a, b = RNG.integers(pop, size=2)
            idx.append(a if (r[a], -c[a]) < (r[b], -c[b]) else b)
        P = X[idx]
        # SBX 交叉
        Q = P.copy()
        for i in range(0, pop-1, 2):
            if RNG.random() < 0.9:
                u = RNG.random(nvar)
                beta = np.where(u <= .5, (2*u)**(1/16),
                                (1/(2*(1-u)))**(1/16))
                Q[i] = .5*((1+beta)*P[i]+(1-beta)*P[i+1])
                Q[i+1] = .5*((1-beta)*P[i]+(1+beta)*P[i+1])
        # 多項式突變
        mut = RNG.random((pop, nvar)) < 1.0/nvar
        Q = np.where(mut, Q+RNG.normal(0, (HI-LO)*0.10, (pop, nvar)), Q)
        Q = np.clip(Q, LO, HI)
        FQ = np.array([evaluate(x) for x in Q])
        # 環境選擇
        XA = np.vstack([X, Q]); FA = np.vstack([F, FQ])
        rA = nds(FA); cA = crowding(FA)
        order = sorted(range(len(XA)), key=lambda i: (rA[i], -cA[i]))
        X, F = XA[order[:pop]], FA[order[:pop]]
        print(f'      世代 {g+1:2d}/{gen}   前緣大小 {int((nds(F)==0).sum()):2d}'
              f'   最佳各目標 {np.min(F,axis=0).round(3)}')
    return X, F


def main():
    fits = prep(collect())
    # 目標函數的觀測側也要用同一條線排除簡併廢區，兩側才可比。
    fits = [f for f in fits if f['k'] >= K_MIN]
    ks = np.array([f['k'] for f in fits])
    rbs = np.array([f['rb'] for f in fits])
    edges = np.quantile(ks, np.linspace(0, 1, NBIN+1))
    edges[-1] *= 1.001
    q = np.quantile(rbs, [.25, .75])
    obs = dict(med=summary(rbs, ks, edges), rho=spearman(rbs, ks),
               pos=float(np.mean(rbs > 0)), iqr=float(q[1]-q[0]),
               sc=float(np.nanstd(summary(rbs, ks, edges))))
    knots = np.exp(np.linspace(np.log(0.03), np.log(3.0), NKNOT))

    print('══ r_b(k) 的多目標校準逼近（NSGA-II）══\n')
    print(f'   循環 {len(fits)}   節點 {NKNOT} 個（對數等距 0.03–3.0）')
    print(f'   族群 {POP} × 世代 {GEN} = {POP*(GEN+1)} 次完整管線評估')
    print(f'   共同亂數：AR(1) 雜訊固定重用，目標函數為確定性\n')
    print(f'   實測目標值   ρ={obs["rho"]:+.3f}   正值比例={obs["pos"]:.3f}'
          f'   IQR={obs["iqr"]:.4f}')
    print(f'   分層中位數   ' + '  '.join(f'{v:+.4f}' for v in obs['med']))
    print()

    ev = make_evaluator(fits, edges, knots, obs)
    X, F = evolve(ev, NKNOT)

    front = X[nds(F) == 0]
    print(f'\n── Pareto 前緣（{len(front)} 條曲線）──')
    print(f'   {"k":>8}' + ''.join(f'{"":>4}' for _ in range(0)) +
          f'{"中位":>10}{"最小":>10}{"最大":>10}{"寬度/中位":>11}')
    print('   '+'-'*50)
    rows = []
    for i, kn in enumerate(knots):
        v = front[:, i]
        med, lo, hi = np.median(v), v.min(), v.max()
        rel = (hi-lo)/abs(med) if abs(med) > 1e-9 else np.inf
        print(f'   {kn:>8.3f}{med:>10.5f}{lo:>10.5f}{hi:>10.5f}{rel*100:>10.0f}%')
        rows.append([f'{kn:.4f}', f'{med:.6f}', f'{lo:.6f}', f'{hi:.6f}'])

    med_curve = np.median(front, axis=0)
    mono = np.all(np.diff(med_curve) > -1e-4)
    span = med_curve.max()/max(med_curve.min(), 1e-9)
    print(f'\n── 判定 ──')
    print(f'   前緣中位曲線   ' + '  '.join(f'{v:+.4f}' for v in med_curve))
    print(f'   單調遞增        {"✓ 是" if mono else "✘ 否"}'
          f'   （未強制，由資料決定）')
    print(f'   兩端比值        {span:.2f} 倍')
    widths = [(front[:, i].max()-front[:, i].min()) for i in range(NKNOT)]
    tight = np.median(widths) < 0.010
    print(f'   前緣寬度中位    {np.median(widths):.4f}'
          f'   → {"✓ 曲線被定住" if tight else "✘ 資料撐不起這麼細的描述"}')

    with open(f'{OUT}/rb_vs_k_nsga2.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['k_knot', 'rb_median', 'rb_front_min', 'rb_front_max'])
        w.writerows(rows)
        w.writerow([]); w.writerow(['front_size', len(front)])
        w.writerow(['monotone', bool(mono)])
    print(f'\n輸出 → {OUT}/rb_vs_k_nsga2.csv')


if __name__ == '__main__':
    main()
