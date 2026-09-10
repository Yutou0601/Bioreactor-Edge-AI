# -*- coding: utf-8 -*-
"""
平衡尾段探針（Equilibrium-Tail Probe, ETP）
════════════════════════════════════════════════════════════════════════

想法
────
兩通道模型   dP/dt = -k_La (P - P_eq) - r_b
當循環跑到 P -> P_eq 時，**物理項自行歸零**，殘餘的下降速率就只剩 r_b。
故不需要擬合、不需要共用參數、不需要 tau 槓桿——
**只需要找到「有跑到平衡」的循環，量它的尾段速率。**

判定平衡的三個條件（都必須成立才採用）：
  (1) 尾段速率 << 前段速率            (rate_tail / rate_head < THR_RATIO)
  (2) 尾段的二階變化接近零            (曲率已攤平)
  (3) 尾段夠長                        (>= MIN_TAIL_HR)

7-8 月的 4:1 批次全程近乎直線（前後半速率比 1.05-1.23），**從未達到平衡**，
故本法對它們不適用；而 1:1 批次（CO2 分壓 2.5 倍高）與部分歷史長循環會達到。

輸出 -> docs/analysis_charts_3batch/equilibrium_tail.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
from paths import testing_data          # Testing_data 的位置解析
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv
import glob
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TD = testing_data()
M, PORD = 2.0, 6
THR_RATIO = 0.45          # 尾段/前段速率比上限
MIN_TAIL_HR = 6.0
MIN_CYC_HR = 12.0


def weak_rate(t, y, tc, m):
    u = (t-tc)/m
    ins = np.abs(u) < 1
    if ins.sum() < 20:
        return np.nan, np.nan
    base = 1-u[ins]**2
    ph = base**PORD
    dph = PORD*base**(PORD-1)*(-2*u[ins])/m
    w = np.trapezoid(ph, t[ins])
    if w <= 0:
        return np.nan, np.nan
    return (np.trapezoid(dph*y[ins], t[ins])/w,      # 下降速率 (>0)
            np.trapezoid(ph*y[ins], t[ins])/w)       # 代表壓力


def load(folder):
    rows = []
    for fp in sorted(glob.glob(os.path.join(folder, '*.csv'))):
        for line in open(fp, encoding='utf-8', errors='replace'):
            p = line.strip().split(',')
            if len(p) < 14:
                continue
            try:
                rows.append((dt.datetime(int(p[0]), int(p[1]), int(p[2]),
                                         int(p[3]), int(p[4]), int(float(p[5]))),
                             float(p[11]), float(p[7])))
            except Exception:
                continue
    rows.sort()
    return rows


def segment(rows):
    ts = [r[0] for r in rows]; P = np.array([r[1] for r in rows])
    h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
    out, valley, start = [], P[0], 0
    for i in range(1, len(P)):
        if h[i]-h[i-1] > 1.0:
            if h[i-1]-h[start] > MIN_CYC_HR:
                out.append((start, i-1))
            start, valley = i, P[i]; continue
        if P[i]-valley > 0.03:
            if h[i-1]-h[start] > MIN_CYC_HR:
                out.append((start, i-1))
            start, valley = i, P[i]
        elif P[i] < valley:
            valley = P[i]
    if h[-1]-h[start] > MIN_CYC_HR:
        out.append((start, len(P)-1))
    return out, h, P, ts


def analyse(folder, tag, rows_out):
    if not os.path.isdir(folder):
        return
    rows = load(folder)
    if len(rows) < 2000:
        return
    cyc, h, P, ts = segment(rows)
    kept = 0
    for a, b in cyc:
        t = h[a:b+1]-h[a]; y = P[a:b+1]
        dur = t[-1]
        if dur < MIN_CYC_HR or (y[0]-y[-1]) < 0.08:
            continue
        m = min(M, dur/6)
        r_head, p_head = weak_rate(t, y, t[0]+m, m)
        r_tail, p_tail = weak_rate(t, y, t[-1]-m, m)
        r_mid, _ = weak_rate(t, y, dur*0.5, m)
        if not np.isfinite(r_head) or not np.isfinite(r_tail) or r_head <= 0:
            continue
        ratio = r_tail/r_head
        # 尾段長度：從速率降到 head 的 THR_RATIO 起算
        tail_hr = 0.0
        for frac in np.linspace(0.3, 0.95, 30):
            rr, _ = weak_rate(t, y, dur*frac, m)
            if np.isfinite(rr) and rr < THR_RATIO*r_head:
                tail_hr = dur*(1-frac)
                break
        eq = (ratio < THR_RATIO) and (tail_hr >= MIN_TAIL_HR)
        if eq:
            kept += 1
        rows_out.append(dict(folder=tag, start=ts[a].strftime('%Y-%m-%d %H:%M'),
                             dur_hr=f'{dur:.1f}', P0=f'{y[0]:.2f}',
                             Pend=f'{y[-1]:.2f}',
                             r_head=f'{r_head:.5f}', r_mid=f'{r_mid:.5f}',
                             r_tail=f'{r_tail:.5f}',
                             ratio=f'{ratio:.3f}', tail_hr=f'{tail_hr:.1f}',
                             equilibrium='YES' if eq else 'no'))
    print(f'   {tag:<38} 循環 {len(cyc):>4}   達平衡 {kept:>3}')


def main():
    print('══ 平衡尾段探針：掃描全部資料夾 ══')
    print(f'   判定：尾段/前段速率 < {THR_RATIO}，且尾段 >= {MIN_TAIL_HR} hr\n')
    out = []
    cands = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if os.path.isdir(p):
            if glob.glob(os.path.join(p, '*.csv')):
                cands.append((p, d))
            for sub in sorted(os.listdir(p)):
                sp = os.path.join(p, sub)
                if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                    cands.append((sp, f'{d}/{sub}'))
    for p, tag in cands:
        try:
            analyse(p, tag, out)
        except Exception as e:
            print(f'   {tag:<38} 略過（{type(e).__name__}）')

    eq = [r for r in out if r['equilibrium'] == 'YES']
    print(f'\n══ 達到平衡的循環：{len(eq)} / {len(out)} ══')
    if eq:
        print(f"{'資料夾':<26}{'起始':<18}{'時長':>7}{'r_head':>9}"
              f"{'r_tail':>9}{'比':>7}{'尾段hr':>8}")
        print('-' * 86)
        for r in sorted(eq, key=lambda x: float(x['r_tail']))[:30]:
            print(f"{r['folder'][:25]:<26}{r['start']:<18}{r['dur_hr']:>7}"
                  f"{r['r_head']:>9}{r['r_tail']:>9}{r['ratio']:>7}"
                  f"{r['tail_hr']:>8}")
        v = np.array([float(r['r_tail']) for r in eq])
        print(f"\n   ★ 尾段速率（= r_b 的直接量測）")
        print(f"      中位 {np.median(v):.5f}   平均 {v.mean():.5f} ± {v.std():.5f}")
        print(f"      四分位 [{np.percentile(v,25):.5f}, {np.percentile(v,75):.5f}]"
              f"   全距 [{v.min():.5f}, {v.max():.5f}]   n = {len(v)}")
        print(f"\n   對照：泵開/關對照法 0.00440；集合歸屬臨界點 0.0043-0.0046")
        # 依資料夾分組
        print(f"\n   依資料夾：")
        for f in sorted({r['folder'] for r in eq}):
            w = np.array([float(r['r_tail']) for r in eq if r['folder'] == f])
            print(f"      {f[:34]:<36} n={len(w):>3}  中位 {np.median(w):.5f}")

    with open(f'{OUT}/equilibrium_tail.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader(); w.writerows(out)
    print(f'\n輸出 → {OUT}/equilibrium_tail.csv')


if __name__ == '__main__':
    main()
