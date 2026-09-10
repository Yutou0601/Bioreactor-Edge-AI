
# -*- coding: utf-8 -*-
"""
類型學的校準與驗證（Calibrated Typology & Validation）
════════════════════════════════════════════════════════════════════════

前一版類型學用固定懲罰 β = 3·log n，但虛無校準顯示該設定下 AR(1) 替代序列
最多可產生 11 個假變點。本檔改為**逐通道校準 β**，使每個通道在虛無下的
偽陽性率 ≤ 5%，再重跑類型學，並對已知事件做嚴格的類型驗證。

⚠ 類型的定義（比「操作者 vs 自然」精確）：
   ★ 控制重組  = 控制帶本身移動了（P0 / Pend 變）
   ● 製程漂移  = 控制帶不變，但系統反應變了（kLa / 形狀變）
   兩者都可能由人造成。區別在「控制組態」還是「系統反應」。

輸出 -> docs/analysis_charts_3batch/typology_validation.csv
"""
import sys
import csv
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import optimal_partition                  # noqa: E402
from changepoint_forensics import gather_rich, GAP_DAYS            # noqa: E402

NSUR = 200          # 虛無替代序列數
FPR = 0.05          # 目標偽陽性率
ALIGN = 3           # 事件對齊容差（天）

# ⚠ P0（補氣上限）**不是**乾淨的設定點，證據（scratchpad/setpoint_purity.py）：
#   · P0   與 log kLa  r = −0.218, p = 4.5e-04  → 與製程狀態顯著相關
#   · Pend 與 log kLa  r = −0.021, p = 0.74     → 與製程狀態無關
#   · 相異值集中度：Pend 前 3 值涵蓋 65%，P0 僅 35%
#   · τ 切換時 P0 僅動 0.01（＝壓力量化的一個 LSB），卻造成 2/4 誤判
#   物理上：閾值觸發系統裡「觸發下限」才是控制器比較的設定點；
#   「補氣上限」是補氣結束後**達到**的壓力，屬製程結果。
CHANS = [('P0',    '補氣上限', False, 'resp'),
         ('Pend',  '觸發下限', False, 'band'),
         ('dur',   '循環時長', True,  'resp'),
         ('kla',   'kLa 代理', True,  'resp'),
         ('shape', '曲線形狀', False, 'resp'),
         ('noise', '訊號雜訊', True,  'qual')]

# 已知事件與**物理上應有的類型**
KNOWN = [
    (dt.date(2026, 4,  7), '手動排氣',        '★', '人為排氣直接擾動壓力帶'),
    (dt.date(2026, 1,  9), '組成 4:1→1:1',   '●', '換氣但壓力帶設定不變'),
    (dt.date(2026, 7, 27), 'τ 切換 1→5min',  '●', '改循環泵工作比，非壓力設定'),
    (dt.date(2026, 7, 30), 'τ 切換 5→10min', '●', '同上'),
]


def prep(vals, logscale):
    v = np.asarray(vals, float)
    ok = np.isfinite(v) & ((v > 0) if logscale else np.ones(len(v), bool))
    y = np.log(v[ok]) if logscale else v[ok]
    return y, np.where(ok)[0]


def _min_beta_mult(s, logn, lo=1.0, hi=32.0, tol=0.25):
    """單一序列上，使變點數歸零所需的最小 β 倍率（二分搜尋）。"""
    if len(optimal_partition(s, lo*logn)) == 0:
        return lo
    if len(optimal_partition(s, hi*logn)) > 0:
        return hi
    while hi-lo > tol:
        mid = (lo+hi)/2
        if len(optimal_partition(s, mid*logn)) > 0:
            lo = mid
        else:
            hi = mid
    return hi


def calibrate_beta(y, rng, fpr=FPR, nsur=NSUR):
    """校準 β，使 AR(1) 虛無下出現任何變點的機率 ≤ fpr。

    對每條替代序列以二分搜尋求「歸零所需的最小 β」，取其 (1−fpr) 分位數。
    比逐格掃描快約 8 倍。
    """
    z = y-y.mean()
    if z.std() < 1e-12:
        return np.inf, 0.0
    phi = float(np.clip(np.corrcoef(z[:-1], z[1:])[0, 1], -0.95, 0.95))
    sd = z.std()*np.sqrt(max(1-phi**2, 1e-6))
    n = len(y); logn = np.log(n)
    mins = np.empty(nsur)
    for j in range(nsur):
        s = np.empty(n); s[0] = rng.normal(0, z.std())
        for i in range(1, n):
            s[i] = phi*s[i-1]+rng.normal(0, sd)
        mins[j] = _min_beta_mult(s, logn)
    return float(np.quantile(mins, 1-fpr)), phi


def main():
    rows = gather_rich()
    T = [r['t'] for r in rows]
    n = len(rows)
    rng = np.random.default_rng(7)
    print('══ 類型學校準與驗證 ══')
    print(f'   循環 {n} 個   {T[0].date()} → {T[-1].date()}\n')

    print('── 步驟 1  逐通道校準 β（AR(1) 虛無偽陽性率 ≤ 5%）──')
    print(f'   {"通道":<12}{"n":>5}{"φ":>8}{"校準 β":>10}'
          f'{"舊 β=3":>9}{"新變點數":>10}')
    print('   '+'-'*56)
    hits, detail = {}, {}
    for key, lab, lg, grp in CHANS:
        y, idx = prep([r[key] for r in rows], lg)
        m, phi = calibrate_beta(y, rng)
        cps_old = optimal_partition(y, 3.0*np.log(len(y)))
        cps = optimal_partition(y, m*np.log(len(y))) if np.isfinite(m) else []
        print(f'   {lab:<12}{len(y):>5}{phi:>+8.2f}{m:>10.1f}'
              f'{len(cps_old):>9}{len(cps):>10}')
        detail[lab] = (m, phi, len(cps_old), len(cps))
        for c in cps:
            hits.setdefault(T[idx[c]].date(), set()).add((lab, grp))

    # 空窗地圖
    gapmap = {}
    for i in range(1, n):
        g = (T[i]-T[i-1]).total_seconds()/86400
        if g > GAP_DAYS:
            gapmap[T[i].date()] = g

    def classify(s):
        grps = {g for _, g in s}
        if 'band' in grps:
            return '★ 控制重組'
        if 'resp' in grps:
            return '● 製程漂移'
        if 'qual' in grps:
            return '⚠ 訊噪異常'
        return '· 其他'

    print('\n── 步驟 2  校準後的變點與類型 ──')
    print(f'   {"日期":<13}{"空窗":>7}  {"類型":<14}通道')
    print('   '+'-'*66)
    audit = []
    for d in sorted(hits):
        s = hits[d]
        g = gapmap.get(d, 0.0)
        cls = '✘ 資料空窗' if g > GAP_DAYS else classify(s)
        chans = '/'.join(sorted(lab for lab, _ in s))
        print(f'   {str(d):<13}{(f"{g:.1f}d" if g else "—"):>7}  '
              f'{cls:<14}{chans}')
        audit.append((d, g, cls, chans))
    ng = sum(1 for _, g, c, _ in audit if c.startswith('✘'))
    print(f'\n   校準後共 {len(audit)} 個變點'
          f'（舊 β=3 時為 81 個），其中 {ng} 個落在空窗')

    print('\n── 步驟 3  已知事件的類型驗證 ──')
    print(f'   {"事件":<18}{"日期":<13}{"應為":<6}{"偵測":<13}'
          f'{"判定":<14}結果')
    print('   '+'-'*76)
    nd = nt = 0
    for d, name, want, why in KNOWN:
        near = sorted(((abs((x-d).days), x) for x, _, _, _ in audit),
                      key=lambda z: z[0])
        if near and near[0][0] <= ALIGN:
            dd = near[0][1]
            got = next(c for x, _, c, _ in audit if x == dd)
            nd += 1
            mark = got[0]
            okk = ('✓ 類型正確' if mark == want
                   else f'✘ 類型錯誤（應 {want}）')
            if mark == want:
                nt += 1
            print(f'   {name:<18}{str(d):<13}{want:<6}'
                  f'{str(dd)+f"(±{near[0][0]})":<13}{got:<14}{okk}')
        else:
            print(f'   {name:<18}{str(d):<13}{want:<6}'
                  f'{"未偵測":<13}{"—":<14}✘ 漏檢')
    print(f'\n   偵測率 {nd}/{len(KNOWN)}   '
          f'類型正確率 {nt}/{len(KNOWN)}'
          f'（在偵測到的當中 {nt}/{nd if nd else 1}）')

    print('\n── 步驟 4  結論 ──')
    if nt == len(KNOWN):
        print('   類型學在全部已知事件上正確。')
    else:
        print(f'   ⚠ 類型學在 {len(KNOWN)-nt} 個已知事件上不正確或漏檢。')
        print('     不可宣稱「全部分對」。論文須據實報告此結果。')

    with open(f'{OUT}/typology_validation.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['date', 'gap_days', 'classification', 'channels'])
        for a in audit:
            w.writerow([a[0], f'{a[1]:.1f}', a[2], a[3]])
    print(f'\n輸出 → {OUT}/typology_validation.csv')


if __name__ == '__main__':
    main()
