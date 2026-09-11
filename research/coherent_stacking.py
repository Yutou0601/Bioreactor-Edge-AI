
# -*- coding: utf-8 -*-
"""
相干循環疊加：把埋在雜訊裡的 ORP／pH 軌跡拉出來
════════════════════════════════════════════════════════════════════════

**為什麼先前看不到生物訊號**：單一循環的 ΔORP 被 ±20 mV 的感測雜訊吃掉
（`multivariate_increments.py` 量到各條件的 dORP/dt 中位數全是 0.000）。

**但每個循環都是同一個實驗的重複。** 按正規化時間對齊後相干疊加，
雜訊以 1/√N 下降：泵關組 38 個循環 ⇒ 20/√38 ≈ 3.2 mV。
單看一個循環看不見的系統性軌跡，疊起來就會浮出來。

這是**訊號縮放**的用法，而且**時間不連續完全不影響**——每個循環各自
正規化，跨空窗照樣可以疊。

為什麼 ORP 重要：物理溶解 CO2 **不消耗 H2**，只有產甲烷菌會
（CO2 + 4H2 → CH4 + 2H2O）。所以 ORP 的系統性變化是**只有生物會造成**的。

檢定：
  S1  各條件的疊加軌跡與其自助信賴帶
  S2  ⚠ **已作廢**（2026-09-11）。原本印的「改善」欄是 sd/se，而 se 就是
      sd/√n，所以它恆等於 √n——**不可能失敗，因此不構成證據**。實測以純
      亂數代入可得完全相同的 √N 吻合。欄位保留但改名為「√n（恆等）」，
      不得再引用為「疊加有效」的佐證。真正的證據是 S4。
  S3  疊加軌跡的終點值是否隨循環設定而異（生物活性的條件相依性）
  S4  置換虛無：把循環內的時間順序打散再疊，軌跡應消失

輸出 -> docs/analysis_charts_3batch/coherent_stacking.csv
"""
import os
import sys
import csv
import glob
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import TD                                 # noqa: E402
from multivariate_increments import load4, seg, cond_of            # noqa: E402

NG = 40           # 正規化時間格點
NBOOT = 2000


def stack(cycles, ch, ng=NG):
    """把多個循環的某一通道對齊疊加。每個循環先減去自身起點。"""
    G = np.linspace(0, 1, ng)
    M = []
    for t, y in cycles:
        v = y[ch]
        if not np.all(np.isfinite(v)):
            continue
        tn = (t-t[0])/(t[-1]-t[0])
        M.append(np.interp(G, tn, v-v[0]))
    return G, np.array(M)


def main():
    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if glob.glob(os.path.join(p, '*.csv')):
            folders.append((p, d))
        for s in sorted(os.listdir(p)):
            sp = os.path.join(p, s)
            if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                folders.append((sp, f'{d}/{s}'))

    seen, byc = {}, {}
    for path, tag in folders:
        try:
            raw = load4(path)
        except Exception:
            continue
        if len(raw) < 2000:
            continue
        ts = [r[0] for r in raw]
        P = np.array([r[1] for r in raw]); O = np.array([r[2] for r in raw])
        H = np.array([r[3] for r in raw])
        h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
        for a, b in seg(h, P):
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            seen[key] = 1
            c, _ = cond_of(tag, ts[a].date())
            if c == 'other':
                continue
            byc.setdefault(c, []).append(
                (h[a:b+1]-h[a],
                 {'P': P[a:b+1], 'ORP': O[a:b+1], 'pH': H[a:b+1]}))

    print('══ 相干循環疊加 ══\n')
    conds = sorted(byc, key=lambda c: -len(byc[c]))
    for c in conds:
        print(f'   {c:<10} {len(byc[c]):>3} 個循環')

    rng = np.random.default_rng(7)
    out_rows = []

    # ── S1／S2 疊加軌跡與訊噪比 ─────────────────────────
    for ch, unit in (('ORP', 'mV'), ('pH', '')):
        print(f'\n── {ch} 的疊加軌跡（每循環減去自身起點）──')
        print(f'   {"條件":<10}{"n":>4}{"單循環 σ":>12}{"疊加 SE":>11}'
              f'{"√n(恆等)":>10}{"終點值":>12}{"95% CI":>22}')
        print('   '+'-'*80)
        for c in conds:
            G, M = stack(byc[c], ch)
            if len(M) < 5:
                continue
            end = M[:, -1]
            sd = end.std(ddof=1)
            se = sd/np.sqrt(len(end))
            bs = np.array([np.mean(rng.choice(end, len(end), replace=True))
                           for _ in range(NBOOT)])
            lo, hi = np.quantile(bs, [.025, .975])
            sig = '  ✓' if (lo > 0) or (hi < 0) else ''
            print(f'   {c:<10}{len(M):>4}{sd:>12.3f}{se:>11.3f}'
                  f'{sd/se:>9.1f}×{end.mean():>12.3f}'
                  f'{f"[{lo:+.3f}, {hi:+.3f}]":>22}{sig}')
            out_rows.append([ch, c, len(M), f'{sd:.4f}', f'{se:.4f}',
                             f'{end.mean():.4f}', f'{lo:.4f}', f'{hi:.4f}'])

    # ── S3 條件相依性 ─────────────────────────────────
    print('\n── S3  ORP 疊加終點是否隨循環設定而異？──')
    print('   （物理溶解 CO2 不消耗 H2 ⇒ ORP 的系統性變化只有生物造成）')
    ends = {}
    for c in conds:
        G, M = stack(byc[c], 'ORP')
        if len(M) >= 5:
            ends[c] = M[:, -1]
    ks = list(ends)
    print(f'   {"條件 A":<10}{"條件 B":<10}{"差值":>10}{"Welch t":>10}{"p":>10}')
    print('   '+'-'*50)
    from math import erfc, sqrt as _s
    for i in range(len(ks)):
        for j in range(i+1, len(ks)):
            a, b = ends[ks[i]], ends[ks[j]]
            va, vb = a.var(ddof=1)/len(a), b.var(ddof=1)/len(b)
            if va+vb <= 0:
                continue
            t = (a.mean()-b.mean())/_s(va+vb)
            p = erfc(abs(t)/_s(2))
            mk = '  ✓' if p < 0.05 else ''
            print(f'   {ks[i]:<10}{ks[j]:<10}{a.mean()-b.mean():>10.3f}'
                  f'{t:>10.2f}{p:>10.3f}{mk}')

    # ── S4 置換虛無：打散循環內順序後再疊 ────────────────
    print('\n── S4  置換虛無（打散循環內的時間順序再疊）──')
    print('   若疊加出的軌跡是真的，打散後應該消失。')
    for c in conds[:3]:
        G, M = stack(byc[c], 'ORP')
        if len(M) < 5:
            continue
        obs = abs(M[:, -1].mean())
        null = []
        for _ in range(500):
            perm = []
            for t, y in byc[c]:
                v = y['ORP'].copy()
                rng.shuffle(v)
                tn = (t-t[0])/(t[-1]-t[0])
                perm.append(np.interp(G, tn, v-v[0]))
            null.append(abs(np.mean([p[-1] for p in perm])))
        null = np.array(null)
        pv = (np.sum(null >= obs)+1)/(len(null)+1)
        print(f'   {c:<10} 實測 |終點| = {obs:.3f}   '
              f'虛無 {null.mean():.3f}±{null.std():.3f}   p = {pv:.3f}'
              f'{"  ✓ 非隨機" if pv < 0.05 else "  ✘ 落在虛無內"}')

    with open(f'{OUT}/coherent_stacking.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['channel', 'cond', 'n_cycles', 'sd_single', 'se_stacked',
                    'end_mean', 'ci_lo', 'ci_hi'])
        w.writerows(out_rows)
    print(f'\n輸出 → {OUT}/coherent_stacking.csv')


if __name__ == '__main__':
    main()
