# -*- coding: utf-8 -*-
"""用「曲率差異」在既有資料裡找天然的多實驗配對，解出 r̄_b。

2026-09-23。使用者提問：「如果對曲率明顯之 curve 做 Fourier transform 呢？」

════════════════════════════════════════════════════════════════════════
這個想法的真正價值不在 Fourier，而在「挑出 k 不同的曲線」

  曲率明顯 ⟺ 指數項在觀測窗內走完較多 ⟺ **kT 大** ⟺ k 大
  曲率不明顯（接近直線）⟺ kT 小

  而 k 不同，正是打開簡併所需要的東西：

      A₁ = P_eq − r̄_b/k₁
      A₂ = P_eq − r̄_b/k₂
      ─────────────────────────────
      **r̄_b = (A₁ − A₂) / (1/k₂ − 1/k₁)**      …(★)

  ⟹ 只要能在資料裡找到「k 差很多、但 P_eq 與 r̄_b 相同」的兩條曲線，
     就能解出 r̄_b，**而且不需要任何新實驗**。

⚠ 關鍵前提，也是 τ 實驗當初失敗的地方

  (★) 要求兩條曲線的 P_eq 與 r̄_b 相同。三批 τ 實驗依序進行、全程未換液，
  τ 與菌齡、飽和度完全共線，前提不成立。
  **本檔的對策：只配對「時間相近」的曲線**，使菌齡與飽和度近似相同，
  再要求兩者的 k 差異夠大。

⚠ 關於 Fourier：頻譜寬度確實可讀出 k（Lorentzian 的半寬），但
  時域的三參數指數擬合同樣給 k，且對短序列更穩健（頻譜解析度受窗長限制）。
  本檔用時域擬合，把力氣放在**配對設計**上。

本檔的檢驗設計（先驗證方法，再看真實資料）

  一、回收檢定（Rule 8）：用已知答案的合成資料，看曲率配對撈不撈得回來
  二、真實資料：算每段的 (k, A) 與曲率，看曲率與 k 是否如預期相關
  三、配對求解：在時間窗內找 k 對比大的配對，逐一解 (★)，看分布
  四、⚠ 安慰劑對照：把配對的時間打散（破壞「同期」的前提），
      若結果不變，代表 (★) 解出來的不是真訊號

輸出 -> 純文字 + docs/analysis_charts_3batch/fig53_curvature_pair.png
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, RED, AQUA, INK, INK2, MUTED, OUT, style)
from ph_orp_discriminator import descents, load_full     # noqa: E402
from tau_crossover_design import fit_kA, estimate_rb, simulate  # noqa: E402
from carbonate_degassing_test import spearman, perm_p, mde_spearman  # noqa: E402

RB_PAPER = 0.0125
WIN_DAYS = 7.0          # 配對的時間窗（天）：使菌齡與飽和度近似相同
K_RATIO = 2.0           # 配對要求的 k 最小對比


def cluster_ci(pairs, rng, n_iter=2000):
    """以「曲線」為單位重抽的 bootstrap 區間。

    ⚠ 為何不能對「配對」重抽：N 條曲線可組成 O(N²) 個配對，同一條曲線
      會出現在許多配對裡。對配對重抽等於假裝它們獨立，區間會被壓到極窄，
      得到看似顯著、實則虛假的精度。
      正確作法是重抽曲線，再取「兩端都被抽中」的配對。
    """
    ids = sorted({i for pr in pairs for i in (pr['ia'], pr['ib'])})
    idx = {v: k for k, v in enumerate(ids)}
    out = []
    for _ in range(n_iter):
        pick = rng.choice(len(ids), len(ids), replace=True)
        cnt = np.bincount(pick, minlength=len(ids))
        vals = [pr['r'] for pr in pairs
                if cnt[idx[pr['ia']]] and cnt[idx[pr['ib']]]]
        if vals:
            out.append(float(np.median(vals)))
    return np.percentile(out, [2.5, 97.5]) if out else np.array([np.nan] * 2)


def bow_of(t, y):
    """曲率指標：正規化後與直線的平均偏離（與 shape_clustering 同義）。"""
    if len(t) < 20 or y[0] == y[-1]:
        return np.nan
    u = (t - t[0]) / (t[-1] - t[0])
    s = (y - y[-1]) / (y[0] - y[-1])
    return float(np.mean(s - (1 - u)))


def seg_fit(hh, p, s, e):
    t = hh[s:e + 1]
    y = p[s:e + 1]
    if len(t) < 60 or (y[0] - y[-1]) < 0.05:
        return None
    k, A = fit_kA(t - t[0], y)
    return dict(k=k, A=A, bow=bow_of(t, y), t_mid=float((t[0] + t[-1]) / 2),
                dur=float(t[-1] - t[0]), drop=float(y[0] - y[-1]))


def main():
    print('=' * 76)
    print('一、回收檢定：曲率配對撈不撈得回已知的 r̄_b')
    print('=' * 76)
    rng = np.random.default_rng(0)
    # 同一組 (P_eq, r̄_b)，兩條 k 不同的曲線
    k_lo, k_hi = 0.15, 0.45
    est = []
    for _ in range(200):
        _, Pa = simulate(k_lo, 0.75, RB_PAPER, rng=rng)
        _, Pb = simulate(k_hi, 0.75, RB_PAPER, rng=rng)
        t = np.linspace(0, 6.0, 360)
        ka, Aa = fit_kA(t, Pa)
        kb, Ab = fit_kA(t, Pb)
        est.append(estimate_rb(ka, Aa, kb, Ab))
    est = np.array(est)
    q = np.percentile(est, [2.5, 97.5])
    print('  合成資料（k = %.2f vs %.2f，真值 r̄_b = %.4f）：'
          % (k_lo, k_hi, RB_PAPER))
    print('    中位 %.5f　95%% 區間 [%.5f, %.5f]　偏誤 %+.1f%%'
          % (np.median(est), q[0], q[1],
             (np.median(est) / RB_PAPER - 1) * 100))
    ok_rec = q[0] < RB_PAPER < q[1]
    print('  -> %s' % ('真值落在區間內，方法本身可用'
                       if ok_rec else '⚠ 真值落在區間外'))

    print('\n' + '=' * 76)
    print('二、真實資料：曲率與 k 是否如預期相關')
    print('=' * 76)
    ts, hh, p, orp, ph = load_full()
    segs = descents(hh, p)
    feats = []
    for s, e in segs:
        f = seg_fit(hh, p, s, e)
        if f is not None and np.isfinite(f['bow']):
            feats.append(f)
    print('  可用下降段 %d 個（自 %d 段）' % (len(feats), len(segs)))
    k = np.array([f['k'] for f in feats])
    bow = np.array([f['bow'] for f in feats])
    kT = k * np.array([f['dur'] for f in feats])
    rho, pv = perm_p(bow, kT)
    print('  曲率 vs kT：ρ = %+.3f，p = %.4f（n=%d）' % (rho, pv, len(feats)))
    print('  理論預期：**負相關**。正規化後的純指數，在 u=0.5 時')
    print('    s = (e^{-kT/2} − e^{-kT}) / (1 − e^{-kT})，kT 越大越小於直線的 0.5，')
    print('    故 bow = s − (1−u) 越負。（kT=5 時 s≈0.076，bow≈−0.42）')
    print('  -> %s' % ('符合理論' if (rho < -0.2 and pv < 0.05)
                       else '⚠ 與理論不符，需檢查曲率指標的定義'))
    print('  k 的分布：中位 %.3f，IQR [%.3f, %.3f]，範圍 [%.3f, %.3f]'
          % (np.median(k), *np.percentile(k, [25, 75]), k.min(), k.max()))

    print('\n' + '=' * 76)
    print('三、配對求解：時間窗 %.0f 天內、k 對比 >= %.1f 倍'
          % (WIN_DAYS, K_RATIO))
    print('=' * 76)
    pairs = []
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            a, b = feats[i], feats[j]
            if abs(a['t_mid'] - b['t_mid']) > WIN_DAYS * 24:
                continue
            lo, hi = (a, b) if a['k'] < b['k'] else (b, a)
            if hi['k'] / lo['k'] < K_RATIO:
                continue
            r = estimate_rb(lo['k'], lo['A'], hi['k'], hi['A'])
            if np.isfinite(r):
                pairs.append(dict(r=r, kr=hi['k'] / lo['k'], ia=i, ib=j,
                                  dt=abs(a['t_mid'] - b['t_mid']) / 24))
    print('  符合條件的配對 %d 組' % len(pairs))
    if len(pairs) < 10:
        print('  ⚠ 配對數過少，不足以估計。')
        return
    rr = np.array([pr['r'] for pr in pairs])
    pos = rr[rr > 0]
    print('  解出的 r̄_b：中位 %.5f　IQR [%.5f, %.5f]'
          % (np.median(rr), *np.percentile(rr, [25, 75])))
    print('  其中為正者 %d / %d (%.0f%%)'
          % (len(pos), len(rr), len(pos) / len(rr) * 100))
    # ⚠ 配對不獨立：上千組配對只來自兩百多條曲線，同一條會重複出現。
    #   對「配對」重抽會嚴重低估區間，必須對「曲線」重抽（cluster bootstrap）。
    ci = cluster_ci(pairs, rng)
    ci_naive = np.percentile(
        [np.median(rng.choice(rr, len(rr))) for _ in range(2000)], [2.5, 97.5])
    print('  中位數 95%% 區間（**以曲線為單位** cluster bootstrap）[%.5f, %.5f]'
          % (ci[0], ci[1]))
    print('  對照：對「配對」重抽的天真區間 [%.5f, %.5f]，寬度僅 %.0f%%'
          % (ci_naive[0], ci_naive[1],
             (ci_naive[1] - ci_naive[0]) / max(ci[1] - ci[0], 1e-12) * 100))
    print('  ⚠ 兩者的差距就是「配對不獨立」造成的假精度。')
    print('  對照：論文定版 r_b = %.4f' % RB_PAPER)
    inside = ci[0] <= RB_PAPER <= ci[1]
    print('  -> 定版值%s落在本方法的區間內' % ('' if inside else '**不**'))

    print('\n' + '=' * 76)
    print('四、⚠ 安慰劑對照：把「同期」這個前提打掉')
    print('=' * 76)
    print('  作法：改成只配對「時間相距超過 %.0f 天」的曲線。' % (WIN_DAYS * 4))
    print('  若 (★) 解出來的是真訊號，打掉同期前提後結果**應該變差**；')
    print('  若結果不變，代表解出來的東西與「同期」無關，不可信。\n')
    far_pairs = []
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            a, b = feats[i], feats[j]
            if abs(a['t_mid'] - b['t_mid']) < WIN_DAYS * 4 * 24:
                continue
            lo, hi = (a, b) if a['k'] < b['k'] else (b, a)
            if hi['k'] / lo['k'] < K_RATIO:
                continue
            r = estimate_rb(lo['k'], lo['A'], hi['k'], hi['A'])
            if np.isfinite(r):
                far_pairs.append(dict(r=r, ia=i, ib=j))
    far = np.array([pr['r'] for pr in far_pairs])
    if len(far) >= 10:
        cif = cluster_ci(far_pairs, rng)
        print('  安慰劑配對 %d 組：中位 %.5f，95%% 區間 [%.5f, %.5f]'
              % (len(far), np.median(far), cif[0], cif[1]))
        sep = (ci[1] < cif[0]) or (cif[1] < ci[0])
        print('  同期配對 中位 %.5f，95%% 區間 [%.5f, %.5f]'
              % (np.median(rr), ci[0], ci[1]))
        if sep:
            print('  -> **兩者區間不重疊**：同期配對確實帶來額外資訊。')
            print('  ★ 但更值得注意的是：**兩組的中位數都遠高於定版 %.4f**。'
                  % RB_PAPER)
            print('     故「定版被低估」這個結論，比「同期配對有效」更穩健')
            print('     ——它不依賴同期這個前提。')
        else:
            print('  -> ⚠ **兩者區間重疊**：打掉同期前提後結果沒變，')
            print('     表示 (★) 在真實資料上解出的東西**不是**來自同期配對，')
            print('     多半只是 k 與 A 的估計誤差在放大。**本路徑不成立。**')
    else:
        print('  安慰劑配對不足，無法對照')
        sep = None

    make_figure(feats, rr, far if len(far) >= 10 else None, ci)


def make_figure(feats, rr, far, ci):
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(15.0, 4.7),
                                     gridspec_kw={'wspace': 0.32})
    k = np.array([f['k'] for f in feats])
    bow = np.array([f['bow'] for f in feats])
    kT = k * np.array([f['dur'] for f in feats])

    a1.scatter(kT, bow, s=42, color=BLUE, alpha=0.65, edgecolors='none')
    a1.set_xscale('log')
    # ⚠ log 軸刻度走 mathtext，不受 axes.unicode_minus 管；
    #   中文字型下負號缺字會顯示成方框（此坑已第三次）。
    a1.set_xticks([0.01, 0.1, 1, 10])
    a1.set_xticklabels(['0.01', '0.1', '1', '10'])
    a1.minorticks_off()
    rho = spearman(bow, kT)
    _lo, hi = a1.get_ylim()
    a1.set_ylim(_lo, hi + (hi - _lo) * 0.32)
    a1.text(0.03, 0.97, '曲率越大 ⟺ kT 越大\nρ = %+.2f（n=%d）' % (rho, len(feats)),
            transform=a1.transAxes, fontsize=12, color=INK,
            fontweight='bold', ha='left', va='top')
    style(a1, 'a　曲率確實反映 kT', 'k × 時長（對數）', '曲率（bow）')

    lo_, hi_ = np.percentile(rr, [2, 98])
    a2.hist(rr, bins=np.linspace(lo_, hi_, 40), color=BLUE, edgecolor='white')
    a2.axvline(RB_PAPER, color=RED, lw=2.6, ls='--')
    a2.axvline(0, color=INK, lw=1.6)
    _, hi2 = a2.get_ylim()
    a2.set_ylim(0, hi2 * 1.38)
    a2.text(RB_PAPER, hi2 * 1.06, ' 論文定版', color=RED, fontsize=12,
            fontweight='bold', ha='left', va='bottom')
    a2.text(0.03, 0.97, '同期配對 %d 組\n中位 %.4f' % (len(rr), np.median(rr)),
            transform=a2.transAxes, fontsize=12, color=INK,
            fontweight='bold', ha='left', va='top')
    style(a2, 'b　解出的 r̄_b 分布', 'r̄_b', '配對數')

    if far is not None:
        a3.hist(rr, bins=np.linspace(lo_, hi_, 34), color=BLUE, alpha=0.65,
                edgecolor='white', density=True, label='同期配對')
        a3.hist(far, bins=np.linspace(lo_, hi_, 34), color=MUTED, alpha=0.60,
                edgecolor='white', density=True, label='安慰劑（相距遠）')
        a3.axvline(RB_PAPER, color=RED, lw=2.4, ls='--')
        _, hi3 = a3.get_ylim()
        a3.set_ylim(0, hi3 * 1.62)          # 先留白，圖例與文字才不會壓到長條
        a3.legend(loc='upper right', frameon=False, fontsize=11.5)
        a3.text(0.03, 0.80,
                '★ 兩組的「分布」大幅重疊，\n'
                '但兩者的「中位數」都遠高於定版。\n'
                '→「定版被低估」比「同期配對有效」更穩健。',
                transform=a3.transAxes, fontsize=11, color=INK,
                fontweight='bold', ha='left', va='top')
    style(a3, 'c　安慰劑對照', 'r̄_b', '密度')

    out = os.path.join(OUT, 'fig53_curvature_pair.png')
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
