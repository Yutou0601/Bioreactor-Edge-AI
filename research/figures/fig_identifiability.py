
# -*- coding: utf-8 -*-
"""
新圖組（一）：可辨識性障礙 與 配對基準的解法
════════════════════════════════════════════════════════════════════════

改版後論文的主軸是「**如何**從單一量化壓力通道把 r_b 挖出來」，
所以圖要說的是方法的因果鏈，不是操作史。

  figA  障礙：兩組差很多的 (k, r_b) 配出幾乎相同的軌跡
        —— 說明為什麼直接擬合的數字不能信
  figB  解法：配對基準模擬讓估計假影在兩邊抵消
        —— 實測 ρ 與 B0/B1/B2 的比較，＋聚合中位數的回收

一律輸出 .pdf/.svg（向量）＋ .png（1200 dpi 後備）。

輸出 -> docs/paper_figures/
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import matplotlib.pyplot as plt                                    # noqa: E402

from paper_style import apply, save, W, C, U, FS_NOTE, FS_SMALL    # noqa: E402
from analyze_three_batches import OUT                              # noqa: E402
from rb_vs_k_form import fit_LE_fast, KGRID                        # noqa: E402
from residual_structure import collect                             # noqa: E402
from rb_recovery_study import curvature                            # noqa: E402

FIGDIR = os.path.join(os.path.dirname(OUT), 'paper_figures')


def read_matched():
    """讀 degeneracy_matched.csv。"""
    base, extra = {}, {}
    with open(f'{OUT}/degeneracy_matched.csv', encoding='utf-8-sig') as fh:
        for row in csv.reader(fh):
            if not row or not row[0]:
                continue
            if row[0] in ('B0', 'B1', 'B2'):
                base[row[0]] = (float(row[1]), float(row[2]), float(row[3]))
            elif row[0] in ('rho_observed', 'rb_observed_median', 'n_cycles'):
                extra[row[0]] = float(row[1])
    return base, extra


# ══════════════════════════════════════════════════════════════
def profile(t, y):
    """固定 k、重解線性參數，一次算完整條剖面 (k, r_b, SSE)。"""
    E = np.exp(-KGRID[:, None]*t[None, :])
    n = len(t)
    G = np.empty((len(KGRID), 3, 3))
    G[:, 0, 0] = (E*E).sum(1)+1e-12
    G[:, 0, 1] = G[:, 1, 0] = E @ t
    G[:, 0, 2] = G[:, 2, 0] = E.sum(1)
    G[:, 1, 1] = float(t @ t); G[:, 1, 2] = G[:, 2, 1] = t.sum()
    G[:, 2, 2] = n
    b = np.empty((len(KGRID), 3))
    b[:, 0] = E @ y; b[:, 1] = float(t @ y); b[:, 2] = y.sum()
    c = np.linalg.solve(G, b[:, :, None])[:, :, 0]
    sse = float(y @ y)-np.einsum('ij,ij->i', c, b)
    return KGRID, -c[:, 1], sse, c


def _band(t, y, tol=0.01):
    """1 % SSE 容忍帶內 r_b 的跨幅——簡併程度的直接度量。"""
    kk, rr, ss, c = profile(t, y)
    ok = ss <= ss.min()*(1+tol)
    return float(rr[ok].max()-rr[ok].min()), (kk, rr, ss, c, ok)


def figA(cycles):
    """障礙：簡併循環 vs 可辨識循環。

    ⚠ 初版挑「時長接近中位」的循環當示範，結果挑到一個 k=0.45、本來就好
      辨識的例子，兩個解只差 3 %，完全看不出簡併。示範用的例子要**由簡併
      程度本身**挑，並且要有可辨識的對照，才說得出為什麼需要曲率篩選。
    """
    # ⚠ 第二版改挑「跨幅最大」，結果挑到病態片段：r_b = +3.23（真值的 300 倍）、
    #   軌跡先升後降、壓力只有 0.24——那是壞切分，不是有代表性的簡併循環。
    #   取極值必取離群。改挑**兩組各自的中位數代表**：曲率篩選擋掉的典型循環
    #   vs 通過的典型循環，這樣圖說明的才是「篩選在做什麼」。
    cand, cv, spans = [], [], []
    for _, t, y in cycles:
        if len(t) < 50:
            continue
        c0 = curvature(t, y)
        amp = y[0]-y[-1]
        if not np.isfinite(c0) or amp <= 0.10:
            continue
        try:
            s, _ = _band(t, y)
        except Exception:
            continue
        cand.append((t, y)); cv.append(c0); spans.append(s)
    cv, spans = np.array(cv), np.array(spans)

    def median_rep(mask):
        idx = np.where(mask)[0]
        return int(idx[np.argsort(spans[idx])[len(idx)//2]])

    jbad = median_rep(cv < 0.45)                # 被篩掉的典型
    jgood = median_rep(cv >= 0.45)              # 通過的典型

    apply()
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.05))

    # ── (a) 簡併循環：兩組解、同一條軌跡 ──────────────
    t, y = cand[jbad]
    _, (kk, rr, ss, c, ok) = _band(t, y)
    jb = int(np.argmin(ss))
    idx = np.where(ok)[0]
    ja = idx[int(np.argmax(np.abs(rr[idx]-rr[jb])))]
    ax = axes[0]
    ax.plot(t, y, '.', ms=0.7, color=C['sec'], alpha=.5,
            label='measured', rasterized=True)
    for j, st, lab in ((jb, '-', 'best'), (ja, '--', 'alternative')):
        ax.plot(t, c[j, 0]*np.exp(-kk[j]*t)+c[j, 1]*t+c[j, 2], st, lw=1.0,
                color=(C['main'] if j == jb else C['accent']),
                label=f'{lab}:  $k$={kk[j]:.2f},  $r_b$={rr[j]:+.3f}')
    ax.set_xlabel('Time since refill  (hr)')
    ax.set_ylabel(f'Pressure  ({U["p"]})')
    # 圖例移到左下、**貼在註解正上方**——放右上會壓到軌跡起點。
    ax.legend(loc='lower left', bbox_to_anchor=(0.0, 0.13), frameon=False,
              handlelength=1.6, fontsize=FS_SMALL, borderaxespad=0.3)
    # 面板標題一律首字母大寫（其餘小寫）——這一個先前漏改成 'a rejected'。
    ax.set_title(f'(a)  A rejected cycle  (curvature {cv[jbad]:.2f})',
                 loc='left')
    # ⚠ 註解必須**留在座標區內**。寫成一長行時 savefig 的 bbox='tight'
    #   會把畫布往外撐開，整張圖的長寬比就毀了，還會壓到隔壁面板。
    ax.text(.03, .02, 'both curves fit within 1 % of\nthe same residual '
            'sum of squares', transform=ax.transAxes,
            fontsize=FS_NOTE, va='bottom')
    # 右上角是空的（軌跡由左上往右下走）——用來寫判讀，不浪費版面。
    ax.text(.97, .95, 'nearly straight:\n$k$ unconstrained',
            transform=ax.transAxes, fontsize=FS_NOTE, ha='right', va='top')

    # ── (b) 兩條剖面對照 ──────────────────────────────
    ax = axes[1]
    for j, col, lab in ((jbad, C['accent'], f'rejected  (curv {cv[jbad]:.2f})'),
                        (jgood, C['main'], f'retained  (curv {cv[jgood]:.2f})')):
        t2, y2 = cand[j]
        sp, (k2, r2, s2, _, ok2) = _band(t2, y2)
        ax.plot(k2, r2, '-', lw=1.1, color=col,
                label=f'{lab},  span {sp:.3f}')
        ax.fill_between(k2, -1, 1, where=ok2, color=col, alpha=.14, lw=0)
    ax.axhline(0, color=C['sec'], lw=.5, ls=':')
    ax.set_xscale('log')
    lo = min(_band(cand[j][0], cand[j][1])[1][1].min()
             for j in (jbad, jgood))
    hi = max(_band(cand[j][0], cand[j][1])[1][1].max()
             for j in (jbad, jgood))
    pad = 0.12*(hi-lo)
    ax.set_ylim(lo-pad, hi+pad*3.2)
    ax.set_xlabel(r'Fixed relaxation constant $k$  '+f'({U["inv"]})')
    ax.set_ylabel(r'Recovered $r_b$  'f'({U["rate"]})')
    ax.legend(loc='upper left', frameon=False, fontsize=FS_SMALL,
              handlelength=1.6)
    ax.text(.97, .30, 'shaded: within 1 %\nof min SSE', transform=ax.transAxes,
            fontsize=FS_NOTE, ha='right', va='bottom')
    ax.set_title('(b)  The screen separates the two', loc='left')

    fig.tight_layout(pad=0.3, w_pad=1.0)
    save(fig, 'figA_identifiability', FIGDIR)


# ══════════════════════════════════════════════════════════════
def read_invert():
    """degeneracy_invert.csv：β 掃描的校準曲線與偏誤。"""
    head, rows = {}, []
    with open(f'{OUT}/degeneracy_invert.csv', encoding='utf-8-sig') as fh:
        grab = False
        for r in csv.reader(fh):
            if not r:
                continue
            if r[0] == 'beta':
                grab = True; continue
            if grab:
                rows.append([float(v) for v in r])
            elif len(r) > 1:
                head[r[0]] = float(r[1])
    a = np.array(rows)
    return head, a[:, 0], a[:, 1], a[:, 2], a[:, 5], a[:, 6]


def figB():
    """簡併判讀：把 k 依賴當成待反解的參數，而不是假設。

    ⚠ 舊版畫的是 B0/B1/B2 三根長條，其中 B2 的斜率是從**實測的
      (r̂_b, k̂) 配對**迴歸來的——而 ρ(r̂_b, k̂) 正是要被解釋的量。用被
      解釋量算出來的參數當真值，ρ 保證會高，那根 0.797 不構成證據。
      改成掃 β 反解之後，曲線在 0.75–0.77 就飽和，構不到實測的 0.831。
      同時把「k 依賴的代價」畫出來：偏誤 0% 只成立於 β=0。
    """
    base, extra = read_matched()
    _, beta, rho, rsd, bias, seln = read_invert()
    rho_obs = extra['rho_observed']

    # 相容區間與修正量由 rb_corrected.py 決定，這裡只讀，不重算——
    # 兩邊各算一次遲早會不一致。
    cc, comp = {}, []
    with open(f'{OUT}/rb_corrected.csv', encoding='utf-8-sig') as fh:
        grab = False
        for r in csv.reader(fh):
            if not r:
                continue
            if r[0] == 'beta':
                grab = True; continue
            if grab:
                if int(r[5]):
                    comp.append(float(r[0]))
            elif len(r) > 1:
                cc[r[0]] = float(r[1])
    bmin, bmax = min(comp), max(comp)
    corr_pct = (cc['rb_corrected']/cc['rb_uncorrected']-1)*100
    apply()
    # ⚠ 2026-08-24 改為單欄、兩格上下堆疊。並排版寬 6.89" 必須跨欄，
    #   而跨欄要切連續分節符，Word 塞不下就整塊推到次頁，在圖上方
    #   留下大片空白。堆疊後寬 3.27"（＝ACM 單欄），排進文字流即可。
    #   畫布寬度亦改為 3.27"，字級才不會被縮放。
    # ⚠ 2026-08-24 由 3.30" 壓到 2.58"：Word 實測左欄放不下「圖＋長圖說」
    #   這一整塊（約 4.9"），整塊被推到右欄，左欄底下留了約 4.5" 空白。
    #   兩格共用同一條 β 軸，上格的 x 標籤原本是重複的，改 sharex 直接
    #   省掉一整行加一組刻度標籤。
    fig, axes = plt.subplots(2, 1, figsize=(3.27, 2.58), sharex=True)

    # ── (a) 校準曲線：ρ 需要多強的 k 依賴 ────────────────
    ax = axes[0]
    ax.fill_between(beta, rho-rsd, rho+rsd, color=C['fill'], alpha=.55, lw=0)
    ax.plot(beta, rho, 'o-', ms=2.8, lw=1.1, color=C['main'],
            label=r'truth $r_b\propto k^{\beta}$')
    ax.plot([0], [base['B1'][0]], 's', ms=4, color=C['sec'],
            label='random, indep. of $k$')
    ax.axhline(rho_obs, color=C['accent'], lw=1.1, ls='--')
    ax.text(.02, rho_obs+.02, f'observed  {rho_obs:.3f}', color=C['accent'],
            fontsize=FS_NOTE, va='bottom', ha='left')
    # ⚠ 說明文字不可放在虛線與曲線之間——那道空隙只有 0.07 高，字會同時
    #   壓到 observed 虛線與曲線。相容區間改用色帶標，字放圖底空白處。
    ax.axvspan(bmin, bmax, color=C['accent'], alpha=.10, lw=0, zorder=0)
    ax.text((bmin+bmax)/2, .06,
            f'compatible\n$\\beta$ = {bmin:.2f}–{bmax:.2f}',
            fontsize=FS_SMALL, ha='center', va='bottom')
    # x 標籤只掛在下格（sharex），上格重複掛會多佔一行
    ax.set_ylabel(r'$\rho(\hat r_b,\ \hat k)$')
    ax.set_ylim(0, 1.02)
    ax.legend(loc='center right', frameon=False, fontsize=FS_SMALL,
              handlelength=1.4)
    ax.set_title('(a)  A constant truth is excluded', loc='left')

    # ── (b) 由偏誤曲線讀出修正量 ─────────────────────────
    ax = axes[1]
    ax.axvspan(bmin, bmax, color=C['accent'], alpha=.10, lw=0, zorder=0)
    ax.axhline(0, color=C['sec'], lw=.8, ls=':')
    ax.plot(beta, bias, 'o-', ms=2.8, lw=1.1, color=C['main'],
            label='estimator bias')
    ax.plot(beta, seln, 's--', ms=2.6, lw=1.0, color=C['sec'],
            label='screen selection')
    ax.set_xlabel(r'Exponent $\beta$  of the $k$ dependence')
    # 堆疊版的格高只剩一半，原標籤會溢到上一格去。
    ax.set_ylabel('Bias of the median  (%)')
    # ⚠ 舊式固定壓到 −8。去重後兩條曲線都落在正值，那片負區全是死空間，
    #   在單欄堆疊版裡等於白白吃掉四分之一格高。改為貼著實際資料，只保
    #   留讓零虛線看得見的餘裕。
    _lo = min(seln.min(), bias.min(), 0.)
    ax.set_ylim(_lo - 2, max(seln.max(), bias.max()) + 6)
    # ⚠ 圖例佔住左上，修正量放 (bmin+bmax)/2 會直接壓在 'estimator bias'
    #   後面。挪到右上角、避開圖例的水平範圍。
    # ⚠ 位置改用軸比例。原本綁 bias.max()+8.6，而上限已改為隨
    #   seln.max()（達 30%）而定，綁絕對值會讓字掉進圖中央壓到虛線。
    ax.text(.98, .95, f'correction {corr_pct:+.1f} %',
            transform=ax.transAxes, fontsize=FS_SMALL, ha='right', va='top')
    ax.legend(loc='upper left', frameon=False, fontsize=FS_SMALL,
              handlelength=1.4)
    ax.set_title('(b)  The calibrated correction', loc='left')

    fig.tight_layout(pad=0.3, h_pad=0.45)
    save(fig, 'figB_matched_baseline', FIGDIR)


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    print('══ 新圖組（一）══\n')
    cycles = collect()
    figA(cycles)
    figB()


if __name__ == '__main__':
    main()
