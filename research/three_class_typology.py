
# -*- coding: utf-8 -*-
"""
三類事件типология（Transient / Reconfiguration / Drift）
════════════════════════════════════════════════════════════════════════

前一版把事件分兩類（控制重組 vs 製程漂移），在 2026-07-30 誤判：
那天 Pend 由 0.92 掉到 0.22 又立刻回到 0.92——**那是一次排氣，不是改設定**。

資料顯示這種孤立深跌在全資料集出現 45 次（17.6%），局部中位長期穩在 0.71–0.72，
每隔一兩週深跌一次再回復。這是一個**物理上真實的獨立事件類**，必須自成一類。

  ⚡ 瞬時介入   控制面孤立偏移、立刻回復          → 手動排氣
  ★ 持續重組   控制面階梯移位並維持              → 改設定點
  ● 製程漂移   僅反應面改變、控制面穩定           → 反應器本身變了
  ✘ 空窗假象   落在 >3 天的記錄中斷              → 不可主張

控制面由 CRPP（`control_plane_partition.py`）自資料判定，結果為 {Pend}。

輸出 -> docs/analysis_charts_3batch/three_class_typology.csv
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
from typology_validation import calibrate_beta, prep, ALIGN        # noqa: E402

HAMPEL_W = 9        # 局部中位窗（循環數）
HAMPEL_T = 0.15     # 判定孤立偏移的門檻 kg/cm²
RETURN_N = 2        # 「立刻回復」的定義：N 個循環內回到局部水準
QUANT = 0.01        # 壓力感測器量化步階 kg/cm²
MIN_SHIFT = 3*QUANT  # 持續重組的最小水準移位（3 個量化步階）
#   ↑ 由感測器解析度決定，不是隨手挑的。先前用 n·log(變異數) 成本時，
#     τ 切換造成 P0 移動 0.01（＝**一個 LSB**）被判成控制重組，
#     導致 4 個已知事件只對 2 個。任何小於數個 LSB 的「移位」都不可信。

# CRPP 的判定結果（見 control_plane_partition.py）
CONTROL = [('Pend', '觸發下限')]
RESPONSE = [('P0', '補氣上限'), ('dur', '循環時長'),
            ('kla', 'kLa 代理'), ('shape', '曲線形狀')]

KNOWN = [
    (dt.date(2026, 1,  9), '組成 4:1→1:1',   '●', '換氣，壓力設定不變'),
    (dt.date(2026, 7, 27), 'τ 切換 1→5min',  '●', '改泵工作比，非壓力設定'),
    (dt.date(2026, 7, 30), 'τ 切換 5→10min', '●', '同上'),
]


def partition_mean(y, beta):
    """**均值移位專用**的最佳分割。

    成本 = 段內平方和（隱含固定變異數），因此**只對均值改變敏感**。
    先前用 n·log(段內變異數) 會同時偵測變異數改變，造成
    2025-10-19（0.73→0.73）與 2026-04-06（0.72→0.72）這種
    「水準完全沒變」的假重組。
    """
    n = len(y)
    cs = np.concatenate([[0.0], np.cumsum(y)])
    cs2 = np.concatenate([[0.0], np.cumsum(y*y)])

    def cost(s, e):
        m = e-s
        if m < 3:
            return np.inf
        return cs2[e]-cs2[s] - (cs[e]-cs[s])**2/m

    F = np.full(n+1, np.inf); F[0] = -beta
    prev = np.zeros(n+1, int)
    for e in range(1, n+1):
        for s in range(0, e):
            c = F[s]+cost(s, e)+beta
            if c < F[e]:
                F[e] = c; prev[e] = s
    cps, e = [], n
    while e > 0:
        cps.append(prev[e]); e = prev[e]
    return sorted(set(cps[:-1]))


def calibrate_mean(y, rng, fpr=0.05, nsur=200):
    """為 partition_mean 校準 β（AR(1) 虛無偽陽性 ≤ fpr）。

    β 的單位是變異數，故以資料自身的穩健噪聲尺度標準化。
    """
    z = y-y.mean()
    if z.std() < 1e-12:
        return np.inf, 0.0, 0.0
    phi = float(np.clip(np.corrcoef(z[:-1], z[1:])[0, 1], -0.95, 0.95))
    sd = z.std()*np.sqrt(max(1-phi**2, 1e-6))
    n = len(y)
    # 穩健噪聲尺度：一階差分的 MAD / sqrt(2)
    d = np.diff(y)
    s2 = (1.4826*np.median(np.abs(d-np.median(d)))/np.sqrt(2))**2
    s2 = max(s2, (QUANT/2)**2)          # 下限 = 量化誤差

    def min_mult(s):
        lo, hi = 0.5, 4096.0
        if len(partition_mean(s, lo*s2)) == 0:
            return lo
        if len(partition_mean(s, hi*s2)) > 0:
            return hi
        while hi/lo > 1.15:
            mid = np.sqrt(lo*hi)
            if len(partition_mean(s, mid*s2)) > 0:
                lo = mid
            else:
                hi = mid
        return hi

    mins = np.empty(nsur)
    for j in range(nsur):
        s = np.empty(n); s[0] = rng.normal(0, z.std())
        for i in range(1, n):
            s[i] = phi*s[i-1]+rng.normal(0, sd)
        mins[j] = min_mult(s)
    return float(np.quantile(mins, 1-fpr)), phi, s2


def hampel(v, w=HAMPEL_W, thr=HAMPEL_T):
    """回傳 (孤立偏移的索引, 以局部中位取代後的序列)。"""
    v = np.asarray(v, float)
    n = len(v)
    med = np.empty(n)
    for i in range(n):
        lo, hi = max(0, i-w//2), min(n, i+w//2+1)
        seg = np.delete(v[lo:hi], min(i-lo, hi-lo-1))
        med[i] = np.median(seg) if len(seg) else v[i]
    idx = np.where(np.abs(v-med) > thr)[0]
    clean = v.copy()
    clean[idx] = med[idx]
    return idx, clean, med


def main():
    rows = gather_rich()
    T = [r['t'] for r in rows]
    n = len(rows)
    rng = np.random.default_rng(23)
    print('══ 三類事件類型學 ══')
    print(f'   循環 {n} 個   {T[0].date()} → {T[-1].date()}\n')

    gapmap = {}
    for i in range(1, n):
        g = (T[i]-T[i-1]).total_seconds()/86400
        if g > GAP_DAYS:
            gapmap[T[i].date()] = g

    events = {}

    # ── ⚡ 瞬時介入：控制面的孤立偏移 ──────────────────────
    print('── ⚡ 瞬時介入（控制面孤立偏移，立刻回復）──')
    for key, lab in CONTROL:
        v = np.array([r[key] for r in rows], float)
        idx, clean, med = hampel(v)
        # 只保留「立刻回復」者：後 RETURN_N 個循環回到局部水準
        keep = []
        for i in idx:
            back = all(abs(v[j]-med[j]) <= HAMPEL_T
                       for j in range(i+1, min(n, i+1+RETURN_N)))
            if back:
                keep.append(i)
        print(f'   {lab}：孤立偏移 {len(idx)} 次，其中立刻回復 {len(keep)} 次'
              f'（{len(keep)/n*100:.1f}% 的循環）')
        down = [i for i in keep if v[i] < med[i]]
        print(f'      往下（排氣）{len(down)} 次   往上 {len(keep)-len(down)} 次')
        print(f'      深度中位 {np.median([med[i]-v[i] for i in down]):+.2f}'
              f' kg/cm²（往下者）')
        for i in keep:
            events.setdefault(T[i].date(), set()).add(('⚡', lab))

    # ── ★ 持續重組：Hampel 濾波後的控制面均值移位 ──────────
    print('\n── ★ 持續重組（控制面階梯移位並維持）──')
    print(f'   成本＝段內平方和（只對均值敏感）；'
          f'最小效應量 {MIN_SHIFT:.2f} kg/cm² ＝ 3 個量化步階')
    for key, lab in CONTROL:
        v = np.array([r[key] for r in rows], float)
        _, clean, _ = hampel(v)
        y, idx = prep(clean, False)
        m, phi, s2 = calibrate_mean(y, rng)
        cps = partition_mean(y, m*s2)
        print(f'   {lab}：校準 β = {m:.0f}·σ̂²（σ̂={np.sqrt(s2):.4f}，'
              f'φ={phi:+.2f}）→ 候選 {len(cps)} 個')
        kept = 0
        for c in cps:
            before = np.median(y[max(0, c-8):c])
            after = np.median(y[c:c+8])
            d = after-before
            if abs(d) < MIN_SHIFT:
                print(f'      {T[idx[c]].date()}   {before:.3f} → {after:.3f}'
                      f'   Δ={d:+.3f}   ✘ 未達最小效應量，剔除')
                continue
            kept += 1
            events.setdefault(T[idx[c]].date(), set()).add(('★', lab))
            print(f'      {T[idx[c]].date()}   {before:.3f} → {after:.3f}'
                  f'   Δ={d:+.3f}   ✓ 保留')
        print(f'      → 通過最小效應量者 {kept} 個')

    # ── ● 製程漂移：反應面變點 ────────────────────────────
    print('\n── ● 製程漂移（僅反應面改變）──')
    for key, lab in RESPONSE:
        y, idx = prep([r[key] for r in rows], key in ('dur', 'kla'))
        m, phi = calibrate_beta(y, rng)
        cps = optimal_partition(y, m*np.log(len(y)))
        print(f'   {lab}：校準 β = {m:.1f}·log n  → {len(cps)} 個變點')
        for c in cps:
            events.setdefault(T[idx[c]].date(), set()).add(('●', lab))

    # ── 合併分類（優先序：空窗 > 持續重組 > 瞬時介入 > 漂移）──
    def classify(s, d):
        if gapmap.get(d, 0) > GAP_DAYS:
            return '✘ 空窗假象'
        marks = {m for m, _ in s}
        if '★' in marks:
            return '★ 持續重組'
        if '⚡' in marks:
            return '⚡ 瞬時介入'
        return '● 製程漂移'

    audit = [(d, gapmap.get(d, 0.0), classify(events[d], d),
              '/'.join(sorted(f'{m}{l}' for m, l in events[d])))
             for d in sorted(events)]

    from collections import Counter
    cnt = Counter(a[2] for a in audit)
    print(f'\n── 分類彙總（共 {len(audit)} 個事件日）──')
    for k, v in cnt.most_common():
        print(f'   {k}   {v:>3} 個')

    # ── 已知事件驗證 ─────────────────────────────────────
    print('\n── 已知事件驗證 ──')
    print(f'   {"事件":<18}{"日期":<13}{"應為":<6}{"偵測":<15}{"判定":<14}結果')
    print('   '+'-'*76)
    nd = nt = 0
    for d, name, want, why in KNOWN:
        near = sorted(((abs((x-d).days), x) for x, _, _, _ in audit),
                      key=lambda z: z[0])
        if near and near[0][0] <= ALIGN:
            dd = near[0][1]
            got = next(c for x, _, c, _ in audit if x == dd)
            nd += 1
            ok = got[0] == want
            nt += ok
            print(f'   {name:<18}{str(d):<13}{want:<6}'
                  f'{str(dd)+f"(±{near[0][0]})":<15}{got:<14}'
                  f'{"✓" if ok else f"✘ 應 {want}"}')
        else:
            print(f'   {name:<18}{str(d):<13}{want:<6}'
                  f'{"未偵測":<15}{"—":<14}✘ 漏檢')
    print(f'\n   偵測 {nd}/{len(KNOWN)}   類型正確 {nt}/{len(KNOWN)}')
    print('\n   ⚠ 2026-04-07 未列入驗證集：使用者的描述是「應該是手動排氣」'
          '（不確定），\n     且同日 kLa 躍升 2.4×，真值標籤本身有歧義。'
          '不可拿來充人數。')

    with open(f'{OUT}/three_class_typology.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['date', 'gap_days', 'class', 'signals'])
        for a in audit:
            w.writerow([a[0], f'{a[1]:.1f}', a[2], a[3]])
    print(f'\n輸出 → {OUT}/three_class_typology.csv')


if __name__ == '__main__':
    main()
