
# -*- coding: utf-8 -*-
"""§5 的兩張結果圖（指導教授 2026-08-24 指定）。

figG_estimates —— §5.2「Physical and Biological Rate Estimation」
  (a) 一個代表性循環：感測器寫下的階梯數字、擬合曲線，以及兩項各自的貢獻
      教授原話：「最好選一個 representative cycle ... 讓讀者看到模型確實
      fit 得上」
  (b) k̂ 的分布（對數軸——k 橫跨兩個數量級）
  (c) r̂_b 的分布，標出中位數

figH_null —— §5.4「Evaluation Against the Purely Physical Null Model」
  純物理虛無下「聚合中位」的分布，與實測中位並列。
  教授原話：「如果 observed value 明顯落在 null distribution 外面，
  這張圖會非常有說服力」

⚠ 虛無的實作照論文 Algorithm 3：逐循環擬合 r_b ≡ 0 的兩參數式，
  由該擬合重新生成、加該段自己殘差尺度的 AR(1) 雜訊、量化到 0.01，
  再走同一個 Algorithm 1。虛無因此擁有除生物項以外的每一個自由度。
⚠ 逐段估計值不可單獨引用（見論文限制節）；本圖畫分布，不畫單點。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from dataset_c import collect_c                                # noqa: E402
from degeneracy_matched import CURV_MIN, ar1                   # noqa: E402
from fig_pressure_cascade import FIGDIR                        # noqa: E402
from paper_style import C, FS_NOTE, FS_SMALL, W, apply, save   # noqa: E402
from rb_recovery_study import curvature                        # noqa: E402
from simulator_check import QUANT, fit_LE                      # noqa: E402

RNG = np.random.default_rng(20260824)
KGRID = np.arange(0.01, 3.001, 0.02)
# 抽樣次數 41：0 次超過實測時，置換 p 值為 (0+1)/(41+1) = 0.024，
# 與論文 §5.4 所報的數字一致。p 值在此**受抽樣次數限制**——虛無中位
# 只有 0.0004 而實測 0.0128，兩者相距極遠，再多抽樣也不會有超過的，
# 所報的 0.024 是該預算下的上界，不是「剛好落在邊緣」。
DRAWS = 41


def fit_phys(t, y):
    """r_b ≡ 0 的兩參數擬合：P_eq + A e^{-kt}。虛無的參照就是它。"""
    best = None
    for k in KGRID:
        A = np.vstack([np.exp(-k * t), np.ones_like(t)]).T
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y - A @ c
        s = float(r @ r)
        if best is None or s < best[0]:
            best = (s, c, k, r)
    s, c, k, r = best
    return dict(amp=c[0], peq=c[1], k=k, resid=r,
                sd=np.sqrt(s / max(len(t) - 3, 1)))


def retained():
    """通過曲率預篩的循環，連同各自的 LE 擬合。"""
    out = []
    for tag, t, y in collect_c():
        cv = curvature(t, y)
        if not np.isfinite(cv) or cv < CURV_MIN:
            continue
        out.append((tag, t, y, fit_LE(t, y)))
    return out


def pick_representative(rows):
    """選一個能代表整體的循環：k、r_b、時長都接近各自的中位。

    ⚠ 不挑「擬合最漂亮」的那一個——那會是選擇性展示。以離中位的
      距離排序，取最接近者。
    ⚠ 但必須先排除病態段：A 與 k 互相交換，k 極小時 A 會爆到 58，
      整條指數項掉出資料範圍之外；239 段裡另有 50 段（21%）的 r_b
      是負的。拿這些去示範「模型擬合得上」正好反效果。
    """
    ks = np.array([f['k'] for *_, f in rows])
    rb = np.array([f['rb'] for *_, f in rows])
    am = np.array([f['amp'] for *_, f in rows])
    sd = np.array([f['sd'] for *_, f in rows])
    du = np.array([t[-1] for _, t, _, _ in rows])
    km, rm, amd, sdm, dum = (float(np.median(v)) for v in (ks, rb, am, sd, du))
    ok = (rb > 0) & (am > 0) & (am < 4 * amd) & (sd < 1.8 * sdm)
    score = (np.abs(np.log(ks / km)) + np.abs(rb - rm) / rm
             + np.abs(np.log(du / dum)))
    score = np.where(ok, score, np.inf)
    assert np.isfinite(score).any(), '沒有任何循環通過代表性條件'
    return rows[int(np.argmin(score))]


def fig_estimates(rows):
    apply()
    fig, ax = plt.subplots(1, 3, figsize=(W, 1.52))

    # ── (a) 代表性循環 ─────────────────────────────────────
    _tag, t, y, f = pick_representative(rows)
    phys = f['peq'] + f['amp'] * np.exp(-f['k'] * t)
    curve = phys - f['rb'] * t
    # 兩條線之間的落差就是生物那一份——畫成陰影，讀者才看得到分解。
    # 陰影不進圖例：圖說已說明它是生物那一份，而四列圖例會過寬。
    ax[0].fill_between(t, curve, phys, color=C['accent'], alpha=.16, lw=0)
    # ⚠ 標籤不可寫成 'logged (0.01 step)'：那是圖例裡最長的一行，會往右
    #   伸到欄寬的八成，正落在下降曲線底下而被壓到。量化階改由圖說交代。
    ax[0].step(t, y, where='post', lw=.7, color=C['main'], label='logged')
    ax[0].plot(t, curve, lw=1.1, color=C['accent'], label='fitted total')
    ax[0].plot(t, phys, lw=.8, ls='--', color=C['sec'],
               label='physical part')
    ax[0].set_xlabel('Time since refill (hr)', fontsize=FS_NOTE)
    ax[0].set_ylabel('Pressure (kg/cm$^2$)', fontsize=FS_NOTE)
    ax[0].set_title('(a) One cycle, observed and fitted',
                    fontsize=FS_NOTE)
    # ⚠ 兩欄會寬到溢出格外、壓到 (b)；四列直排又會撞到下降曲線。
    #   三列單欄配上加大的底部留白，是唯一兩邊都不犯的排法。
    ax[0].legend(fontsize=FS_SMALL, frameon=False, loc='lower left',
                 labelspacing=.18, handlelength=1.0, borderpad=.15)
    lo = min(float(np.min(y)), float(np.min(curve)))
    hi = max(float(np.max(y)), float(np.max(phys)))
    # 底部多留白：四列的圖例需要地方站，否則會壓到下降曲線。
    # 頂部也要留：k̂ 與 r̂_b 兩列站在右上角，留白不夠時帽子會頂到框線、
    # 第二列會壓到曲線起點。把上緣抬高才有位置，硬移只會換一邊犯。
    pad = (hi - lo) * .10
    ax[0].set_ylim(lo - pad * 3.4, hi + pad * 2.9)
    ax[0].text(.97, .965,
               '$\\hat{k}$ = %.2f /hr\n$\\hat{r}_b$ = %.4f' % (f['k'], f['rb']),
               transform=ax[0].transAxes, fontsize=FS_SMALL, linespacing=1.5,
               color=C['main'], ha='right', va='top')

    # ── (b) k̂ 的分布 ──────────────────────────────────────
    ks = np.array([g['k'] for _, _, _, g in rows])
    ax[1].hist(ks, bins=np.logspace(np.log10(.01), np.log10(3), 26),
               color=C['fill'], edgecolor=C['main'], lw=.5)
    ax[1].set_xscale('log')
    ax[1].axvline(np.median(ks), color=C['accent'], lw=1.0)
    ax[1].set_xlabel('$\\hat{k}$ (/hr)', fontsize=FS_NOTE)
    ax[1].set_ylabel('Cycles', fontsize=FS_NOTE)
    ax[1].set_title('(b) Relaxation rate', fontsize=FS_NOTE)
    ax[1].text(.97, .93, 'median %.2f' % np.median(ks),
               transform=ax[1].transAxes, ha='right', va='top',
               fontsize=FS_SMALL, color=C['accent'])

    # ── (c) r̂_b 的分布 ────────────────────────────────────
    rb = np.array([g['rb'] for _, _, _, g in rows])
    lo, hi = -0.02, 0.06
    ax[2].hist(np.clip(rb, lo, hi), bins=32, range=(lo, hi),
               color=C['fill'], edgecolor=C['main'], lw=.5)
    med = float(np.median(rb))
    ax[2].axvline(med, color=C['accent'], lw=1.0)
    ax[2].axvline(0, color=C['main'], lw=.6, ls=':')
    ax[2].set_xlabel('$\\hat{r}_b$ (kg/cm$^2$/hr)', fontsize=FS_NOTE)
    ax[2].set_ylabel('Cycles', fontsize=FS_NOTE)
    ax[2].set_title('(c) Biological removal rate', fontsize=FS_NOTE)
    ax[2].text(.97, .93, 'median %.4f' % med, transform=ax[2].transAxes,
               ha='right', va='top', fontsize=FS_SMALL, color=C['accent'])
    # ⚠ 兩端的柱子是超出繪圖範圍者的堆積，不是真的有那麼多段落在那裡。
    #   不標明會讓讀者以為 -0.02 附近有一個真實的眾數。
    n_lo = int((rb < lo).sum())
    n_hi = int((rb > hi).sum())
    # 放在中位數標籤的正下方、同樣靠右：左上角會與中位數那行相撞。
    # 拆成上下兩排：單排會橫跨大半個格寬，右端貼近中位數紅線，
    # 且左端會伸到 0.000 附近的柱子上方。
    ax[2].text(.97, .78, '%d below\n%d above range' % (n_lo, n_hi),
               transform=ax[2].transAxes, ha='right', va='top',
               linespacing=1.35, fontsize=FS_SMALL - .8, color=C['main'])

    for a in ax:
        a.tick_params(labelsize=FS_SMALL)
        a.grid(alpha=.20)
    fig.tight_layout(pad=0.30)
    save(fig, 'figG_estimates', FIGDIR)
    return med


def fig_null(rows, observed):
    """Algorithm 3：把生物項強制設為零，看同一條流程還能生出什麼。"""
    apply()
    phys = []
    for _tag, t, y, _f in rows:
        g = fit_phys(t, y)
        r = g['resid']
        phi = (float(np.corrcoef(r[:-1], r[1:])[0, 1])
               if r.std() > 0 else 0.)
        phys.append((t, g, max(g['sd'], QUANT / 4),
                     float(np.clip(phi * 1.3, 0, .98))))

    meds = []
    for _d in range(DRAWS):
        got = []
        for t, g, sd, phi in phys:
            z = g['peq'] + g['amp'] * np.exp(-g['k'] * t) + ar1(len(t), sd, phi)
            w = np.round(z / QUANT) * QUANT
            if curvature(t, w) < CURV_MIN:
                continue
            got.append(fit_LE(t, w)['rb'])
        if got:
            meds.append(float(np.median(got)))
    meds = np.array(meds)
    # 置換 p 值一律用 +1 修正：0 次超過不等於機率為零。
    p = (1 + int((meds >= observed).sum())) / (1 + len(meds))

    fig, ax = plt.subplots(figsize=(W * 0.62, 1.42))
    ax.hist(meds, bins=18, color=C['fill'], edgecolor=C['main'], lw=.5,
            label='null: $r_b \\equiv 0$')
    ax.axvline(observed, color=C['accent'], lw=1.3)
    ax.annotate('observed\n%.4f' % observed,
                xy=(observed, ax.get_ylim()[1] * .72),
                xytext=(-4, 0), textcoords='offset points',
                ha='right', va='center', fontsize=FS_SMALL,
                color=C['accent'])
    ax.set_xlabel('Aggregate median $\\hat{r}_b$ (kg/cm$^2$/hr)',
                  fontsize=FS_NOTE)
    ax.set_ylabel('Draws', fontsize=FS_NOTE)
    ax.set_title('Physics alone does not reach the observed rate',
                 fontsize=FS_NOTE)
    # 註記放中段的空白處：虛無全擠在左側，(.03) 會壓到直條。
    ax.text(.32, .92, 'null median %.5f\n$p$ = %.3f'
            % (float(np.median(meds)), p),
            transform=ax.transAxes, va='top', fontsize=FS_SMALL,
            color=C['main'])
    ax.tick_params(labelsize=FS_SMALL)
    ax.grid(alpha=.20)
    fig.tight_layout(pad=0.30)
    save(fig, 'figH_null', FIGDIR)
    print('   虛無中位 %.5f，最大抽樣 %.5f，實測 %.5f，p = %.3f'
          % (float(np.median(meds)), float(meds.max()), observed, p))


def main():
    rows = retained()
    print('通過預篩的循環：%d' % len(rows))
    med = fig_estimates(rows)
    fig_null(rows, med)


if __name__ == '__main__':
    main()
