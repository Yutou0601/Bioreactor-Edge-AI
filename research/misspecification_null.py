# -*- coding: utf-8 -*-
"""
測試 A1：模型設定誤差本身能不能製造出 rb？
════════════════════════════════════════════════════════════════════════

背景
────
joint_fit_calibrated.py 的自助校準，虛無資料是用「同一個單指數模型」的擬合值
加上重抽殘差產生的（make_null 內呼叫 traj）。因此**模型設定誤差同時存在於真實
資料與虛無資料裡，會互相抵消**——該檢定能認證「估計量會不會從噪聲造出 rb」，
但無法認證「模型是不是對的」。

而殘差診斷顯示模型確實設定錯誤：26 個循環的末點殘差 26/26 同號
（符號檢定 p = 3e-8），殘差沿循環呈 U 形、前段符號隨 tau 翻轉——
單指數擬合雙時間尺度過程的典型指紋。two_state_model.csv 亦顯示雙指數的
AICc 遠優於單指數，但機理式雙態參數化不可辨識（sane=False，kla 頂到上界）。

本測試
──────
改用**雙指數、且完全不含生物匯（rb ≡ 0）**的軌跡當「真相」產生合成資料，
送進**現行的一步聯合擬合**。若它仍回收出接近實測 0.01104 的 rb，
就證明設定誤差本身足以製造主結果；若回收 rb ≈ 0，則主結果對設定誤差穩健。

兩種真相
────────
  A 每循環各自擬合雙指數（漸近線自由）——形狀最貼近實測，對虛無最寬容
  B 每批共用漸近線——限制較嚴，較不易用「很慢的第二指數」去模仿常數匯

輸出 -> docs/analysis_charts_3batch/misspecification_null.csv + fig30
"""
import os
import sys

import numpy as np
from scipy import optimize

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT, RED, AQUA, BLUE, INK, INK2, MUTED, style  # noqa: E402
from joint_fit_calibrated import load, joint, two_step, BN, BLOCK, QUANT  # noqa: E402

NBOOT = 200
OBS_RB = 0.011038849949434663      # 實測（校準後）的共用 rb


# ══════════════════════════════════════════════════════════════════
# 雙指數真相：P(t) = C + A1 e^{-l1 t} + A2 e^{-l2 t}，A1+A2 = P0 - C
# dP/dt -> 0 當 P -> C，故**不含**任何常數生物匯，rb 恆為 0。
# ══════════════════════════════════════════════════════════════════
def biexp(t, P0, C, f, l1, l2):
    amp = P0 - C
    return C + amp * (f * np.exp(-l1 * t) + (1 - f) * np.exp(-l2 * t))


def fit_biexp(t, P, C_fixed=None):
    P0 = P[0]

    def resid(th):
        C = C_fixed if C_fixed is not None else th[0]
        f, l1, l2 = th[-3:]
        return biexp(t, P0, C, f, l1, l2) - P

    if C_fixed is None:
        x0 = [max(P[-1] - 0.15, 0.05), 0.5, 0.5, 0.05]
        lo = [0.02, 0.0, 1e-3, 1e-4]
        hi = [min(P[-1], 0.95), 1.0, 8.0, 1.0]
    else:
        x0 = [0.5, 0.5, 0.05]
        lo = [0.0, 1e-3, 1e-4]
        hi = [1.0, 8.0, 1.0]
    r = optimize.least_squares(resid, x0, bounds=(lo, hi), max_nfev=8000)
    C = C_fixed if C_fixed is not None else r.x[0]
    f, l1, l2 = r.x[-3:]
    if l1 < l2:                                  # 令 l1 為快尺度
        f, l1, l2 = 1 - f, l2, l1
    return C, f, l1, l2, float(np.sqrt(np.mean(resid(r.x) ** 2)))


def build_truth(D, shared_C):
    """回傳 {batch: [(t, P_obs, base_biexp), ...]}，base 即 rb≡0 的真相軌跡。"""
    truth, info = {}, []
    for b in BN:
        C_fixed = None
        if shared_C:
            # 以該批所有循環的自由擬合漸近線中位數作為共用值
            cs = [fit_biexp(t, P)[0] for t, P in D[b]]
            C_fixed = float(np.median(cs))
        lst = []
        for t, P in D[b]:
            C, f, l1, l2, rmse = fit_biexp(t, P, C_fixed)
            lst.append((t, P, biexp(t, P[0], C, f, l1, l2)))
            info.append((b, C, f, l1, l2, rmse))
        truth[b] = lst
    return truth, info


def synth(truth, rng):
    """在雙指數真相上疊區塊自助殘差，並量化到感測器解析度。"""
    out = {}
    for b in BN:
        lst = []
        for t, P, base in truth[b]:
            res = P - base
            n = len(res)
            rr = np.concatenate([res[j:j + BLOCK] for j in
                                 rng.integers(0, max(n - BLOCK, 1),
                                              size=n // BLOCK + 2)])[:n]
            lst.append((t, np.round((base + rr) / QUANT) * QUANT))
        out[b] = lst
    return out


def run(D, shared_C, tag, rng):
    truth, info = build_truth(D, shared_C)
    rmse = np.mean([x[5] for x in info])
    l1 = np.median([x[3] for x in info])
    l2 = np.median([x[4] for x in info])
    print(f'\n── 真相 {tag} ──')
    print(f'   雙指數擬合 RMSE = {rmse:.5f} kg/cm²'
          f'   （單指數聯合擬合約 0.0103~0.0158）')
    print(f'   快尺度 lambda1 中位 = {l1:.3f} /hr（半衰期 {np.log(2)/l1:.2f} hr）')
    print(f'   慢尺度 lambda2 中位 = {l2:.3f} /hr（半衰期 {np.log(2)/l2:.2f} hr）')
    print(f'   本真相的生物匯 rb 恆為 0（漸近線處 dP/dt = 0）')

    rb_j, rb_2 = [], []
    for i in range(NBOOT):
        s = synth(truth, rng)
        try:
            rb_j.append(float(joint(s)[4]))
        except Exception:
            pass
        try:
            rb_2.append(float(two_step(s)[0]))
        except Exception:
            pass
        if (i + 1) % 50 == 0:
            print(f'   ... {i+1}/{NBOOT}')
    rb_j = np.array(rb_j)
    rb_2 = np.array([x for x in rb_2 if np.isfinite(x)])
    p = float((rb_j >= OBS_RB).mean())
    print(f'\n   【一步聯合擬合】在此虛無下回收的假 rb：')
    print(f'      中位 = {np.median(rb_j):.5f}   95% = {np.percentile(rb_j,95):.5f}'
          f'   最大 = {rb_j.max():.5f}   n = {len(rb_j)}')
    print(f'      實測 {OBS_RB:.5f} → p = {p:.4f}   '
          f'{"✗ 設定誤差足以製造主結果" if p > 0.05 else "★ 主結果對設定誤差穩健"}')
    if len(rb_2):
        print(f'   【兩步驟法】中位 = {np.median(rb_2):.5f}'
              f'   95% = {np.percentile(rb_2,95):.5f}')
    return rb_j, rb_2, dict(tag=tag, rmse=rmse, l1=l1, l2=l2,
                            med=float(np.median(rb_j)),
                            p95=float(np.percentile(rb_j, 95)),
                            mx=float(rb_j.max()), p=p, n=len(rb_j))


def main():
    D = load()
    print('══ A1：以「雙指數、rb≡0」為真相的設定誤差虛無檢定 ══')
    print(f'   26 個循環，B = {NBOOT}，實測共用 rb = {OBS_RB:.5f}')
    rng = np.random.default_rng(7)
    a_j, a_2, ia = run(D, False, 'A（每循環自由漸近線）', rng)
    b_j, b_2, ib = run(D, True, 'B（每批共用漸近線）', rng)

    import csv
    fp = f'{OUT}/misspecification_null.csv'
    with open(fp, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(ia.keys()))
        w.writeheader()
        w.writerow(ia)
        w.writerow(ib)
    figures(a_j, b_j, ia, ib)
    print(f'\n輸出 → {fp}')


def figures(a_j, b_j, ia, ib):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.4))
    for ax, v, meta, col in ((axes[0], a_j, ia, AQUA), (axes[1], b_j, ib, BLUE)):
        ax.hist(v, bins=28, color=col, alpha=0.85,
                label='雙指數 rb≡0 的合成資料')
        ax.axvline(OBS_RB, color=RED, lw=2.6)
        ax.annotate(f'實測 {OBS_RB:.5f}\np = {meta["p"]:.3f}',
                    xy=(0.62, 0.72), xycoords='axes fraction',
                    fontsize=10.5, color=RED, fontweight='bold')
        ax.annotate(f'虛無中位 {meta["med"]:.5f}', xy=(0.04, 0.88),
                    xycoords='axes fraction', fontsize=9.5, color=INK2)
        style(ax, f'真相 {meta["tag"]}', '回收的 rb (kg/cm²/hr)', '次數')
        ax.legend(frameon=False, fontsize=9)
    fig.suptitle('圖30  設定誤差虛無檢定：把「真相」換成不含生物匯的雙指數',
                 fontweight='bold', x=0.05, ha='left', y=0.99)
    fig.text(0, -0.06,
             '自助校準的虛無資料原本是用同一個單指數模型產生的，故模型設定誤差在真實與虛無資料裡互相抵消。'
             '本圖改以雙指數（rb 恆為 0）為真相：\n'
             '若實測值落在分佈之內，代表設定誤差本身即可製造出該結果；落在分佈之外，'
             '才表示主結果對設定誤差穩健。',
             fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig30_misspecification_null.png', bbox_inches='tight')
    plt.close(fig)
    print('  圖 30 完成')


if __name__ == '__main__':
    main()
