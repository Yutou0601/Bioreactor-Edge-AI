
# -*- coding: utf-8 -*-
"""
端點選擇偏誤：r_b 被高估了多少？
════════════════════════════════════════════════════════════════════════

`residual_structure.py` 發現：循環**內部**的疊加平均殘差全部落在
±0.006（佔幅度）以內，但**最後一點是 −0.0675，達其 SEM 的 6.75 倍**。
模擬對照在同一點只有雜訊等級。

病因是切分方式本身：

    seg_clean() 讓循環結束在「補氣觸發的前一刻」
    ⇒ 該點是**因為壓力夠低才被選中**的
    ⇒ 它系統性地低於底層趨勢（對極值取樣的經典偏誤）

而 **線性項的斜率對端點的槓桿最大**，所以 r_b 會被往上拉。
先前 r_b = 0.01347 的估計**含這個偏誤**。

本檔：逐步裁掉循環尾端，看 r_b 收斂到哪裡。
  · 若 r_b 隨裁切迅速下降並趨於平穩 ⇒ 平穩值才是無偏估計
  · 若 r_b 幾乎不動                 ⇒ 端點偏誤可忽略

同一裁切也套在**模擬對照**上當基準——模擬沒有觸發選擇，
所以它的 r_b 不該隨裁切改變；若也改變，那是裁切本身的產物。

輸出 -> docs/analysis_charts_3batch/endpoint_bias.csv
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

from analyze_three_batches import OUT                              # noqa: E402
from simulator_check import fit_LE, QUANT                          # noqa: E402
# ⚠ 2026-08-24：本檔的結果被論文 §5.3 引用，必須與主結果跑在同一個
#   集合上。原本用 residual_structure.collect（351 段，含重複副本、未
#   套排除準則），算出的裁切區間貼著舊中位 0.0128 而非現行的 0.0132。
from dataset_c import collect_c as collect                         # noqa: E402
from degeneracy_matched import CURV_MIN                            # noqa: E402
from rb_recovery_study import curvature                            # noqa: E402

RNG = np.random.default_rng(8675309)
TRIMS = [0, 5, 10, 20, 30, 45, 60, 90]        # 裁掉尾端幾分鐘


def rb_at_trim(cycles, trim_min):
    out = []
    for item in cycles:
        t, y = item[-2], item[-1]
        keep = t <= (t[-1]-trim_min/60.0)
        if keep.sum() < 20:
            continue
        tt, yy = t[keep], y[keep]
        if yy[0]-yy[-1] <= 0:
            continue
        out.append(fit_LE(tt, yy)['rb'])
    return np.array(out)


def main():
    # ⚠ 必須套與主結果相同的曲率預篩。論文 §5.3 把這裡的裁切區間直接
    #   擺在 §5.2 的中位數旁邊，兩者若不是同一批循環，讀者一對比就錯。
    cyc = [(tag, t, y) for tag, t, y in collect()
           if np.isfinite(curvature(t, y)) and curvature(t, y) >= CURV_MIN]
    print('══ 端點選擇偏誤：r_b 被高估了多少？ ══\n')
    print(f'   循環 {len(cyc)} 個（已套 c >= {CURV_MIN} 預篩）')

    # 模擬對照（無觸發選擇）
    sims = []
    for tag, t, y in cyc:
        f = fit_LE(t, y)
        r = f['resid']
        phi = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if r.std() > 0 else 0.
        phi = float(np.clip(phi*1.3, 0, 0.98))
        sd = max(f['sd'], QUANT/4)
        e = RNG.normal(0, sd*np.sqrt(1-phi**2), len(t))
        nz = np.empty(len(t)); nz[0] = RNG.normal(0, sd)
        for i in range(1, len(t)):
            nz[i] = phi*nz[i-1]+e[i]
        yy = f['peq']+f['amp']*np.exp(-f['k']*t)-f['rb']*t+nz
        sims.append((tag, t, np.round(yy/QUANT)*QUANT))

    print('\n── 裁掉尾端後的 r_b ──')
    print(f'   {"裁切":>6}{"n":>6}{"真實 r_b 中位":>15}{"相對 0 分":>11}'
          f'{"模擬對照":>12}{"對照變化":>11}')
    print('   '+'-'*62)
    rows, base_r, base_s = [], None, None
    for tm in TRIMS:
        vr = rb_at_trim(cyc, tm)
        vs = rb_at_trim(sims, tm)
        mr, ms = float(np.median(vr)), float(np.median(vs))
        if base_r is None:
            base_r, base_s = mr, ms
        print(f'   {tm:>4} 分{len(vr):>6}{mr:>15.5f}'
              f'{(mr/base_r-1)*100:>10.0f}%{ms:>12.5f}'
              f'{(ms/base_s-1)*100:>10.0f}%')
        rows.append([tm, len(vr), f'{mr:.6f}', f'{ms:.6f}',
                     f'{np.mean(vr>0):.4f}'])

    # ── 判讀 ────────────────────────────────────────────
    vr0 = rb_at_trim(cyc, 0)
    vr9 = rb_at_trim(cyc, 90)
    vs0 = rb_at_trim(sims, 0)
    vs9 = rb_at_trim(sims, 90)
    d_real = float(np.median(vr9))/float(np.median(vr0))-1
    d_sim = float(np.median(vs9))/float(np.median(vs0))-1
    print(f'\n   真實：0 → 90 分裁切，r_b 變化 {d_real*100:+.0f} %')
    print(f'   對照：0 → 90 分裁切，r_b 變化 {d_sim*100:+.0f} %')
    print(f'   → 扣掉裁切本身的效應，端點偏誤約 '
          f'{(d_real-d_sim)*100:+.0f} %')

    print('\n══ 判定 ══')
    if abs(d_real-d_sim) > 0.15:
        print('   ✘ **端點選擇偏誤顯著**。')
        print(f'      r_b = {np.median(vr0):.5f}（含偏誤，先前報告的值）')
        print(f'      r_b = {np.median(vr9):.5f}（裁掉尾端 90 分）')
        print('      ⇒ 論文必須報告裁切後的值，並說明偏誤來源。')
    else:
        print('   ✓ 端點偏誤在裁切下不顯著，原估計可用。')

    with open(f'{OUT}/endpoint_bias.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['trim_min', 'n', 'rb_real_median', 'rb_sim_median',
                    'pos_frac_real'])
        w.writerows(rows)
    print(f'\n輸出 → {OUT}/endpoint_bias.csv')


if __name__ == '__main__':
    main()
