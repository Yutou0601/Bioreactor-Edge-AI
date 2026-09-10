# -*- coding: utf-8 -*-
"""
驗證 misspecification_null.py 的結論是否可信
════════════════════════════════════════════════════════════════════════

在用一個新腳本推翻論文主結果之前，該腳本本身必須先通過驗證。本檔跑七項檢查：

  V1 正對照  單指數真相 + 已知 rb = 0.011 → 估計量應回收 ≈ 0.011（否則測試台壞了）
  V2 負對照  單指數真相 + rb = 0          → 應回收 ≈ 0（且須與原 make_null 一致）
  V3 純偏誤  雙指數真相 + 無噪聲          → 回收值即「純設定誤差偏誤」，不含任何抽樣噪聲
  V4 收斂性  檢查 joint() 的解有沒有頂到參數界（頂界＝解無意義）
  V5 振幅分解 慢分量佔總壓降多少？若其半衰期 >> 循環長度，它在窗口內近乎線性，
             批評者會說「慢指數只是 rb 改名」——故必須量化並正面回應
  V6 保守真相 C  強制兩個時間尺度都在循環內可解析（λ2 ≥ 0.15/hr，半衰期 ≤ 4.6 hr），
             排除「用超慢指數模仿常數匯」的疑慮
  V7 完整管線誤判示範  對「真值 rb = 0」的雙指數合成資料，跑**現行完整管線**
             （一步聯合擬合 + 它自己的 make_null 自助校準），看它會不會發出偽陽性

輸出 -> 主控台 + docs/analysis_charts_3batch/verify_misspecification.csv
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

from analyze_three_batches import OUT                       # noqa: E402
from joint_fit_calibrated import (load, joint, traj, make_null,  # noqa: E402
                                  BN, BLOCK, QUANT)
from misspecification_null import (build_truth, synth, fit_biexp,  # noqa: E402
                                   biexp, OBS_RB)

NB = 100
K0 = {'1.1 (1min)': 0.03843490648639361,
      '2.1 (5min)': 0.14886624187122727,
      '3.1 (10min)': 0.16729997686314324}
PEQ0 = 0.9053820006486397
BOUNDS = dict(kla=(1e-3, 3.0), peq=(0.0, 0.95), rb=(0.0, 0.1))
rows = []


def note(tag, verdict, detail):
    mark = {'PASS': '[PASS]', 'FAIL': '[FAIL]', 'INFO': '[INFO]'}[verdict]
    print(f'  {mark} {tag}: {detail}')
    rows.append(dict(check=tag, verdict=verdict, detail=detail))


def resid_noise(D, base_fn, rng):
    """以 base_fn 產生的軌跡為底，疊上實測殘差的區塊自助 + 感測器量化。"""
    out = {}
    for b in BN:
        lst = []
        for t, P in D[b]:
            base = base_fn(b, t, P)
            res = P - base
            n = len(res)
            rr = np.concatenate([res[j:j + BLOCK] for j in
                                 rng.integers(0, max(n - BLOCK, 1),
                                              size=n // BLOCK + 2)])[:n]
            lst.append((t, np.round((base + rr) / QUANT) * QUANT))
        out[b] = lst
    return out


def main():
    D = load()
    rng = np.random.default_rng(11)
    print('══ 驗證 misspecification_null.py ══')
    print(f'   26 個循環；實測共用 rb = {OBS_RB:.5f}\n')

    # ── V1 正對照 ────────────────────────────────────────────────
    print('V1 正對照：單指數真相，植入已知 rb = 0.011')
    RB_TRUE = 0.011
    est = []
    for _ in range(NB):
        s = resid_noise(D, lambda b, t, P: traj(t, P[0], K0[b], PEQ0, RB_TRUE), rng)
        est.append(float(joint(s)[4]))
    est = np.array(est)
    ok = abs(np.median(est) - RB_TRUE) < 0.15 * RB_TRUE
    note('V1 正對照', 'PASS' if ok else 'FAIL',
         f'植入 {RB_TRUE:.4f} → 回收中位 {np.median(est):.5f} '
         f'（相對偏差 {(np.median(est)/RB_TRUE-1)*100:+.1f}%）')

    # ── V2 負對照 ────────────────────────────────────────────────
    print('\nV2 負對照：單指數真相，rb = 0')
    est0 = []
    for _ in range(NB):
        s = resid_noise(D, lambda b, t, P: traj(t, P[0], K0[b], PEQ0, 0.0), rng)
        est0.append(float(joint(s)[4]))
    est0 = np.array(est0)
    ok = np.median(est0) < 0.25 * OBS_RB
    note('V2 負對照', 'PASS' if ok else 'FAIL',
         f'植入 0 → 回收中位 {np.median(est0):.5f}、95% {np.percentile(est0,95):.5f}'
         f'（原 joint_fit_calibrated 報 0.00075，應相符）')

    # ── V3 純偏誤（無噪聲） ───────────────────────────────────────
    print('\nV3 純偏誤：雙指數真相、完全不加噪聲')
    for shared, tag in ((False, 'A 自由漸近線'), (True, 'B 共用漸近線')):
        truth, _ = build_truth(D, shared)
        clean = {b: [(t, base) for t, P, base in truth[b]] for b in BN}
        th = joint(clean)
        note(f'V3 純偏誤 {tag}', 'INFO',
             f'真值 rb = 0，無噪聲 → 回收 rb = {th[4]:.5f}'
             f'（佔實測 {th[4]/OBS_RB*100:.0f}%）')

    # ── V4 收斂性 ────────────────────────────────────────────────
    print('\nV4 收斂性：檢查解有沒有頂到參數界')
    truth, _ = build_truth(D, False)
    hit = 0
    for _ in range(20):
        th = joint(synth(truth, rng))
        for i, b in enumerate(BN):
            if th[i] <= BOUNDS['kla'][0] * 1.01 or th[i] >= BOUNDS['kla'][1] * 0.99:
                hit += 1
        if th[3] >= BOUNDS['peq'][1] * 0.99 or th[4] >= BOUNDS['rb'][1] * 0.99:
            hit += 1
    note('V4 收斂性', 'PASS' if hit == 0 else 'FAIL',
         f'20 次重複、每次 5 個參數，頂界次數 = {hit}')

    # ── V5 振幅分解 ──────────────────────────────────────────────
    print('\nV5 振幅分解：慢分量在一個循環內貢獻多少壓降？')
    for b in BN:
        fs, l1s, l2s, frac_slow, hl_ratio = [], [], [], [], []
        for t, P in D[b]:
            C, f, l1, l2, _ = fit_biexp(t, P)
            amp = P[0] - C
            T = t[-1]
            d_fast = amp * f * (1 - np.exp(-l1 * T))
            d_slow = amp * (1 - f) * (1 - np.exp(-l2 * T))
            fs.append(f); l1s.append(l1); l2s.append(l2)
            frac_slow.append(d_slow / max(d_fast + d_slow, 1e-9))
            hl_ratio.append((np.log(2) / l2) / T)
        note(f'V5 {b}', 'INFO',
             f'慢分量佔循環內總壓降 {np.median(frac_slow)*100:.0f}%；'
             f'其半衰期 / 循環長度 = {np.median(hl_ratio):.1f}倍'
             f'（>1 表示窗口內近乎線性）')

    # ── V6 保守真相 C ────────────────────────────────────────────
    print('\nV6 保守真相 C：強制 λ2 ≥ 0.15/hr（半衰期 ≤ 4.6 hr，循環內可解析）')
    truthC = {}
    for b in BN:
        lst = []
        for t, P in D[b]:
            from scipy import optimize
            P0 = P[0]

            def r(th):
                return biexp(t, P0, th[0], th[1], th[2], th[3]) - P
            res = optimize.least_squares(
                r, [max(P[-1] - 0.15, 0.05), 0.5, 0.5, 0.3],
                bounds=([0.02, 0.0, 0.16, 0.15], [min(P[-1], 0.95), 1.0, 8.0, 1.0]),
                max_nfev=8000)
            lst.append((t, P, biexp(t, P0, *res.x)))
        truthC[b] = lst
    rmseC = np.mean([np.sqrt(np.mean((P - base) ** 2))
                     for b in BN for t, P, base in truthC[b]])
    estC = []
    for _ in range(NB):
        estC.append(float(joint(synth(truthC, rng))[4]))
    estC = np.array(estC)
    pC = float((estC >= OBS_RB).mean())
    note('V6 保守真相 C', 'INFO',
         f'擬合 RMSE = {rmseC:.5f}；回收假 rb 中位 {np.median(estC):.5f}、'
         f'95% {np.percentile(estC,95):.5f}；實測 {OBS_RB:.5f} → p = {pC:.3f}')

    # ── V7 完整管線誤判示範 ──────────────────────────────────────
    print('\nV7 完整管線誤判示範：對真值 rb=0 的資料跑「聯合擬合 + 它自己的自助校準」')
    truth, _ = build_truth(D, False)
    fp_hits = 0
    TRIALS = 5
    for k in range(TRIALS):
        s = synth(truth, rng)
        th = joint(s)                       # 這份資料的真值 rb = 0
        nulls = []
        for _ in range(60):                 # 管線自己的虛無：用單指數 base
            nulls.append(float(joint(make_null(s, th, rng))[4]))
        nulls = np.array(nulls)
        p = float((nulls >= th[4]).mean())
        fp = p < 0.05
        fp_hits += fp
        print(f'   試驗 {k+1}: 估得 rb = {th[4]:.5f}（真值 0）、'
              f'自身虛無中位 {np.median(nulls):.5f} → p = {p:.3f}'
              f'  {"← 偽陽性" if fp else ""}')
    note('V7 完整管線', 'FAIL' if fp_hits else 'PASS',
         f'{fp_hits}/{TRIALS} 次對真值為 0 的資料發出「顯著」判定')

    fp = f'{OUT}/verify_misspecification.csv'
    with open(fp, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['check', 'verdict', 'detail'])
        w.writeheader()
        w.writerows(rows)
    print(f'\n輸出 → {fp}')


if __name__ == '__main__':
    main()
